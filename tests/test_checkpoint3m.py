"""Fixed handoff stage diagnostics; no live launcher, browser or credentials."""
from contextlib import ExitStack
from unittest.mock import Mock, patch
import subprocess

from test_firefox_url_handoff import FirefoxUrlHandoffFixture
from friday.desktop.browser_execution import BrowserTarget
from friday.desktop.firefox_url_handoff import (FirefoxUrlHandoff, FAILURE_STAGES,
    UnavailableFirefoxUrlAdapter, UrlHandoffFailure)
from friday.desktop.handoffs import HandoffOperation, HandoffRequest
from friday.desktop.runtime import DesktopApproval
from friday.desktop.accessibility import Deadline
from friday.tools.access import FolderDecision


class Checkpoint3MTests(FirefoxUrlHandoffFixture):
    def request(self):
        return HandoffRequest(HandoffOperation.SEARCH, value='python tutorials')

    def execute_handoff(self):
        with ExitStack() as stack:
            lease=self.execution.prepare(self.request(),stack)
            self.assertNotIn('result',lease)
            self.execution.authorize(lease,self.auth,self.approval,DesktopApproval)
            return self.execution.execute(lease)

    def test_disabled_capability_is_distinct_from_unsupported_verification(self):
        unavailable=FirefoxUrlHandoff(self.execution.cancelled,self.execution.clock)
        with ExitStack() as stack:
            result=unavailable.prepare(self.request(),stack)['result']
        self.assertEqual(result,{'status':'url_handoff_unavailable','failure_stage':'capability_rejection'})
        self.assertIsInstance(unavailable.adapter,UnavailableFirefoxUrlAdapter)
        result=self.adapter.browser_execution.prepare(self.request())['result']
        self.assertEqual(result['status'],'unsupported_capability')
        self.process.assert_not_called();self.auth.authenticate.assert_not_called()

    def test_untyped_context_is_rejected_before_spawn(self):
        target=BrowserTarget.from_request(self.request())
        deadline=Deadline(self.execution.clock()+5,self.execution.cancelled,self.execution.clock)
        with self.assertRaises(UrlHandoffFailure) as caught:
            self.url_adapter.handoff(None,target,deadline)
        self.assertEqual(caught.exception.stage,'context_revalidation')
        self.process.assert_not_called()

    def test_preflight_failure_stages_are_fixed_and_do_not_prompt(self):
        failures=[(self.binary_patch,'launcher_verification'),
                  (self.chain_patch,'launcher_fingerprint'),(self.env_patch,'environment_validation')]
        for mock,stage in failures:
            original=mock.side_effect
            mock.side_effect=ValueError('PRIVATE diagnostic synthetic-secret')
            with ExitStack() as stack:
                result=self.execution.prepare(self.request(),stack)['result']
            self.assertEqual(result,{'status':'url_handoff_unavailable','failure_stage':stage})
            self.assertNotIn('PRIVATE',str(result));self.assertNotIn('synthetic-secret',str(result))
            public_result=self.navigate()
            self.assertFalse(public_result.success)
            self.assertIn('Failure stage: '+FAILURE_STAGES[stage]+'.',public_result.error)
            mock.side_effect=original
        self.auth.authenticate.assert_not_called();self.approval.request.assert_not_called()
        self.process.assert_not_called()

    def test_postapproval_changed_fingerprint_or_environment_never_spawns(self):
        for attribute,changed,stage in [('review',('changed',),'launcher_fingerprint'),
                ('chain',(('changed',),),'launcher_fingerprint'),
                ('environment',(('changed','session'),),'environment_validation')]:
            original=getattr(self,attribute)
            self.approval.request.side_effect=lambda _,a=attribute,v=changed:(setattr(self,a,v) or FolderDecision.ALLOW_ONCE)
            result=self.execute_handoff()
            self.assertEqual(result,{'status':'url_handoff_failed','failure_stage':stage})
            self.process.assert_not_called()
            setattr(self,attribute,original)

    def test_spawn_failure_is_distinct_and_redacted_in_terminal_result(self):
        self.process.side_effect=OSError('PRIVATE argv cookie synthetic-secret')
        result=self.execute_handoff()
        self.assertEqual(result,{'status':'url_handoff_failed','failure_stage':'process_spawn'})
        result=self.navigate()
        self.assertFalse(result.success);self.assertIsNone(result.data)
        self.assertIn('Failure stage: process startup.',result.error)
        for secret in ('PRIVATE','cookie','synthetic-secret'):
            self.assertNotIn(secret,result.error)

    def test_nonzero_exit_and_negative_signal_exit_never_accept(self):
        for code in (1,127,-9):
            self.child.wait.return_value=code
            self.assertEqual(self.execute_handoff(),
                {'status':'url_handoff_failed','failure_stage':'nonzero_exit'})

    def test_long_lived_invocation_is_uncertain_never_submission_success(self):
        now=[0];self.execution.clock=lambda:now[0]
        self.child.poll.return_value=None
        def wait(timeout):
            if timeout==1:return -9
            self.assertLessEqual(timeout,.1)
            now[0]=5
            raise subprocess.TimeoutExpired('synthetic',timeout)
        self.child.wait.side_effect=wait
        self.assertEqual(self.execute_handoff(),{'status':'url_handoff_timeout','failure_stage':'timeout'})
        self.process.assert_called_once();self.child.kill.assert_called_once()

    def test_zero_exit_after_deadline_does_not_become_acceptance(self):
        now=[0];self.execution.clock=lambda:now[0]
        def wait(timeout):
            if timeout!=1:now[0]=5
            return 0
        self.child.wait.side_effect=wait
        self.assertEqual(self.execute_handoff(),{'status':'url_handoff_timeout','failure_stage':'timeout'})

    def test_keyboard_interrupt_is_cancellation_and_reaps_owned_child(self):
        self.child.poll.return_value=None
        self.child.wait.side_effect=[KeyboardInterrupt(),-9]
        self.assertEqual(self.execute_handoff(),{'status':'url_handoff_cancelled','failure_stage':'cancelled'})
        self.child.kill.assert_called_once()

    def test_event_cancellation_after_spawn_is_not_exit_or_page_success(self):
        self.child.poll.return_value=None
        self.process.side_effect=lambda *a,**k:(self.execution.cancelled.set() or self.child)
        with patch('os.kill') as unrelated_kill:
            self.assertEqual(self.execute_handoff(),{'status':'url_handoff_cancelled','failure_stage':'cancelled'})
        self.child.kill.assert_called_once();unrelated_kill.assert_not_called()

    def test_cleanup_failure_overrides_possible_acceptance(self):
        self.child.wait.side_effect=[0,subprocess.TimeoutExpired('PRIVATE',1)]
        self.assertEqual(self.execute_handoff(),{'status':'url_handoff_failed','failure_stage':'process_cleanup'})

    def test_zero_exit_revalidates_then_accepts_without_page_verification(self):
        with patch.object(self.url_adapter,'revalidate',wraps=self.url_adapter.revalidate) as revalidate:
            result=self.execute_handoff()
        self.assertEqual(revalidate.call_count,2)
        self.assertEqual(result['status'],'request_accepted')
        self.assertIs(result['page_load_verified'],False)
        self.assertNotIn('failure_stage',result)

    def test_postexit_installation_change_refuses_acceptance(self):
        self.child.wait.side_effect=lambda **_:(setattr(self,'review',('changed',)) or 0)
        self.assertEqual(self.execute_handoff(),{'status':'url_handoff_failed','failure_stage':'launcher_fingerprint'})

    def test_bus_absence_is_not_a_python_precondition_or_proof_of_launcher_failure(self):
        self.environment += (('DBUS_SESSION_BUS_ADDRESS','unix:path=/synthetic/absent/bus'),)
        self.assertEqual(self.execute_handoff()['status'],'request_accepted')
        self.assertEqual(self.process.call_args.kwargs['env']['DBUS_SESSION_BUS_ADDRESS'],
                         'unix:path=/synthetic/absent/bus')
        # Mock zero exit only proves classification, not real Snap bus independence.

    def test_unknown_diagnostic_text_is_not_forwarded(self):
        self.url_adapter.handoff=Mock(return_value={'status':'url_handoff_failed',
            'failure_stage':'PRIVATE cookie synthetic-secret'})
        result=self.navigate();self.assertFalse(result.success)
        self.assertNotIn('PRIVATE',result.error);self.assertNotIn('synthetic-secret',result.error)
        with self.assertRaises(ValueError):UrlHandoffFailure('PRIVATE')
        with self.assertRaises(TypeError):FAILURE_STAGES['arbitrary']='PRIVATE'
