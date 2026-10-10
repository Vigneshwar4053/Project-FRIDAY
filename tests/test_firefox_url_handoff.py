"""Mocked YouTube handoffs only: no real credentials, Snap, Firefox or network."""
from contextlib import contextmanager, ExitStack
from dataclasses import replace
import os
from pathlib import Path
import stat
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

from test_discovery_workflows import DiscoveryWorkflowFixture
from friday.desktop.browser_execution import BrowserTarget
from friday.desktop.firefox_url_handoff import (FirefoxSnapUrlAdapter, FirefoxUrlHandoff,
    UnavailableFirefoxUrlAdapter, YOUTUBE_URL, ACCEPTED_MESSAGE, LAUNCHER, ARGUMENT_PREFIX)
from friday.desktop.handoffs import HandoffRequest, HandoffOperation, HANDOFF_FAILURE_MESSAGES
from friday.desktop.runtime import DesktopApproval
from friday.desktop.snap import ReviewedSnap
from friday.security.owner import OwnerAuthenticator, OwnerAuthenticationError, SensitiveOperation
from friday.tools.access import FolderDecision
from friday.tools.models import ToolRequest, ToolErrorCategory


class FirefoxUrlHandoffFixture(DiscoveryWorkflowFixture):
    def setUp(self):
        super().setUp()
        self.url_adapter=FirefoxSnapUrlAdapter()
        self.execution=FirefoxUrlHandoff(self.adapter.handoff_cancelled,self.adapter.handoff_clock,self.url_adapter)
        self.adapter.firefox_url_handoff=self.execution
        self.auth=Mock(spec=OwnerAuthenticator);self.adapter.owner_auth=self.auth
        self.review=('synthetic-reviewed-snap',)
        self.chain=(('synthetic-reviewed-chain',),)
        self.environment=(('HOME',str(self.home)),('SNAP_REEXEC','0'),('XDG_RUNTIME_DIR','/synthetic/runtime'))
        @contextmanager
        def executable(app):
            self.assertEqual(app,'firefox')
            with self.apps.executable('firefox') as native:
                yield native[0],LAUNCHER,native[2],native[3],self.review
        self.binary_patch=patch.object(self.url_adapter.snap,'executable',side_effect=executable).start()
        self.chain_patch=patch.object(self.url_adapter,'_chain',side_effect=lambda:self.chain).start()
        self.env_patch=patch.object(self.url_adapter,'_environment',side_effect=lambda:self.environment).start()
        # Any accidental real credential-file read makes the test fail.
        self.credential_guard=patch('friday.security.owner.private_config',side_effect=AssertionError('real credentials forbidden')).start()

    def navigate(self,url=YOUTUBE_URL,**arguments):
        return self.invoke(HandoffOperation.NAVIGATE.value,{'url':url,**arguments})

    def assert_failed(self,result,status):
        self.assertFalse(result.success);self.assertIsNone(result.data)
        self.assertEqual(result.error,HANDOFF_FAILURE_MESSAGES[status])


