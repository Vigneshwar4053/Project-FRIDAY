"""Synthetic admission/watchdog checks. Never retain or embed a real document."""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch

from scripts.phase1e_admission import (AdmissionDenied, ResourceSample, admit,
    available_ram, private_storage_size, require_enforced_bounds,
    OwnedSessionWatchdog, MIB, GIB)
from scripts.phase1e_index_preflight import APPROVED, approved_corpus, hash_file, verify_local_manifest
import hashlib


class AdmissionTests(unittest.TestCase):
    def test_exact_limits_and_reserved_headroom(self):
        admit(ResourceSample(100 * MIB, 2 * GIB, 2 * GIB))
        admit(ResourceSample(0, 0, 4 * GIB), reserved_storage=100 * MIB, reserved_rss=2 * GIB)
        for sample in (ResourceSample(100 * MIB + 1, 0, 4 * GIB),
                       ResourceSample(0, 2 * GIB + 1, 4 * GIB),
                       ResourceSample(0, 0, 2 * GIB - 1)):
            with self.assertRaises(AdmissionDenied):
                admit(sample)
        for reserves in ({'reserved_storage': 1}, {'reserved_rss': 1}):
            with self.assertRaises(AdmissionDenied):
                admit(ResourceSample(100 * MIB, 2 * GIB, 2 * GIB), **reserves)

    def test_missing_invalid_or_negative_measurement_fails_closed(self):
        for value in (-1, True, None, float('nan')):
            with self.assertRaises(AdmissionDenied):
                ResourceSample(value, 0, 4 * GIB)
        with self.assertRaises(AdmissionDenied):
            admit(None)
        with self.assertRaises(AdmissionDenied):
            admit(ResourceSample(0, 0, 4 * GIB), reserved_rss=-1)

    def test_no_polling_fallback_when_hard_bounds_unverified(self):
        for quota, memory in ((False, False), (False, True), (True, False), (1, True)):
            with self.assertRaises(AdmissionDenied):
                require_enforced_bounds(aggregate_storage_quota_verified=quota,
                                        isolated_embedding_memory_limit_verified=memory)
        require_enforced_bounds(aggregate_storage_quota_verified=True,
                                isolated_embedding_memory_limit_verified=True)

    def test_available_ram_parse_failure_is_not_zero_or_unlimited(self):
        for data in ('', 'MemAvailable: malformed kB', 'MemAvailable: -1 kB', 'MemAvailable: 1 MB'):
            with patch('scripts.phase1e_admission.Path.read_text', return_value=data):
                with self.assertRaises(AdmissionDenied):
                    available_ram()
        with patch('scripts.phase1e_admission.Path.read_text', side_effect=PermissionError):
            with self.assertRaises(AdmissionDenied):
                available_ram()

    def test_storage_counts_allocated_bytes_and_refuses_unsafe_identity(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'synthetic.txt'
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'w') as stream:
                stream.write('Original synthetic data')
            self.assertGreaterEqual(private_storage_size(root), path.stat().st_size)
            self.assertEqual(hash_file(path), __import__('hashlib').sha256(path.read_bytes()).hexdigest())
            with self.assertRaises(AdmissionDenied):
                hash_file(path, path.stat().st_size + 1)
            (root / 'linked.txt').symlink_to(path)
            with self.assertRaises(AdmissionDenied):
                private_storage_size(root)

    def test_new_corpus_fingerprint_denies_before_corpus_or_storage_access(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'docs').mkdir()
            (root / 'docs/FRIDAY_PHASE1E_CORPUS.json').write_text(json.dumps(
                {'approval_scope': {}, 'approval_sha256': APPROVED}))
            with patch('scripts.phase1e_index_preflight.review', side_effect=AssertionError('must deny first')):
                with self.assertRaises(AdmissionDenied):
                    approved_corpus(root)

    def test_enforcement_rejection_has_no_storage_or_embedding_effects(self):
        with patch('friday.intelligence.repository.KnowledgeRepository.__init__', side_effect=AssertionError('no retention')), \
             patch('friday.intelligence.chroma_index.ChromaVectorIndex.__init__', side_effect=AssertionError('no vector storage')), \
             patch('friday.intelligence.ollama_embeddings.OllamaEmbeddingProvider.embed_documents', side_effect=AssertionError('no embedding')):
            with self.assertRaises(AdmissionDenied):
                require_enforced_bounds(aggregate_storage_quota_verified=False,
                                        isolated_embedding_memory_limit_verified=False)

    def test_registry_manifest_and_local_wrapper_verified_separately(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            manifests = root / 'manifests/registry.ollama.ai/library/synthetic'
            manifests.mkdir(parents=True)
            (root / 'blobs').mkdir()
            registry = {'schemaVersion': 2, 'mediaType': 'application/vnd.docker.distribution.manifest.v2+json',
                        'config': {}, 'layers': []}
            raw = json.dumps(registry).encode()
            digest = hashlib.sha256(raw).hexdigest()
            blob = root / 'blobs' / ('sha256-' + digest)
            blob.write_bytes(raw)
            wrapper = {**registry, 'layers': [{'mediaType': registry['mediaType'],
                       'digest': 'sha256:' + digest, 'size': len(raw)}]}
            (manifests / 'test').write_text(json.dumps(wrapper))
            result = verify_local_manifest(root, 'synthetic', 'test', digest, registry)
            self.assertEqual(result['registry_manifest_sha256'], digest)
            self.assertNotEqual(result['local_wrapper_sha256'], digest)
            wrapper['layers'][0]['size'] += 1
            (manifests / 'test').write_text(json.dumps(wrapper))
            with self.assertRaises(AdmissionDenied):
                verify_local_manifest(root, 'synthetic', 'test', digest, registry)
            blob.write_bytes(b'changed')
            with self.assertRaises(AdmissionDenied):
                verify_local_manifest(root, 'synthetic', 'test', digest, registry)


class WatchdogTests(unittest.TestCase):
    def child(self):
        # Fixed test code only; no documents, model, tools or Ollama endpoints.
        process = subprocess.Popen([sys.executable, '-B', '-c', 'import time; time.sleep(30)'],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        def cleanup():
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=2)
        self.addCleanup(cleanup)
        return process

    def test_expired_watchdog_terminates_only_owned_child(self):
        owned = self.child()
        unrelated = self.child()
        cancelled = Event()
        with OwnedSessionWatchdog(owned, cancelled, seconds=.05) as watchdog:
            owned.wait(timeout=2)
            self.assertTrue(watchdog.expired.is_set())
            self.assertTrue(cancelled.is_set())
            self.assertIsNone(unrelated.poll())

    def test_finishing_before_deadline_disarms_watchdog(self):
        process = self.child()
        cancelled = Event()
        with OwnedSessionWatchdog(process, cancelled, seconds=1) as watchdog:
            process.terminate()
            process.wait(timeout=2)
        self.assertFalse(cancelled.is_set())
        self.assertFalse(watchdog.expired.is_set())

    def test_dead_or_foreign_process_is_rejected(self):
        process = self.child()
        process.terminate()
        process.wait(timeout=2)
        with self.assertRaises(AdmissionDenied):
            OwnedSessionWatchdog(process, Event())
        with self.assertRaises(AdmissionDenied):
            OwnedSessionWatchdog(object(), Event())

    def test_watchdog_duration_cannot_be_disabled_or_extended(self):
        process = self.child()
        for seconds in (0, -1, 301, float('inf'), float('nan'), True):
            with self.assertRaises(AdmissionDenied):
                OwnedSessionWatchdog(process, Event(), seconds=seconds)
