from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, Mock, patch

from friday.core.assistant import FridayAssistant
from friday.memory import MemoryManager, MemoryStorageError
from friday.providers.base import ModelProvider, ProviderError
from friday.providers.ollama import OllamaProvider


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'data' / 'test.db'
        self.memory = MemoryManager(self.path)
        self.addCleanup(self.memory.close)

    def test_database_creation_and_schema(self):
        self.assertTrue(self.path.is_file())
        with closing(sqlite3.connect(self.path)) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertTrue({'sessions', 'messages', 'memories'} <= tables)
        self.assertIsNone(self.memory.get_most_recent_session())

    def test_sessions_start_end_and_latest(self):
        first = self.memory.start_session()
        self.assertIsNone(first.ended_at)
        self.assertTrue(first.started_at.endswith('+00:00'))
        self.memory.end_session(first.id)
        ended = self.memory.get_most_recent_session()
        self.assertIsNotNone(ended.ended_at)
        self.memory.end_session(first.id)
        self.assertEqual(self.memory.get_most_recent_session(), ended)
        second = self.memory.start_session()
        self.assertGreater(second.id, first.id)
        self.assertEqual(self.memory.get_most_recent_session(), second)

    def test_save_message_and_reopen(self):
        session = self.memory.start_session()
        saved = self.memory.save_message(session.id, 'user', "What's next? ' quoted")
        self.memory.store_memory('preferences', 'editor', 'vim', 3)
        self.memory.end_session(session.id)
        self.memory.close()
        with MemoryManager(self.path) as reopened:
            self.assertEqual(reopened.get_recent_messages(10), [saved])
            self.assertEqual(reopened.get_memory('preferences', 'editor').value, 'vim')
            self.assertEqual(reopened.get_most_recent_session().id, session.id)
            self.assertIsNotNone(reopened.get_most_recent_session().ended_at)

    def test_recent_order_limit_and_session_filter(self):
        first = self.memory.start_session()
        self.memory.save_turn(first.id, 'one', 'answer one')
        second = self.memory.start_session()
        self.memory.save_turn(second.id, 'two', 'answer two')
        recent = self.memory.get_recent_messages(3)
        self.assertEqual([m.content for m in recent], ['answer one', 'two', 'answer two'])
        self.assertEqual([m.id for m in recent], sorted(m.id for m in recent))
        self.assertEqual([m.content for m in self.memory.get_recent_messages(10, first.id)],
                         ['one', 'answer one'])
        self.assertEqual(self.memory.get_recent_messages(0), [])
        self.assertEqual(self.memory.get_recent_messages(10, 999), [])
        with self.assertRaises(ValueError):
            self.memory.get_recent_messages(-1)

    def test_key_value_upsert_retains_id_and_creation_time(self):
        created = self.memory.store_memory('preferences', 'editor', 'vim', 2)
        updated = self.memory.store_memory('preferences', 'editor', 'VS Code', 8)
        self.assertEqual(created.id, updated.id)
        self.assertEqual(created.created_at, updated.created_at)
        self.assertGreaterEqual(updated.updated_at, created.updated_at)
        self.assertEqual(updated.value, 'VS Code')
        self.assertEqual(updated.importance, 8)
        other = self.memory.store_memory('project', 'editor', 'nano')
        self.assertNotEqual(other.id, updated.id)
        self.assertIsNone(self.memory.get_memory('missing', 'editor'))
        with self.assertRaises(ValueError):
            self.memory.store_memory('preferences', 'editor', 'vim', 11)

    def test_reject_unknown_or_ended_session(self):
        session = self.memory.start_session()
        self.memory.end_session(session.id)
        for session_id in (session.id, 999):
            with self.assertRaises(MemoryStorageError):
                self.memory.save_turn(session_id, 'hello', 'answer')
            with self.assertRaises(MemoryStorageError):
                self.memory.save_message(session_id, 'user', 'hello')
        self.assertEqual(self.memory.get_recent_messages(10), [])

    def test_reject_invalid_messages(self):
        session = self.memory.start_session()
        for role, content in (('thinking', 'private'), ('user', ' '), ('assistant', '')):
            with self.assertRaises(ValueError):
                self.memory.save_message(session.id, role, content)
        self.assertEqual(self.memory.get_recent_messages(10), [])

    def test_turn_rolls_back_when_second_insert_fails(self):
        session = self.memory.start_session()
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("CREATE TRIGGER fail_assistant BEFORE INSERT ON messages "
                       "WHEN NEW.role = 'assistant' BEGIN SELECT RAISE(ABORT, 'test failure'); END")
            db.commit()
        with self.assertRaises(MemoryStorageError):
            self.memory.save_turn(session.id, 'hello', 'answer')
        self.assertEqual(self.memory.get_recent_messages(10), [])

    def test_closed_manager_and_invalid_database(self):
        self.memory.close()
        self.memory.close()
        with self.assertRaises(MemoryStorageError):
            self.memory.start_session()
        with self.assertRaises(MemoryStorageError):
            MemoryManager(Path(self.directory.name))


class AssistantMemoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'test.db'
        self.memory = MemoryManager(self.path)
        self.addCleanup(self.memory.close)
        self.provider = Mock(spec=ModelProvider)
        self.provider.chat.return_value = 'Answer'

    def assistant(self, limit=4):
        return FridayAssistant(self.provider, 'System', memory=self.memory, recent_memory_limit=limit)

    def test_startup_without_previous_session(self):
        assistant = self.assistant()
        self.assertIsNone(assistant.previous_session)
        self.assertEqual(assistant.messages, [{'role': 'system', 'content': 'System'}])
        self.assertEqual(self.memory.get_most_recent_session().id, assistant.session_id)

    def test_startup_restores_previous_context_in_new_session(self):
        previous = self.assistant()
        previous.respond('Remember my project is FRIDAY')
        previous.end_session()
        self.memory.close()
        with MemoryManager(self.path) as reopened:
            current = FridayAssistant(self.provider, 'System', memory=reopened, recent_memory_limit=4)
            self.assertEqual(current.previous_session.id, previous.session_id)
            self.assertNotEqual(current.session_id, previous.session_id)
            current.respond('Which project?')
            sent = self.provider.chat.call_args.args[0]
            self.assertEqual(sent[1:3], [
                {'role': 'user', 'content': 'Remember my project is FRIDAY'},
                {'role': 'assistant', 'content': 'Answer'},
            ])
            self.assertEqual(len(reopened.get_recent_messages(10, current.session_id)), 2)
            current.end_session()

    def test_successful_turn_persisted_before_return(self):
        assistant = self.assistant()
        assistant.respond(' Hello ')
        self.assertEqual([(m.role, m.content) for m in self.memory.get_recent_messages(10)],
                         [('user', 'Hello'), ('assistant', 'Answer')])

    def test_provider_failure_interrupt_and_empty_reply_save_nothing(self):
        assistant = self.assistant()
        for failure in (ProviderError('offline'), KeyboardInterrupt()):
            self.provider.chat.side_effect = failure
            with self.assertRaises(type(failure)):
                assistant.respond('hello')
        self.provider.chat.side_effect = None
        self.provider.chat.return_value = ' '
        with self.assertRaises(ProviderError):
            assistant.respond('hello')
        self.assertEqual(self.memory.get_recent_messages(10), [])
        self.assertEqual(len(assistant.messages), 1)

    def test_persistence_failure_leaves_history_unchanged(self):
        assistant = self.assistant()
        with patch.object(self.memory, 'save_turn', side_effect=MemoryStorageError('disk full')):
            with self.assertRaises(MemoryStorageError):
                assistant.respond('hello')
        self.assertEqual(self.memory.get_recent_messages(10), [])
        self.assertEqual(len(assistant.messages), 1)

    def test_context_bound_applies_to_startup_and_later_requests(self):
        first = self.assistant()
        for index in range(5):
            first.respond(str(index))
        first.end_session()
        second = self.assistant(limit=3)
        # Drop the orphan reply caused by the odd limit, preserving a full turn.
        self.assertEqual(len(second.messages), 3)
        for index in range(5):
            second.respond(f'next {index}')
            sent = self.provider.chat.call_args.args[0]
            self.assertLessEqual(len(sent), 5)  # system + at most 3 recent + current user
            self.assertEqual(sent[1]['role'], 'user')
        # All successful messages stay in SQLite even when model context is bounded.
        self.assertEqual(len(self.memory.get_recent_messages(100)), 20)

    def test_zero_limit_and_empty_intervening_session(self):
        first = self.assistant()
        first.respond('hello')
        first.end_session()
        empty = self.assistant()
        empty.end_session()
        third = self.assistant()
        self.assertEqual(third.previous_session.id, empty.session_id)
        self.assertEqual(third.messages[1]['content'], 'hello')
        disabled = self.assistant(limit=0)
        disabled.respond('current')
        sent = self.provider.chat.call_args.args[0]
        self.assertEqual(sent[1:], [{'role': 'user', 'content': 'current'}])
        self.assertIn('No prior-session conversation messages are included', sent[0]['content'])

    def test_sanitized_ollama_answer_is_only_assistant_content_persisted(self):
        provider = OllamaProvider('http://127.0.0.1:11434', 'qwen3:4b')
        assistant = FridayAssistant(provider, 'System', memory=self.memory)
        with patch('friday.providers.ollama.urllib.request.urlopen') as urlopen:
            response = MagicMock()
            urlopen.return_value.__enter__.return_value = response
            for content in ('synthetic private</think>Hello!', '<think>synthetic private</think>Hello!'):
                response.read.return_value = json.dumps({'message': {
                    'content': content, 'thinking': 'separate private'}}).encode()
                self.assertEqual(assistant.respond('hello'), 'Hello!')
            response.read.return_value = json.dumps({'message': {'content': 'private</think>'}}).encode()
            with self.assertRaises(ProviderError):
                assistant.respond('hello')
        saved = self.memory.get_recent_messages(20)
        self.assertEqual(len(saved), 4)
        self.assertEqual([m.content for m in saved if m.role == 'assistant'], ['Hello!', 'Hello!'])
        self.assertNotIn('private', repr(saved))
        with MemoryManager(self.path) as reopened:
            capturing = Mock(spec=ModelProvider)
            capturing.chat.return_value = 'Final answer'
            restarted = FridayAssistant(capturing, 'System', memory=reopened)
            restarted.respond('What did we discuss?')
            sent = capturing.chat.call_args.args[0]
            self.assertEqual([m['content'] for m in sent if m['role'] == 'assistant'],
                             ['Hello!', 'Hello!'])
            self.assertNotIn('private', repr(sent))
            self.assertNotIn('<think>', repr(sent))
            self.assertNotIn('</think>', repr(sent))
            restarted.end_session()

    def test_cross_session_request_has_exact_history_and_memory_provenance(self):
        from friday.config.settings import settings
        # Test fixtures only; no project-specific facts enter production prompts.
        user = 'We are developing a C game engine.'
        answer = 'We can start with an SDL2 window and game loop.'
        self.provider.chat.return_value = answer
        first = FridayAssistant(self.provider, settings.system_prompt, memory=self.memory)
        first.respond(user)
        first.end_session()
        self.memory.close()
        with MemoryManager(self.path) as reopened:
            restarted = FridayAssistant(self.provider, settings.system_prompt, memory=reopened)
            restarted.respond('do you remember about our c project')
            sent = self.provider.chat.call_args.args[0]
            self.assertEqual([message['role'] for message in sent],
                             ['system', 'user', 'assistant', 'user'])
            self.assertEqual(sent[1:], [
                {'role': 'user', 'content': user},
                {'role': 'assistant', 'content': answer},
                {'role': 'user', 'content': 'do you remember about our c project'},
            ])
            self.assertTrue(sent[0]['content'].startswith(settings.system_prompt))
            self.assertIn('Persistent local conversation memory is enabled', sent[0]['content'])
            self.assertIn('first 2 user/assistant messages', sent[0]['content'])
            self.assertIn('genuine previous conversation history', sent[0]['content'])
            self.assertIn('Do not claim to be a fresh session', sent[0]['content'])
            self.assertIn('Only claim to remember information supported', sent[0]['content'])
            self.assertNotIn('C game engine', sent[0]['content'])
            self.assertNotIn('SDL2', sent[0]['content'])
            self.assertIsNotNone(restarted.previous_session.ended_at)
            restarted.end_session()

    def test_provenance_disappears_when_restored_history_leaves_window(self):
        first = self.assistant()
        first.respond('previous fact')
        first.end_session()
        restarted = self.assistant(limit=2)
        restarted.respond('current one')
        self.assertIn('first 2 user/assistant messages', self.provider.chat.call_args.args[0][0]['content'])
        restarted.respond('current two')
        sent = self.provider.chat.call_args.args[0]
        self.assertEqual(sent[1:], [
            {'role': 'user', 'content': 'current one'},
            {'role': 'assistant', 'content': 'Answer'},
            {'role': 'user', 'content': 'current two'},
        ])
        self.assertIn('No prior-session conversation messages are included', sent[0]['content'])
        self.assertNotIn('were retrieved from previous sessions', sent[0]['content'])

    def test_no_history_means_no_claim_of_retrieved_facts(self):
        assistant = self.assistant()
        assistant.respond('Do you remember my project?')
        sent = self.provider.chat.call_args.args[0]
        self.assertEqual(sent[1:], [{'role': 'user', 'content': 'Do you remember my project?'}])
        self.assertIn('No prior-session conversation messages are included', sent[0]['content'])
        self.assertIn('must not claim to remember earlier sessions or guess facts', sent[0]['content'])

    def test_provenance_counts_only_retained_prior_messages(self):
        first = self.assistant()
        for index in range(3):
            first.respond(f'previous {index}')
        first.end_session()
        restarted = self.assistant(limit=3)
        restarted.respond('new request')
        sent = self.provider.chat.call_args.args[0]
        self.assertEqual(sent[1:3], [
            {'role': 'user', 'content': 'previous 2'},
            {'role': 'assistant', 'content': 'Answer'},
        ])
        self.assertIn('first 2 user/assistant messages', sent[0]['content'])
        restarted.respond('another request')
        sent = self.provider.chat.call_args.args[0]
        self.assertIn('No prior-session conversation messages are included', sent[0]['content'])

    def test_old_memory_denial_is_history_not_current_instruction(self):
        first = self.assistant()
        self.provider.chat.return_value = "I don't have memory; I'm a fresh session."
        first.respond('a generic project fact')
        first.end_session()
        restarted = self.assistant()
        restarted.respond('What did we discuss?')
        sent = self.provider.chat.call_args.args[0]
        self.assertEqual(sent[2]['content'], "I don't have memory; I'm a fresh session.")
        self.assertIn('even if older replies deny having memory', sent[0]['content'])
