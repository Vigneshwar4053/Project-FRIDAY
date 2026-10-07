import ctypes
import errno
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import Mock, patch

from friday.models import JobStatus, ModelManager
from friday.providers.base import ModelProvider, ProviderError
from friday.sync import (NativeSemaphore, NativeUnavailable, PythonSemaphore,
                         SynchronizationError, create_synchronization)
from friday.sync.native import DEFAULT_LIBRARY_PATH


def prove_model_exclusion(test, synchronization):
    """Independent synchronous managers share one gate, not one unsafe queue."""
    counter_lock = threading.Lock()
    barrier = threading.Barrier(6)
    active = 0
    maximum = 0
    failures = []

    class CountingProvider(ModelProvider):
        def chat(self, messages):
            nonlocal active, maximum
            with counter_lock:
                active += 1
                maximum = max(maximum, active)
            try:
                time.sleep(0.01)  # Yield to contenders inside the protected section.
                return 'answer'
            finally:
                with counter_lock:
                    active -= 1

    provider = CountingProvider()
    managers = [ModelManager(provider, 'test-model', synchronization=synchronization) for _ in range(6)]
    jobs = [manager.create_job([{'role': 'user', 'content': 'test'}]) for manager in managers]

    def run(index):
        try:
            barrier.wait(timeout=3)
            with managers[index]:
                managers[index].execute_job(jobs[index])
        except BaseException as exc:
            with counter_lock:
                failures.append(type(exc).__name__)

    threads = [threading.Thread(target=run, args=(i,), daemon=True) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3)
    test.assertFalse(any(thread.is_alive() for thread in threads), 'gate deadlocked')
    test.assertEqual(failures, [])
    test.assertEqual(maximum, 1)
    test.assertEqual(active, 0)
    test.assertTrue(all(job.status == JobStatus.COMPLETED for job in jobs))


class SynchronizationContract:
    def setUp(self):
        self.sync = self.make_sync()
        self.addCleanup(self.sync.close)

    def test_acquire_release_and_context(self):
        self.sync.acquire()
        self.sync.release()
        with self.sync as entered:
            self.assertIs(entered, self.sync)
        with self.sync:
            pass

    def test_context_releases_after_all_exception_types(self):
        for failure in (ValueError('test'), ProviderError('offline'), KeyboardInterrupt(), SystemExit()):
            with self.subTest(failure=type(failure)):
                with self.assertRaises(type(failure)):
                    with self.sync:
                        raise failure
                with self.sync:
                    pass

    def test_recursive_acquire_and_extra_release_rejected(self):
        with self.assertRaises(SynchronizationError):
            self.sync.release()
        with self.sync:
            with self.assertRaises(SynchronizationError):
                self.sync.acquire()

    def test_close_is_idempotent_and_use_after_close_rejected(self):
        self.sync.close()
        self.sync.close()
        with self.assertRaises(SynchronizationError):
            self.sync.acquire()
        with self.assertRaises(SynchronizationError):
            self.sync.release()

    def test_close_while_held_rejected_without_destroying(self):
        with self.sync:
            with self.assertRaises(SynchronizationError):
                self.sync.close()
        with self.sync:
            pass

    def test_waiter_blocks_and_cannot_release_another_owner(self):
        started = threading.Event()
        entered = threading.Event()
        wrong_owner = []
        def wait():
            try:
                self.sync.release()
            except SynchronizationError:
                wrong_owner.append(True)
            started.set()
            with self.sync:
                entered.set()
        with self.sync:
            thread = threading.Thread(target=wait, daemon=True)
            thread.start()
            self.assertTrue(started.wait(2))
            self.assertFalse(entered.wait(0.03))
            with self.assertRaises(SynchronizationError):
                self.sync.close()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertTrue(entered.is_set())
        self.assertEqual(wrong_owner, [True])

    def test_close_while_acquire_in_flight_is_rejected(self):
        started = threading.Event()
        proceed = threading.Event()
        acquired = threading.Event()
        original = self.sync._acquire_resource
        def delayed_acquire():
            started.set()
            if not proceed.wait(2):
                raise RuntimeError('test timeout')
            original()
        def use():
            with self.sync:
                acquired.set()
        with patch.object(self.sync, '_acquire_resource', side_effect=delayed_acquire):
            thread = threading.Thread(target=use, daemon=True)
            thread.start()
            try:
                self.assertTrue(started.wait(2))
                with self.assertRaises(SynchronizationError):
                    self.sync.close()
            finally:
                proceed.set()
                thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertTrue(acquired.is_set())

    def test_multiple_model_executions_are_mutually_exclusive(self):
        prove_model_exclusion(self, self.sync)

    def test_manager_failure_and_interrupt_release_resource(self):
        provider = Mock(spec=ModelProvider)
        with ModelManager(provider, 'test-model', synchronization=self.sync) as manager:
            for failure in (ProviderError('offline'), RuntimeError('unexpected'), KeyboardInterrupt(), SystemExit()):
                provider.chat.side_effect = failure
                job = manager.create_job([])
                if isinstance(failure, Exception):
                    manager.execute_job(job)
                else:
                    with self.assertRaises(type(failure)):
                        manager.execute_job(job)
                self.assertEqual(job.status, JobStatus.FAILED)
                self.assertIsNotNone(job.finished_at)
                provider.chat.side_effect = None
                provider.chat.return_value = 'recovered'
                self.assertEqual(manager.generate([]), 'recovered')
        # Injected gate remains open after the manager closes.
        with self.sync:
            pass


