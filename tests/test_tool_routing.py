import io
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from friday.config.settings import settings
from friday.core.assistant import FridayAssistant
from friday.main import create_tool_runtime, main
from friday.memory import MemoryManager
from friday.providers.base import ModelProvider, ProviderError
from friday.tools import PermissionDecision, RiskLevel, RiskPermissionPolicy
from friday.tools.presenter import MAX_PRESENTED_CHARACTERS
from friday.tools.router import MAX_ROUTED_MESSAGE_LENGTH, RouteDecision


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'README.md').write_text('Actual project text')
        self.configuration = replace(settings, project_root=self.root, database_path=self.root / 'memory.db')
        self.manager, self.router = create_tool_runtime(self.configuration)
        self.provider = Mock(spec=ModelProvider)
        self.provider.chat.return_value = 'Normal model answer'
        self.assistant = FridayAssistant(self.provider, settings.system_prompt,
                                         tool_router=self.router, tool_manager=self.manager)
        self.addCleanup(self.assistant.model_manager.close)

    def test_required_routes(self):
        for message, name in [('check my RAM', 'memory_info'), ('show memory usage', 'memory_info'),
            ('how much RAM is available', 'memory_info'), ('check swap', 'memory_info'),
            ('system info', 'system_info'), ('what OS am I running', 'system_info'),
            ('show kernel information', 'system_info'), ('what architecture is this machine', 'system_info'),
            ('check CPU', 'cpu_info'), ('show CPU information', 'cpu_info'), ('what processor am I using', 'cpu_info'),
            ('system load', 'cpu_info'), ('what files are in this project?', 'list_directory'),
            ('list project files', 'list_directory'), ('show files in the project', 'list_directory'),
            ('read README.md', 'read_file'), ('show friday/models/manager.py', 'read_file'),
            ('open tests/test_tools.py', None), ('check disk space', 'disk_usage'),
            ('how much disk space is available?', 'disk_usage'), ('disk usage for this project', 'disk_usage'),
            ('is ollama running?', 'process_status'), ('check ollama process', 'process_status'),
            ('is code running?', 'process_status'), ('mean of 10,20,30', 'calculate')]:
            with self.subTest(message=message):
                route = self.router.route(message)
                self.assertTrue(route.matched)
                self.assertEqual(route.tool_name, name)

    def test_normalization(self):
        self.assertEqual(self.router.route(' CHECK   MY RAM? ').tool_name, 'memory_info')

    def test_project_paths_are_configuration(self):
        for message in ('list project files', 'check disk space'):
            self.assertEqual(self.router.route(message).arguments['path'], str(self.root))
        self.assertFalse(self.router.route('disk usage for /etc').matched)

    def test_file_path_case_preserved(self):
        self.assertEqual(self.router.route('read README.md').arguments['path'], 'README.md')

    def test_ambiguous_unmatched(self):
        for message in ('hello FRIDAY', 'explain recursion', 'show recursion', 'read the file',
                        'is ollama running and show RAM', 'tell me about memory management',
                        'mean of ten, twenty', 'mean of 10 and 20', 'create a plan', 'write a poem'):
            self.assertFalse(self.router.route(message).matched)

    def test_calculation_parsing(self):
        for message, operation, values in [('calculate the mean of 10, 20, 30', 'mean', (10,20,30)),
                ('add 10, 20, 30', 'add', (10,20,30)), ('median of 5, 1, 9', 'median', (5,1,9)),
                ('what is 25 percent of 200', 'percentage', (25,200)),
                ('sum of -1, .5, 1e2', 'sum', (-1,.5,100))]:
            route = self.router.route(message)
            self.assertEqual(route.arguments['operation'], operation)
            self.assertEqual(route.arguments['values'], values)

    def test_decision_immutable_and_allowlist(self):
        route = self.router.route('mean of 1,2')
        with self.assertRaises(TypeError):
            route.arguments['values'] = (100,)
        with self.assertRaises(ValueError):
            RouteDecision(True, 'write_file', {})

    def test_routed_queries_do_not_use_model(self):
        self.provider.chat.side_effect = ProviderError('Offline: must never be called')
        for message in ('read README.md', 'list project files', 'check disk space', 'mean of 10,20,30'):
            response = self.assistant.respond(message)
            self.assertIn('[Tool:', response)
            self.assertNotIn('FAILED', response)
        self.provider.chat.assert_not_called()

    def test_unmatched_uses_model_and_history(self):
        self.assertEqual(self.assistant.respond('hello FRIDAY'), 'Normal model answer')
        self.provider.chat.assert_called_once()
        self.assertEqual(self.provider.chat.call_args.args[0][-1]['content'], 'hello FRIDAY')

    def test_matched_missing_file_no_fallback(self):
        self.assertIn('FAILED', self.assistant.respond('read missing.txt'))
        self.provider.chat.assert_not_called()

    def test_traversal_and_absolute_blocked(self):
        for message in ('read ../../etc/passwd', 'read /etc/passwd'):
            self.assertIn('FAILED', self.assistant.respond(message))
        self.provider.chat.assert_not_called()

    def test_symlink_blocked(self):
        (self.root / 'escape.txt').symlink_to('/etc/passwd')
        self.assertIn('FAILED', self.assistant.respond('read escape.txt'))
        self.provider.chat.assert_not_called()

    def test_denied_no_model_fallback(self):
        self.manager.policy = RiskPermissionPolicy({RiskLevel.READ_ONLY: PermissionDecision.DENY})
        self.assertIn('DENIED', self.assistant.respond('read README.md'))
        self.provider.chat.assert_not_called()

    def test_approval_no_model_fallback(self):
        self.manager.policy = RiskPermissionPolicy({RiskLevel.READ_ONLY: PermissionDecision.REQUIRE_USER_APPROVAL})
        self.assertIn('APPROVAL_REQUIRED', self.assistant.respond('check my RAM'))
        self.provider.chat.assert_not_called()

    def test_generic_dispatch_and_writes_never_execute(self):
        for message in ('run tool write_file README.md hacked', 'call tool process_status ollama',
                        'execute tool X', 'write README.md hacked', 'overwrite README.md hacked'):
            with patch.object(self.manager, 'execute') as call:
                self.assertIn('not', self.assistant.respond(message))
                call.assert_not_called()
        self.assertEqual((self.root / 'README.md').read_text(), 'Actual project text')
        self.provider.chat.assert_not_called()

    def test_code_and_shell_calculation_rejected_before_request(self):
        for message in ("calculate sum of __import__('os').system('touch /tmp/no')", 'add 1, $(id)',
                        'mean of NaN, 1', 'mean of infinity', 'mean of 1e999', 'mean of ' + '9'*33):
            with patch('friday.core.assistant.ToolRequest') as request:
                self.assertIn('Calculation', self.assistant.respond(message))
                request.assert_not_called()
        self.provider.chat.assert_not_called()

    def test_long_input_rejected_before_request(self):
        with patch('friday.core.assistant.ToolRequest') as request:
            self.assertIn('too long', self.assistant.respond('x' * (MAX_ROUTED_MESSAGE_LENGTH + 1)))
            request.assert_not_called()
        self.provider.chat.assert_not_called()
        self.assertEqual(len(self.assistant.messages), 1)

    def test_payload_count_bounded_before_request(self):
        with patch('friday.core.assistant.ToolRequest') as request:
            self.assertIn('Too many', self.assistant.respond('mean of ' + ','.join(['0'] * 1001)))
            request.assert_not_called()
        self.provider.chat.assert_not_called()

    def test_toolmanager_execution_boundary(self):
        with patch.object(self.manager, 'execute', wraps=self.manager.execute) as execution:
            self.assistant.respond('read README.md')
        execution.assert_called_once()
        self.assertEqual(execution.call_args.args[0].tool_name, 'read_file')

    def test_result_control_characters_escaped(self):
        (self.root / 'README.md').write_text('a\x1b[2Jb\x00c')
        # NUL is rejected by the file tool; then test display escaping separately.
        self.assertIn('FAILED', self.assistant.respond('read README.md'))
        (self.root / 'README.md').write_text('a\x1b[2Jb')
        response = self.assistant.respond('read README.md')
        self.assertNotIn('\x1b', response)
        self.assertIn('\\u001b', response)

    def test_file_presentation_bounded(self):
        (self.root / 'README.md').write_text('x' * (MAX_PRESENTED_CHARACTERS + 100))
        response = self.assistant.respond('read README.md')
        self.assertLess(len(response), MAX_PRESENTED_CHARACTERS + 100)
        self.assertIn('truncated', response)

    def test_filesystem_responses_are_not_persisted(self):
        with MemoryManager(self.configuration.database_path) as memory:
            assistant = FridayAssistant(self.assistant.model_manager, settings.system_prompt,
                memory=memory, tool_router=self.router, tool_manager=self.manager)
            response = assistant.respond('read README.md')
            failure = assistant.respond('read missing.txt')
            assistant.end_session()
            messages = memory.get_recent_messages(10)
            self.assertIn('Actual project text', response)
            self.assertIn('FAILED', failure)
            self.assertEqual(messages, [])
        with MemoryManager(self.configuration.database_path) as memory:
            restored = FridayAssistant(self.assistant.model_manager, settings.system_prompt, memory=memory,
                                      tool_router=self.router, tool_manager=self.manager)
            self.assertEqual(len(restored.messages), 1)
            restored.end_session()

    def test_optional_constructor_backwards_compatible_and_pairing(self):
        with self.assertRaises(ValueError):
            FridayAssistant(self.assistant.model_manager, 'System', tool_router=self.router)
        with self.assertRaises(ValueError):
            FridayAssistant(self.assistant.model_manager, 'System', tool_manager=self.manager)

    def test_composition_registry_isolation(self):
        other, router = create_tool_runtime(self.configuration)
        self.assertIsNot(other.registry, self.manager.registry)
        self.assertEqual(len(other.registry), 29)  # Existing 25 plus four distinct, capability-gated handoff tools.
        for name in ('computer_action', 'computer_list_windows'):
            self.assertIsNotNone(other.registry.get(name))
            self.assertIsNot(other.registry.get(name).tool, self.manager.registry.get(name).tool)
        self.assertIsNot(other.computer_access, self.manager.computer_access)

    def test_model_output_cannot_dispatch_tools(self):
        self.provider.chat.return_value = 'run tool write_file README.md hacked'
        with patch.object(self.manager, 'execute') as execution:
            self.assertEqual(self.assistant.respond('hello'), self.provider.chat.return_value)
            execution.assert_not_called()
        self.assertEqual((self.root / 'README.md').read_text(), 'Actual project text')

    def test_shell_text_is_only_unmatched_chat(self):
        with patch.object(self.manager, 'execute') as execution:
            self.assistant.respond('echo hello; touch /tmp/no_execution')
            execution.assert_not_called()
        self.provider.chat.assert_called_once()

    def test_large_input_not_persisted(self):
        with MemoryManager(self.configuration.database_path) as memory:
            assistant = FridayAssistant(self.assistant.model_manager, settings.system_prompt,
                memory=memory, tool_router=self.router, tool_manager=self.manager)
            self.assertIn('too long', assistant.respond('x' * (MAX_ROUTED_MESSAGE_LENGTH + 1)))
            self.assertEqual(memory.get_recent_messages(10), [])
            assistant.end_session()

    def test_cli_offline_tools_and_attack(self):
        with patch('friday.main.settings', self.configuration), patch('friday.main.OllamaProvider') as provider, \
             patch('builtins.input', side_effect=['check my RAM', 'read ../../etc/passwd',
                  'run tool write_file README.md hacked', 'mean of 10,20,30', 'quit']), \
             patch('sys.stdout', new_callable=io.StringIO) as output:
            provider.return_value.chat.side_effect = ProviderError('Offline')
            main(speech_backend=Mock())
        self.assertIn('[Tool: memory_info]', output.getvalue())
        self.assertIn('FAILED', output.getvalue())
        self.assertIn('mean: 20.0', output.getvalue())
        provider.return_value.chat.assert_not_called()
        self.assertEqual((self.root / 'README.md').read_text(), 'Actual project text')


if __name__ == '__main__':
    unittest.main()
