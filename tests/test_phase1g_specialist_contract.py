"""Candidate interface checks only; synthetic evidence and mocked HTTP, no inference."""
from dataclasses import replace
import json
from unittest.mock import MagicMock, Mock, patch

from tests.test_intelligence_foundation import FoundationFixture, OWASP
from friday.intelligence.models import KnowledgeError
from friday.intelligence.permissions import KnowledgeDecision
from friday.intelligence.rag import RagOrchestrator, render_answer
from friday.intelligence.retrieval import RetrievalService
from friday.models import ModelManager
from friday.models.profile import standard_profile
from friday.providers.ollama import OllamaProvider
from friday.providers.base import ProviderError

CANDIDATE = 'dr-ry/foundation-sec-8b-instruct-chat-GGUF:latest'
VALID = '{"claims":[{"text":"Check permissions for each object.","citations":["S1"]}]}'


class SpecialistContractTests(FoundationFixture):
    def setUp(self):
        super().setUp()
        self.revision = self.indexed('owasp', OWASP)
        self.scope = (self.revision.source.source_id,)
        self.documents = {self.scope[0]: {'source_url': self.revision.source.identifier,
            'processed_sha256': self.revision.content_sha256,
            'document_version': self.revision.document_revision,
            'license': {'name': 'Original synthetic fixture'}}}
        self.service = RetrievalService(self.repo, self.provider, self.index, self.auth,
            compact_evidence=True, require_topic_match=True)

    def bundle(self):
        return self.service.retrieve('object authorization', self.scope)

    def render(self, content, bundle):
        return render_answer(content, bundle, self.repo, self.scope, self.manifest, self.documents)

    def test_candidate_cannot_enter_live_rag(self):
        opening = Mock()
        provider = OllamaProvider('http://127.0.0.1:11434', CANDIDATE)
        with ModelManager(provider, CANDIDATE) as manager, \
             patch('friday.providers.ollama.urllib.request.urlopen') as http:
            rag = RagOrchestrator(manager, standard_profile(), 'Synthetic system', opening)
            self.assertIn('failed safely', rag.answer('object authorization'))
            self.assertEqual(rag.last_status['failure_category'], 'model_mismatch')
            opening.assert_not_called()
            http.assert_not_called()

    def test_candidate_http_adapter_contract_without_loading(self):
        provider = OllamaProvider('http://127.0.0.1:11434', CANDIDATE)
        response = MagicMock()
        response.read.return_value = json.dumps({'done': True, 'done_reason': 'stop',
            'eval_count': 60, 'message': {'content': VALID}}).encode()
        profile = replace(standard_profile(), json_output=True, require_complete=True)
        with ModelManager(provider, CANDIDATE) as manager, \
             patch('friday.providers.ollama.urllib.request.urlopen') as http:
            http.return_value.__enter__.return_value = response
            bundle = self.bundle()
            messages = [{'role': 'system', 'content': 'Use only supplied synthetic evidence; return claims JSON.'},
                {'role': 'user', 'content': bundle.serialize(compact=True)}]
            raw = manager.generate(messages, profile=profile, private=True)
            answer, citations = self.render(raw, bundle)
            self.assertEqual(citations, 1)
            self.assertIn('Verified sources:', answer)
            payload = json.loads(http.call_args.args[0].data)
            self.assertEqual(payload['model'], CANDIDATE)
            self.assertEqual(payload['format'], 'json')
            self.assertFalse(payload['think'])
            self.assertEqual(payload['options'], standard_profile().options)
            self.assertEqual(http.call_args.kwargs['timeout'], 300)
            self.assertEqual(manager.last_job.messages, [])
            self.assertIsNone(manager.last_job.result)
            http.assert_called_once()

    def test_unknown_missing_and_malformed_citations_fail_closed(self):
        bundle = self.bundle()
        for output in (VALID.replace('S1', 'S99'), VALID.replace('["S1"]', '[]'), 'not JSON'):
            with self.subTest(output=output), self.assertRaises(KnowledgeError):
                self.render(output, bundle)

    def test_existing_evidence_budget_and_authorization_are_model_independent(self):
        bundle = self.bundle()
        self.assertLessEqual(len(bundle.evidence), 3)
        self.assertLessEqual(len(bundle.serialize(compact=True).encode()), 2048)
        self.assertFalse(bundle.persist)
        self.assertFalse(bundle.speech_eligible)
        calls = self.provider.embed_query.call_count
        self.approve.return_value = KnowledgeDecision.DENY
        from friday.intelligence.permissions import KnowledgeAuthorizationDenied
        with self.assertRaises(KnowledgeAuthorizationDenied):
            self.bundle()
        self.assertEqual(self.provider.embed_query.call_count, calls)

    def test_revoked_evidence_rejected_by_renderer(self):
        bundle = self.bundle()
        self.repo.revoke(self.scope[0], self.auth)
        with self.assertRaises(KnowledgeError):
            self.render(VALID, bundle)

    def test_candidate_length_exhaustion_keeps_private_job_empty(self):
        provider = OllamaProvider('http://127.0.0.1:11434', CANDIDATE)
        response = MagicMock()
        response.read.return_value = json.dumps({'done': True, 'done_reason': 'length',
            'eval_count': 768, 'message': {'content': VALID}}).encode()
        with ModelManager(provider, CANDIDATE) as manager, \
             patch('friday.providers.ollama.urllib.request.urlopen') as http:
            http.return_value.__enter__.return_value = response
            with self.assertRaises(ProviderError) as raised:
                manager.generate([{'role': 'user', 'content': 'Synthetic'}],
                    profile=replace(standard_profile(), json_output=True, require_complete=True), private=True)
            self.assertEqual(raised.exception.category, 'output_length')
            self.assertEqual(manager.last_job.messages, [])
            self.assertIsNone(manager.last_job.result)
            self.assertEqual(manager.last_job.error, 'Private knowledge generation failed.')
