"""Bounded predefined numerical operations, with no source-code interface."""
import math
import statistics

from friday.tools.base import Tool
from friday.tools.models import ArgumentSpec, ArgumentType, RiskLevel, ToolSpec

MAX_VALUES = 1000
MAX_NUMERIC_MAGNITUDE = 10**12
MAX_EXPONENT_MAGNITUDE = 100
OPERATIONS = frozenset({'add', 'subtract', 'multiply', 'divide', 'power',
                        'sum', 'mean', 'median', 'min', 'max', 'count', 'sort',
                        'percentage'})
_BINARY_OPERATIONS = frozenset({'subtract', 'divide', 'power', 'percentage'})
_EMPTY_OPERATIONS = frozenset({'sum', 'count', 'sort'})


def _bounded_number(value):
    if (type(value) not in (int, float) or
            not -MAX_NUMERIC_MAGNITUDE <= value <= MAX_NUMERIC_MAGNITUDE or
            (type(value) is float and not math.isfinite(value))):
        raise ValueError('A finite bounded real number is required.')
    return value


class CalculateTool(Tool):
    def __init__(self):
        super().__init__(ToolSpec('calculate', 'Perform a predefined bounded numerical operation.',
                         {'operation': ArgumentSpec(ArgumentType.STRING),
                          'values': ArgumentSpec(ArgumentType.ARRAY)}, RiskLevel.READ_ONLY))

    def execute(self, arguments):
        operation, values = arguments['operation'], arguments['values']
        if operation not in OPERATIONS or len(values) > MAX_VALUES:
            raise ValueError('Unsupported operation or too many operands.')
        if operation in _BINARY_OPERATIONS and len(values) != 2:
            raise ValueError('This operation requires exactly two operands.')
        if not values and operation not in _EMPTY_OPERATIONS:
            raise ValueError('This operation requires operands.')
        for value in values:
            _bounded_number(value)

        if operation in {'add', 'sum'}:
            result = math.fsum(values)
        elif operation == 'subtract':
            result = values[0] - values[1]
        elif operation == 'multiply':
            result = 1
            for value in values:
                result = _bounded_number(result * value)
        elif operation in {'divide', 'percentage'}:
            if values[1] == 0:
                raise ValueError('Zero denominator.')
            result = values[0] / values[1]
            if operation == 'percentage':
                result *= 100
        elif operation == 'power':
            base, exponent = values
            if abs(exponent) > MAX_EXPONENT_MAGNITUDE:
                raise ValueError('Exponent exceeds the limit.')
            # Fixed-size floating-point power avoids arbitrary-size integer powers.
            result = math.pow(base, exponent)
        elif operation == 'mean':
            result = statistics.fmean(values)
        elif operation == 'median':
            result = statistics.median(values)
        elif operation == 'min':
            result = min(values)
        elif operation == 'max':
            result = max(values)
        elif operation == 'count':
            result = len(values)
        else:  # The explicit whitelist leaves only sort.
            result = sorted(values)
        if operation != 'sort':
            _bounded_number(result)
        return {'operation': operation, 'result': result, 'input_count': len(values)}


def register_computation_tools(registry):
    """Explicit registration only; application calls must go through ToolManager."""
    registry.register(CalculateTool())
