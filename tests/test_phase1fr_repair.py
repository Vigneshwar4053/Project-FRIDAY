"""Original synthetic fixtures and mocked HTTP only; no real model requests."""
from contextlib import contextmanager
from dataclasses import replace
import json
import unittest
from unittest.mock import Mock, MagicMock, patch

from tests.test_intelligence_foundation import FoundationFixture, OWASP
from friday.intelligence.models import EvidenceBundle
from friday.intelligence.retrieval import RetrievalService, topic_matches
from friday.intelligence.index import VectorCandidate
from friday.intelligence.rag import RagOrchestrator, INSUFFICIENT, render_answer
from friday.models import ModelManager
from friday.models.profile import standard_profile, deep_profile
from friday.providers.ollama import OllamaProvider
from friday.providers.base import ProviderError


class RepairRetrievalTests(FoundationFixture):
    def setUp(self):
        super().setUp()
        self.relevant = self.indexed('owasp', OWASP)
        self.irrelevant = self.indexed('files', 'File permissions restrict executable files and world-readable configuration.')
        self.scope = tuple(sorted((self.relevant.source.source_id, self.irrelevant.source.source_id)))
        self.service = RetrievalService(self.repo, self.provider, self.index, self.auth,
            compact_evidence=True, require_topic_match=True)

    def candidates(self, revisions):
        ids = [self.repo.connection.execute('SELECT chunk_id FROM chunks WHERE revision_id=? ORDER BY ordinal',
                    (r.revision_id,)).fetchone()[0] for r in revisions]
        self.index.query.side_effect = None
        self.index.query.return_value = tuple(VectorCandidate(cid, .1+i*.01) for i, cid in enumerate(ids))

    def test_irrelevant_first_candidate_skipped_for_relevant_candidate(self):
        self.candidates([self.irrelevant, self.relevant])
        result = self.service.retrieve('Explain broken object-level authorization', self.scope)
        self.assertEqual([e.chunk.source_id for e in result.evidence], [self.relevant.source.source_id])
        self.assertEqual(result.evidence[0].citation_id, 'S1')

    def test_irrelevant_only_returns_missing_topic(self):
        self.candidates([self.irrelevant])
        result = self.service.retrieve('BOLA', self.scope)
        self.assertFalse(result.evidence)
        self.assertEqual(result.empty_reason, 'no_relevant_evidence')

    def test_topic_links_and_title_do_not_supply_substantive_support(self):
        for text in ('See Insecure_Direct_Object_Reference.md for authorization.',
                     'Objects have names.', 'Authorization on every request.'):
            self.assertFalse(topic_matches('object-level authorization', Mock(text=text)))
        self.assertTrue(topic_matches('IDOR', Mock(text='Check access permissions for each object.')))

    def test_compact_budget_accounts_for_exact_serialized_utf8(self):
        self.candidates([self.relevant])
        bundle = self.service.retrieve('object authorization', self.scope)
        compact = bundle.serialize(compact=True)
        full = bundle.serialize()
        self.assertLess(len(compact.encode()), len(full.encode()))
        self.service.evidence_bytes = len(compact.encode())
        self.assertEqual(self.service.retrieve('object authorization', self.scope).evidence, bundle.evidence)
        self.service.evidence_bytes -= 1
        self.assertFalse(self.service.retrieve('object authorization', self.scope).evidence)
        item = json.loads(compact)[0]
        self.assertEqual(item['text'], bundle.evidence[0].chunk.text)
        self.assertEqual(set(item), {'citation', 'title', 'text'})

    def test_whole_multibyte_chunk_not_truncated(self):
        revision = self.indexed('unicode', 'Authorization checks each object. ' + 'é'*500)
        self.candidates([revision])
        scope = (revision.source.source_id,)
        bundle = self.service.retrieve('object authorization', scope)
        self.assertTrue(bundle.evidence)
        size = len(bundle.serialize(compact=True).encode())
        self.assertGreater(size, len(bundle.serialize(compact=True)))
        self.service.evidence_bytes = size - 1
        self.assertFalse(self.service.retrieve('object authorization', scope).evidence)

    def test_revoked_source_cannot_be_rescued_by_topic_match(self):
        self.candidates([self.relevant, self.irrelevant])
        self.repo.revoke(self.relevant.source.source_id, self.auth)
        self.assertFalse(self.service.retrieve('object authorization', self.scope).evidence)

    def test_existing_retrieval_defaults_preserved(self):
        self.candidates([self.irrelevant])
        self.assertTrue(self.retriever.retrieve('object authorization', self.scope).evidence)
        self.assertFalse(self.retriever.compact_evidence)
        self.assertFalse(self.retriever.require_topic_match)

    def test_compact_map_retains_exact_citation_provenance(self):
        self.candidates([self.relevant])
        bundle = self.service.retrieve('object authorization', self.scope)
        revision = self.relevant
        docs = {revision.source.source_id: {'source_url': revision.source.identifier,
            'processed_sha256': revision.content_sha256, 'document_version': revision.document_revision,
            'license': {'name': 'Synthetic'}}}
        raw = json.dumps({'claims': [{'text': 'Check access for each object.', 'citations': ['S1']}]})
        answer, count = render_answer(raw, bundle, self.repo, self.scope, self.manifest, docs)
        self.assertEqual(count, 1)
        self.assertIn(bundle.evidence[0].chunk.chunk_id, answer)
        self.assertIn(revision.source.identifier, answer)
        self.repo.revoke(revision.source.source_id, self.auth)
        with self.assertRaisesRegex(Exception, 'Grounding failure'):
            render_answer(raw, bundle, self.repo, self.scope, self.manifest, docs)