class FirefoxUrlHandoffTests(FirefoxUrlHandoffFixture):
    def test_exact_command_executes_without_model_or_atspi(self):
        assistant,provider=self.assistant()
        with patch('friday.desktop.atspi.AtspiBackend.list_windows',side_effect=AssertionError('AT-SPI forbidden')):
            response=assistant.respond('open firefox and go to youtube')
        self.assertIn(ACCEPTED_MESSAGE,response)
        self.assertNotIn('Verified:',response);self.assertNotIn('No workflow steps',response)
        provider.chat.assert_not_called();self.process.assert_called_once()
        self.assertEqual(self.memory.get_recent_messages(100),[])
        self.assertEqual(self.memory.recent_work(),())

    def test_fixed_executable_argv_environment_and_no_shell(self):
        result=self.navigate();self.assertTrue(result.success)
        self.assertEqual(result.data['status'],'request_accepted')
        self.assertFalse(result.data['page_load_verified'])
        call=self.process.call_args
        self.assertEqual(call.args[0],['/usr/bin/snap','run','firefox','--new-window',YOUTUBE_URL])
        self.assertIs(call.kwargs['shell'],False)
        fd=call.kwargs['pass_fds'][0]
        self.assertEqual(call.kwargs['executable'],f'/proc/self/fd/{fd}')
        self.assertEqual(call.kwargs['env'],dict(self.environment))
        for key in ('stdin','stdout','stderr'):self.assertEqual(call.kwargs[key],subprocess.DEVNULL)
        self.assertTrue(call.kwargs['close_fds']);self.assertTrue(call.kwargs['start_new_session'])
        self.assertEqual(call.kwargs['cwd'],'/')

    def test_auth_before_exact_allow_once_before_process(self):
        order=[]
        self.auth.authenticate.side_effect=lambda _:order.append('auth')
        self.approval.request.side_effect=lambda _:(order.append('permission') or FolderDecision.ALLOW_ONCE)
        self.process.side_effect=lambda *a,**k:(order.append('process') or self.child)
        self.assertTrue(self.navigate().success)
        self.assertEqual(order,['auth','permission','process'])
        auth=self.auth.authenticate.call_args.args[0]
        permission=self.approval.request.call_args.args[0]
        self.assertIs(auth.operation,SensitiveOperation.BROWSER_NAVIGATION)
        self.assertEqual(auth.application_id,'firefox');self.assertEqual(auth.target,permission.target)
        self.assertIn(YOUTUBE_URL,permission.target);self.assertIn('firefox',permission.target)
        self.assertIn('not be independently verified',permission.effect)
        self.assertIn('Allow once',permission.prompt());self.assertIn('Deny',permission.prompt())

    def test_fresh_auth_and_permission_for_each_handoff(self):
        self.assertTrue(self.navigate().success);self.assertTrue(self.navigate().success)
        self.assertEqual(self.auth.authenticate.call_count,2)
        self.assertEqual(self.approval.request.call_count,2);self.assertEqual(self.process.call_count,2)

    def test_actual_authenticator_synthetic_correct_and_incorrect_secrets(self):
        reader=Mock(return_value='synthetic-passphrase')
        provider=Mock();provider.verify.side_effect=lambda _,value:value=='synthetic-passphrase'
        self.adapter.owner_auth=OwnerAuthenticator('/synthetic/never-read',reader=reader,
            provider_factory=lambda:provider,clock=lambda:1)
        with patch('friday.security.owner.load_hash',return_value='synthetic-hash'):
            self.assertTrue(self.navigate().success)
            reader.return_value='synthetic-wrong-passphrase'
            result=self.navigate()
        self.assertEqual(result.error_category,ToolErrorCategory.OWNER_AUTHENTICATION)
        self.assertEqual(self.process.call_count,1);self.assertEqual(self.approval.request.call_count,1)
        self.assertNotIn('synthetic-wrong-passphrase',str(result));self.assertNotIn('synthetic-hash',str(result))

    def test_bad_passphrase_has_zero_permission_or_actions(self):
        self.auth.authenticate.side_effect=OwnerAuthenticationError('synthetic-secret')
        result=self.navigate();self.assertFalse(result.success)
        self.approval.request.assert_not_called();self.process.assert_not_called()
        self.assertNotIn('synthetic-secret',str(result))

    def test_missing_authenticator_has_zero_actions(self):
        self.adapter.owner_auth=None;self.assertFalse(self.navigate().success)
        self.approval.request.assert_not_called();self.process.assert_not_called()

    def test_permission_denial_has_zero_actions(self):
        self.approval.request.return_value=FolderDecision.DENY
        self.assertFalse(self.navigate().success);self.auth.authenticate.assert_called_once()
        self.process.assert_not_called()

    def test_persistent_grant_is_rejected(self):
        self.approval.request.return_value=FolderDecision.ALLOW_PERSISTENT
        self.assertFalse(self.navigate().success);self.process.assert_not_called()

    def test_interrupted_approval_has_zero_actions(self):
        self.approval.request.side_effect=KeyboardInterrupt()
        self.assertFalse(self.navigate().success);self.process.assert_not_called()

    def test_missing_capability_precedes_authentication(self):
        self.binary_patch.side_effect=FileNotFoundError('synthetic-private-path')
        self.assertFalse(self.navigate().success)
        self.auth.authenticate.assert_not_called();self.approval.request.assert_not_called();self.process.assert_not_called()

    def test_nonfixed_dispatcher_is_unavailable_before_authentication(self):
        @contextmanager
        def wrong_dispatcher(_):
            with self.apps.executable('firefox') as native:
                yield native[0],Path('/tmp/other-launcher'),native[2],native[3],self.review
        self.binary_patch.side_effect=wrong_dispatcher
        self.assertFalse(self.navigate().success)
        self.auth.authenticate.assert_not_called();self.process.assert_not_called()

    def test_busy_handoff_does_not_launch_another_process(self):
        self.execution._busy.acquire()
        try:self.assert_failed(self.navigate(),'url_handoff_failed')
        finally:self.execution._busy.release()
        self.process.assert_not_called()

    def test_existing_firefox_remote_exit_zero_is_acceptance_only(self):
        # No enumeration or attribution is needed when Firefox forwards the URL.
        with patch('os.readlink',side_effect=AssertionError('process inference forbidden')):
            result=self.navigate()
        self.assertTrue(result.success);self.assertIs(result.data['page_load_verified'],False)
        self.child.kill.assert_not_called();self.process.assert_called_once()

    def test_cancel_during_revalidation_stops_before_spawn(self):
        original=self.url_adapter.revalidate
        def cancel(context,deadline):
            self.adapter.stop_handoffs();return original(context,deadline)
        self.url_adapter.revalidate=cancel
        self.assert_failed(self.navigate(),'url_handoff_cancelled');self.process.assert_not_called()

    def test_unreviewed_destination_has_zero_actions(self):
        for url in ('https://example.com/','https://www.youtube.com/watch?v=x',
                    'https://www.youtube.com/?token=synthetic-secret','http://www.youtube.com/',
                    'https://www.youtube.com.evil.example/','https://user:pass@www.youtube.com/',
                    'https://www.youtube.com:443/','https://www.youtube.com/#x','https://www.youtube.com'):
            with self.subTest(url=url):self.assertFalse(self.navigate(url).success)
        self.auth.authenticate.assert_not_called();self.process.assert_not_called()

    def test_shell_injection_and_arbitrary_flags_paths_rejected(self):
        for url in ('$(touch /tmp/friday-injection)','`id`','--no-sandbox',
                    YOUTUBE_URL+'; touch /tmp/friday-injection',YOUTUBE_URL+'\n--private'):
            with self.subTest(url=url):self.assertFalse(self.navigate(url).success)
        for extra in ({'args':'--no-sandbox'},{'application_id':'vscode'},{'executable':'/tmp/attacker'},{'shell':True}):
            self.assertFalse(self.navigate(**extra).success)
        self.auth.authenticate.assert_not_called();self.process.assert_not_called()

    def test_other_browser_workflows_remain_plan_only(self):
        assistant,provider=self.assistant()
        for command in ('open firefox and search for python tutorials','open firefox and go to gatewalla'):
            response=assistant.respond(command);self.assertNotIn(ACCEPTED_MESSAGE,response)
        self.auth.authenticate.assert_not_called();self.process.assert_not_called();provider.chat.assert_not_called()

    def test_process_failure_does_not_claim_acceptance(self):
        self.child.wait.return_value=1
        self.assert_failed(self.navigate(),'url_handoff_failed');self.process.assert_called_once()

    def test_process_spawn_exception_never_leaks(self):
        self.process.side_effect=OSError('PRIVATE_CONTENT synthetic-secret')
        result=self.navigate();self.assert_failed(result,'url_handoff_failed')
        self.assertNotIn('PRIVATE_CONTENT',str(result));self.assertNotIn('synthetic-secret',str(result))

    def test_process_timeout_is_bounded_uncertain_and_not_retried(self):
        now=[0];self.execution.clock=lambda:now[0]
        self.child.poll.return_value=None
        def wait(timeout):
            if timeout==1:return -9
            self.assertLessEqual(timeout,.1);now[0]=6
            raise subprocess.TimeoutExpired('synthetic-fixed-command',timeout)
        self.child.wait.side_effect=wait
        result=self.navigate();self.assert_failed(result,'url_handoff_timeout')
        self.assertIn('may have reached Firefox',result.error)
        self.process.assert_called_once();self.child.kill.assert_called_once()

    def test_cancellation_before_authentication_has_zero_actions(self):
        self.adapter.stop_handoffs();self.assert_failed(self.navigate(),'cancelled')
        self.auth.authenticate.assert_not_called();self.process.assert_not_called()

    def test_cancellation_during_authentication_has_zero_actions(self):
        self.auth.authenticate.side_effect=lambda _:self.adapter.stop_handoffs()
        self.assertFalse(self.navigate().success);self.approval.request.assert_not_called();self.process.assert_not_called()

    def test_cancellation_after_approval_has_zero_actions(self):
        self.approval.request.side_effect=lambda _:(self.adapter.stop_handoffs() or FolderDecision.ALLOW_ONCE)
        self.assert_failed(self.navigate(),'url_handoff_cancelled');self.process.assert_not_called()

    def test_cancellation_after_start_only_stops_owned_invocation(self):
        self.child.poll.return_value=None
        self.process.side_effect=lambda *a,**k:(self.adapter.stop_handoffs() or self.child)
        with patch('os.kill') as kill:
            self.assert_failed(self.navigate(),'url_handoff_cancelled')
        self.process.assert_called_once();self.child.kill.assert_called_once();kill.assert_not_called()

    def test_installation_change_after_approval_rejected_before_spawn(self):
        self.approval.request.side_effect=lambda _:(setattr(self,'review',('changed',)) or FolderDecision.ALLOW_ONCE)
        self.assert_failed(self.navigate(),'url_handoff_failed');self.process.assert_not_called()

    def test_chain_change_after_approval_rejected_before_spawn(self):
        self.approval.request.side_effect=lambda _:(setattr(self,'chain',(('changed',),)) or FolderDecision.ALLOW_ONCE)
        self.assert_failed(self.navigate(),'url_handoff_failed');self.process.assert_not_called()

    def test_session_change_after_approval_rejected_before_spawn(self):
        self.approval.request.side_effect=lambda _:(setattr(self,'environment',(('changed','session'),)) or FolderDecision.ALLOW_ONCE)
        self.assert_failed(self.navigate(),'url_handoff_failed');self.process.assert_not_called()

    def test_dispatcher_change_after_approval_rejected_before_spawn(self):
        def approve(_):
            self.paths['firefox'].write_bytes(b'\x7fELFchanged');return FolderDecision.ALLOW_ONCE
        self.approval.request.side_effect=approve
        self.assert_failed(self.navigate(),'url_handoff_failed');self.process.assert_not_called()

    def test_adapter_substitution_after_approval_rejected_before_spawn(self):
        self.approval.request.side_effect=lambda _:(setattr(self.execution,'adapter',UnavailableFirefoxUrlAdapter()) or FolderDecision.ALLOW_ONCE)
        self.assert_failed(self.navigate(),'url_handoff_failed');self.process.assert_not_called()

    def test_installation_change_after_spawn_prevents_acceptance(self):
        self.child.wait.side_effect=lambda **_:(setattr(self,'review',('changed',)) or 0)
        self.assert_failed(self.navigate(),'url_handoff_failed');self.process.assert_called_once()

    def test_lease_is_exact_and_single_use(self):
        request=ToolRequest(HandoffOperation.NAVIGATE.value,{'url':YOUTUBE_URL})
        with self.adapter.execution(request):
            self.assertEqual(self.adapter.execute(request.tool_name,request.arguments)['status'],'request_accepted')
            with self.assertRaises(PermissionError):self.adapter.execute(request.tool_name,request.arguments)
        self.process.assert_called_once()

    def test_unauthorized_or_tampered_lease_cannot_launch(self):
        with ExitStack() as stack:
            lease=self.execution.prepare(HandoffRequest(HandoffOperation.NAVIGATE,value=YOUTUBE_URL),stack)
            with self.assertRaises(PermissionError):self.execution.execute(lease)
            self.execution.authorize(lease,self.auth,self.approval,DesktopApproval)
            lease['url_handoff_context']=replace(lease['url_handoff_context'],snap_identity=('changed',))
            with self.assertRaises(PermissionError):self.execution.execute(lease)
        self.process.assert_not_called()

    def test_general_snap_policy_remains_app_only(self):
        self.assertEqual(ReviewedSnap.arguments('firefox'),['run','firefox'])
        for app in ('firefox','vscode'):
            with self.assertRaises(ValueError):ReviewedSnap.arguments(app,url=YOUTUBE_URL)

    def test_legacy_url_launcher_cannot_bypass_handoff(self):
        self.apps.production=True
        result=self.invoke('launch_application',{'application_id':'firefox','url':YOUTUBE_URL})
        self.assertEqual(result.data['status'],'invalid_target');self.process.assert_not_called()

    def test_verified_window_backend_remains_disabled(self):
        self.assertFalse(self.adapter.browser_execution.available(BrowserTarget.from_request(
            HandoffRequest(HandoffOperation.NAVIGATE,value=YOUTUBE_URL))))

    def test_unverified_status_cannot_be_used_by_other_handoffs(self):
        self.adapter.execute=Mock(return_value={'status':'request_accepted','url':YOUTUBE_URL,
            'page_load_verified':False,'message':ACCEPTED_MESSAGE})
        # Stub authorization only to test ToolManager's output contract.
        from contextlib import nullcontext
        self.adapter.execution=Mock(return_value=nullcontext())
        result=self.invoke(HandoffOperation.SEARCH.value,{'query':'youtube'})
        self.assertFalse(result.success);self.assertIsNone(result.data)


