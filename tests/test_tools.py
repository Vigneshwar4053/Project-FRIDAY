from dataclasses import FrozenInstanceError
import math
import unittest
from unittest.mock import Mock

from friday.tools import (ArgumentSpec, ArgumentType, PermissionDecision, PermissionPolicy,
                          RiskLevel, RiskPermissionPolicy, Tool, ToolManager, ToolRegistry,
                          ToolRequest, ToolResult, ToolSpec, ToolStatus)


class EchoTool(Tool):
    """Purely in-memory fixture, never a production/system tool."""
    def __init__(self, name='echo', risk=RiskLevel.READ_ONLY, arguments=None):
        super().__init__(ToolSpec(name, 'Echo in-memory data.',
                                 arguments if arguments is not None else {'text': ArgumentSpec(ArgumentType.STRING)},
                                 risk))
        self.calls = 0
        self.received = None
        self.failure = None

    def execute(self, arguments):
        self.calls += 1
        self.received = arguments
        if self.failure is not None:
            raise self.failure
        return {'echo': arguments.get('text', ''), 'nested': {'values': [1, 2]}}


class RegistryTests(unittest.TestCase):
    def test_registration_lookup_listing_and_unknown(self):
        registry = ToolRegistry()
        first, second = EchoTool(), EchoTool('other')
        registry.register(first)
        registry.register(second)
        self.assertEqual(len(registry), 2)
        self.assertIs(registry.get('echo').tool, first)
        self.assertEqual(registry.list_tools(), (first.spec, second.spec))
        self.assertIsNone(registry.get('missing'))

    def test_duplicate_rejected_without_replacing_tool(self):
        registry = ToolRegistry()
        original = EchoTool()
        registry.register(original)
        with self.assertRaises(ValueError):
            registry.register(EchoTool())
        self.assertIs(registry.get('echo').tool, original)
        self.assertEqual(len(registry), 1)

    def test_registries_are_isolated(self):
        first, second = ToolRegistry(), ToolRegistry()
        first.register(EchoTool())
        self.assertEqual(second.list_tools(), ())
        self.assertIsNone(second.get('echo'))

    def test_list_and_metadata_cannot_corrupt_registry(self):
        registry = ToolRegistry()
        tool = EchoTool()
        registry.register(tool)
        listing = registry.list_tools()
        with self.assertRaises(TypeError):
            listing[0].arguments['new'] = ArgumentSpec(ArgumentType.INTEGER)
        with self.assertRaises(FrozenInstanceError):
            listing[0].name = 'changed'
        with self.assertRaises(FrozenInstanceError):
            registry.get('echo').spec = tool.spec
        copied = list(listing)
        copied.clear()
        self.assertEqual(len(registry.list_tools()), 1)

    def test_registered_risk_is_snapshot_not_replaceable_tool_metadata(self):
        registry = ToolRegistry()
        tool = EchoTool(risk=RiskLevel.PRIVILEGED)
        registry.register(tool)
        tool._spec = ToolSpec('renamed', 'Changed local metadata.', {}, RiskLevel.READ_ONLY)
        result = ToolManager(registry).execute(ToolRequest('echo', {'text': 'hello'}))
        self.assertEqual(result.status, ToolStatus.DENIED)
        self.assertEqual(tool.calls, 0)
        self.assertIsNone(registry.get('renamed'))

    def test_undeclared_objects_and_abstract_tool_rejected(self):
        with self.assertRaises(ValueError):
            ToolRegistry().register(object())
        with self.assertRaises(TypeError):
            Tool(ToolSpec('abstract', 'abstract fixture', {}, RiskLevel.READ_ONLY))


class DataAndSchemaTests(unittest.TestCase):
    def test_request_copies_nested_arguments_and_has_identity(self):
        arguments = {'payload': {'items': [1, {'name': 'original'}]}}
        request = ToolRequest('echo', arguments)
        arguments['payload']['items'][1]['name'] = 'changed'
        arguments['extra'] = True
        self.assertEqual(request.arguments['payload']['items'][1]['name'], 'original')
        self.assertNotIn('extra', request.arguments)
        self.assertNotEqual(request.request_id, ToolRequest('echo', {}).request_id)
        self.assertIsNotNone(request.created_at.tzinfo)
        with self.assertRaises(TypeError):
            request.arguments['payload']['items'][1]['name'] = 'changed'
        with self.assertRaises(FrozenInstanceError):
            request.tool_name = 'changed'

    def test_request_rejects_non_json_and_bad_identity(self):
        for arguments in ({'bad': object()}, {'bad': math.nan}, {'bad': math.inf}, {1: 'bad'}, []):
            with self.subTest(arguments_type=type(arguments)):
                with self.assertRaises(ValueError):
                    ToolRequest('echo', arguments)
        with self.assertRaises(ValueError):
            ToolRequest('', {})
        with self.assertRaises(ValueError):
            ToolRequest('echo', {}, request_id='')

    def test_cyclic_request_fails_cleanly(self):
        value = []
        value.append(value)
        with self.assertRaisesRegex(ValueError, 'cyclic'):
            ToolRequest('echo', {'value': value})

    def test_schema_copies_declarations_and_is_immutable(self):
        declarations = {'text': ArgumentSpec(ArgumentType.STRING)}
        spec = ToolSpec('echo', 'fixture', declarations, RiskLevel.READ_ONLY)
        declarations.clear()
        self.assertIn('text', spec.arguments)
        with self.assertRaises(FrozenInstanceError):
            spec.arguments['text'].required = False

    def test_invalid_schema_or_risk_rejected(self):
        for name, args, risk in (('Bad Name', {}, RiskLevel.READ_ONLY),
                                 ('valid', {'text': str}, RiskLevel.READ_ONLY),
                                 ('valid', {}, 'read_only')):
            with self.assertRaises(ValueError):
                ToolSpec(name, 'fixture', args, risk)
        with self.assertRaises(ValueError):
            ArgumentSpec('string')


