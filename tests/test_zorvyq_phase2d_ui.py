"""Offscreen fixture data only, reusing the desktop's disconnected test harness."""
import importlib.util
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from unittest.mock import patch, Mock
from datetime import timedelta
from time import monotonic, sleep
from tests import test_zorvyq_desktop as harness
from tests.test_zorvyq_phase2d import T, record

@unittest.skipUnless(importlib.util.find_spec('PySide6'),'Qt unavailable')
class AwarenessUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):harness.DesktopTests.setUpClass.__func__(cls)
    setUp=harness.DesktopTests.setUp
    cleanup=harness.DesktopTests.cleanup
    wait_idle=harness.DesktopTests.wait_idle

    def wait_query(self):
        deadline=monotonic()+5
        while monotonic()<deadline:
            self.app.processEvents()
            if self.window.awareness_panel.worker is None:return
            sleep(.005)
        self.fail('Bounded history query did not finish')

    def labels(self,widget):
        from PySide6.QtWidgets import QLabel
        return '\n'.join(label.text() for label in widget.findChildren(QLabel))

    def test_real_cards_refresh_task_reopen_delete_and_empty_history(self):
        w=self.window;p=w.awareness_panel;self.wait_query()
        self.assertIn('No recent activity recorded',self.labels(p.dashboard))
        self.assertIn('Activity History',w.pages)
        with patch('zorvyq.awareness.store.now',return_value=T):w.activity_store.configure(enabled=True,consent=True)
        for i in range(5):w.activity_store.insert(record(i,start=i+1,end=i+11))
        for i in range(4):w.tasks.save(title='Fixture completed '+str(i),status='Completed')
        w.tasks_panel.refresh();self.wait_query()
        self.assertEqual(p.recent.count(),6) # three records, each with its details action
        self.assertEqual(p.completed.count(),6)
        latest=w.tasks.recent_completed()[0];w.tasks.change_status(latest,'Pending');w.tasks_panel.refresh();self.wait_query()
        self.assertNotIn(latest['title'],self.labels(p.dashboard))
        w.tasks.delete(w.tasks.recent_completed()[0]['id']);w.tasks_panel.refresh();self.wait_query()
        self.assertEqual(p.completed.count(),4)
        w.activity_store.delete();w.monitoring.revision+=1;p.check();self.wait_query()
        self.assertIn('No recent activity recorded',self.labels(p.dashboard))

    def test_queries_permission_voice_summary_no_model_access(self):
        w=self.window;chat=w.chats['AI Chat'];w.controller.ask=Mock()
        chat['input'].setPlainText('What were my last three activities?')
        with patch.object(w.awareness_panel,'confirm',return_value=False):w.send_chat('AI Chat')
        w.controller.ask.assert_not_called();self.assertIn('denied',w.status.text())
        chat['input'].setPlainText('What were my last three activities?')
        with patch.object(w.awareness_panel,'confirm',return_value=True),patch.object(w,'say') as say:
            w.send_chat('AI Chat');self.wait_idle()
        from PySide6.QtWidgets import QTextBrowser
        self.assertIn('No recent activity',' '.join(b.toPlainText() for b in chat['scroll'].widget().findChildren(QTextBrowser)))
        w.controller.ask.assert_not_called()
        from zorvyq.voice import speech_summary
        self.assertIn('No recent activity',speech_summary('No recent activity recorded.'))
        with patch.object(w.awareness_panel,'confirm',return_value=False),patch.object(w.controller,'summarize_activity') as summarize:
            w.awareness_panel.summarize();summarize.assert_not_called()

    def test_live_dashboard_uses_observed_events_and_clears_on_pause(self):
        from tests.test_zorvyq_phase2d import event
        w=self.window;p=w.awareness_panel;self.wait_query()
        with patch('zorvyq.awareness.store.now',return_value=T):w.activity_store.configure(enabled=True,consent=True)
        m=w.monitoring;m.clock=lambda:T+timedelta(seconds=60);m.boundary=T;m.adapter=Mock()
        m.adapter.buckets.return_value={'w':{'type':'currentwindow'},'a':{'type':'afkstatus'}}
        m.adapter.events.side_effect=lambda bucket,*_:([event(1,1,29),event(2,31,29,app='firefox')] if bucket=='w' else [event(3,0,60,status='not-afk')])
        m.tick();p.check();self.wait_query()
        self.assertIn('Firefox',p.current.text());self.assertIn('29s observed',p.current.text())
        self.assertEqual(p.recent.count(),2);self.assertEqual(p.dashboard_state.text(),'ON')
        m.configure(paused=True);p.check();self.wait_query()
        self.assertEqual(p.dashboard_state.text(),'PAUSED');self.assertNotIn('Firefox',p.current.text())
        self.assertFalse(w.activity_store.preferences()['start_at_login'])
        self.assertFalse(w.activity_store.preferences()['background'])

    def test_required_chat_phrases_are_intercepted_without_inference(self):
        from zorvyq.awareness.intelligence import intent
        for text in ('What application am I using?','What were my last three activities?',
                     'What was I doing yesterday?','How much time did I spend programming?',
                     'Which websites did I visit today?',"Summarize today's activity."):
            self.assertIsNotNone(intent(text))

    def test_independent_background_toggle_runs_reviewed_worker_only_after_consent(self):
        p=self.window.awareness_panel;self.wait_query()
        with patch.object(p,'confirm',return_value=False),patch('zorvyq.awareness.background.BackgroundService.apply') as apply:
            p.switches['background'].setChecked(True);apply.assert_not_called()
            self.assertFalse(self.window.activity_store.preferences()['background'])
        with patch.object(p,'confirm',return_value=True),patch('zorvyq.awareness.background.BackgroundService.apply') as apply:
            p.switches['background'].setChecked(True)
            deadline=monotonic()+5
            while p.service_worker is not None and monotonic()<deadline:self.app.processEvents();sleep(.005)
            self.assertIsNone(p.service_worker);apply.assert_called_once_with(True,approved=True)
            self.assertTrue(self.window.activity_store.preferences()['background'])
            self.assertTrue(p.switches['start_at_login'].isChecked())
