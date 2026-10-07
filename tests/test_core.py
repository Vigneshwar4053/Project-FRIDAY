import unittest
from unittest.mock import Mock

from friday.config.settings import Settings
from friday.core.assistant import FridayAssistant
from friday.providers.base import ModelProvider, ProviderError


class AssistantTests(unittest.TestCase):
    def setUp(self):
        self.provider = Mock(spec=ModelProvider)
        self.provider.chat.return_value = ' Answer '
        self.assistant = FridayAssistant(self.provider, 'System')

    def test_interface_is_abstract(self):
        with self.assertRaises(TypeError):
            ModelProvider()

    def test_successful_history_and_followup(self):
        self.assertEqual(self.assistant.respond(' Hello '), 'Answer')
        self.assistant.respond('Next')
        self.assertEqual(self.provider.chat.call_args.args[0], [
            {'role': 'system', 'content': 'System'},
            {'role': 'user', 'content': 'Hello'},
            {'role': 'assistant', 'content': 'Answer'},
            {'role': 'user', 'content': 'Next'},
        ])
        self.assertEqual(len(self.assistant.messages), 5)

    def test_failure_and_interrupt_preserve_history(self):
        for failure in (ProviderError('offline'), KeyboardInterrupt()):
            with self.subTest(failure=type(failure)):
                self.provider.chat.side_effect = failure
                with self.assertRaises(type(failure)):
                    self.assistant.respond('Hello')
                self.assertEqual(self.assistant.messages, [
                    {'role': 'system', 'content': 'System'}])

    def test_empty_reply_preserves_history(self):
        for reply in ('', '  ', None):
            self.provider.chat.return_value = reply
            with self.assertRaises(ProviderError):
                self.assistant.respond('Hello')
            self.assertEqual(len(self.assistant.messages), 1)

    def test_blank_input_does_not_call_provider(self):
        with self.assertRaises(ValueError):
            self.assistant.respond('  ')
        self.provider.chat.assert_not_called()

    def test_provider_cannot_mutate_existing_history(self):
        def mutate(messages):
            messages[0]['content'] = 'Changed'
            return 'OK'
        self.provider.chat.side_effect = mutate
        self.assistant.respond('Hello')
        self.assertEqual(self.assistant.messages[0]['content'], 'System')

    def test_sessions_are_independent(self):
        other = FridayAssistant(self.provider, 'Other')
        self.assistant.respond('Hello')
        self.assertEqual(len(other.messages), 1)

    def test_identity_uses_settings(self):
        settings = Settings(assistant_name='FRIDAY', user_name='Vigneshwar')
        self.assertIn("FRIDAY, Vigneshwar's personal local AI assistant", settings.system_prompt)
        self.assertIn('no tools', settings.system_prompt)
        self.assertFalse(settings.ollama_think)