class ToolManagerTests(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.tool = EchoTool()
        self.registry.register(self.tool)
        self.policy = Mock(spec=PermissionPolicy)
        self.policy.evaluate.return_value = PermissionDecision.ALLOW
        self.manager = ToolManager(self.registry, self.policy)

    def request(self, arguments=None):
        return ToolRequest('echo', arguments if arguments is not None else {'text': 'hello'})

    def test_success_has_structured_data_identity_and_timing(self):
        request = self.request()
        result = self.manager.execute(request)
        self.assertIsInstance(result, ToolResult)
        self.assertTrue(result.success)
        self.assertEqual(result.status, ToolStatus.SUCCESS)
        self.assertEqual(result.data['echo'], 'hello')
        self.assertEqual(result.tool_name, request.tool_name)
        self.assertEqual(result.request_id, request.request_id)
        self.assertEqual(result.requested_at, request.created_at)
        self.assertLessEqual(result.requested_at, result.started_at)
        self.assertLessEqual(result.started_at, result.finished_at)
        self.assertIsNone(result.error)
        self.assertEqual(self.tool.calls, 1)
        self.policy.evaluate.assert_called_once_with(self.tool.spec, request)

    def test_unknown_tool_fails_before_policy_or_execution(self):
        request = ToolRequest('missing', {})
        result = self.manager.execute(request)
        self.assertEqual(result.status, ToolStatus.UNKNOWN_TOOL)
        self.assertEqual(result.request_id, request.request_id)
        self.assertFalse(result.success)
        self.assertEqual(self.tool.calls, 0)
        self.policy.evaluate.assert_not_called()

    def test_invalid_missing_wrong_extra_null_arguments(self):
        for arguments in ({}, {'text': 4}, {'text': None}, {'text': 'ok', 'extra': 'bad'}):
            with self.subTest(arguments=arguments):
                result = self.manager.execute(self.request(arguments))
                self.assertEqual(result.status, ToolStatus.INVALID_ARGUMENTS)
                self.assertFalse(result.success)
        self.assertEqual(self.tool.calls, 0)
        self.policy.evaluate.assert_not_called()

    def test_all_declared_types_validate_without_coercion(self):
        arguments = {kind.value: ArgumentSpec(kind) for kind in ArgumentType}
        tool = EchoTool('typed', arguments=arguments)
        self.registry.register(tool)
        values = {'string': 'value', 'integer': 1, 'number': 2.5, 'boolean': True,
                  'object': {'key': 'value'}, 'array': [1, 'two']}
        self.assertTrue(self.manager.execute(ToolRequest('typed', values)).success)
        values['number'] = 2
        self.assertTrue(self.manager.execute(ToolRequest('typed', values)).success)
        for key, invalid in (('string', 1), ('integer', True), ('number', False),
                             ('boolean', 1), ('object', []), ('array', {})):
            invalid_values = dict(values, **{key: invalid})
            result = self.manager.execute(ToolRequest('typed', invalid_values))
            self.assertEqual(result.status, ToolStatus.INVALID_ARGUMENTS)
        self.assertEqual(tool.calls, 2)

    def test_optional_argument_may_be_omitted(self):
        optional = EchoTool('optional', arguments={'text': ArgumentSpec(ArgumentType.STRING, required=False)})
        self.registry.register(optional)
        self.assertTrue(self.manager.execute(ToolRequest('optional', {})).success)
        self.assertEqual(optional.received, {})

    def test_denied_tool_is_never_called(self):
        self.policy.evaluate.return_value = PermissionDecision.DENY
        result = self.manager.execute(self.request())
        self.assertEqual(result.status, ToolStatus.DENIED)
        self.assertIsNone(result.data)
        self.assertEqual(self.tool.calls, 0)

    def test_approval_required_is_not_executed(self):
        self.policy.evaluate.return_value = PermissionDecision.REQUIRE_USER_APPROVAL
        result = self.manager.execute(self.request())
        self.assertEqual(result.status, ToolStatus.APPROVAL_REQUIRED)
        self.assertFalse(result.success)
        self.assertEqual(self.tool.calls, 0)

    def test_policy_failure_is_safe_and_never_executes(self):
        self.policy.evaluate.side_effect = RuntimeError('secret policy implementation')
        result = self.manager.execute(self.request())
        self.assertEqual(result.status, ToolStatus.FAILED)
        self.assertNotIn('secret', result.error)
        self.assertEqual(self.tool.calls, 0)

    def test_invalid_policy_decisions_fail_closed(self):
        for decision in ('allow', None, True, object()):
            self.policy.evaluate.return_value = decision
            self.assertEqual(self.manager.execute(self.request()).status, ToolStatus.FAILED)
        self.assertEqual(self.tool.calls, 0)

    def test_tool_exceptions_are_safe_and_manager_recovers(self):
        self.tool.failure = RuntimeError('/private/implementation secret token')
        result = self.manager.execute(self.request())
        self.assertEqual(result.status, ToolStatus.FAILED)
        self.assertEqual(result.error, 'Tool execution failed.')
        self.assertIsNone(result.data)
        self.tool.failure = None
        self.assertTrue(self.manager.execute(self.request()).success)

    def test_tool_and_policy_interrupts_propagate(self):
        for failure in (KeyboardInterrupt(), SystemExit()):
            self.tool.failure = failure
            with self.assertRaises(type(failure)):
                self.manager.execute(self.request())
            self.tool.failure = None
            self.policy.evaluate.side_effect = failure
            calls_before = self.tool.calls
            with self.assertRaises(type(failure)):
                self.manager.execute(self.request())
            self.assertEqual(self.tool.calls, calls_before)
            self.policy.evaluate.side_effect = None

    def test_policy_cannot_mutate_active_request(self):
        def mutate(spec, request):
            request.arguments['text'] = 'changed'
            return PermissionDecision.ALLOW
        self.policy.evaluate.side_effect = mutate
        self.assertEqual(self.manager.execute(self.request()).status, ToolStatus.FAILED)
        self.assertEqual(self.tool.calls, 0)

    def test_output_is_copied_and_immutable(self):
        output = {'values': [{'text': 'original'}]}
        self.tool.execute = Mock(return_value=output)
        result = self.manager.execute(self.request())
        output['values'][0]['text'] = 'changed'
        self.assertEqual(result.data['values'][0]['text'], 'original')
        with self.assertRaises(TypeError):
            result.data['values'][0]['text'] = 'changed'
        with self.assertRaises(FrozenInstanceError):
            result.status = ToolStatus.DENIED

    def test_invalid_tool_output_becomes_safe_failure(self):
        for output in (object(), {'bad': math.nan}):
            self.tool.execute = Mock(return_value=output)
            result = self.manager.execute(self.request())
            self.assertEqual(result.status, ToolStatus.FAILED)
            self.assertIsNone(result.data)

    def test_non_request_is_programmer_error(self):
        with self.assertRaises(TypeError):
            self.manager.execute({'tool_name': 'echo'})
        self.assertEqual(self.tool.calls, 0)


class PermissionTests(unittest.TestCase):
    def test_default_risk_decisions_and_execution_counts(self):
        registry = ToolRegistry()
        manager = ToolManager(registry)
        expected = {RiskLevel.READ_ONLY: ToolStatus.SUCCESS, RiskLevel.WRITE: ToolStatus.APPROVAL_REQUIRED,
                    RiskLevel.EXECUTE: ToolStatus.APPROVAL_REQUIRED, RiskLevel.PRIVILEGED: ToolStatus.DENIED}
        for risk, status in expected.items():
            tool = EchoTool(risk.value, risk)
            registry.register(tool)
            result = manager.execute(ToolRequest(tool.spec.name, {'text': 'test'}))
            self.assertEqual(result.status, status)
            self.assertEqual(tool.calls, int(status is ToolStatus.SUCCESS))

    def test_override_is_copied_and_requires_valid_enums(self):
        overrides = {RiskLevel.READ_ONLY: PermissionDecision.DENY}
        policy = RiskPermissionPolicy(overrides)
        overrides.clear()
        registry = ToolRegistry()
        tool = EchoTool()
        registry.register(tool)
        self.assertEqual(ToolManager(registry, policy).execute(ToolRequest('echo', {'text': 'test'})).status,
                         ToolStatus.DENIED)
        self.assertEqual(tool.calls, 0)
        with self.assertRaises(ValueError):
            RiskPermissionPolicy({'read_only': 'allow'})

    def test_explicit_policy_applies_even_if_falsey(self):
        class DenyPolicy(PermissionPolicy):
            def __bool__(self):
                return False
            def evaluate(self, spec, request):
                return PermissionDecision.DENY
        registry = ToolRegistry()
        tool = EchoTool()
        registry.register(tool)
        result = ToolManager(registry, DenyPolicy()).execute(ToolRequest('echo', {'text': 'test'}))
        self.assertEqual(result.status, ToolStatus.DENIED)
        self.assertEqual(tool.calls, 0)
