from unittest.mock import Mock
import io
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from friday.config.settings import settings
from friday.memory import MemoryManager
import unittest
from unittest.mock import patch

from friday.main import main
from friday.providers.base import ProviderError


class CLITests(unittest.TestCase):
    def run_cli(self, inputs, response='Hello'):
        with TemporaryDirectory() as directory, \
             patch('friday.main.settings', replace(settings, database_path=Path(directory) / 'test.db')), \
             patch('friday.main.OllamaProvider') as provider, \
             patch('builtins.input', side_effect=inputs), \
             patch('sys.stdout', new_callable=io.StringIO) as output:
            if isinstance(response, BaseException):
                provider.return_value.chat.side_effect = response
            else:
                provider.return_value.chat.return_value = response
            main(speech_backend=Mock())
            with MemoryManager(Path(directory) / 'test.db') as memory:
                self.assertIsNotNone(memory.get_most_recent_session().ended_at)
            return output.getvalue(), provider.return_value.chat.call_count

    def test_exit_aliases(self):
        for command in ('exit', 'quit', '/bye', ' EXIT '):
            output, calls = self.run_cli([command])
            self.assertIn('FRIDAY LOCAL AI', output)
            self.assertIn('Model: qwen3:4b', output)
            self.assertIn('Goodbye.', output)
            self.assertEqual(calls, 0)

    def test_stop_commands_do_not_call_model(self):
        for command in ('stop', '/stop', 'STOP'):
            output, calls = self.run_cli([command, 'quit'])
            self.assertIn('Computer-use STOP set', output)
            self.assertEqual(calls, 0)

    def test_malformed_stop_never_becomes_model_input(self):
        output, calls = self.run_cli(['stop now', '/stop now', 'quit'])
        self.assertIn('Usage: stop', output)
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
