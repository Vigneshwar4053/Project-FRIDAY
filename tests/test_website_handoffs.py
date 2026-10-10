"""Owner website routing and mock execution; no live browser or credential I/O."""
from contextlib import ExitStack, nullcontext
from unittest.mock import Mock, patch
import subprocess
import unittest

from test_firefox_url_handoff import FirefoxUrlHandoffFixture
from friday.desktop.browser_execution import BrowserTarget, compile_browser_plan, exact_destination
from friday.desktop.firefox_url_handoff import ACCEPTED_MESSAGE, ARGUMENT_PREFIX
from friday.desktop.handoffs import HandoffOperation, HandoffRequest
from friday.desktop.runtime import DesktopApproval
from friday.desktop.websites import WEBSITES, SITE_ALIASES, approved_url, site_destination
from friday.desktop.workflows import parse_workflow
from friday.security.owner import OwnerAuthenticator, OwnerAuthenticationError
from friday.tools.access import FolderDecision
from friday.tools.models import ToolErrorCategory

EXPECTED = {
    'youtube':'https://www.youtube.com/',
    'linkedin':'https://www.linkedin.com/in/sameti-thirumani-vigneshwar/',
    'whatsapp':'https://web.whatsapp.com/',
    'github':'https://github.com/Vigneshwar4053',
    'pw_study':'https://www.pw.live/study-v2/study',
}
COMMANDS = {
    'open my linkedin':'linkedin',
    'open linkedin':'linkedin',
    'open whatsapp':'whatsapp',
    'open whatsapp web':'whatsapp',
    'open my github':'github',
    'open github':'github',
    'open pw study':'pw_study',
    'open physics wallah':'pw_study',
    'open youtube':'youtube',
    'open firefox and go to linkedin':'linkedin',
    'open firefox and go to whatsapp':'whatsapp',
    'open firefox and go to github':'github',
    'open firefox and go to pw study':'pw_study',
    'open firefox and go to youtube':'youtube',
}


class WebsiteRegistryTests(unittest.TestCase):
    def test_only_the_five_exact_owner_urls_are_registered(self):
        self.assertEqual(dict(WEBSITES),EXPECTED)
        with self.assertRaises(TypeError):WEBSITES['other']='https://other.example/'
        with self.assertRaises(TypeError):SITE_ALIASES['other']='github'

    def test_each_alias_resolves_without_guessing(self):
        for alias,key in SITE_ALIASES.items():
            with self.subTest(alias=alias):
                self.assertEqual(site_destination(alias),EXPECTED[key])
                self.assertEqual(site_destination(alias.upper()),EXPECTED[key])
                self.assertEqual(exact_destination(alias),EXPECTED[key])
        for value in ('facebook','linkedin.com','github.com','Whats App',None):
            self.assertIsNone(site_destination(value))

    def test_every_supported_command_compiles_exactly(self):
        for command,key in COMMANDS.items():
            with self.subTest(command=command):
                request=compile_browser_plan(parse_workflow(command))
                self.assertEqual(request,HandoffRequest(HandoffOperation.NAVIGATE,value=EXPECTED[key]))

    def test_url_validation_is_exact_and_case_sensitive(self):
        for url in EXPECTED.values():
            self.assertTrue(approved_url(url));self.assertEqual(exact_destination(url),url)
            for changed in (url+'/',url+'?x=1',url+'#x',url.upper(),url+' ',url.replace('https:','http:'),
                            url.replace('https://','https://user:pass@')):
                with self.subTest(changed=changed):self.assertFalse(approved_url(changed))
        for value in ('https://github.com/','https://www.linkedin.com/',
                      'https://www.pw.live/','https://whatsapp.com/',None,42):
            self.assertFalse(approved_url(value))

    def test_unknown_site_compounds_never_infer_domains(self):
        for site in ('facebook','unknownsite','github.com','linkedin.com','You Tube','wikipedia'):
            plan=parse_workflow('open firefox and go to '+site)
            self.assertIsNotNone(plan.clarification);self.assertIsNone(compile_browser_plan(plan))
            self.assertNotIn('https://'+site,plan.response())

    def test_generic_github_homepage_is_not_an_executable_destination(self):
        with self.assertRaises(ValueError):exact_destination('https://github.com/')
        with self.assertRaises(ValueError):compile_browser_plan(parse_workflow('open firefox and go to https://github.com/'))


