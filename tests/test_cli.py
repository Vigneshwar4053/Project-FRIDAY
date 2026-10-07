import io
import unittest
from unittest.mock import patch

from friday.main import main
from friday.providers.base import ProviderError


class CLITests(unittest.TestCase):
    def run_cli(self, inputs, response='Hello'):
        with patch('friday.main.OllamaProvider') as provider, \
             patch('builtins.input', side_effect=inputs), \
             patch('sys.stdout', new_callable=io.StringIO) as output:
            if isinstance(response, BaseException):
                provider.return_value.chat.side_effect = response
            else:
                provider.return_value.chat.return_value = response
            main()
            return output.getvalue(), provider.return_value.chat.call_count

    def test_exit_aliases(self):
        for command in ('exit', 'quit', '/bye', ' EXIT '):
            output, calls = self.run_cli([command])
            self.assertIn('FRIDAY LOCAL AI', output)
            self.assertIn('Model: qwen3:4b', output)
            self.assertIn('Goodbye.', output)
            self.assertEqual(calls, 0)

    def test_ctrl_c_and_eof(self):
        for error in (KeyboardInterrupt(), EOFError()):
            output, calls = self.run_cli([error])
            self.assertIn('Goodbye.', output)
            self.assertEqual(calls, 0)

    def test_blank_then_conversation(self):
        output, calls = self.run_cli([' ', 'Hi', 'quit'])
        self.assertIn('FRIDAY: Hello', output)
        self.assertEqual(calls, 1)

    def test_connection_error_recovers(self):
        output, calls = self.run_cli(['Hi', 'quit'], ProviderError('offline'))
        self.assertIn('Error: offline', output)
        self.assertIn('Goodbye.', output)
        self.assertEqual(calls, 1)

    def test_interrupt_during_generation_exits(self):
        output, calls = self.run_cli(['Hi'], KeyboardInterrupt())
        self.assertIn('Goodbye.', output)
        self.assertEqual(calls, 1)
