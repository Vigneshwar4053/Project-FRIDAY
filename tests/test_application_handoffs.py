"""Owner-authorized handoff contracts: mock windows/processes/credentials only.

No .env is read or modified by this suite. The authenticator's loader/provider
are mocked; no real owner secret or GUI observation is used.
"""
from dataclasses import replace
from unittest.mock import Mock, patch

from test_discovery_workflows import DiscoveryWorkflowFixture
from friday.desktop.accessibility import DesktopFailure
from friday.desktop.handoffs import HandoffOperation, HandoffProof, HandoffRequest, HandoffVerifier, HANDOFF_FAILURE_MESSAGES
from friday.desktop.observation import WindowRef
from friday.desktop.registry import ApplicationRegistry
from friday.security.owner import OwnerAuthenticator, OwnerAuthenticationError, SensitiveOperation
from friday.tools.access import FolderDecision
from friday.tools.models import ToolRequest, ToolErrorCategory


class MockVerifier(HandoffVerifier):
    def __init__(self):
        self.calls=[];self.callback=None;self.proof=True
    def supports(self,operation): return operation in {HandoffOperation.PROJECT,HandoffOperation.FILE}
    def verify(self,target,deadline):
        deadline.check();self.calls.append(target)
        if self.callback: self.callback(target)
        deadline.check()
        return (HandoffProof(target,WindowRef('vscode','synthetic_window','synthetic_process'),True)
                if self.proof else None)


