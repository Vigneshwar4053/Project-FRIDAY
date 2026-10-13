"""Offline corpus review and synthetic contract tests; never embed real text."""
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from scripts import phase1d_dataset as dataset
from scripts.phase1e_review import review
from test_intelligence_foundation import FoundationFixture
from phase1c_rag_benchmark import MemorySample
from threading import Event


class CorpusReviewTests(unittest.TestCase):
    def setUp(self):
        if not dataset.DATASET.exists():
            self.skipTest('Local Phase 1D corpus is required for offline review tests')
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'corpus'
        shutil.copytree(dataset.DATASET, self.root)

    def test_exact_corpus_without_transport_retention_or_embeddings(self):
        with patch('http.client.HTTPSConnection', side_effect=AssertionError('network forbidden')), \
             patch('friday.intelligence.repository.KnowledgeRepository.__init__', side_effect=AssertionError('retention forbidden')), \
             patch('friday.intelligence.ollama_embeddings.OllamaEmbeddingProvider.__init__', side_effect=AssertionError('embedding forbidden')):
            result = review(self.root)
        self.assertEqual(result['eligible_count'], 20)
        self.assertEqual(result['workload']['chunks'], 312)
        self.assertEqual({b['id'] for b in result['blocked']},
                         {'wstg-345317d8a05797f6', 'cheatsheets-92f7483b28548679'})
        approved = json.loads((dataset.ROOT / 'docs/FRIDAY_PHASE1E_CORPUS.json').read_text())
        self.assertEqual(result['approval_sha256'], approved['approval_sha256'])

    def test_unlisted_document_is_rejected(self):
        (self.root / 'processed/unapproved.txt').write_text('Unapproved synthetic document')
        with self.assertRaises(ValueError):
            review(self.root)

    def test_private_filename_is_rejected_before_any_content_validation(self):
        (self.root / '.env').touch()
        with patch('scripts.phase1d_dataset.validate', side_effect=AssertionError('content must not be read')):
            with self.assertRaises(ValueError):
                review(self.root)

    def test_saved_tree_cannot_substitute_source(self):
        path = self.root / 'sources/wstg-tree.json'
        tree = json.loads(path.read_text())
        tree['tree'][0]['sha'] = '0' * 40
        path.write_text(json.dumps(tree))
        with self.assertRaises(ValueError):
            review(self.root)

    def test_candidate_selection_cannot_authorize_another_document(self):
        path = self.root / 'reports/source-review.json'
        evidence = json.loads(path.read_text())
        evidence['sources']['wstg']['candidates'][0]['path'] = 'document/unapproved.md'
        path.write_text(json.dumps(evidence))
        with self.assertRaises(ValueError):
            review(self.root)


class IncrementalBudgetTests(FoundationFixture):
    def test_each_batch_is_bounded_and_completed_chunks_are_not_reembedded(self):
        revision = self.ingest('bounded', ('Original synthetic defensive security evidence. ' * 240))
        scope = (revision.source.source_id,)
        counts = []
        while True:
            count = self.indexer.index_batch(scope)
            if not count:
                break
            counts.append(count)
            self.assertLessEqual(len(counts), 20)
        self.assertGreater(len(counts), 1)
        for call in self.provider.embed_documents.call_args_list:
            texts = call.args[0]
            self.assertLessEqual(len(texts), 4)
            self.assertLessEqual(sum(len(t.encode()) for t in texts), 6144)
        previous = self.provider.embed_documents.call_count
        self.assertEqual(self.indexer.index_batch(scope), 0)
        self.assertEqual(previous, self.provider.embed_documents.call_count)

    def test_revocation_between_batches_stops_remaining_embeddings(self):
        revision = self.ingest('bounded', 'Synthetic defensive evidence. ' * 350)
        scope = (revision.source.source_id,)
        self.assertEqual(self.indexer.index_batch(scope), 4)
        self.repo.revoke(revision.source.source_id, self.auth)
        previous = self.provider.embed_documents.call_count
        self.assertEqual(self.indexer.index_batch(scope), 0)
        self.assertEqual(previous, self.provider.embed_documents.call_count)


class ResourceGateTests(unittest.TestCase):
    def test_sampler_cancels_on_additional_rss_or_low_available_memory(self):
        for worker_rss, available_kib in ((3 * 1024**3, 4 * 1024**2), (0, 1024**2)):
            with self.subTest(worker_rss=worker_rss, available_kib=available_kib), \
                 patch('phase1c_rag_benchmark.ollama_pids', return_value=[]), \
                 patch('phase1c_rag_benchmark.cpu_seconds', return_value=0), \
                 patch('phase1c_rag_benchmark.rss', side_effect=lambda pid: worker_rss if pid == 123 else 0), \
                 patch('phase1c_rag_benchmark.Path.read_text', return_value=f'MemAvailable: {available_kib} kB\n'):
                cancelled = Event()
                sampler = MemorySample(123, cancelled, 0, 0)
                with patch.object(sampler.stop, 'wait', side_effect=lambda _: sampler.stop.set()):
                    sampler.run()
                self.assertTrue(cancelled.is_set())
                self.assertTrue(sampler.unsafe)