class RepairGenerationTests(unittest.TestCase):
    def setUp(self):
        self.provider = OllamaProvider('http://127.0.0.1:11434', 'qwen3:4b', think=True)
        self.manager = ModelManager(self.provider, 'qwen3:4b')
        self.addCleanup(self.manager.close)
        self.response = MagicMock()
        patcher = patch('friday.providers.ollama.urllib.request.urlopen')
        self.http = patcher.start()
        self.addCleanup(patcher.stop)
        self.http.return_value.__enter__.return_value = self.response
        self.profile = replace(standard_profile(), think=False, require_complete=True)

    def reply(self, **metadata):
        self.response.read.return_value = json.dumps({'message': {'content': '{"claims":[]}',
            'thinking': 'PRIVATE_THINKING'}, **metadata}).encode()

    def test_explicit_rag_profile_does_not_change_global_or_general_chat(self):
        original = deep_profile()
        rag = RagOrchestrator(self.manager, original, 'Synthetic system', Mock())
        self.assertFalse(rag.profile.think)
        self.assertTrue(rag.profile.require_complete)
        for name in ('num_predict', 'num_ctx', 'timeout_seconds', 'temperature', 'max_context_bytes'):
            self.assertEqual(getattr(rag.profile, name), getattr(original, name))
        self.assertTrue(original.think)
        self.reply(done=True, done_reason='stop')
        self.manager.generate([{'role':'user', 'content':'Synthetic'}], profile=rag.profile, private=True)
        payload = json.loads(self.http.call_args.args[0].data)
        self.assertFalse(payload['think'])
        self.assertEqual(payload['options'], original.options)
        self.assertEqual(self.http.call_args.kwargs['timeout'], original.timeout_seconds)
        self.assertIsNone(self.provider._profile)
        self.assertTrue(self.provider.think)
        # Legacy missing finish metadata remains accepted for ordinary chat.
        self.reply()
        self.assertEqual(self.manager.generate([{'role':'user', 'content':'Synthetic'}]), '{"claims":[]}')
        self.assertTrue(json.loads(self.http.call_args.args[0].data)['think'])

    def test_length_exhaustion_never_leaks_partial_content_or_thinking(self):
        self.reply(done=True, done_reason='length', eval_count=768)
        with self.assertRaisesRegex(ProviderError, 'output-token limit'):
            self.manager.generate([{'role':'user', 'content':'Synthetic'}], profile=self.profile, private=True)
        self.assertEqual(self.provider.last_generation_metrics['completion'], 'truncated')
        self.assertEqual(self.provider.last_generation_metrics['output_tokens'], 768)
        self.assertEqual(self.manager.last_job.messages, [])
        self.assertIsNone(self.manager.last_job.result)
        self.assertNotIn('PRIVATE', self.manager.last_job.error)
        self.http.assert_called_once()

    def test_explicit_rag_requires_confirmed_finish_reason(self):
        for metadata in ({}, {'done':True}, {'done_reason':'stop'}, {'done':False, 'done_reason':'stop'},
                         {'done':True, 'done_reason':'unknown'}, {'done':True, 'done_reason':''}):
            with self.subTest(metadata=metadata):
                self.reply(**metadata)
                with self.assertRaises(ProviderError):
                    self.manager.generate([{'role':'user', 'content':'Synthetic'}], profile=self.profile, private=True)
                self.assertIsNone(self.manager.last_job.result)
                self.assertEqual(self.manager.last_job.messages, [])

    def test_confirmed_stop_releases_only_final_content(self):
        self.reply(done=True, done_reason='stop', eval_count=180)
        result = self.manager.generate([{'role':'user', 'content':'Synthetic'}], profile=self.profile, private=True)
        self.assertEqual(result, '{"claims":[]}')
        self.assertNotIn('PRIVATE', result)
        self.assertEqual(self.provider.last_generation_metrics['completion'], 'normal')

    def test_timeout_has_no_retry_or_private_job_leak(self):
        self.http.side_effect = TimeoutError('PRIVATE')
        with self.assertRaises(ProviderError):
            self.manager.generate([{'role':'user', 'content':'Synthetic'}], profile=self.profile, private=True)
        self.http.assert_called_once()
        self.assertIsNone(self.provider._profile)
        self.assertEqual(self.manager.last_job.messages, [])
        self.assertIsNone(self.manager.last_job.result)


if __name__ == '__main__':
    unittest.main()