class HandoffTests(DiscoveryWorkflowFixture):
    def setUp(self):
        super().setUp()
        self.verifier=MockVerifier();self.adapter.handoff_verifier=self.verifier
        self.auth=Mock(spec=OwnerAuthenticator);self.auth.authenticate.return_value=None
        self.adapter.owner_auth=self.auth

    def open_project(self):
        return self.invoke('open_project_in_vscode',{'project_id':'friday'})

    def assert_rejected(self,result,status):
        self.assertFalse(result.success)
        self.assertIsNone(result.data)
        self.assertEqual(result.error_category,ToolErrorCategory.HANDOFF_FAILED)
        self.assertEqual(result.error,HANDOFF_FAILURE_MESSAGES[status])

    def file_arguments(self):
        self.command('find data.js in downloads')
        return dict(self.router.route('open it in vs code').arguments)

    def test_project_exact_scope_and_verified_postcondition(self):
        result=self.open_project()
        self.assertEqual(result.data['status'],'verified')
        target=self.verifier.calls[0]
        self.assertEqual(target.path,str(self.project));self.assertEqual(target.operation,HandoffOperation.PROJECT)
        self.assertEqual(self.approval.request.call_args.args[0].operation,'open_project_in_vscode')
        owner=self.auth.authenticate.call_args.args[0]
        self.assertEqual(owner.operation,SensitiveOperation.OPEN_PROJECT)
        self.assertEqual(owner.target,self.approval.request.call_args.args[0].target)
        self.assertEqual(self.memory.recent_work(),())

    def test_file_exact_scope_no_contents_read(self):
        item=self.file();arguments=self.file_arguments()
        result=self.invoke('open_file_in_vscode',arguments)
        self.assertEqual(result.data['status'],'verified')
        self.assertEqual(self.verifier.calls[0].path,str(item))
        self.assertEqual(self.verifier.calls[0].operation,HandoffOperation.FILE)
        self.assertEqual(self.auth.authenticate.call_args.args[0].operation,SensitiveOperation.OPEN_FILE)
        self.assertNotIn('NEVER_READ_PRIVATE_CONTENT',str(result))
        self.assertEqual(self.approval.request.call_args.args[0].operation,'open_file_in_vscode')

    def test_authentication_precedes_separate_permission(self):
        events=[]
        self.auth.authenticate.side_effect=lambda _ :events.append('authentication')
        self.approval.request.side_effect=lambda _ :(events.append('permission') or FolderDecision.ALLOW_ONCE)
        self.open_project();self.assertEqual(events,['authentication','permission'])

    def test_correct_and_incorrect_synthetic_passphrases(self):
        provider=Mock();provider.verify.side_effect=lambda _,secret:secret=='synthetic-passphrase'
        reader=Mock(return_value='synthetic-passphrase')
        self.adapter.owner_auth=OwnerAuthenticator('/synthetic/unused-credential-path',reader=reader,provider_factory=lambda:provider)
        with patch('friday.security.owner.load_hash',return_value='synthetic-provider-hash'):
            self.assertEqual(self.open_project().data['status'],'verified')
            reader.return_value='synthetic-incorrect-passphrase'
            result=self.open_project()
        self.assertFalse(result.success);self.assertEqual(result.error_category,ToolErrorCategory.OWNER_AUTHENTICATION)
        self.assertEqual(self.process.call_count,1)
        self.assertEqual(self.approval.request.call_count,1)
        self.assertNotIn(reader.return_value,str(result));self.assertEqual(self.memory.get_recent_messages(100),[])

    def test_denied_authentication_has_no_approval_or_launch(self):
        self.auth.authenticate.side_effect=OwnerAuthenticationError('Denied')
        self.assertFalse(self.open_project().success)
        self.process.assert_not_called();self.approval.request.assert_not_called()

    def test_denied_action_after_authentication_has_no_launch(self):
        self.approval.request.return_value=FolderDecision.DENY
        self.assertFalse(self.open_project().success)
        self.auth.authenticate.assert_called_once();self.process.assert_not_called()

    def test_missing_authenticator_cannot_execute_mock_eligible_handoff(self):
        self.adapter.owner_auth=None
        self.assertFalse(self.open_project().success)
        self.process.assert_not_called();self.approval.request.assert_not_called()

    def test_each_request_authenticates_fresh(self):
        self.open_project();self.open_project()
        self.assertEqual(self.auth.authenticate.call_count,2);self.assertEqual(self.approval.request.call_count,2)

    def test_changed_project_after_permission_rejected(self):
        def changed(_):
            self.project.rename(self.project.parent/'old');self.project.mkdir()
            return FolderDecision.ALLOW_ONCE
        self.approval.request.side_effect=changed
        self.assertFalse(self.open_project().success);self.process.assert_not_called()

    def test_symlink_substitution_after_permission_rejected(self):
        def changed(_):
            old=self.project.parent/'old';self.project.rename(old);self.project.symlink_to(old,target_is_directory=True)
            return FolderDecision.ALLOW_ONCE
        self.approval.request.side_effect=changed
        self.assertFalse(self.open_project().success);self.process.assert_not_called()

    def test_changed_file_after_permission_rejected(self):
        item=self.file();arguments=self.file_arguments()
        self.approval.request.side_effect=lambda _ :(item.write_text('changed') and FolderDecision.ALLOW_ONCE)
        self.assertFalse(self.invoke('open_file_in_vscode',arguments).success);self.process.assert_not_called()

    def test_wrong_target_type_no_auth_or_action(self):
        self.file();arguments=self.file_arguments()
        result=self.invoke('open_project_in_vscode',arguments)
        self.assert_rejected(result,'invalid_target')
        self.auth.authenticate.assert_not_called();self.process.assert_not_called()

    def test_unsupported_verifier_rejects_before_authentication(self):
        self.adapter.handoff_verifier=HandoffVerifier()
        self.assert_rejected(self.open_project(),'unsupported_capability')
        self.auth.authenticate.assert_not_called();self.approval.request.assert_not_called();self.process.assert_not_called()

    def test_snap_project_handoff_remains_blocked(self):
        self.adapter.applications=ApplicationRegistry()
        with patch.object(self.adapter.applications,'executable',side_effect=FileNotFoundError()):
            result=self.open_project()
        self.assert_rejected(result,'unsupported_target')
        self.auth.authenticate.assert_not_called();self.approval.request.assert_not_called();self.process.assert_not_called()

    def test_snap_file_handoff_remains_blocked(self):
        self.file();arguments=self.file_arguments();self.adapter.applications=ApplicationRegistry()
        with patch.object(self.adapter.applications,'executable',side_effect=FileNotFoundError()):
            result=self.invoke('open_file_in_vscode',arguments)
        self.assert_rejected(result,'unsupported_target');self.process.assert_not_called()
        self.auth.authenticate.assert_not_called()

    def test_arbitrary_paths_flags_and_shell_arguments_rejected(self):
        for operation,arguments in (
            ('open_project_in_vscode',{'project_id':'friday','flags':'--disable-sandbox'}),
            ('open_file_in_vscode',{'token':'/etc/passwd'}),
            ('open_project_in_vscode',{'project_id':'../project'}),
            ('open_project_in_vscode',{'project_id':'friday; touch /tmp/pwn'}),
            ('open_project_in_vscode',{'project_id':'friday','token':'a'*32})):
            self.assertFalse(self.invoke(operation,arguments).success)
        self.process.assert_not_called();self.auth.authenticate.assert_not_called()

    def test_fixed_native_argv_no_shell(self):
        self.open_project()
        argv=self.process.call_args.args[0];options=self.process.call_args.kwargs
        self.assertNotIn('shell',options);self.assertEqual(argv[1:4],['--new-window','--disable-extensions','--skip-add-to-recently-opened'])
        self.assertEqual(argv[-2],'--');self.assertTrue(argv[-1].startswith('/proc/self/fd/'))
        self.assertTrue(options['executable'].startswith('/proc/self/fd/'))

    def test_process_launch_without_proof_is_not_success(self):
        self.verifier.proof=False
        result=self.open_project();self.assert_rejected(result,'handoff_unverified')
        self.assertNotIn('Verified:',result.error);self.assertEqual(self.memory.recent_work(),())

    def test_wrong_window_or_target_proof_rejected(self):
        for wrong in ('window','target','hidden'):
            def verify(target,deadline):
                return HandoffProof(replace(target,path=str(self.project.parent/'other')) if wrong=='target' else target,
                    WindowRef('firefox' if wrong=='window' else 'vscode','window','identity'),wrong!='hidden')
            self.verifier.verify=verify
            self.assert_rejected(self.open_project(),'handoff_unverified')

    def test_verification_timeout_stops_with_no_completion_claim(self):
        clock=Mock(return_value=100);self.adapter.handoff_clock=clock
        self.verifier.callback=lambda _ :setattr(clock,'return_value',106)
        result=self.open_project();self.assert_rejected(result,'timeout')
        self.assertNotIn('Verified:',result.error)

    def test_stop_prevents_launch(self):
        self.adapter.stop_handoffs()
        self.assert_rejected(self.open_project(),'cancelled');self.process.assert_not_called()
        self.auth.authenticate.assert_not_called();self.approval.request.assert_not_called()

    def test_production_legacy_project_route_cannot_bypass_verifier(self):
        from copy import copy
        native=copy(self.apps)
        self.apps.production=True;self.adapter.handoff_verifier=HandoffVerifier()
        with patch.object(self.apps,'executable',side_effect=native.executable):
            result=self.invoke('open_project',{'project_id':'friday'})
        self.assertEqual(result.data['status'],'unsupported_capability')
        self.auth.authenticate.assert_not_called();self.process.assert_not_called()

    def test_production_legacy_url_route_cannot_bypass_disabled_browser(self):
        from copy import copy
        native=copy(self.apps)
        self.apps.production=True
        with patch.object(self.apps,'executable',side_effect=native.executable):
            result=self.invoke('launch_application',{'application_id':'firefox','url':'https://github.com/'})
        self.assertEqual(result.data['status'],'unsupported_capability')
        self.auth.authenticate.assert_not_called();self.process.assert_not_called()

    def test_cancelled_permission_stops_before_launch(self):
        self.approval.request.side_effect=KeyboardInterrupt()
        self.assertFalse(self.open_project().success);self.process.assert_not_called()

    def test_file_symlink_after_approval_rejected(self):
        item=self.file();arguments=self.file_arguments()
        def replace_file(_):
            other=item.with_name('old.js');item.rename(other);item.symlink_to(other)
            return FolderDecision.ALLOW_ONCE
        self.approval.request.side_effect=replace_file
        self.assertFalse(self.invoke('open_file_in_vscode',arguments).success);self.process.assert_not_called()

    def test_target_changes_during_verification_no_success(self):
        item=self.file();arguments=self.file_arguments()
        self.verifier.callback=lambda _ :item.write_text('changed during verification')
        self.assert_rejected(self.invoke('open_file_in_vscode',arguments),'handoff_failed')

    def test_failed_native_launch_does_not_call_verifier(self):
        self.child.wait.return_value=1
        self.assert_rejected(self.open_project(),'handoff_failed')
        self.assertEqual(self.verifier.calls,[])

    def test_single_use_exact_request_lease(self):
        request=ToolRequest('open_project_in_vscode',{'project_id':'friday'})
        with self.adapter.execution(request):
            self.assertEqual(self.adapter.execute(request.tool_name,dict(request.arguments))['status'],'verified')
            with self.assertRaises(PermissionError): self.adapter.execute(request.tool_name,dict(request.arguments))
        self.assertEqual(self.process.call_count,1)

    def test_unknown_project_or_receipt_rejected(self):
        result=self.invoke('open_project_in_vscode',{'project_id':'unregistered'})
        self.assert_rejected(result,'unavailable')
        result=self.invoke('open_file_in_vscode',{'token':'a'*32})
        self.assert_rejected(result,'invalid_selection');self.process.assert_not_called()

    def test_firefox_operations_disabled_even_with_mock_verifier(self):
        for operation,arguments in (
            ('navigate_firefox_to_exact_url',{'url':'https://www.youtube.com/'}),
            ('search_firefox_for_query',{'query':'Python tutorials'})):
            result=self.invoke(operation,arguments)
            self.assert_rejected(result,'unsupported_capability')
        self.auth.authenticate.assert_not_called();self.approval.request.assert_not_called();self.process.assert_not_called()

    def test_unknown_browser_urls_or_extra_arguments_rejected(self):
        for arguments in ({'url':'Gatewallah'},{'url':'javascript:alert(1)'},{'url':'https://user:pass@example.com/'},
                          {'url':'https://www.youtube.com/','arguments':'--shell'}):
            self.assertFalse(self.invoke('navigate_firefox_to_exact_url',arguments).success)
        self.process.assert_not_called()

    def test_compound_browser_plan_cannot_execute_partial_launch(self):
        assistant,provider=self.assistant()
        for command in ('open firefox and go to youtube','open firefox and search for Python tutorials'):
            self.assertIsNotNone(self.router.route(command).workflow);assistant.respond(command)
        self.auth.authenticate.assert_not_called();self.process.assert_not_called();provider.chat.assert_not_called()
