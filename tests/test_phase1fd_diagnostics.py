"""Content-free RAG status over synthetic SQLite evidence and mocked HTTP."""
from contextlib import contextmanager
import json
import urllib.error
from unittest.mock import Mock, MagicMock, patch

from tests.test_intelligence_foundation import FoundationFixture, OWASP
from friday.intelligence.models import KnowledgeError
from friday.intelligence.rag import RagOrchestrator, live_orchestrator
from friday.intelligence.permissions import KnowledgeDecision
from friday.models import ModelManager
from friday.models.profile import standard_profile
from friday.providers.ollama import OllamaProvider
from friday.providers.base import ProviderError
from friday.config.settings import Settings
from friday.sync import SynchronizationError

VALID = '{"claims":[{"text":"Check each object permission.","citations":["S1"]}]}'


class DiagnosticTests(FoundationFixture):
    def setUp(self):
        super().setUp()
        revision = self.indexed('owasp', OWASP)
        self.sid = revision.source.source_id
        self.documents = {self.sid: {'source_url': revision.source.identifier,
            'processed_sha256': revision.content_sha256,
            'document_version': revision.document_revision, 'license': {'name': 'Synthetic'}}}
        self.provider_chat = OllamaProvider('http://127.0.0.1:11434', 'qwen3:4b')
        self.manager = ModelManager(self.provider_chat, 'qwen3:4b')
        self.addCleanup(self.manager.close)
        self.preflight = Mock()
        @contextmanager
        def opening():
            yield self.retriever, self.documents, self.preflight
        self.sink = Mock()
        self.rag = RagOrchestrator(self.manager, standard_profile(), 'Synthetic system', opening,
                                  diagnostic_sink=self.sink)
        patcher = patch('friday.providers.ollama.urllib.request.urlopen')
        self.http = patcher.start()
        self.addCleanup(patcher.stop)
        self.response = MagicMock()
        self.http.return_value.__enter__.return_value = self.response
        self.reply()

    def reply(self, content=VALID, reason='stop', tokens=90, **extra):
        self.response.read.return_value = json.dumps({'done': True, 'done_reason': reason,
            'eval_count': tokens, 'message': {'content': content}, **extra}).encode()

    def answer(self, category=None, stage=None):
        result = self.rag.answer('object authorization')
        status = self.rag.last_status
        self.assertEqual(status['failure_category'], category)
        self.assertEqual(status['failure_stage'], stage)
        self.assertEqual(set(status), {'status', 'failure_stage', 'failure_category', 'done_reason',
            'output_token_count', 'retrieved_evidence_count', 'citation_validation_status', 'elapsed_seconds'})
        encoded = json.dumps(status)
        for secret in ('PRIVATE', 'object authorization', 'Check each object permission', OWASP):
            self.assertNotIn(secret, encoded)
        self.assertEqual(self.sink.call_args.args[0], status)
        return result

    def test_success_and_rag_only_json_mode(self):
        self.assertIn('Verified sources:', self.answer())
        self.assertEqual(self.rag.last_status['status'], 'success')
        self.assertEqual(self.rag.last_status['citation_validation_status'], 'verified')
        self.assertEqual(self.rag.last_status['done_reason'], 'stop')
        payload = json.loads(self.http.call_args.args[0].data)
        self.assertEqual(payload['format'], 'json')
        self.assertEqual(payload['options']['num_predict'], 768)
        self.assertEqual(self.http.call_args.kwargs['timeout'], 300)
        self.assertFalse(payload['think'])
        self.manager.generate([{'role': 'user', 'content': 'Synthetic'}], profile=standard_profile())
        self.assertNotIn('format', json.loads(self.http.call_args.args[0].data))

    def test_validation_categories(self):
        cases = [('PRIVATE not JSON', 'malformed_json'),
                 ('{"claims":[],"unexpected":true}', 'invalid_structure'),
                 ('{"claims":[{"text":"PRIVATE","citations":["S9"]}]}', 'citation_rejected'),
                 ('{"claims":[{"text":"PRIVATE","citations":[]}]}', 'missing_citation'),
                 ('{"claims":[{"text":"PRIVATE"}]}', 'missing_citation'),
                 ('{"claims":[],"claims":[]}', 'malformed_json')]
        for content, category in cases:
            with self.subTest(category=category, content=content):
                self.reply(content)
                self.assertNotIn('PRIVATE', self.answer(category, 'validation'))
                self.assertEqual(self.manager.last_job.messages, [])
                self.assertIsNone(self.manager.last_job.result)

    def test_length_and_incomplete_output_never_released(self):
        for reason, category in [('length', 'output_length'), ('unknown', 'incomplete_output')]:
            self.reply(reason=reason, tokens=768)
            self.assertNotIn('Verified sources:', self.answer(category, 'generation'))
            self.assertEqual(self.rag.last_status['output_token_count'], 768)
        self.assertEqual(self.http.call_count, 2)

    def test_connection_and_timeout_categories_no_retry_or_stale_metrics(self):
        self.answer()
        cases = [(TimeoutError('PRIVATE'), 'generation_timeout'),
                 (urllib.error.URLError(TimeoutError('PRIVATE')), 'generation_timeout'),
                 (urllib.error.URLError('PRIVATE'), 'connection_failure'),
                 (ConnectionRefusedError('PRIVATE'), 'connection_failure')]
        self.http.reset_mock()
        for error, category in cases:
            self.http.side_effect = error
            self.assertNotIn('PRIVATE', self.answer(category, 'generation'))
            self.assertIsNone(self.rag.last_status['done_reason'])
            self.assertIsNone(self.rag.last_status['output_token_count'])
            self.assertEqual(self.manager.last_job.error, 'Private knowledge generation failed.')
        self.assertEqual(self.http.call_count, len(cases))

    def test_retrieval_authorization_no_evidence_and_revoked(self):
        self.approve.return_value = KnowledgeDecision.DENY
        self.answer('authorization_denied', 'authorization')
        self.approve.return_value = KnowledgeDecision.ALLOW_ONCE
        self.provider.embed_query.side_effect = KnowledgeError('PRIVATE')
        self.answer('retrieval_failure', 'retrieval')
        self.provider.embed_query.side_effect = None
        self.repo.revoke(self.sid, self.auth)
        self.answer('no_evidence', 'retrieval')
        self.assertEqual(self.rag.last_status['status'], 'insufficient_evidence')
        self.http.assert_not_called()

    def test_preflight_categories_preserved_without_stale_generation_metrics(self):
        self.answer()
        for category in ('residency_conflict', 'residency_timeout', 'source_changed', 'connection_failure'):
            self.preflight.side_effect = ProviderError('PRIVATE', category=category)
            self.answer(category, 'pre_inference')
            self.assertIsNone(self.rag.last_status['done_reason'])
        self.preflight.side_effect = KnowledgeError('PRIVATE', category='connection_failure')
        self.answer('connection_failure', 'pre_inference')
        self.assertEqual(self.http.call_count, 1)

    def test_synchronization_failure(self):
        with patch.object(self.manager.synchronization, 'acquire', side_effect=SynchronizationError('PRIVATE')):
            self.answer('synchronization_failure', 'generation')
        self.http.assert_not_called()

    def test_content_free_unknown_failure_and_display_failure(self):
        self.http.side_effect = ProviderError('PRIVATE', category='PRIVATE')
        self.answer('provider_failure', 'generation')
        self.http.side_effect = None
        self.sink.side_effect = RuntimeError('PRIVATE')
        self.assertIn('Verified sources:', self.answer())

    def test_live_display_requires_opt_in_and_interactive_terminal(self):
        for enabled, interactive, displayed in ((False, True, False), (True, False, False), (True, True, True)):
            rag = live_orchestrator(self.manager, Settings(), diagnostics=enabled)
            with patch('scripts.phase1e_index.revalidate', side_effect=KnowledgeError('PRIVATE')), \
                 patch('sys.stdin.isatty', return_value=interactive), \
                 patch('sys.stdout.isatty', return_value=interactive), patch('builtins.print') as output:
                self.assertNotIn('PRIVATE', rag.answer('object authorization'))
                self.assertEqual(output.called, displayed)
                if displayed:
                    self.assertNotIn('PRIVATE', output.call_args.args[0])
                    self.assertIn('backend_failure', output.call_args.args[0])

    def test_empty_claims_and_source_revocation_during_generation(self):
        self.reply(content='{"claims":[]}')
        self.answer('no_evidence', 'validation')
        self.assertEqual(self.rag.last_status['citation_validation_status'], 'no_claims')
        self.reply()
        def revoke(*args, **kwargs):
            self.repo.revoke(self.sid, self.auth)
            return self.response
        self.http.return_value.__enter__.side_effect = revoke
        self.assertNotIn('Verified sources:', self.answer('source_changed', 'validation'))

    def test_embedding_connection_timeout_residency_and_sync_categories(self):
        from friday.intelligence.models import IndexManifest
        from friday.intelligence.ollama_embeddings import OllamaEmbeddingProvider
        from time import monotonic
        manifest = IndexManifest('nomic-embed-text:v1.5', '0'*64, 768,
            document_prefix='search_document: ', query_prefix='search_query: ')
        embedding = OllamaEmbeddingProvider(manifest, self.manager.synchronization)
        for error, category in ((ConnectionRefusedError('PRIVATE'), 'connection_failure'),
                                (TimeoutError('PRIVATE'), 'generation_timeout')):
            with patch('friday.intelligence.ollama_embeddings.http.client.HTTPConnection') as connection:
                connection.return_value.request.side_effect = error
                with self.assertRaises(KnowledgeError) as raised:
                    embedding._request('/api/ps', monotonic()+10)
                self.assertEqual(raised.exception.category, category)
                self.assertNotIn('PRIVATE', str(raised.exception))
        with patch.object(embedding, '_verify'), patch.object(embedding, '_request', return_value={'models': [{}]}):
            with self.assertRaises(KnowledgeError) as raised:
                embedding.embed_query('Synthetic')
            self.assertEqual(raised.exception.category, 'residency_conflict')
        with patch.object(self.manager.synchronization, 'acquire', side_effect=SynchronizationError('PRIVATE')):
            with self.assertRaises(KnowledgeError) as raised:
                embedding.embed_query('Synthetic')
            self.assertEqual(raised.exception.category, 'synchronization_failure')

    def test_cleanup_failure_cannot_report_success_or_release_answer(self):
        opening = self.rag.open_retrieval
        @contextmanager
        def broken_close():
            with opening() as runtime:
                yield runtime
            raise RuntimeError('PRIVATE')
        self.rag.open_retrieval = broken_close
        result = self.answer('backend_failure', 'validation')
        self.assertNotIn('Verified sources:', result)
        self.assertEqual(self.rag.last_status['status'], 'failed')