class LauncherChainTests(unittest.TestCase):
    def test_package_hash_mismatch_rejected_without_execution(self):
        adapter=FirefoxSnapUrlAdapter()
        with patch('friday.desktop.firefox_url_handoff.directory_descriptor') as directory, \
             patch('pathlib.Path.resolve',return_value=Path('/snap/firefox/8763')), \
             patch('os.fstat',return_value=SimpleNamespace(st_uid=0,st_dev=1,st_ino=2,
                 st_mode=stat.S_IFREG|0o755,st_size=3,st_mtime_ns=4)), \
             patch('os.fstatvfs',return_value=SimpleNamespace(f_flag=os.ST_RDONLY)), \
             patch('os.open',return_value=123),patch('os.close'),patch('os.read',return_value=b'bad'):
            directory.return_value.__enter__.return_value=123
            with self.assertRaises(ValueError):adapter._chain()

    def test_mutable_package_mount_rejected_without_execution(self):
        adapter=FirefoxSnapUrlAdapter()
        with patch('friday.desktop.firefox_url_handoff.directory_descriptor') as directory, \
             patch('pathlib.Path.resolve',return_value=Path('/snap/firefox/8763')), \
             patch('os.fstat',return_value=SimpleNamespace(st_uid=0)), \
             patch('os.fstatvfs',return_value=SimpleNamespace(f_flag=0)):
            directory.return_value.__enter__.return_value=123
            with self.assertRaises(ValueError):adapter._chain()

    def test_missing_safe_desktop_session_rejected(self):
        with patch('friday.desktop.runtime.desktop_environment',return_value=('wayland',None)):
            with self.assertRaises(ValueError):FirefoxSnapUrlAdapter._environment()

    def test_loader_and_secret_environment_not_forwarded(self):
        with patch('friday.desktop.runtime.desktop_environment',return_value=('wayland',
                {'HOME':'/synthetic','XDG_RUNTIME_DIR':'/synthetic/runtime'})):
            environment=dict(FirefoxSnapUrlAdapter._environment())
        self.assertEqual(environment,{'HOME':'/synthetic','XDG_RUNTIME_DIR':'/synthetic/runtime','SNAP_REEXEC':'0'})

    def test_adapter_accepts_only_canonical_navigation_target(self):
        adapter=FirefoxSnapUrlAdapter()
        self.assertFalse(adapter.available(BrowserTarget.from_request(HandoffRequest(HandoffOperation.SEARCH,value='youtube'))))
        with self.assertRaises(ValueError):adapter.handoff(None,None,None)


if __name__=='__main__':unittest.main()
