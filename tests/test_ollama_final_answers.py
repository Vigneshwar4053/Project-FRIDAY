from unittest.mock import Mock
"""Offline response-boundary regressions: never save incomplete deliberation."""
import io
import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from friday.config.settings import settings
from friday.core.assistant import FridayAssistant
from friday.models.profile import InferenceProfile, deep_profile
from friday.providers.base import ProviderError
from friday.providers.ollama import OllamaProvider


class FinalAnswerTests(unittest.TestCase):
    def setUp(self):
        self.provider = OllamaProvider('http://127.0.0.1:11434', 'qwen3:4b', think=True)
        self.response = MagicMock()
        self.patch = patch('friday.providers.ollama.urllib.request.urlopen')
        self.http = self.patch.start()
        self.addCleanup(self.patch.stop)
        self.http.return_value.__enter__.return_value = self.response
        self.messages = [{'role': 'user', 'content': 'Public question'}]

    def reply(self, content, **metadata):
        self.response.read.return_value = json.dumps({
            'message': {'content': content, 'thinking': 'PRIVATE_TRACE'}, **metadata}).encode()

    def test_standard_explicitly_disables_thinking(self):
        self.reply('Final answer', done=True, done_reason='stop')
        with self.provider.inference_profile(InferenceProfile()):
            self.assertEqual(self.provider.chat(self.messages), 'Final answer')
        self.assertIs(json.loads(self.http.call_args.args[0].data)['think'], False)

    def test_explicit_deep_thinking_returns_only_final(self):
        self.reply('<think>PRIVATE_TRACE</think>Final answer', done=True, done_reason='stop')
        with self.provider.inference_profile(replace(deep_profile(), think=True)):
            self.assertEqual(self.provider.chat(self.messages), 'Final answer')
        payload = json.loads(self.http.call_args.args[0].data)
        self.assertIs(payload['think'], True)
        self.assertEqual(payload['options']['num_predict'], 2048)
        self.assertIsNone(self.provider._profile)

    def test_intent_still_disables_thinking_even_with_deep_profile(self):
        self.reply('{"kind":"chat","response":"Public answer"}', done=True, done_reason='stop')
        with self.provider.intent_mode(), self.provider.inference_profile(deep_profile()):
            self.provider.chat(self.messages)
        self.assertIs(json.loads(self.http.call_args.args[0].data)['think'], False)

    def test_length_stop_rejected_for_both_levels_without_retry(self):
        for profile in (InferenceProfile(), deep_profile()):
            with self.subTest(profile=profile):
                self.http.reset_mock()
                self.reply('Apparently useful but partial PRIVATE_TRACE', done=True, done_reason='length')
                with self.provider.inference_profile(profile), self.assertRaisesRegex(ProviderError, 'output-token limit') as error:
                    self.provider.chat(self.messages)
                self.assertNotIn('PRIVATE_TRACE', str(error.exception))
                self.http.assert_called_once()

    def test_incomplete_or_invalid_stop_rejected(self):
        for metadata in ({'done':False}, {'done':1}, {'done_reason':'unexpected'}, {'done_reason':[]}):
            with self.subTest(metadata=metadata):
                self.reply('PRIVATE_TRACE', **metadata)
                with self.assertRaises(ProviderError): self.provider.chat(self.messages)

    def test_unmarked_observed_reasoning_is_rejected(self):
        for content in ('Okay, the user is asking who they are. Let me think...',
                        'Let me think about this. PRIVATE_TRACE',
                        'I need to answer the question. PRIVATE_TRACE',
                        'The user wants an answer. PRIVATE_TRACE'):
            for profile in (InferenceProfile(), deep_profile()):
                with self.subTest(content=content, profile=profile):
                    self.reply(content, done=True, done_reason='stop')
                    with self.provider.inference_profile(profile), self.assertRaises(ProviderError):
                        self.provider.chat(self.messages)

    def test_thinking_only_never_becomes_answer(self):
        for profile in (InferenceProfile(), deep_profile()):
            for content in ('', '<think>PRIVATE_TRACE', 'PRIVATE_TRACE</think>'):
                self.reply(content, done=True, done_reason='stop')
                with self.provider.inference_profile(profile), self.assertRaises(ProviderError):
                    self.provider.chat(self.messages)

    def test_valid_plain_and_orphan_final_preserved(self):
        for content, expected in (('I can help with Python.', 'I can help with Python.'),
                                  ('PRIVATE_TRACE</think>You are the configured project owner.',
                                   'You are the configured project owner.')):
            self.reply(content, done=True, done_reason='stop')
            self.assertEqual(self.provider.chat(self.messages), expected)

    def test_thinking_setting_requires_boolean(self):
        for value in ('false', 1, None):
            with self.assertRaises(ValueError): InferenceProfile(think=value)

    def test_failed_l2_and_l3_do_not_save_or_retain_reasoning(self):
        for request in ('do you know who am i', 'think deeply about recursion'):
            assistant = FridayAssistant(self.provider, 'Public system', workload_configuration=replace(settings, adaptive_workloads=True))
            memory = MagicMock()
            assistant.memory = memory
            self.reply('Okay, the user is asking. PRIVATE_TRACE', done=True, done_reason='length')
            with self.assertRaises(ProviderError): assistant.respond(request)
            memory.save_turn.assert_not_called()
            self.assertNotIn('PRIVATE_TRACE', repr(assistant.messages))
            self.assertIsNone(assistant.model_manager.last_job.result)
            self.assertNotIn('PRIVATE_TRACE', assistant.model_manager.last_job.error)
            self.assertNotIn('PRIVATE_TRACE', repr(assistant.last_performance.public()))
            assistant.model_manager.close()

    def test_sqlite_and_cli_only_receive_verified_final_answer(self):
        from friday.main import main
        with TemporaryDirectory() as root:
            database = Path(root) / 'memory.db'
            config = replace(settings, database_path=database, adaptive_workloads=True)
            self.reply('Okay, the user is asking. PRIVATE_TRACE', done=True, done_reason='length')
            with patch('friday.main.settings', config), patch('builtins.input', side_effect=['do you know who am i','exit']), patch('sys.stdout', new_callable=io.StringIO) as output:
                main(speech_backend=Mock())
            self.assertNotIn('PRIVATE_TRACE', output.getvalue())
            self.assertIn('output-token limit', output.getvalue())
            import sqlite3
            from contextlib import closing
            with closing(sqlite3.connect(database)) as connection:
                self.assertNotIn('PRIVATE_TRACE', repr(connection.execute('SELECT * FROM messages').fetchall()))
