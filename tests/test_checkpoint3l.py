"""Checkpoint 3L contracts: synthetic credentials, mocked launcher, no navigation."""
from contextlib import ExitStack
from dataclasses import replace
import subprocess
from unittest.mock import patch

from test_firefox_url_handoff import FirefoxUrlHandoffFixture
from friday.desktop.browser_execution import BrowserTarget, compile_browser_plan
from friday.desktop.firefox_url_handoff import FirefoxUrlHandoff, ACCEPTED_MESSAGE, EXECUTION_BLOCKER
from friday.desktop.handoffs import HandoffOperation, HandoffRequest
from friday.desktop.runtime import DesktopApproval
from friday.desktop.websites import WEBSITES, search_url, site_search_query, MAX_SEARCH_URL_BYTES
from friday.desktop.workflows import parse_workflow
from friday.security.owner import OwnerAuthenticationError
from friday.tools.access import FolderDecision


class Checkpoint3LTests(FirefoxUrlHandoffFixture):
    def search(self, query='python tutorials', **extra):
        return self.invoke(HandoffOperation.SEARCH.value, {'query':query, **extra})

    def test_required_search_commands_execute_exact_google_url(self):
        assistant, provider = self.assistant()
        commands = {
            'search firefox for python tutorials':'python tutorials',
            'open firefox and search for python':'python',
            'search google for cybersecurity':'cybersecurity',
            'search for OWASP top 10':'OWASP top 10',
            'google python decorators':'python decorators',
            'search stackoverflow for python errors':'site:stackoverflow.com python errors',
        }
        for command, query in commands.items():
            with self.subTest(command=command):
                self.process.reset_mock()
                self.assertIn(ACCEPTED_MESSAGE, assistant.respond(command))
                self.process.assert_called_once()
                self.assertEqual(self.process.call_args.args[0],
                    ['/usr/bin/snap','run','firefox','--new-window',search_url(query)])
                self.assertIs(self.process.call_args.kwargs['shell'], False)
                scope = self.auth.authenticate.call_args.args[0].target
                self.assertIn(search_url(query),scope)
                self.assertEqual(scope,self.approval.request.call_args.args[0].target)
        self.assertEqual(self.auth.authenticate.call_count,len(commands))
        self.assertEqual(self.approval.request.call_count,len(commands))
        provider.chat.assert_not_called()
        self.assertEqual(self.memory.get_recent_messages(100),[])
        self.assertEqual(self.memory.recent_work(),())

    def test_unicode_special_characters_and_flags_are_query_data(self):
        expected = {
            'python tutorials':'python+tutorials',
            'C++ & Python #1 café':'C%2B%2B+%26+Python+%231+caf%C3%A9',
            'తెలుగు 日本語':'%E0%B0%A4%E0%B1%86%E0%B0%B2%E0%B1%81%E0%B0%97%E0%B1%81+%E6%97%A5%E6%9C%AC%E8%AA%9E',
            '--private ?q=a%20b / "test"':'--private+%3Fq%3Da%2520b+%2F+%22test%22',
        }
        assistant,provider=self.assistant()
        for query,encoded in expected.items():
            url='https://www.google.com/search?q='+encoded
            self.assertEqual(search_url(query),url)
            self.assertIn(ACCEPTED_MESSAGE,assistant.respond('search for '+query))
            self.assertEqual(self.process.call_args.args[0][-1],url)
        provider.chat.assert_not_called()

    def test_query_and_encoded_url_bounds(self):
        self.assertTrue(self.search('x'*256).success)
        self.assertLessEqual(len(search_url('é'*128)),MAX_SEARCH_URL_BYTES)
        for query in ('x'*257,'é'*129,'','   ','a\nb','a\x85b','$(id)','`id`','; id'):
            self.process.reset_mock()
            self.assertFalse(self.search(query).success)
            self.process.assert_not_called()
        with patch('friday.desktop.websites.MAX_SEARCH_URL_BYTES',35):
            with self.assertRaises(ValueError):search_url('python')

    def test_domain_restrictions_and_owner_registry_domains(self):
        for alias,domain in [('my github','github.com'),('my linkedin','www.linkedin.com'),
                             ('gatewalla','www.pw.live'),('whatsapp','web.whatsapp.com'),
                             ('google','www.google.com'),('youtube','www.youtube.com'),
                             ('stack overflow','stackoverflow.com')]:
            value=site_search_query(alias,'python')
            self.assertEqual(value,'site:'+domain+' python')
            self.assertTrue(self.search(value).success)
        assistant,provider=self.assistant()
        for command in ('search unknownsite for python','search evil.example for python',
                        'search for site:evil.example python','search for site:stackoverflow.com.evil python'):
            self.process.reset_mock();self.auth.reset_mock();self.approval.reset_mock()
            self.assertNotIn(ACCEPTED_MESSAGE,assistant.respond(command))
            self.process.assert_not_called();self.auth.authenticate.assert_not_called()
            self.approval.request.assert_not_called()
        provider.chat.assert_not_called()

    def test_website_intent_never_discovers_and_local_discovery_survives(self):
        for command in ('open gatewall','open gatewalla','open my gatewall','open my gatewalla',
                        'open firefox and go to gatewalla'):
            route=self.router.route(command)
            self.assertIsNotNone(route.workflow)
            self.assertEqual(compile_browser_plan(route.workflow).value,WEBSITES['pw_study'])
        for command in ('open website unknownsite','open unknownsite website',
                        'open unknownsite in firefox','open https://unknown.example/',
                        'open firefox and go to unknownsite'):
            route=self.router.route(command)
            self.assertIsNotNone(route.workflow)
            self.assertIsNone(compile_browser_plan(route.workflow))
            self.assertIn('HTTPS URL',route.message)
        for command in ('open portfolio','open my portfolio','find notes.txt'):
            self.assertEqual(self.router.route(command).tool_name,'discover_target')
        self.assertNotIn('gatewall',WEBSITES)
        self.assertNotIn('gatewalla',WEBSITES)

    def test_search_authentication_and_denial_prevent_launch(self):
        self.auth.authenticate.side_effect=OwnerAuthenticationError('synthetic-private-secret')
        result=self.search();self.assertFalse(result.success)
        self.assertNotIn('synthetic-private-secret',str(result))
        self.process.assert_not_called();self.approval.request.assert_not_called()
        self.auth.authenticate.side_effect=None
        self.approval.request.return_value=FolderDecision.DENY
        self.assertFalse(self.search().success);self.process.assert_not_called()
        self.approval.request.return_value=FolderDecision.ALLOW_PERSISTENT
        self.assertFalse(self.search().success);self.process.assert_not_called()

    def test_search_target_substitution_invalidates_authorization(self):
        with ExitStack() as stack:
            lease=self.execution.prepare(HandoffRequest(HandoffOperation.SEARCH,value='python'),stack)
            self.execution.authorize(lease,self.auth,self.approval,DesktopApproval)
            lease['url_handoff_target']=BrowserTarget.from_request(HandoffRequest(HandoffOperation.SEARCH,value='changed'))
            with self.assertRaises(PermissionError):self.execution.execute(lease)
        self.process.assert_not_called()
        with self.assertRaises(ValueError):
            replace(BrowserTarget.from_request(HandoffRequest(HandoffOperation.SEARCH,value='python')),
                    url='https://www.google.com/search?q=changed')

    def test_search_result_url_substitution_is_rejected(self):
        from contextlib import nullcontext
        from unittest.mock import Mock
        self.adapter.execution=Mock(return_value=nullcontext())
        self.adapter.execute=Mock(return_value={'status':'request_accepted','url':search_url('changed'),
            'message':ACCEPTED_MESSAGE,'page_load_verified':False})
        result=self.search('python');self.assertFalse(result.success);self.assertIsNone(result.data)

    def test_search_launcher_change_cancellation_and_timeout(self):
        def approve(_):
            self.chain=(('changed',),)
            return FolderDecision.ALLOW_ONCE
        self.approval.request.side_effect=approve
        self.assert_failed(self.search(),'url_handoff_failed');self.process.assert_not_called()
        self.approval.request.side_effect=lambda _:(self.adapter.stop_handoffs() or FolderDecision.ALLOW_ONCE)
        self.assert_failed(self.search(),'url_handoff_cancelled');self.process.assert_not_called()
        self.execution.cancelled.clear();self.approval.request.side_effect=None
        now=[0];self.execution.clock=lambda:now[0];self.child.poll.return_value=None
        def wait(timeout):
            if timeout==1:return -9
            now[0]=6
            raise subprocess.TimeoutExpired('synthetic',timeout)
        self.child.wait.side_effect=wait
        self.assert_failed(self.search(),'url_handoff_timeout')
        self.process.assert_called_once();self.child.kill.assert_called_once()

    def test_search_nonzero_exit_and_spawn_exception_have_no_acceptance_or_leaks(self):
        self.child.wait.return_value=1
        self.assert_failed(self.search(),'url_handoff_failed')
        self.process.side_effect=OSError('private-cookie synthetic-secret')
        result=self.search();self.assert_failed(result,'url_handoff_failed')
        self.assertNotIn('private-cookie',str(result));self.assertNotIn('synthetic-secret',str(result))
        self.assertFalse(self.search(args='--private').success)

    def test_search_cancellation_after_spawn_stops_only_its_invocation(self):
        self.child.poll.return_value=None
        def wait(timeout):
            if timeout==1:return -9
            self.adapter.stop_handoffs()
            raise subprocess.TimeoutExpired('synthetic',timeout)
        self.child.wait.side_effect=wait
        self.assert_failed(self.search(),'url_handoff_cancelled')
        self.process.assert_called_once();self.child.kill.assert_called_once()

    def test_search_executable_fingerprint_change_after_approval_blocks_spawn(self):
        def approve(_):
            self.paths['firefox'].write_bytes(b'\x7fELFchanged-after-approval')
            return FolderDecision.ALLOW_ONCE
        self.approval.request.side_effect=approve
        self.assert_failed(self.search(),'url_handoff_failed')
        self.process.assert_not_called()

    def test_unresolved_live_failure_disables_production_navigation_and_search(self):
        self.adapter.firefox_url_handoff=FirefoxUrlHandoff(self.adapter.handoff_cancelled,self.adapter.handoff_clock)
        assistant,provider=self.assistant()
        for command in ('open youtube','open my github','open gatewalla','search for python'):
            self.assertEqual(assistant.respond(command),EXECUTION_BLOCKER)
        self.auth.authenticate.assert_not_called();self.approval.request.assert_not_called()
        self.process.assert_not_called();provider.chat.assert_not_called()
