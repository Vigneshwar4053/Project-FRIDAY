"""Synthetic browser evidence only; no real .env, Firefox, D-Bus or network."""
from dataclasses import replace
from unittest.mock import Mock, patch
import unittest

from test_discovery_workflows import DiscoveryWorkflowFixture
from friday.desktop.browser_execution import (BrowserTarget, BrowserContext, BrowserWindow,
    NavigationReceipt, NavigationProof, UnavailableFirefoxBackend, compile_browser_plan,
    exact_destination, SEARCH_PROVIDER)
from friday.desktop.handoffs import HandoffOperation, HandoffRequest, HANDOFF_FAILURE_MESSAGES
from friday.desktop.observation import WindowRef
from friday.desktop.workflows import parse_workflow, WorkflowPlan
from friday.security.owner import OwnerAuthenticator, OwnerAuthenticationError
from friday.tools.access import FolderDecision
from friday.tools.models import ToolRequest, ToolErrorCategory


class SyntheticBrowser(UnavailableFirefoxBackend):
    def __init__(self):
        self.calls=[]; self.running=True; self.enabled=True
        self.identity=BrowserContext('synthetic_browser',(1,2,3,4),'synthetic_session')
        self.window_ok=True; self.proof_ok=True; self.callback=None; self.window_current=True
    def supports(self,target): return self.enabled
    def context(self,target): return self.identity
    def revalidate(self,context,deadline):
        deadline.check()
        return context == self.identity
    def acquire(self,context,target,deadline):
        deadline.check(); self.calls.append('acquire')
        if self.callback: self.callback('acquire')
        if not self.window_ok: return None
        return BrowserWindow(context,WindowRef('firefox','synthetic_window','synthetic_process'),True,not self.running)
    def revalidate_window(self,window,deadline):
        deadline.check()
        return self.window_current
    def navigate(self,window,target,deadline):
        deadline.check(); self.calls.append('navigate')
        if self.callback: self.callback('navigate')
        return NavigationReceipt(target,window,'synthetic_navigation')
    def verify(self,receipt,deadline):
        deadline.check(); self.calls.append('verify')
        if self.callback: self.callback('verify')
        return NavigationProof(receipt,receipt.target.url,self.proof_ok)


class TargetTests(unittest.TestCase):
    def test_youtube_reviewed_forms(self):
        for value in ('youtube','YouTube','https://www.youtube.com','https://www.youtube.com/'):
            self.assertEqual(exact_destination(value),'https://www.youtube.com/')
    def test_unsafe_and_unreviewed_destinations(self):
        for value in ('javascript:alert(1)','data:text/html,x','file:///tmp/a','http://www.youtube.com/',
                      'https://user:pass@www.youtube.com/','https://www.youtube.com:443/',
                      'https://127.0.0.1/','https://localhost/','https://private.example/',
                      'https://www.youtube.com.evil.example/','https://www.youtube.com/watch?v=x',
                      'https://www.youtube.com/#x','https://www.youtube.com/?x=1',
                      'https://www.youtube.com/?','https://www.youtube.com/#',
                      'https://www.youtube.com/\n','https://www.youtube.com\\@evil/',
                      'https://www..youtube.com/','https://[::1]/','unknownsite'):
            with self.subTest(value=value), self.assertRaises(ValueError): exact_destination(value)
    def test_search_encoding(self):
        target=BrowserTarget.from_request(HandoffRequest(HandoffOperation.SEARCH,value='C++ & Python #1 café'))
        self.assertEqual(target.url,SEARCH_PROVIDER+'?q=C%2B%2B+%26+Python+%231+caf%C3%A9')
    def test_query_bound_and_injection(self):
        for value in ('x'*257,'; touch /tmp/x','$(id)','`id`','hello\nworld','   '):
            with self.subTest(value=value),self.assertRaises(ValueError):
                BrowserTarget.from_request(HandoffRequest(HandoffOperation.SEARCH,value=value))
    def test_compiler_reviewed_patterns(self):
        for command in ('open firefox and go to youtube','open firefox and open youtube',
                        'open firefox and go to https://www.youtube.com/',
                        'open firefox and search for python tutorials','open firefox and search for gatewalla'):
            with self.subTest(command=command):
                self.assertIsNotNone(compile_browser_plan(parse_workflow(command)))
    def test_unknown_site_never_invents_domain(self):
        plan=parse_workflow('open firefox and go to unknownsite')
        self.assertIsNotNone(plan.clarification); self.assertIsNone(compile_browser_plan(plan))
        self.assertNotIn('gatewalla.com',plan.response())
    def test_plan_shape_not_generic_interpreter(self):
        plan=parse_workflow('open firefox and go to youtube')
        self.assertIsNone(compile_browser_plan(WorkflowPlan(plan.steps[:-1])))
        self.assertIsNone(compile_browser_plan(WorkflowPlan(tuple(reversed(plan.steps)))))
        self.assertIsNone(compile_browser_plan(parse_workflow('open downloads and find data.js')))
    def test_unreviewed_exact_site_stays_non_executable(self):
        with self.assertRaises(ValueError):
            compile_browser_plan(parse_workflow('open firefox and go to https://example.com/'))


