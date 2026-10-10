"""Synthetic credentials only. Mock cryptography is not real Argon2 validation."""
import base64
from contextlib import redirect_stdout, redirect_stderr
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from friday.security.owner import (Argon2Provider, OwnerAuthenticator, OwnerRequest,
    SensitiveOperation, OwnerAuthenticationError, hidden_secret, load_hash, validate_hash)
from friday.security.setup_owner import setup
from test_discovery_workflows import DiscoveryWorkflowFixture
from friday.desktop.registry import ApplicationRegistry
from friday.tools.access import FolderDecision

TEST_SECRET='synthetic-test-passphrase'
ENCODED='$argon2id$v=19$m=65536,t=3,p=1$'+base64.b64encode(b's'*16).decode().rstrip('=')+'$'+base64.b64encode(b'h'*32).decode().rstrip('=')


def config(path, encoded=ENCODED):
    path.write_text('FRIDAY_OWNER_AUTH_ENABLED=true\nFRIDAY_OWNER_AUTH_HASH='+encoded+'\n')
    path.chmod(0o600)


class FakeProvider:
    """Test double only; never reachable through production provider selection."""
    def verify(self, encoded, secret): return encoded==ENCODED and secret==TEST_SECRET
    def hash(self, secret): return ENCODED


class OwnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.path=self.root/'.env';config(self.path)
        self.clock=Mock(return_value=100)
        self.reader=Mock(return_value=TEST_SECRET)
        self.auth=OwnerAuthenticator(self.path,reader=self.reader,provider_factory=FakeProvider,clock=self.clock)
        self.request=OwnerRequest(SensitiveOperation.OPEN_FILE,'vscode','/synthetic/data.js')

    def test_correct_authentication_is_one_request_only(self):
        self.assertIsNone(self.auth.authenticate(self.request));self.auth.authenticate(self.request)
        self.assertEqual(self.reader.call_count,2)
        self.assertNotIn(TEST_SECRET,str(vars(self.auth)))

    def test_incorrect_secret_generic_failure(self):
        self.reader.return_value='synthetic-wrong-guess'
        with self.assertRaises(OwnerAuthenticationError) as error: self.auth.authenticate(self.request)
        self.assertNotIn(self.reader.return_value,str(error.exception))

    def test_missing_and_disabled_configuration(self):
        self.path.unlink()
        with self.assertRaises(OwnerAuthenticationError): self.auth.authenticate(self.request)
        config(self.path);self.path.write_text('FRIDAY_OWNER_AUTH_ENABLED=false\nFRIDAY_OWNER_AUTH_HASH='+ENCODED)
        with self.assertRaises(OwnerAuthenticationError): self.auth.authenticate(self.request)
        self.reader.assert_not_called()

    def test_malformed_and_unbounded_hashes_fail_before_input(self):
        for value in ('plaintext',ENCODED.replace('argon2id','argon2i'),ENCODED.replace('65536','999999999'),ENCODED.replace('p=1','p=200')):
            config(self.path,value)
            with self.assertRaises(OwnerAuthenticationError): self.auth.authenticate(self.request)
        self.reader.assert_not_called()

    def test_private_permissions_required_and_symlinks_rejected(self):
        self.path.chmod(0o644)
        with self.assertRaises(OwnerAuthenticationError): load_hash(self.path)
        self.path.chmod(0o600);other=self.root/'link';other.symlink_to(self.path)
        with self.assertRaises(OwnerAuthenticationError): load_hash(other)

    def test_hardlinks_and_duplicate_config_rejected(self):
        os.link(self.path,self.root/'copy')
        with self.assertRaises(OwnerAuthenticationError): load_hash(self.path)
        (self.root/'copy').unlink()
        with self.path.open('a') as stream: stream.write('FRIDAY_OWNER_AUTH_ENABLED=true\n')
        with self.assertRaises(OwnerAuthenticationError): load_hash(self.path)

    def test_three_failures_cooldown_is_bounded_without_sleep(self):
        self.reader.return_value='synthetic-wrong-guess'
        for _ in range(3):
            with self.assertRaises(OwnerAuthenticationError): self.auth.authenticate(self.request)
        self.reader.return_value=TEST_SECRET
        with self.assertRaises(OwnerAuthenticationError): self.auth.authenticate(self.request)
        self.assertEqual(self.reader.call_count,3)
        self.clock.return_value=131;self.auth.authenticate(self.request)
        self.assertEqual(self.reader.call_count,4)

    def test_cancelled_input_and_provider_errors_do_not_escape(self):
        self.reader.side_effect=KeyboardInterrupt()
        with self.assertRaises(OwnerAuthenticationError): self.auth.authenticate(self.request)
        self.reader.side_effect=RuntimeError(TEST_SECRET)
        with self.assertRaises(OwnerAuthenticationError) as error: self.auth.authenticate(self.request)
        self.assertNotIn(TEST_SECRET,str(error.exception))

    def test_configuration_change_during_entry_denied(self):
        self.reader.side_effect=lambda _: (self.path.unlink() or TEST_SECRET)
        with self.assertRaises(OwnerAuthenticationError): self.auth.authenticate(self.request)

    def test_no_output_contains_secret(self):
        output=io.StringIO()
        with redirect_stdout(output),redirect_stderr(output): self.auth.authenticate(self.request)
        self.assertEqual(output.getvalue(),'')

    def test_noninteractive_entry_denied(self):
        with patch('sys.stdin.isatty',return_value=False),patch('getpass.getpass') as read:
            with self.assertRaises(OwnerAuthenticationError): hidden_secret('Hidden: ')
            read.assert_not_called()

    def test_getpass_echo_fallback_denied(self):
        import getpass, warnings
        with patch('sys.stdin.isatty',return_value=True),patch('sys.stderr.isatty',return_value=True),\
             patch('getpass.getpass',side_effect=lambda _: warnings.warn('No echo control',getpass.GetPassWarning)):
            with self.assertRaises(OwnerAuthenticationError): hidden_secret('Hidden: ')

    def test_dependency_absence_fails_before_secret_entry(self):
        self.auth.provider_factory=Mock(side_effect=OwnerAuthenticationError('Dependency unavailable.'))
        with self.assertRaises(OwnerAuthenticationError): self.auth.authenticate(self.request)
        self.reader.assert_not_called()

    def test_argon_provider_delegates_costs_salt_and_verification(self):
        import types
        hasher=Mock();hasher.hash.return_value=ENCODED;hasher.verify.return_value=True
        module=types.ModuleType('argon2');module.PasswordHasher=Mock(return_value=hasher)
        module.Type=types.SimpleNamespace(ID='test_argon2id_type')
        errors=types.ModuleType('argon2.exceptions');errors.VerificationError=ValueError
        with patch.dict('sys.modules',{'argon2':module,'argon2.exceptions':errors}):
            provider=Argon2Provider();provider.hash(TEST_SECRET);provider.hash(TEST_SECRET)
            module.PasswordHasher.assert_called_once_with(time_cost=3,memory_cost=65536,parallelism=1,
                hash_len=32,salt_len=16,type=module.Type.ID)
            salts=[call.kwargs['salt'] for call in hasher.hash.call_args_list]
            self.assertEqual([len(salt) for salt in salts],[16,16]);self.assertNotEqual(*salts)
            self.assertTrue(provider.verify(ENCODED,TEST_SECRET))
            hasher.verify.side_effect=ValueError('synthetic failure')
            self.assertFalse(provider.verify(ENCODED,TEST_SECRET))

    def test_request_is_immutable_and_invalid_scope_rejected(self):
        from dataclasses import FrozenInstanceError
        with self.assertRaises(FrozenInstanceError): self.request.target='/another/file'
        with self.assertRaises(ValueError): OwnerRequest('open_file','vscode','/synthetic/file')
        with self.assertRaises(ValueError): OwnerRequest(SensitiveOperation.OPEN_FILE,'shell','/synthetic/file')
        with self.assertRaises(ValueError): OwnerRequest(SensitiveOperation.BROWSER_NAVIGATION,'vscode','https://example.com/')

    def test_setup_requires_explicit_existing_update(self):
        with patch('friday.security.setup_owner.excluded_from_git',return_value=True):
            with self.assertRaises(OwnerAuthenticationError): setup(self.root,reader=self.reader,provider_factory=FakeProvider)
        self.reader.assert_not_called()

    def test_setup_stores_only_hash_and_preserves_other_keys(self):
        self.path.write_text('OTHER_SETTING=synthetic\n');self.path.chmod(0o600)
        with patch('friday.security.setup_owner.excluded_from_git',return_value=True):
            setup(self.root,update_existing=True,reader=self.reader,provider_factory=FakeProvider)
        content=self.path.read_text()
        self.assertNotIn(TEST_SECRET,content);self.assertIn('OTHER_SETTING=synthetic',content)
        self.assertEqual(load_hash(self.path),ENCODED);self.assertEqual(self.path.stat().st_mode&0o777,0o600)

    def test_setup_new_file_and_confirmation_denial(self):
        self.path.unlink();self.reader.side_effect=[TEST_SECRET,'synthetic-wrong-confirmation']
        with patch('friday.security.setup_owner.excluded_from_git',return_value=True):
            with self.assertRaises(OwnerAuthenticationError): setup(self.root,reader=self.reader,provider_factory=FakeProvider)
            self.assertFalse(self.path.exists())
            self.reader.side_effect=None
            setup(self.root,reader=self.reader,provider_factory=FakeProvider)
        self.assertEqual(load_hash(self.path),ENCODED)

    def test_setup_git_exclusion_required(self):
        with patch('friday.security.setup_owner.excluded_from_git',return_value=False):
            with self.assertRaises(OwnerAuthenticationError): setup(self.root,reader=self.reader,provider_factory=FakeProvider)
        self.reader.assert_not_called()

    def test_real_argon2_if_separately_installed(self):
        try: provider=Argon2Provider()
        except OwnerAuthenticationError: self.skipTest('Argon2 not installed; mock tests do not verify real password hashing.')
        first=provider.hash(TEST_SECRET);second=provider.hash(TEST_SECRET)
        self.assertNotEqual(first,second);validate_hash(first)
        self.assertTrue(provider.verify(first,TEST_SECRET))
        self.assertFalse(provider.verify(first,'synthetic-wrong-guess'))