class FallbackTests(SynchronizationContract, unittest.TestCase):
    @staticmethod
    def make_sync():
        return PythonSemaphore()


class NativeTests(SynchronizationContract, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            sync = NativeSemaphore()
        except NativeUnavailable as exc:
            raise unittest.SkipTest(str(exc))
        sync.close()

    @staticmethod
    def make_sync():
        return NativeSemaphore()

    def test_native_signatures_and_null_arguments(self):
        library = self.sync._library  # White-box ABI test only; not application API.
        self.assertEqual(library.friday_semaphore_create.argtypes, [])
        self.assertIs(library.friday_semaphore_create.restype, ctypes.c_void_p)
        for operation in ('acquire', 'release', 'destroy'):
            function = getattr(library, f'friday_semaphore_{operation}')
            self.assertEqual(function.argtypes, [ctypes.c_void_p])
            self.assertIs(function.restype, ctypes.c_int)
            self.assertEqual(function(None), errno.EINVAL)

    def test_native_acquire_error_never_falls_back(self):
        with patch.object(self.sync._library, 'friday_semaphore_acquire', return_value=errno.EINVAL), \
             patch('friday.sync.PythonSemaphore') as fallback:
            with self.assertRaisesRegex(SynchronizationError, 'acquire failed'):
                self.sync.acquire()
            fallback.assert_not_called()
        with self.sync:
            pass

    def test_native_release_error_never_falls_back_or_destroys_held_gate(self):
        self.sync.acquire()
        with patch.object(self.sync._library, 'friday_semaphore_release', return_value=errno.EINVAL):
            with self.assertRaisesRegex(SynchronizationError, 'release failed'):
                self.sync.release()
        with self.assertRaises(SynchronizationError):
            self.sync.close()
        self.sync.release()

    def test_interrupt_delivered_after_native_acquire_releases_mutex(self):
        acquire = self.sync._library.friday_semaphore_acquire
        def interrupted(handle):
            self.assertEqual(acquire(handle), 0)
            raise KeyboardInterrupt()
        with patch.object(self.sync._library, 'friday_semaphore_acquire', side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                self.sync.acquire()
        with self.sync:
            pass

    def test_native_destroy_error_retains_live_handle(self):
        with patch.object(self.sync._library, 'friday_semaphore_destroy', return_value=errno.EBUSY):
            with self.assertRaisesRegex(SynchronizationError, 'destroy failed'):
                self.sync.close()
        with self.sync:
            pass
        self.sync.close()
        self.assertIsNone(self.sync._handle)


class SelectionAndOwnershipTests(unittest.TestCase):
    def test_missing_library_selects_explicit_fallback(self):
        with TemporaryDirectory() as directory:
            sync = create_synchronization(Path(directory) / 'missing.so')
        self.assertIsInstance(sync, PythonSemaphore)
        self.assertIsNotNone(sync.fallback_reason)
        with sync:
            pass
        sync.close()

    def test_initialization_failure_can_fallback(self):
        with patch('friday.sync.NativeSemaphore', side_effect=NativeUnavailable('cannot initialize')):
            sync = create_synchronization()
        self.assertEqual(sync.fallback_reason, 'cannot initialize')
        sync.close()

    def test_arbitrary_initialization_error_is_not_hidden(self):
        with patch('friday.sync.NativeSemaphore', side_effect=RuntimeError('unexpected')):
            with self.assertRaises(RuntimeError):
                create_synchronization()

    def test_native_null_create_reports_initialization_failure(self):
        library = Mock()
        library.friday_semaphore_create.return_value = None
        with patch('friday.sync.native.ctypes.CDLL', return_value=library):
            with self.assertRaises(NativeUnavailable):
                NativeSemaphore(DEFAULT_LIBRARY_PATH)
        library.friday_semaphore_destroy.assert_not_called()

    def test_manager_closes_default_owned_resource(self):
        provider = Mock(spec=ModelProvider)
        with ModelManager(provider, 'test-model') as manager:
            sync = manager.synchronization
        manager.close()
        with self.assertRaises(SynchronizationError):
            sync.acquire()
        with self.assertRaises(SynchronizationError):
            manager.create_job([])

    def test_manager_closes_external_resource_zero_times(self):
        sync = PythonSemaphore()
        manager = ModelManager(Mock(spec=ModelProvider), 'test-model', synchronization=sync)
        with patch.object(sync, 'close', wraps=sync.close) as close:
            manager.close()
            manager.close()
            close.assert_not_called()
        with sync:
            pass
        sync.close()

    def test_manager_rejects_close_during_execution(self):
        provider = Mock(spec=ModelProvider)
        manager = ModelManager(provider, 'test-model')
        def reply(messages):
            with self.assertRaises(SynchronizationError):
                manager.close()
            return 'answer'
        provider.chat.side_effect = reply
        self.assertEqual(manager.generate([]), 'answer')
        manager.close()

    def test_acquire_failure_marks_job_failed_without_provider_call(self):
        sync = PythonSemaphore()
        sync.close()
        provider = Mock(spec=ModelProvider)
        with ModelManager(provider, 'test-model', synchronization=sync) as manager:
            job = manager.execute_job(manager.create_job([]))
        self.assertEqual(job.status, JobStatus.FAILED)
        self.assertIsNotNone(job.finished_at)
        self.assertIn('synchronization failed', job.error)
        provider.chat.assert_not_called()