class BrowserExecutionTests(DiscoveryWorkflowFixture):
    def setUp(self):
        super().setUp()
        self.backend=SyntheticBrowser()
        self.execution=self.adapter.browser_execution
        self.execution.backend=self.backend
        self.auth=Mock(spec=OwnerAuthenticator)
        self.adapter.owner_auth=self.auth
    def navigate(self):
        return self.invoke(HandoffOperation.NAVIGATE.value,{'url':'https://www.youtube.com/'})
    def rejected(self,result,status):
        self.assertFalse(result.success); self.assertIsNone(result.data)
        self.assertEqual(result.error,HANDOFF_FAILURE_MESSAGES[status])
    def test_exact_authenticated_approved_verified_navigation(self):
        result=self.navigate()
        self.assertTrue(result.success); self.assertEqual(result.data['status'],'verified')
        self.assertEqual(result.data['phases'],('authenticated','permission_approved',
            'firefox_window_attributed','navigation_attempted','navigation_verified'))
        self.assertEqual(self.auth.authenticate.call_args.args[0].target,
                         self.approval.request.call_args.args[0].target)
        self.assertEqual(self.approval.request.call_args.args[0].operation,HandoffOperation.NAVIGATE.value)
        self.assertEqual(self.backend.calls,['acquire','navigate','verify'])
        self.process.assert_not_called(); self.assertEqual(self.memory.recent_work(),())
    def test_real_authenticator_synthetic_correct_incorrect_cooldown(self):
        reader=Mock(return_value='synthetic-passphrase')
        provider=Mock(); provider.verify.side_effect=lambda _,value:value=='synthetic-passphrase'
        auth=OwnerAuthenticator('/synthetic/never-read',reader=reader,provider_factory=lambda:provider,clock=lambda:1)
        self.adapter.owner_auth=auth
        with patch('friday.security.owner.load_hash',return_value='synthetic-hash'):
            self.assertTrue(self.navigate().success)
            reader.return_value='synthetic-wrong-passphrase'
            for _ in range(4):
                result=self.navigate()
                self.assertEqual(result.error_category,ToolErrorCategory.OWNER_AUTHENTICATION)
        self.assertEqual(reader.call_count,4);self.assertEqual(self.approval.request.call_count,1)
        self.assertEqual(self.backend.calls,['acquire','navigate','verify'])
        self.assertNotIn(reader.return_value,str(result)); self.assertEqual(self.memory.get_recent_messages(100),[])
    def test_bad_auth_zero_launch_navigation_permission(self):
        self.auth.authenticate.side_effect=OwnerAuthenticationError('synthetic-secret')
        result=self.navigate(); self.assertFalse(result.success)
        self.assertNotIn('synthetic-secret',str(result))
        self.approval.request.assert_not_called();self.assertEqual(self.backend.calls,[])
    def test_missing_authenticator(self):
        self.adapter.owner_auth=None
        self.assertFalse(self.navigate().success);self.assertEqual(self.backend.calls,[])
    def test_deny_after_auth_zero_actions(self):
        self.approval.request.return_value=FolderDecision.DENY
        self.assertFalse(self.navigate().success)
        self.auth.authenticate.assert_called_once();self.assertEqual(self.backend.calls,[])
    def test_persistent_grant_not_accepted(self):
        self.approval.request.return_value=FolderDecision.ALLOW_PERSISTENT
        self.assertFalse(self.navigate().success);self.assertEqual(self.backend.calls,[])
    def test_fresh_auth_and_permission_each_time(self):
        self.navigate();self.navigate()
        self.assertEqual(self.auth.authenticate.call_count,2)
        self.assertEqual(self.approval.request.call_count,2)
    def test_search_exact_scope(self):
        result=self.invoke(HandoffOperation.SEARCH.value,{'query':'python tutorials'})
        self.assertEqual(result.data['url'],SEARCH_PROVIDER+'?q=python+tutorials')
        scope=self.approval.request.call_args.args[0].target
        self.assertIn('python tutorials',scope);self.assertIn(SEARCH_PROVIDER,scope)
        self.assertEqual(scope,self.auth.authenticate.call_args.args[0].target)
    def test_changed_executable_or_session_after_approval(self):
        def changed(_):
            self.backend.identity=replace(self.backend.identity,executable_identity=(9,9,9,9))
            return FolderDecision.ALLOW_ONCE
        self.approval.request.side_effect=changed
        self.rejected(self.navigate(),'handoff_failed');self.assertEqual(self.backend.calls,[])
    def test_changed_backend_after_approval(self):
        self.approval.request.side_effect=lambda _:(setattr(self.execution,'backend',SyntheticBrowser()) or FolderDecision.ALLOW_ONCE)
        self.rejected(self.navigate(),'handoff_failed');self.assertEqual(self.backend.calls,[])
    def test_capability_removed_after_approval(self):
        self.approval.request.side_effect=lambda _:(setattr(self.backend,'enabled',False) or FolderDecision.ALLOW_ONCE)
        self.rejected(self.navigate(),'handoff_failed');self.assertEqual(self.backend.calls,[])
    def test_unattributed_window_no_navigation(self):
        self.backend.window_ok=False
        self.rejected(self.navigate(),'window_unverified');self.assertEqual(self.backend.calls,['acquire'])
    def test_wrong_window_application(self):
        self.backend.acquire=Mock(return_value=WindowRef('vscode','wrong','wrong_process'))
        self.rejected(self.navigate(),'window_unverified');self.assertEqual(self.backend.calls,[])
    def test_hidden_window_no_navigation(self):
        self.backend.acquire=Mock(return_value=BrowserWindow(self.backend.identity,
            WindowRef('firefox','hidden','process'),False,False))
        self.rejected(self.navigate(),'window_unverified')
    def test_navigation_proof_required(self):
        self.backend.proof_ok=False
        self.rejected(self.navigate(),'navigation_unverified')
    def test_redirects_and_alternate_destinations_rejected(self):
        self.backend.verify=lambda receipt,deadline:NavigationProof(receipt,'https://example.com/',True)
        self.rejected(self.navigate(),'navigation_unverified')
    def test_different_navigation_receipt_rejected(self):
        self.backend.verify=lambda receipt,deadline:NavigationProof(replace(receipt,navigation_id='different'),receipt.target.url,True)
        self.rejected(self.navigate(),'navigation_unverified')
    def test_different_window_proof_rejected(self):
        def verify(receipt,deadline):
            other=replace(receipt.window,window=WindowRef('firefox','other','other_process'))
            return NavigationProof(replace(receipt,window=other),receipt.target.url,True)
        self.backend.verify=verify
        self.rejected(self.navigate(),'navigation_unverified')
    def test_running_firefox_does_not_imply_completion(self):
        self.backend.running=True;self.backend.proof_ok=False
        self.rejected(self.navigate(),'navigation_unverified')
    def test_not_running_launch_is_separate_phase(self):
        self.backend.running=False
        result=self.navigate();self.assertIn('launch_attempted',result.data['phases'])
    def test_timeout_stops_before_navigation(self):
        now=[0];self.execution.clock=lambda:now[0]
        self.backend.callback=lambda phase:now.__setitem__(0,11)
        self.rejected(self.navigate(),'timeout');self.assertEqual(self.backend.calls,['acquire'])
    def test_cancel_before_request(self):
        self.adapter.stop_handoffs()
        self.rejected(self.navigate(),'cancelled');self.auth.authenticate.assert_not_called()
        self.assertEqual(self.backend.calls,[])
    def test_cancel_after_permission(self):
        self.approval.request.side_effect=lambda _:(self.adapter.stop_handoffs() or FolderDecision.ALLOW_ONCE)
        self.rejected(self.navigate(),'cancelled');self.assertEqual(self.backend.calls,[])
    def test_cancel_after_acquire_no_navigation(self):
        self.backend.callback=lambda phase:self.adapter.stop_handoffs()
        self.rejected(self.navigate(),'cancelled');self.assertEqual(self.backend.calls,['acquire'])
    def test_one_use_lease_and_changed_target_rejected(self):
        request=ToolRequest(HandoffOperation.NAVIGATE.value,{'url':'https://www.youtube.com/'})
        with self.adapter.execution(request):
            self.assertEqual(self.adapter.execute(request.tool_name,request.arguments)['status'],'verified')
            with self.assertRaises(PermissionError):self.adapter.execute(request.tool_name,request.arguments)
        lease=self.execution.prepare(HandoffRequest(HandoffOperation.NAVIGATE,value='https://www.youtube.com/'))
        from friday.desktop.runtime import DesktopApproval
        self.execution.authorize(lease,self.auth,self.approval,DesktopApproval)
        lease['browser_target']=BrowserTarget.from_request(HandoffRequest(HandoffOperation.SEARCH,value='changed'))
        with self.assertRaises(PermissionError):self.execution.execute(lease)
    def test_default_production_backend_no_auth_no_partial_launch(self):
        self.execution.backend=UnavailableFirefoxBackend()
        self.rejected(self.navigate(),'unsupported_capability')
        self.auth.authenticate.assert_not_called();self.approval.request.assert_not_called();self.process.assert_not_called()
    def test_workflow_dispatch_with_verified_mock_no_model(self):
        assistant,provider=self.assistant()
        response=assistant.respond('open firefox and go to youtube')
        self.assertIn('Verified:',response);provider.chat.assert_not_called()
        self.assertEqual(self.backend.calls,['acquire','navigate','verify'])
        self.assertEqual(self.memory.get_recent_messages(100),[])
    def test_default_workflow_executes_zero_steps(self):
        self.execution.backend=UnavailableFirefoxBackend()
        assistant,provider=self.assistant()
        with patch.object(self.manager,'execute',wraps=self.manager.execute) as execute:
            response=assistant.respond('open firefox and search for python tutorials')
        self.assertIn('No workflow steps',response);execute.assert_not_called();provider.chat.assert_not_called()
        self.auth.authenticate.assert_not_called();self.process.assert_not_called()
    def test_unknown_site_zero_execution(self):
        assistant,provider=self.assistant()
        response=assistant.respond('open firefox and go to unknownsite')
        self.assertIn('unrecognized',response);self.auth.authenticate.assert_not_called()
        self.assertEqual(self.backend.calls,[]);self.process.assert_not_called()
    def test_unreviewed_exact_url_zero_execution(self):
        assistant,provider=self.assistant()
        response=assistant.respond('open firefox and go to https://private.example/')
        self.assertIn('outside the reviewed policy',response);self.auth.authenticate.assert_not_called()
        self.assertEqual(self.backend.calls,[])
    def test_no_extra_arguments_or_shell(self):
        result=self.invoke(HandoffOperation.NAVIGATE.value,{'url':'https://www.youtube.com/','args':'--no-sandbox'})
        self.assertFalse(result.success);self.process.assert_not_called();self.assertEqual(self.backend.calls,[])
        self.assertFalse(self.invoke(HandoffOperation.SEARCH.value,{'query':'$(touch /tmp/x)'}).success)
    def test_backend_errors_do_not_leak_content(self):
        self.backend.navigate=Mock(side_effect=ValueError('PRIVATE_CONTENT synthetic-secret'))
        result=self.navigate();self.assertFalse(result.success)
        self.assertNotIn('PRIVATE_CONTENT',str(result));self.assertNotIn('synthetic-secret',str(result))
    def test_stop_routing_cancels_browser_workflow(self):
        assistant,provider=self.assistant();assistant.respond('stop')
        self.assertTrue(self.execution.cancelled.is_set());self.assertEqual(self.backend.calls,[])
    def test_legacy_app_only_unchanged(self):
        result=self.invoke('launch_application',{'application_id':'firefox'})
        self.assertEqual(result.data['status'],'launch_accepted')
        self.auth.authenticate.assert_not_called();self.assertEqual(self.backend.calls,[])
    def test_vscode_still_disabled(self):
        self.rejected(self.invoke('open_project_in_vscode',{'project_id':'friday'}),'unsupported_capability')
        self.auth.authenticate.assert_not_called();self.process.assert_not_called()

    def test_backend_capability_failure_no_partial_execution(self):
        self.backend.supports=Mock(side_effect=ValueError('PRIVATE_CONTENT'))
        self.rejected(self.navigate(),'unsupported_capability')
        self.auth.authenticate.assert_not_called();self.assertEqual(self.backend.calls,[])
    def test_no_automatic_retry_action_count_bounded(self):
        self.backend.proof_ok=False
        self.navigate()
        self.assertEqual(self.backend.calls,['acquire','navigate','verify'])
    def test_concurrent_task_rejected_no_actions(self):
        self.execution._busy.acquire()
        try:
            self.rejected(self.navigate(),'handoff_failed')
            self.assertEqual(self.backend.calls,[])
        finally:self.execution._busy.release()
    def test_exact_url_punctuation_not_removed(self):
        assistant,provider=self.assistant()
        response=assistant.respond('open firefox and go to https://www.youtube.com/...')
        self.assertIn('outside the reviewed policy',response)
        self.auth.authenticate.assert_not_called();self.assertEqual(self.backend.calls,[])
    def test_credential_query_or_destination_never_read_as_secret(self):
        self.rejected(self.invoke(HandoffOperation.NAVIGATE.value,{'url':'https://www.youtube.com/?token=x'}),'unsupported_destination')
        self.auth.authenticate.assert_not_called();self.assertEqual(self.backend.calls,[])
    def test_gateway_policy_denial_precedes_owner_auth(self):
        from friday.tools import RiskPermissionPolicy, RiskLevel, PermissionDecision
        self.manager.policy=RiskPermissionPolicy({RiskLevel.EXECUTE:PermissionDecision.DENY})
        self.assertFalse(self.navigate().success)
        self.auth.authenticate.assert_not_called();self.assertEqual(self.backend.calls,[])

    def test_window_changes_before_navigation_rejected(self):
        self.backend.window_current=False
        self.rejected(self.navigate(),'window_unverified')
        self.assertEqual(self.backend.calls,['acquire'])
    def test_window_changes_after_navigation_no_success(self):
        self.backend.callback=lambda phase:setattr(self.backend,'window_current',False) if phase=='verify' else None
        self.rejected(self.navigate(),'navigation_unverified')