class WebsiteExecutionTests(FirefoxUrlHandoffFixture):
    def test_each_approved_url_executes_only_the_fixed_firefox_argv(self):
        for key,url in EXPECTED.items():
            with self.subTest(site=key):
                self.process.reset_mock()
                result=self.navigate(url)
                self.assertTrue(result.success);self.assertEqual(result.data['url'],url)
                self.assertEqual(result.data['message'],ACCEPTED_MESSAGE)
                self.assertIs(result.data['page_load_verified'],False)
                self.process.assert_called_once()
                self.assertEqual(self.process.call_args.args[0],['/usr/bin/snap','run','firefox','--new-window',url])
                self.assertIs(self.process.call_args.kwargs['shell'],False)
                self.assertEqual(self.process.call_args.kwargs['env']['SNAP_REEXEC'],'0')
                auth=self.auth.authenticate.call_args.args[0]
                approval=self.approval.request.call_args.args[0]
                self.assertEqual(auth.target,approval.target)
                self.assertEqual(auth.application_id,'firefox')
                self.assertIn(url,approval.target);self.assertIn(url,approval.effect)
        self.assertEqual(self.auth.authenticate.call_count,5);self.assertEqual(self.approval.request.call_count,5)

    def test_every_supported_command_executes_without_a_model(self):
        assistant,provider=self.assistant()
        for command,key in COMMANDS.items():
            with self.subTest(command=command):
                self.process.reset_mock()
                response=assistant.respond(command)
                self.assertIn(ACCEPTED_MESSAGE,response);self.assertNotIn('Plan only',response)
                self.process.assert_called_once()
                self.assertEqual(self.process.call_args.args[0][-1],EXPECTED[key])
        self.assertEqual(self.auth.authenticate.call_count,len(COMMANDS))
        self.assertEqual(self.approval.request.call_count,len(COMMANDS))
        provider.chat.assert_not_called();self.assertEqual(self.memory.get_recent_messages(100),[])
        self.assertEqual(self.memory.recent_work(),())

    def test_open_github_uses_owner_profile_not_homepage(self):
        assistant,provider=self.assistant();response=assistant.respond('open github')
        self.assertIn(ACCEPTED_MESSAGE,response)
        self.assertEqual(self.process.call_args.args[0][-1],'https://github.com/Vigneshwar4053')
        self.assertNotEqual(self.process.call_args.args[0][-1],'https://github.com/')
        provider.chat.assert_not_called()

    def test_fresh_authentication_and_permission_for_repeated_and_different_sites(self):
        for url in (EXPECTED['linkedin'],EXPECTED['linkedin'],EXPECTED['github']):
            self.assertTrue(self.navigate(url).success)
        self.assertEqual(self.auth.authenticate.call_count,3)
        self.assertEqual(self.approval.request.call_count,3)
        targets=[call.args[0].target for call in self.approval.request.call_args_list]
        self.assertEqual(targets[0],targets[1]);self.assertNotEqual(targets[1],targets[2])

    def test_incorrect_passphrase_blocks_all_sites_without_leakage(self):
        reader=Mock(return_value='synthetic-wrong-passphrase')
        provider=Mock();provider.verify.return_value=False
        for url in EXPECTED.values():
            self.adapter.owner_auth=OwnerAuthenticator('/synthetic/never-read',reader=reader,
                provider_factory=lambda:provider,clock=lambda:1)
            with patch('friday.security.owner.load_hash',return_value='synthetic-hash'):
                result=self.navigate(url)
            self.assertEqual(result.error_category,ToolErrorCategory.OWNER_AUTHENTICATION)
            self.assertNotIn('synthetic-wrong-passphrase',str(result));self.assertNotIn('synthetic-hash',str(result))
        self.approval.request.assert_not_called();self.process.assert_not_called()

    def test_denial_blocks_all_sites(self):
        self.approval.request.return_value=FolderDecision.DENY
        for url in EXPECTED.values():self.assertFalse(self.navigate(url).success)
        self.assertEqual(self.auth.authenticate.call_count,5);self.process.assert_not_called()

    def test_unsupported_websites_and_url_variants_never_authenticate_or_launch(self):
        for url in ('https://github.com/','https://github.com/Vigneshwar4053/',
                    'https://web.whatsapp.com/?text=synthetic-private-text','https://web.whatsapp.com/#x',
                    'https://www.linkedin.com/in/other/','https://www.pw.live/study-v2/study/',
                    'https://www.pw.live/study-v2/study?','http://web.whatsapp.com/',
                    'javascript:alert(1)','file:///tmp/secret','data:text/html,x'):
            with self.subTest(url=url):self.assertFalse(self.navigate(url).success)
        self.auth.authenticate.assert_not_called();self.approval.request.assert_not_called();self.process.assert_not_called()

    def test_unknown_site_workflows_execute_zero_steps(self):
        assistant,provider=self.assistant()
        for command in ('open firefox and go to facebook','open firefox and go to https://example.com/',
                        'open firefox and go to https://github.com/'):
            response=assistant.respond(command);self.assertNotIn(ACCEPTED_MESSAGE,response)
        self.auth.authenticate.assert_not_called();self.process.assert_not_called();provider.chat.assert_not_called()

    def test_argument_injection_and_other_application_selection_rejected(self):
        for url in EXPECTED.values():
            for changed in (url+'; id',url+'$(id)',url+'\n--private',url+' --no-sandbox'):
                self.assertFalse(self.navigate(changed).success)
            for extra in ({'args':'--private'},{'application_id':'vscode'},{'executable':'/tmp/other'},{'shell':True}):
                self.assertFalse(self.navigate(url,**extra).success)
        self.auth.authenticate.assert_not_called();self.process.assert_not_called()

    def test_substitution_to_another_approved_url_invalidates_authorization(self):
        with ExitStack() as stack:
            request=HandoffRequest(HandoffOperation.NAVIGATE,value=EXPECTED['linkedin'])
            lease=self.execution.prepare(request,stack)
            self.execution.authorize(lease,self.auth,self.approval,DesktopApproval)
            lease['url_handoff_target']=BrowserTarget.from_request(HandoffRequest(
                HandoffOperation.NAVIGATE,value=EXPECTED['github']))
            with self.assertRaises(PermissionError):self.execution.execute(lease)
        self.process.assert_not_called()

    def test_adapter_cannot_substitute_result_url(self):
        self.url_adapter.handoff=Mock(return_value={'status':'request_accepted',
            'url':EXPECTED['github'],'message':ACCEPTED_MESSAGE,'page_load_verified':False})
        self.assert_failed(self.navigate(EXPECTED['linkedin']),'url_handoff_failed')
        self.process.assert_not_called()

    def test_manager_rejects_substituted_url_even_if_approved(self):
        self.adapter.execution=Mock(return_value=nullcontext())
        self.adapter.execute=Mock(return_value={'status':'request_accepted','url':EXPECTED['github'],
            'message':ACCEPTED_MESSAGE,'page_load_verified':False})
        result=self.navigate(EXPECTED['linkedin']);self.assertFalse(result.success);self.assertIsNone(result.data)

    def test_changed_launcher_fingerprint_blocks_each_site(self):
        def approve(_):
            self.paths['firefox'].write_bytes(b'\x7fELFchanged-after-approval');return FolderDecision.ALLOW_ONCE
        self.approval.request.side_effect=approve
        for url in EXPECTED.values():
            self.paths['firefox'].write_bytes(b'\x7fELFfixture')
            self.assert_failed(self.navigate(url),'url_handoff_failed')
        self.process.assert_not_called()

    def test_cancellation_after_approval_prevents_all_site_launches(self):
        self.approval.request.side_effect=lambda _:(self.adapter.stop_handoffs() or FolderDecision.ALLOW_ONCE)
        for url in EXPECTED.values():
            self.execution.cancelled.clear()
            self.assert_failed(self.navigate(url),'url_handoff_cancelled')
        self.process.assert_not_called()

    def test_timeout_for_each_site_has_one_attempt_and_no_load_claim(self):
        for url in EXPECTED.values():
            with self.subTest(url=url):
                now=[0];self.execution.clock=lambda:now[0]
                self.child.poll.return_value=None
                def wait(timeout):
                    if timeout==1:return -9
                    self.assertLessEqual(timeout,.1);now[0]=6
                    raise subprocess.TimeoutExpired('synthetic-command',timeout)
                self.child.wait.side_effect=wait
                self.process.reset_mock();self.child.kill.reset_mock()
                self.assert_failed(self.navigate(url),'url_handoff_timeout')
                self.process.assert_called_once();self.child.kill.assert_called_once()

    def test_success_message_never_claims_page_load_or_site_specific_completion(self):
        self.assertEqual(ACCEPTED_MESSAGE,
            'Firefox navigation request accepted; page load not independently verified.')
        for url in EXPECTED.values():
            result=self.navigate(url);self.assertTrue(result.success)
            self.assertEqual(result.data['message'],ACCEPTED_MESSAGE)
            self.assertIs(result.data['page_load_verified'],False)

    def test_no_login_cookie_profile_content_or_atspi_calls(self):
        with patch('friday.desktop.atspi.AtspiBackend.list_windows',side_effect=AssertionError('UI forbidden')), \
             patch('friday.desktop.atspi.AtspiBackend.observe',side_effect=AssertionError('UI forbidden')):
            for url in EXPECTED.values():self.assertTrue(self.navigate(url).success)
        self.assertEqual(self.memory.recent_work(),());self.assertEqual(self.memory.get_recent_messages(100),[])
        for call in self.process.call_args_list:
            self.assertEqual(call.args[0][1:-1],list(ARGUMENT_PREFIX))
            for key in ('stdin','stdout','stderr'):self.assertEqual(call.kwargs[key],subprocess.DEVNULL)


if __name__=='__main__':unittest.main()
