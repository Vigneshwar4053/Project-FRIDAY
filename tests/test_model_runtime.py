import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, Mock, patch

from friday.core.assistant import FridayAssistant
from friday.memory import MemoryManager
from friday.models import JobStatus, ModelJob, ModelJobQueue, ModelManager, ModelRegistry
from friday.providers.base import ModelProvider, ProviderError
from friday.providers.ollama import OllamaProvider


class JobTests(unittest.TestCase):
    def test_initial_state_and_unique_ids(self):
        job = ModelJob('local-model', [{'role': 'user', 'content': 'hello'}])
        self.assertEqual(job.status, JobStatus.PENDING)
        self.assertEqual(job.priority, 0)
        self.assertIsNone(job.result)
        self.assertIsNone(job.error)
        self.assertIsNone(job.started_at)
        self.assertIsNone(job.finished_at)
        self.assertIsNotNone(job.created_at.tzinfo)
        self.assertNotEqual(job.job_id, ModelJob('local-model', []).job_id)

    def test_request_is_a_snapshot(self):
        messages = [{'role': 'user', 'content': 'original'}]
        job = ModelJob('local-model', messages)
        messages[0]['content'] = 'changed'
        messages.append({'role': 'user', 'content': 'extra'})
        self.assertEqual(job.messages, [{'role': 'user', 'content': 'original'}])

    def test_invalid_model_and_priority(self):
        for model, priority in (('', 0), (' ', 0), ('model', 1.5)):
            with self.assertRaises(ValueError):
                ModelJob(model, [], priority=priority)


class QueueTests(unittest.TestCase):
    def test_fifo_and_length(self):
        queue = ModelJobQueue()
        jobs = [ModelJob('model', []) for _ in range(3)]
        self.assertIsNone(queue.next_job())
        for job in jobs:
            queue.enqueue(job)
        self.assertEqual(len(queue), 3)
        self.assertEqual([queue.next_job() for _ in jobs], jobs)
        self.assertEqual(len(queue), 0)
        self.assertIsNone(queue.next_job())

    def test_priority_and_equal_priority_fifo(self):
        queue = ModelJobQueue()
        jobs = [ModelJob('model', [], priority=p) for p in (5, -1, 0, -1, 5)]
        for job in jobs:
            queue.enqueue(job)
        self.assertEqual([queue.next_job() for _ in jobs],
                         [jobs[1], jobs[3], jobs[2], jobs[0], jobs[4]])

    def test_duplicate_and_terminal_jobs_rejected(self):
        queue = ModelJobQueue()
        job = ModelJob('model', [])
        queue.enqueue(job)
        with self.assertRaises(ValueError):
            queue.enqueue(job)
        queue.next_job()
        job.status = JobStatus.COMPLETED
        with self.assertRaises(ValueError):
            queue.enqueue(job)