class OwnerIntegrationTests(DiscoveryWorkflowFixture):
    def setUp(self):
        super().setUp()
        self.auth=Mock(spec=OwnerAuthenticator);self.adapter.owner_auth=self.auth

    def test_authentication_precedes_exact_permission(self):
        order=[]
        self.auth.authenticate.side_effect=lambda request:order.append(('auth',request))
        self.approval.request.side_effect=lambda request:(order.append(('permission',request)) or FolderDecision.ALLOW_ONCE)
        self.assertEqual(self.invoke('open_project',{'project_id':'friday'}).data['status'],'launch_accepted')
        self.assertEqual([item[0] for item in order],['auth','permission'])
        self.assertEqual(order[0][1].operation,SensitiveOperation.OPEN_PROJECT)
        self.assertEqual(order[0][1].target,order[1][1].target)

    def test_permission_denial_after_authentication_prevents_launch(self):
        self.approval.request.return_value=FolderDecision.DENY
        self.assertFalse(self.invoke('open_project',{'project_id':'friday'}).success)
        self.auth.authenticate.assert_called_once();self.process.assert_not_called()

    def test_authentication_denial_prevents_permission_and_launch(self):
        self.auth.authenticate.side_effect=OwnerAuthenticationError('Denied')
        self.assertFalse(self.invoke('open_project',{'project_id':'friday'}).success)
        self.approval.request.assert_not_called();self.process.assert_not_called()

    def test_each_sensitive_request_requires_fresh_authentication(self):
        for _ in range(2): self.invoke('open_project',{'project_id':'friday'})
        self.assertEqual(self.auth.authenticate.call_count,2);self.assertEqual(self.approval.request.call_count,2)

    def test_app_only_launch_does_not_request_owner_secret(self):
        for app in ('vscode','firefox'): self.invoke('launch_application',{'application_id':app})
        self.auth.authenticate.assert_not_called();self.assertEqual(self.approval.request.call_count,2)

    def test_snap_unsupported_target_rejected_before_authentication(self):
        self.adapter.applications=ApplicationRegistry()
        with patch.object(self.adapter.applications,'executable',side_effect=FileNotFoundError()):
            result=self.invoke('open_project',{'project_id':'friday'})
        self.assertEqual(result.data['status'],'unsupported_target')
        self.auth.authenticate.assert_not_called();self.approval.request.assert_not_called();self.process.assert_not_called()

    def test_file_reference_auth_does_not_read_or_persist_secret(self):
        self.file();self.command('find data.js in downloads')
        assistant,provider=self.assistant()
        result=assistant.respond('open that')
        self.assertNotIn(TEST_SECRET,result);provider.chat.assert_not_called()
        self.assertEqual(self.auth.authenticate.call_args.args[0].operation,SensitiveOperation.OPEN_FILE)
        self.assertEqual(self.memory.recent_work(),())

    def test_hidden_auth_secret_never_enters_tool_history_or_database(self):
        path=self.project/'.env';config(path)
        reader=Mock(return_value=TEST_SECRET)
        self.adapter.owner_auth=OwnerAuthenticator(path,reader=reader,provider_factory=FakeProvider)
        self.file();self.command('find data.js in downloads')
        assistant,provider=self.assistant();output=io.StringIO()
        with redirect_stdout(output),redirect_stderr(output),patch.object(self.manager,'execute',wraps=self.manager.execute) as execute:
            response=assistant.respond('open data.js')
        self.assertNotIn(TEST_SECRET,response+output.getvalue()+str(assistant.messages)+str(execute.call_args))
        self.assertEqual(self.memory.get_recent_messages(100),[]);self.assertEqual(self.memory.recent_work(),())
        provider.chat.assert_not_called();reader.assert_called_once()

    def test_authentication_cancellation_performs_no_action(self):
        path=self.project/'.env';config(path)
        self.adapter.owner_auth=OwnerAuthenticator(path,reader=Mock(side_effect=KeyboardInterrupt()),provider_factory=FakeProvider)
        self.assertFalse(self.invoke('open_project',{'project_id':'friday'}).success)
        self.process.assert_not_called();self.approval.request.assert_not_called()

    def test_unsupported_real_input_never_prompts_for_owner_secret(self):
        from friday.desktop.atspi import AtspiBackend
        from friday.desktop.computer_use import ComputerUsePermissions
        from friday.tools.models import ToolRequest
        permissions=ComputerUsePermissions(AtspiBackend(),self.approval,owner_auth=self.auth)
        from friday.desktop.actions import DesktopAction, Operation, UIState
        from friday.desktop.observation import WindowRef
        action=DesktopAction(Operation.FOCUS,WindowRef('firefox','synthetic_window','synthetic_process'),expected=UIState(focused=True))
        arguments={'action':action.arguments('synthetic_revision')}
        request=ToolRequest('computer_action',arguments)
        with permissions.execution(request): result=permissions.execute('computer_action',arguments)
        self.assertEqual(result['status'],'unsupported');self.auth.authenticate.assert_not_called()
        self.approval.request.assert_not_called()

    def test_chat_credentials_never_reach_model_or_memory(self):
        assistant,provider=self.assistant()
        result=assistant.respond('owner security code '+TEST_SECRET)
        self.assertNotIn(TEST_SECRET,result);provider.chat.assert_not_called()
        self.assertNotIn(TEST_SECRET,str(assistant.messages))
        self.assertEqual(self.memory.get_recent_messages(100),[])
        self.auth.authenticate.assert_not_called();self.process.assert_not_called()
