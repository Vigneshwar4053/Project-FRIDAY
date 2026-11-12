"""Phase 2A boundaries: real service composition, no live inference or private data."""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from friday.config.settings import Settings
from friday.intelligence.permissions import KnowledgeDecision, KnowledgePurpose
from friday.providers.base import ProviderError
from friday.tools.access import FolderDecision
from zorvyq.features import features, Status
from zorvyq.services import Controller, DEFAULT_MODEL, DesktopProvider, LocalService, ProtectedActionsUnavailable

class Deny:
    def request(self, approval):
        return FolderDecision.DENY

class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.configuration = Settings(project_root=root, database_path=root/'conversation.db',
            filesystem_permission_store_path=root/'permissions/grants.json')
        self.approval = Mock(return_value=KnowledgeDecision.DENY)
        self.factory = Mock(return_value=self.approval)
        self.controller = Controller(Deny(), self.factory, self.configuration)
        self.addCleanup(self.controller.close)

    def test_tool_registry_composes_without_credential_read_or_conversation_database(self):
        with patch('friday.security.owner.load_hash', side_effect=AssertionError('credential read')):
            specs = self.controller.tool_inventory()
        self.assertGreater(len(specs), 20)
        self.assertIsNone(self.controller.assistant.memory)
        self.assertFalse(self.configuration.database_path.exists())
        self.assertIn('list_directory', {s.name for s in specs})

    def test_desktop_uses_lazy_compatible_index_factory_and_shared_cancel_event(self):
        from zorvyq.chroma_bridge import CompatibleChromaIndex
        with patch('friday.intelligence.rag.live_orchestrator') as compose:
            self.controller._initialize()
        self.assertIs(compose.call_args.kwargs['index_factory'],CompatibleChromaIndex)
        self.assertIs(compose.call_args.kwargs['cancelled'],self.controller.knowledge_cancelled)
        self.controller.cancel_knowledge()
        self.assertTrue(self.controller.knowledge_cancelled.is_set())

    def test_gui_authenticator_uses_original_verifier_without_startup_credential_read(self):
        from friday.security.owner import OwnerAuthenticator
        self.controller.approval.secret = lambda prompt: None
        with patch('friday.security.owner.load_hash', side_effect=AssertionError('credential read')):
            self.controller.tool_inventory()
        owner = self.controller.assistant.tool_manager.desktop_access.owner_auth
        self.assertIsInstance(owner, OwnerAuthenticator)
        self.assertIs(owner.reader, self.controller.approval.secret)

    def test_general_turn_does_not_persist_or_leave_job_text(self):
        self.controller._initialize()
        with patch.object(self.controller.manager.provider, 'chat', return_value='Safe final answer'):
            result = self.controller.ask('Explain a Python tuple')
        self.assertEqual(result['answer'], 'Safe final answer')
        self.assertFalse(self.configuration.database_path.exists())
        self.assertEqual(self.controller.manager.last_job.messages, [])
        self.assertIsNone(self.controller.manager.last_job.result)
        self.assertEqual(len(self.controller.assistant.messages), 1)

    def test_knowledge_uses_orchestrator_and_preserves_verified_text_exactly(self):
        self.controller._initialize()
        original = 'Historical FRIDAY evidence [C1]\n\nVerified sources:\n[C1] FRIDAY archive'
        self.controller.assistant.knowledge.answer = Mock(return_value=original)
        self.controller.assistant.knowledge.last_status = {'citation_validation_status': 'verified'}
        result = self.controller.ask('Evidence question', approved_knowledge=True)
        self.assertEqual(result['answer'], original)
        self.controller.assistant.knowledge.answer.assert_called_once_with('Evidence question')
        self.assertEqual(len(self.controller.assistant.messages), 1)

    def test_busy_request_refuses_second_request_and_unload(self):
        self.controller._lock.acquire()
        try:
            with self.assertRaises(ProviderError): self.controller.ask('question')
            with self.assertRaises(ProviderError): self.controller.unload(DEFAULT_MODEL, external_approved=True)
        finally:
            self.controller._lock.release()

    def test_unload_without_warning_approval_never_posts(self):
        self.controller._initialize()
        self.controller.service = Mock()
        self.controller.service.models.return_value = {'loaded':[{'name':DEFAULT_MODEL}]}
        with self.assertRaises(ProviderError): self.controller.unload(DEFAULT_MODEL)
        self.controller.service.request.assert_not_called()

    def test_unload_exact_selected_model_only_with_warning_approval(self):
        self.controller._initialize()
        self.controller.service = Mock()
        self.controller.service.models.return_value = {'loaded':[{'name':DEFAULT_MODEL}]}
        self.controller.unload(DEFAULT_MODEL, external_approved=True)
        self.controller.service.request.assert_called_once_with('/api/generate',
            {'model':DEFAULT_MODEL,'keep_alive':0,'stream':False})

    def test_protected_actions_fail_without_credential_reads(self):
        with patch('friday.security.owner.load_hash', side_effect=AssertionError('credential read')):
            with self.assertRaises(PermissionError): ProtectedActionsUnavailable().authenticate(object())

    def test_production_model_fixed_even_if_configuration_selects_candidate(self):
        other = Controller(Deny(), self.factory, replace(self.configuration, ollama_model='candidate'))
        self.addCleanup(other.close)
        self.assertEqual(other.configuration.ollama_model, DEFAULT_MODEL)

    def test_new_and_legacy_invocations_have_identical_typed_routes(self):
        self.controller._initialize()
        router = self.controller.assistant.tool_router
        for new, old in [('ZORVYQ, open my photos.', 'FRIDAY, open my photos.'),
                         ('open downloads in zorvyq browser', 'open downloads in friday browser'),
                         ('open my zorvyq project', 'open my friday project')]:
            a,b=router.route(new),router.route(old)
            self.assertEqual(a.tool_name,b.tool_name)
            self.assertEqual(a.arguments,b.arguments)

    def test_runtime_capabilities_fail_closed_for_missing_service_and_chroma(self):
        registry = {f.feature_id:f for f in features({'models':None,'knowledge':None,'tools':()})}
        self.assertEqual(registry['chat'].status,Status.UNAVAILABLE)
        self.assertEqual(registry['rag'].status,Status.UNAVAILABLE)
        self.assertEqual(registry['specialist'].status,Status.UNAVAILABLE)
        self.assertNotIn(Status.WORKING,{f.status for f in registry.values()})

    def test_remote_model_service_configuration_rejected(self):
        for url in ['https://example.com','http://192.168.1.2:11434','http://user:pass@localhost:11434',
                    'http://localhost:11434/private','http://localhost:11434?token=secret']:
            with self.assertRaises(ValueError): LocalService(url)

    def test_conflicting_resident_model_blocks_before_generation(self):
        service = Mock()
        service.request.return_value = {'models':[{'name':'foundation-sec'}]}
        provider = DesktopProvider(service,self.configuration)
        with patch('friday.providers.ollama.urllib.request.urlopen') as send:
            with self.assertRaises(ProviderError) as error:
                provider.chat([{'role':'user','content':'question'}])
        self.assertEqual(error.exception.category,'residency_conflict')
        send.assert_not_called()

    def test_generation_requests_explicit_unload_after_owned_request(self):
        import json
        service = Mock()
        service.request.return_value = {'models':[]}
        provider = DesktopProvider(service,self.configuration)
        response = Mock()
        response.read.return_value = json.dumps({'message':{'content':'answer'},'done':True,'done_reason':'stop'}).encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=None)
        with patch('friday.providers.ollama.urllib.request.urlopen',return_value=response) as send:
            self.assertEqual(provider.chat([{'role':'user','content':'question'}]),'answer')
        self.assertEqual(json.loads(send.call_args.args[0].data)['keep_alive'],0)

if __name__ == '__main__': unittest.main()