class RegistryTests(unittest.TestCase):
    def test_registration_default_selected_and_active_state(self):
        registry = ModelRegistry()
        self.assertEqual(registry.registered_models, ())
        self.assertIsNone(registry.default_model)
        self.assertIsNone(registry.current_model)
        self.assertIsNone(registry.active_model)
        registry.register('first')
        registry.register('second')
        registry.register('first')
        self.assertEqual(registry.registered_models, ('first', 'second'))
        self.assertEqual(registry.default_model, 'first')
        self.assertEqual(registry.current_model, 'first')
        registry.set_default('second')
        self.assertEqual(registry.default_model, 'second')
        self.assertEqual(registry.current_model, 'first')
        registry.select('second')
        self.assertEqual(registry.current_model, 'second')
        self.assertIsNone(registry.active_model)
        registry.mark_active('first')
        self.assertEqual(registry.active_model, 'first')

    def test_unknown_selection_and_blank_registration(self):
        registry = ModelRegistry()
        for operation in (registry.select, registry.set_default, registry.mark_active):
            with self.assertRaises(ValueError):
                operation('unknown')
        with self.assertRaises(ValueError):
            registry.register(' ')


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.provider = Mock(spec=ModelProvider)
        self.provider.chat.return_value = ' Final answer '
        self.manager = ModelManager(self.provider, 'local-model')
        self.messages = [{'role': 'user', 'content': 'hello'}]

    def test_successful_execution_and_running_transition(self):
        job = self.manager.create_job(self.messages)
        def reply(messages):
            self.assertEqual(job.status, JobStatus.RUNNING)
            self.assertIsNotNone(job.started_at)
            self.assertIsNone(job.finished_at)
            self.assertEqual(self.manager.registry.active_model, 'local-model')
            return ' Final answer '
        self.provider.chat.side_effect = reply
        self.manager.submit_job(job)
        self.assertIs(self.manager.execute_next(), job)
        self.assertEqual(job.status, JobStatus.COMPLETED)
        self.assertEqual(job.result, 'Final answer')
        self.assertIsNone(job.error)
        self.assertLessEqual(job.created_at, job.started_at)
        self.assertLessEqual(job.started_at, job.finished_at)
        self.assertIs(self.manager.last_job, job)
        self.assertIsNone(self.manager.execute_next())
        self.provider.chat.assert_called_once_with(self.messages)

    def test_execution_respects_queue_priorities(self):
        jobs = [self.manager.create_job(self.messages, priority=p) for p in (5, 0, 0)]
        for job in jobs:
            self.manager.submit_job(job)
        self.assertEqual([self.manager.execute_next() for _ in jobs], [jobs[1], jobs[2], jobs[0]])

    def test_failed_execution_records_error_and_finishes(self):
        self.provider.chat.side_effect = ProviderError('offline')
        job = self.manager.create_job(self.messages)
        self.manager.execute_job(job)
        self.assertEqual(job.status, JobStatus.FAILED)
        self.assertEqual(job.error, 'offline')
        self.assertIsNone(job.result)
        self.assertIsNotNone(job.started_at)
        self.assertIsNotNone(job.finished_at)
        self.assertLessEqual(job.started_at, job.finished_at)

    def test_unexpected_failure_is_safe_and_can_recover(self):
        self.provider.chat.side_effect = RuntimeError('sensitive provider details')
        job = self.manager.execute_job(self.manager.create_job(self.messages))
        self.assertEqual(job.status, JobStatus.FAILED)
        self.assertNotIn('sensitive', job.error)
        self.assertIsNotNone(job.finished_at)
        self.provider.chat.side_effect = None
        self.assertEqual(self.manager.generate(self.messages), 'Final answer')

    def test_empty_or_invalid_result_fails(self):
        for result in ('', ' ', None, 123):
            self.provider.chat.return_value = result
            job = self.manager.execute_job(self.manager.create_job(self.messages))
            self.assertEqual(job.status, JobStatus.FAILED)
            self.assertIsNotNone(job.finished_at)
            self.assertIsNone(job.result)

    def test_interrupt_is_recorded_and_reraised(self):
        for failure in (KeyboardInterrupt(), SystemExit()):
            with self.subTest(failure=type(failure)):
                self.provider.chat.side_effect = failure
                job = self.manager.submit_job(self.manager.create_job(self.messages))
                with self.assertRaises(type(failure)):
                    self.manager.execute_next()
                self.assertEqual(job.status, JobStatus.FAILED)
                self.assertIsNotNone(job.finished_at)
                self.assertIsNone(job.result)
                self.assertEqual(len(self.manager.queue), 0)

    def test_generate_failure_preserves_provider_error_behavior(self):
        self.provider.chat.side_effect = ProviderError('offline')
        with self.assertRaisesRegex(ProviderError, 'offline'):
            self.manager.generate(self.messages)
        self.assertEqual(self.manager.last_job.status, JobStatus.FAILED)
        self.assertEqual(len(self.manager.queue), 0)

    def test_direct_execution_removes_queued_job_and_prevents_replay(self):
        job = self.manager.submit_job(self.manager.create_job(self.messages))
        self.manager.execute_job(job)
        self.assertIsNone(self.manager.execute_next())
        with self.assertRaises(ValueError):
            self.manager.execute_job(job)
        self.provider.chat.assert_called_once()

    def test_immediate_generation_leaves_other_jobs_pending(self):
        waiting = self.manager.submit_job(self.manager.create_job(self.messages, priority=-10))
        self.assertEqual(self.manager.generate(self.messages), 'Final answer')
        self.assertEqual(waiting.status, JobStatus.PENDING)
        self.assertIs(self.manager.execute_next(), waiting)

    def test_wrong_model_never_silently_uses_bound_provider(self):
        self.manager.registry.register('other-model')
        self.manager.registry.select('other-model')
        for model in ('other-model', 'unregistered'):
            job = self.manager.execute_job(self.manager.create_job(self.messages, model=model))
            self.assertEqual(job.status, JobStatus.FAILED)
            self.assertIsNotNone(job.finished_at)
        self.provider.chat.assert_not_called()
        self.assertIsNone(self.manager.registry.active_model)

    def test_provider_mutation_does_not_change_job_snapshot(self):
        def mutate(messages):
            messages[0]['content'] = 'changed'
            return 'answer'
        self.provider.chat.side_effect = mutate
        job = self.manager.execute_job(self.manager.create_job(self.messages))
        self.assertEqual(job.messages, self.messages)


class AssistantRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.provider = Mock(spec=ModelProvider)
        self.provider.chat.return_value = 'Answer'
        self.manager = ModelManager(self.provider, 'local-model')

    def test_assistant_routes_through_supplied_manager(self):
        assistant = FridayAssistant(self.manager, 'System')
        with patch.object(self.manager, 'generate', return_value='runtime answer') as generate:
            self.assertEqual(assistant.respond('hello'), 'runtime answer')
        generate.assert_called_once_with([
            {'role': 'system', 'content': 'System'}, {'role': 'user', 'content': 'hello'}])
        self.provider.chat.assert_not_called()

    def test_legacy_provider_constructor_wraps_manager(self):
        assistant = FridayAssistant(self.provider, 'System')
        self.assertIsInstance(assistant.model_manager, ModelManager)
        self.assertIs(assistant.model_manager.provider, self.provider)
        assistant.respond('hello')
        self.assertEqual(assistant.model_manager.last_job.status, JobStatus.COMPLETED)

    def test_memory_persists_only_success_and_restores_through_runtime(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'test.db'
            with MemoryManager(path) as memory:
                assistant = FridayAssistant(self.manager, 'System', memory=memory)
                self.provider.chat.side_effect = ProviderError('offline')
                with self.assertRaises(ProviderError):
                    assistant.respond('failed input')
                self.assertEqual(self.manager.last_job.status, JobStatus.FAILED)
                self.assertEqual(memory.get_recent_messages(20), [])
                self.provider.chat.side_effect = None
                assistant.respond('remember this project')
                assistant.end_session()
            with MemoryManager(path) as reopened:
                restarted = FridayAssistant(self.manager, 'System', memory=reopened)
                restarted.respond('what project?')
                sent = self.manager.last_job.messages
                self.assertEqual(sent[1:3], [
                    {'role': 'user', 'content': 'remember this project'},
                    {'role': 'assistant', 'content': 'Answer'},
                ])
                self.assertIn('genuine previous conversation history', sent[0]['content'])
                self.assertEqual(len(reopened.get_recent_messages(20)), 4)
                restarted.end_session()

    def test_reasoning_sanitization_precedes_job_result(self):
        provider = OllamaProvider('http://127.0.0.1:11434', 'qwen3:4b')
        manager = ModelManager(provider, 'qwen3:4b')
        assistant = FridayAssistant(manager, 'System')
        with patch('friday.providers.ollama.urllib.request.urlopen') as urlopen:
            response = MagicMock()
            urlopen.return_value.__enter__.return_value = response
            response.read.return_value = json.dumps({'message': {
                'content': 'synthetic private</think>Hello!', 'thinking': 'other private'}}).encode()
            self.assertEqual(assistant.respond('hello'), 'Hello!')
        self.assertEqual(manager.last_job.result, 'Hello!')
        self.assertNotIn('private', repr(assistant.messages))

    def test_legacy_constructor_preserves_declared_provider_model(self):
        provider = OllamaProvider('http://127.0.0.1:11434', 'configured-model')
        assistant = FridayAssistant(provider, 'System')
        self.assertEqual(assistant.model_manager.provider_model, 'configured-model')
        self.assertEqual(assistant.model_manager.registry.current_model, 'configured-model')

    def test_manager_rejects_mismatched_provider_configuration(self):
        provider = OllamaProvider('http://127.0.0.1:11434', 'configured-model')
        with self.assertRaisesRegex(ValueError, 'must match'):
            ModelManager(provider, 'different-model')
