import math
import unittest
from unittest.mock import patch

from friday.tools import (PermissionDecision, RiskLevel, RiskPermissionPolicy,
                          ToolManager, ToolRegistry, ToolRequest, ToolStatus)
from friday.tools.computation import (MAX_EXPONENT_MAGNITUDE, MAX_NUMERIC_MAGNITUDE,
                                      MAX_VALUES, register_computation_tools)


class ComputationTests(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        register_computation_tools(self.registry)
        self.manager = ToolManager(self.registry)

    def calculate(self, operation, values):
        return self.manager.execute(ToolRequest('calculate', {'operation': operation, 'values': values}))

    def success(self, operation, values, expected):
        result = self.calculate(operation, values)
        self.assertIs(result.status, ToolStatus.SUCCESS)
        self.assertEqual(result.data['result'], expected)
        self.assertEqual(result.data['operation'], operation)
        self.assertEqual(result.data['input_count'], len(values))

    def failure(self, operation, values):
        result = self.calculate(operation, values)
        self.assertIs(result.status, ToolStatus.FAILED)
        self.assertIsNone(result.data)
        self.assertEqual(result.error, 'Tool execution failed.')

    def test_add(self):
        self.success('add', [10, 20, 30], 60)

    def test_subtract(self):
        self.success('subtract', [20, 5], 15)

    def test_multiply(self):
        self.success('multiply', [2, 3, 4], 24)

    def test_divide(self):
        self.success('divide', [10, 4], 2.5)

    def test_power(self):
        self.success('power', [2, 10], 1024)
        self.success('power', [4, .5], 2)
        self.success('power', [2, -2], .25)

    def test_sum(self):
        self.success('sum', [1, -2, 3], 2)

    def test_mean(self):
        self.success('mean', [10, 20, 30], 20)

    def test_median(self):
        self.success('median', [5, 1, 9, 3, 7], 5)
        self.success('median', [4, 1, 3, 2], 2.5)

    def test_min_max(self):
        self.success('min', [-4, 1, 10], -4)
        self.success('max', [-4, 1, 10], 10)

    def test_count(self):
        self.success('count', [4, 5, 6], 3)

    def test_sort(self):
        self.success('sort', [4, -1, 3.5], (-1, 3.5, 4))

    def test_percentage(self):
        self.success('percentage', [25, 200], 12.5)

    def test_empty_inputs(self):
        for operation in ('add', 'subtract', 'multiply', 'divide', 'power', 'mean', 'median', 'min', 'max', 'percentage'):
            self.failure(operation, [])
        self.success('sum', [], 0)
        self.success('count', [], 0)
        self.success('sort', [], ())

    def test_binary_arity(self):
        for operation in ('subtract', 'divide', 'power', 'percentage'):
            self.failure(operation, [1])
            self.failure(operation, [1, 2, 3])

    def test_unknown_operation(self):
        for operation in ('unknown', 'eval', '__import__', 'ADD', 'add(1,2)'):
            self.failure(operation, [1, 2])

    def test_strings_and_code_are_not_numbers(self):
        for value in ('10', "__import__('os').system('touch /tmp/friday_should_not_exist')"):
            self.failure('sum', [value])

    def test_booleans_and_nested_values(self):
        for value in (True, False, None, [1], {'value': 1}):
            self.failure('count', [value])

    def test_nan_and_infinity_rejected_at_request_boundary(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.assertRaises(ValueError):
                ToolRequest('calculate', {'operation': 'sum', 'values': [value]})

    def test_value_count_limit(self):
        self.success('count', [0] * MAX_VALUES, MAX_VALUES)
        self.failure('count', [0] * (MAX_VALUES + 1))

    def test_magnitude_limit(self):
        for value in (MAX_NUMERIC_MAGNITUDE + 1, -MAX_NUMERIC_MAGNITUDE - 1, 10**10000):
            self.failure('sum', [value])
        self.success('min', [MAX_NUMERIC_MAGNITUDE], MAX_NUMERIC_MAGNITUDE)

    def test_exponent_limit(self):
        self.success('power', [1, MAX_EXPONENT_MAGNITUDE], 1)
        for exponent in (MAX_EXPONENT_MAGNITUDE + 1, -MAX_EXPONENT_MAGNITUDE - 1, 999999999):
            self.failure('power', [999999999, exponent])

    def test_zero_denominators(self):
        self.failure('divide', [1, 0])
        self.failure('percentage', [1, -0.0])

    def test_power_real_domain_and_overflow(self):
        for values in ([-1, .5], [0, -1], [MAX_NUMERIC_MAGNITUDE, MAX_EXPONENT_MAGNITUDE], [2, 50]):
            self.failure('power', values)

    def test_bounded_results(self):
        for operation, values in [('sum', [MAX_NUMERIC_MAGNITUDE] * 2),
                                  ('subtract', [MAX_NUMERIC_MAGNITUDE, -MAX_NUMERIC_MAGNITUDE]),
                                  ('multiply', [MAX_NUMERIC_MAGNITUDE, 2]),
                                  ('divide', [1, 1e-300]),
                                  ('percentage', [MAX_NUMERIC_MAGNITUDE, 1])]:
            self.failure(operation, values)

    def test_multiply_intermediate_limit(self):
        self.failure('multiply', [MAX_NUMERIC_MAGNITUDE, 2, 0])

    def test_schema_errors_do_not_execute(self):
        for args in ({}, {'operation': 'sum'}, {'operation': 3, 'values': [1]},
                     {'operation': 'sum', 'values': '1+2'},
                     {'operation': 'sum', 'values': [1], 'code': 'print(1)'},
                     {'code': 'print(1)'}):
            with patch.object(self.registry.get('calculate').tool, 'execute') as call:
                result = self.manager.execute(ToolRequest('calculate', args))
                self.assertIs(result.status, ToolStatus.INVALID_ARGUMENTS)
                call.assert_not_called()

    def test_risk_and_permissions(self):
        tool = self.registry.get('calculate').tool
        self.assertIs(tool.spec.risk, RiskLevel.READ_ONLY)
        for decision, status in ((PermissionDecision.DENY, ToolStatus.DENIED),
                                 (PermissionDecision.REQUIRE_USER_APPROVAL, ToolStatus.APPROVAL_REQUIRED)):
            manager = ToolManager(self.registry, RiskPermissionPolicy({RiskLevel.READ_ONLY: decision}))
            with patch.object(tool, 'execute') as call:
                result = manager.execute(ToolRequest('calculate', {'operation': 'add', 'values': [1]}))
                self.assertIs(result.status, status)
                call.assert_not_called()

    def test_identity_and_input_isolation(self):
        values = [3, 1, 2]
        request = ToolRequest('calculate', {'operation': 'sort', 'values': values})
        values.append(100)
        result = self.manager.execute(request)
        self.assertEqual(result.data['result'], (1, 2, 3))
        self.assertEqual(result.request_id, request.request_id)
        self.assertEqual(result.tool_name, 'calculate')
        self.assertEqual(result.requested_at, request.created_at)

    def test_failure_does_not_break_next_request(self):
        self.failure('divide', [1, 0])
        self.success('add', [1, 2], 3)

    def test_registration_explicit_and_duplicate_rejected(self):
        self.assertEqual(len(ToolRegistry()), 0)
        with self.assertRaises(ValueError):
            register_computation_tools(self.registry)


if __name__ == '__main__':
    unittest.main()
