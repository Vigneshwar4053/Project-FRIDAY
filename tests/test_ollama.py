import json
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from friday.providers.base import ProviderError
from friday.providers.ollama import OllamaProvider


class OllamaTests(unittest.TestCase):
    def setUp(self):
        self.provider = OllamaProvider('http://127.0.0.1:11434/', 'qwen3:4b', timeout=12)
        self.messages = [{'role': 'user', 'content': 'Hi'}]
        self.patch = patch('friday.providers.ollama.urllib.request.urlopen')
        self.urlopen = self.patch.start()
        self.addCleanup(self.patch.stop)
        self.response = MagicMock()
        self.urlopen.return_value.__enter__.return_value = self.response

    def reply(self, value):
        self.response.read.return_value = json.dumps(value).encode()

    def test_request_and_final_content_only(self):
        self.reply({'message': {'content': ' Hello ', 'thinking': 'private reasoning'}})
        self.assertEqual(self.provider.chat(self.messages), 'Hello')
        request = self.urlopen.call_args.args[0]
        self.assertEqual(request.full_url, 'http://127.0.0.1:11434/api/chat')
        self.assertEqual(request.get_method(), 'POST')
        self.assertEqual(request.get_header('Content-type'), 'application/json')
        self.assertEqual(json.loads(request.data), {
            'model': 'qwen3:4b', 'messages': self.messages, 'stream': False, 'think': False})
        self.assertEqual(self.urlopen.call_args.kwargs['timeout'], 12)

    def test_network_and_timeout_errors(self):
        for error in (urllib.error.URLError('refused'), TimeoutError(), OSError('reset')):
            with self.subTest(error=type(error)):
                self.urlopen.side_effect = error
                with self.assertRaises(ProviderError):
                    self.provider.chat(self.messages)

    def test_http_errors(self):
        for code in (404, 500):
            self.urlopen.side_effect = urllib.error.HTTPError('url', code, 'error', {}, None)
            with self.assertRaisesRegex(ProviderError, 'not found' if code == 404 else 'HTTP 500'):
                self.provider.chat(self.messages)

    def test_invalid_json_and_encoding(self):
        for body in (b'not json', b'\xff'):
            self.response.read.return_value = body
            with self.assertRaises(ProviderError):
                self.provider.chat(self.messages)

    def test_invalid_or_thinking_only_response(self):
        for value in (None, [], {}, {'error': 'bad'}, {'message': []},
                      {'message': {'content': 1}}, {'message': {'content': ' '}},
                      {'message': {'thinking': 'private'}}):
            with self.subTest(value=value):
                self.reply(value)
                with self.assertRaises(ProviderError):
                    self.provider.chat(self.messages)

    def test_observed_orphan_close_returns_only_greeting(self):
        self.reply({'message': {'role': 'assistant',
                               'content': 'Synthetic private reasoning\n</think>\n\nHello, Vigneshwar!'}})
        self.assertEqual(self.provider.chat(self.messages), 'Hello, Vigneshwar!')

    def test_embedded_complete_reasoning_blocks(self):
        for content, expected in (
            ('<think>Synthetic private reasoning</think>\nHello!', 'Hello!'),
            ('First paragraph.\n<think>private</think>\nLast paragraph.',
             'First paragraph.\n\nLast paragraph.'),
            ('<think>one</think>Hello<think>two</think> there!', 'Hello there!'),
            ('<THINK>private</THINK>Answer', 'Answer'),
            ('<think>outer<think>inner</think>outer</think>Answer', 'Answer'),
        ):
            with self.subTest(content=content):
                self.reply({'message': {'content': content, 'thinking': 'separate private text'}})
                self.assertEqual(self.provider.chat(self.messages), expected)

    def test_unclosed_reasoning_never_returned(self):
        self.reply({'message': {'content': 'Safe answer. <think>unfinished private text'}})
        self.assertEqual(self.provider.chat(self.messages), 'Safe answer.')
        for content in ('<think>private', '<think>private</think>',
                        'private</think>', 'private</think><think>more private'):
            with self.subTest(content=content):
                self.reply({'message': {'content': content}})
                with self.assertRaises(ProviderError) as error:
                    self.provider.chat(self.messages)
                self.assertNotIn('private', str(error.exception))

    def test_multiple_orphan_closings_discard_ambiguous_prefix(self):
        self.reply({'message': {'content': 'private</think>more private</think>Final answer'}})
        self.assertEqual(self.provider.chat(self.messages), 'Final answer')

    def test_plain_answer_preserved(self):
        content = 'Hello!\n\n```python\nprint("hello")\n```\nUse 2 < 3 and 5 > 4.'
        self.reply({'message': {'content': content}})
        self.assertEqual(self.provider.chat(self.messages), content)

    def test_only_clean_answer_enters_history_or_followup_request(self):
        from friday.core.assistant import FridayAssistant
        assistant = FridayAssistant(self.provider, 'System')
        self.reply({'message': {'content': 'private</think>Hello!', 'thinking': 'other private'}})
        self.assertEqual(assistant.respond('hello'), 'Hello!')
        self.assertEqual(assistant.messages[-1], {'role': 'assistant', 'content': 'Hello!'})
        self.reply({'message': {'content': 'Next answer'}})
        assistant.respond('next')
        sent = json.loads(self.urlopen.call_args.args[0].data)
        self.assertEqual(sent['messages'][2], {'role': 'assistant', 'content': 'Hello!'})
        self.assertNotIn('private', json.dumps(sent))

    def test_reasoning_only_failure_does_not_enter_history(self):
        from friday.core.assistant import FridayAssistant
        assistant = FridayAssistant(self.provider, 'System')
        self.reply({'message': {'content': 'private</think>', 'thinking': 'more private'}})
        with self.assertRaises(ProviderError):
            assistant.respond('hello')
        self.assertEqual(assistant.messages, [{'role': 'system', 'content': 'System'}])

    def test_cli_never_displays_embedded_reasoning(self):
        import io
        from dataclasses import replace
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from friday.config.settings import settings
        from friday.main import main
        self.reply({'message': {'content': 'synthetic private trace</think>Hello, Vigneshwar!'}})
        with TemporaryDirectory() as directory, \
             patch('friday.main.settings', replace(settings, database_path=Path(directory) / 'test.db')), \
             patch('builtins.input', side_effect=['hello', 'exit']), \
             patch('sys.stdout', new_callable=io.StringIO) as output:
            main()
        self.assertIn('FRIDAY: Hello, Vigneshwar!', output.getvalue())
        self.assertNotIn('synthetic private trace', output.getvalue())
        self.assertNotIn('</think>', output.getvalue())
