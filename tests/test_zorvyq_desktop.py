"""Offscreen UI integration; these tests do not certify physical desktop/audio acceptance."""
import importlib.util
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from unittest.mock import patch
from threading import Thread
from time import monotonic, sleep
from friday.intelligence.permissions import AuthorizationRequest, KnowledgePurpose, KnowledgeDecision

QT = importlib.util.find_spec('PySide6') is not None

@unittest.skipUnless(QT,'Qt dependency not installed')
class DesktopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from zorvyq.preferences import Preferences
        from zorvyq.projects import Projects
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        for name, replacement in [
            ('zorvyq.preferences.Preferences', lambda: Preferences(root/'desktop.json')),
            ('zorvyq.projects.Projects', lambda database, **kwargs: Projects(root/'memory.db', root=root, **kwargs)),
            ('zorvyq.voice.DesktopSpeech.voices', lambda self: ()),
        ]:
            fixture = patch(name, replacement)
            fixture.start()
            self.addCleanup(fixture.stop)
        from zorvyq.desktop.app import build_window
        # Startup must remain metadata only; use disconnected probes deterministically.
        self.service = patch('zorvyq.services.LocalService.models',side_effect=RuntimeError('offline'))
        self.service.start()
        self.addCleanup(self.service.stop)
        self.window = build_window()
        self.window.show()
        self.wait_idle()
        self.window.timer.stop()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.wait_idle()
        self.window.close()
        self.wait_idle()
        self.app.processEvents()

    def wait_idle(self, timeout=5):
        deadline=monotonic()+timeout
        while monotonic()<deadline:
            self.app.processEvents()
            if not self.window.busy:
                # Run initial singleShot before treating the window as idle.
                self.app.processEvents()
                if not self.window.busy:return
            sleep(.005)
        self.fail('Worker did not finish')

    def test_all_pages_disconnected_dashboard_and_no_inference_startup(self):
        self.assertEqual(self.window.windowTitle(),'ZORVYQ — Local AI Assistant')
        self.assertEqual(len(self.window.pages),13)
        self.assertIn('disconnected',self.window.top_status.text())
        self.assertEqual(self.window.controller.manager.invocation_count,0)
        self.assertIsNone(self.window.controller.assistant.memory)
        for page in self.window.pages:
            self.window.navigate(page)
            self.app.processEvents()
            self.assertEqual(self.window.stack.currentIndex(),list(self.window.pages).index(page))

    def test_small_window_and_light_theme_render(self):
        self.window.resize(720,540)
        self.window.apply_theme(True)
        self.app.processEvents()
        self.assertFalse(self.window.grab().isNull())
        self.assertLessEqual(self.window.minimumWidth(),720)

    def test_focus_typing_enter_shift_enter_and_send_signals(self):
        from PySide6.QtTest import QTest
        from PySide6.QtCore import Qt
        from unittest.mock import Mock
        chat=self.window.chats['AI Chat']
        self.window.navigate('AI Chat');chat['input'].setFocus()
        self.window.controller.ask=Mock(return_value={'answer':'Synthetic final answer'})
        QTest.keyClicks(chat['input'],'Question')
        QTest.keyClick(chat['input'],Qt.Key.Key_Return,Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(chat['input'].toPlainText(),'Question\n')
        QTest.keyClicks(chat['input'],'detail')
        QTest.keyClick(chat['input'],Qt.Key.Key_Return)
        self.wait_idle()
        self.assertEqual(self.window.controller.ask.call_args.args[0],'Question\ndetail')
        self.assertFalse(chat['input'].toPlainText())
        self.assertEqual(self.window.controller.ask.call_count,1)
        chat['input'].setPlainText('Button submission')
        chat['send'].click();self.wait_idle()
        self.assertEqual(self.window.controller.ask.call_count,2)

    def test_model_depth_controls_persist_disable_during_work_and_apply_next_turn(self):
        from zorvyq.security import SPECIALIST
        self.window.chat_model.setCurrentIndex(1)
        self.window.select_depth('Medium')
        self.assertEqual(type(self.window.preferences)(self.window.preferences.path).values['selected_model'],SPECIALIST)
        self.assertEqual(type(self.window.preferences)(self.window.preferences.path).values['response_mode'],'Medium')
        captured=[]
        def answer(text,use,**kwargs):
            captured.append(kwargs);sleep(.05);return {'answer':'Synthetic'}
        self.window.controller.ask=answer
        chat=self.window.chats['AI Chat'];chat['input'].setPlainText('Question');self.window.send_chat('AI Chat')
        self.assertFalse(self.window.chat_model.isEnabled())
        self.assertFalse(chat['modes'].buttons()[0].isEnabled())
        self.wait_idle()
        self.assertEqual(captured[0]['model'],SPECIALIST)
        self.assertEqual(captured[0]['mode'],'Medium')

    def test_cyber_modes_cannot_create_accidental_specialist_rag(self):
        from zorvyq.security import SPECIALIST
        chat=self.window.chats['Cybersecurity']
        self.window.cyber_mode.setCurrentIndex(1)
        self.assertFalse(chat['knowledge'].isChecked())
        self.assertEqual(chat['model'].currentData(),SPECIALIST)
        self.window.cyber_mode.setCurrentIndex(0)
        self.assertTrue(chat['knowledge'].isChecked())
        self.assertEqual(chat['model'].currentData(),'qwen3:4b')
        self.assertFalse(chat['model'].isEnabled())

    def test_cyber_failure_explanation_and_expandable_safe_status(self):
        self.window.controller.ask=lambda *args,**kwargs:{'answer':'Generic backend failed',
            'knowledge_status':{'failure_category':'authorization_denied','failure_stage':'authorization','status':'failed','PRIVATE':'SECRET'}}
        chat=self.window.chats['Cybersecurity'];chat['input'].setPlainText('Synthetic')
        self.window.send_chat('Cybersecurity');self.wait_idle()
        from PySide6.QtWidgets import QTextBrowser
        answer=chat['turns'][-1].findChild(QTextBrowser).toPlainText()
        self.assertIn('permission was denied',answer)
        self.assertNotIn('SECRET',chat['diagnostic'].toPlainText())

    def test_knowledge_cancel_control_signals_owned_retrieval_without_freezing_gui(self):
        def ask(*args,**kwargs):
            self.window.controller.knowledge_cancelled.wait(1)
            return {'answer':'Cancelled','knowledge_status':{'failure_category':'cancelled','status':'cancelled'}}
        self.window.controller.ask=ask
        chat=self.window.chats['Cybersecurity'];chat['input'].setPlainText('Synthetic permission-scoped question')
        self.window.send_chat('Cybersecurity')
        self.assertTrue(chat['cancel'].isEnabled())
        chat['cancel'].click();self.wait_idle()
        self.assertTrue(self.window.controller.knowledge_cancelled.is_set())
        self.assertFalse(chat['cancel'].isEnabled())

    def test_operation_preview_then_mocked_run_and_optional_analysis(self):
        from unittest.mock import Mock
        from PySide6.QtWidgets import QPushButton,QMessageBox
        panel=self.window.operation_panel
        panel.open_details('system.health')
        from PySide6.QtWidgets import QDialog,QPlainTextEdit
        dialogs=self.window.findChildren(QDialog)
        dialog=dialogs[-1]
        self.assertIn('system.health',dialog.findChildren(QPlainTextEdit)[0].toPlainText())
        value={'operation_id':'system.health','execution_status':'Completed','observed_metrics':{'resources':{'ram_used_percent':90}},
               'checks_completed':['resources'],'checks_skipped':[],'check_failures':[],'ai_analysis':None}
        self.window.operations.run=Mock(return_value=value)
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):
            next(b for b in dialog.findChildren(QPushButton) if b.text()=='Approve exact scope and Run…').click()
        self.wait_idle()
        self.window.operations.run.assert_called_once()
        self.assertEqual(panel.report['operation_id'],'system.health')
        self.window.controller.analyze_operation=Mock(return_value={'kind':'AI hypotheses — unverified','interpretation':'Synthetic hypothesis'})
        panel.analyze();self.wait_idle()
        self.assertIn('unverified',panel.report['ai_analysis']['kind'])
        self.assertEqual(panel.report['observed_metrics'],value['observed_metrics'])
        dialog.close()

    def test_cybersecurity_selection_reads_model_before_worker_runs(self):
        from zorvyq.security import SPECIALIST
        from unittest.mock import Mock
        self.window.security_model.setCurrentIndex(1)
        self.window.controller.ask = Mock(return_value={'answer':'Mocked specialist answer'})
        self.window.chats['Cybersecurity']['input'].setPlainText('What is a firewall?')
        self.window.send_chat('Cybersecurity')
        self.wait_idle()
        self.assertEqual(self.window.controller.ask.call_args.kwargs['model'],SPECIALIST)

    def test_numbered_chat_and_click_share_snapshot_and_cancel(self):
        from pathlib import Path
        from unittest.mock import Mock
        folder = Path(self.temp.name)/'a space'; folder.mkdir()
        with patch('zorvyq.projects.shutil.which', return_value='/mock/code'), patch('zorvyq.projects.subprocess.run',return_value=Mock(returncode=0)) as launch:
            chat=self.window.chats['AI Chat']
            chat['input'].setPlainText('ZORVYQ, open VS Code')
            self.window.send_chat('AI Chat')
            self.assertEqual(self.window.projects.choices,(folder,))
            chat['input'].setPlainText('1'); self.window.send_chat('AI Chat'); self.wait_idle()
            self.assertEqual(launch.call_args.args[0],['/mock/code','--new-window',str(folder)])
            self.window.choose_projects('AI Chat')
            dialog=self.window.project_dialog; snapshot=self.window.projects.choices
            self.window.click_project(1,dialog,snapshot); self.wait_idle()
            self.assertEqual(launch.call_count,2)
            self.window.choose_projects('AI Chat')
            chat['input'].setPlainText('cancel'); self.window.send_chat('AI Chat')
            self.assertFalse(self.window.projects.choices)
            self.assertEqual(launch.call_count,2)

    def test_intervening_other_workspace_message_expires_project_context(self):
        from pathlib import Path
        from unittest.mock import Mock
        (Path(self.temp.name)/'alpha').mkdir()
        with patch('zorvyq.projects.shutil.which',return_value='/mock/code'), patch('zorvyq.projects.subprocess.run') as launch:
            self.window.choose_projects('AI Chat')
            self.window.controller.ask=Mock(return_value={'answer':'Mock answer'})
            self.window.chats['Cybersecurity']['input'].setPlainText('Another question')
            self.window.send_chat('Cybersecurity'); self.wait_idle()
            self.assertIsNone(self.window.project_page)
            self.assertFalse(self.window.projects.choices)
            launch.assert_not_called()

    def test_worker_does_not_block_gui_timer_and_refuses_parallel_task(self):
        from PySide6.QtCore import QTimer
        ticks=[]
        timer=QTimer();timer.setInterval(5);timer.timeout.connect(lambda:ticks.append(1));timer.start()
        self.window.run_task('speech',lambda:sleep(.08))
        self.assertFalse(self.window.run_task('speech',lambda:None))
        self.wait_idle()
        timer.stop()
        self.assertGreater(len(ticks),2)

    def test_close_during_operation_cancels_then_waits_for_clean_shutdown(self):
        panel=self.window.operation_panel
        self.window.run_task('operation',lambda:(sleep(.05) or {'operation_id':'system.health','execution_status':'Cancelled'}),panel)
        self.window.close()
        self.assertTrue(self.window.close_requested)
        self.assertTrue(self.window.operations.cancelled.is_set())
        deadline=monotonic()+3
        while monotonic()<deadline and (self.window.busy or not self.window.shutdown_complete):
            self.app.processEvents();sleep(.005)
        self.assertTrue(self.window.shutdown_complete)
        self.assertTrue(self.window.controller.closed)
        self.assertTrue(self.window.operations.closed)

    def test_generation_reads_controls_on_gui_thread_and_keeps_verified_text_exact(self):
        self.window.controller.ask=lambda text,use,**kwargs: {'answer':'Historical FRIDAY source [C1]',
            'knowledge_status':{'citation_validation_status':'verified','status':'success'}}
        self.window.chats['AI Chat']['input'].setPlainText('question')
        self.window.send_chat('AI Chat')
        self.wait_idle()
        self.assertEqual(len(self.window.chats['AI Chat']['turns']),2)
        from PySide6.QtWidgets import QTextBrowser
        final=self.window.chats['AI Chat']['turns'][-1].findChild(QTextBrowser)
        self.assertIn('Historical FRIDAY source',final.toPlainText())

    def test_task_intent_never_reaches_model_or_chat_history(self):
        from unittest.mock import Mock
        self.window.controller.ask=Mock()
        chat=self.window.chats['AI Chat']
        with patch.object(self.window.tasks_panel,'edit',return_value=False) as edit:
            chat['input'].setPlainText('Add a task to review my project tomorrow.')
            self.window.send_chat('AI Chat')
        edit.assert_called_once()
        self.window.controller.ask.assert_not_called()
        self.assertEqual(chat['turns'],[])
        self.assertEqual(self.window.tasks.rows(),[])

    def test_ambiguous_task_requires_selection_then_confirmation(self):
        from PySide6.QtWidgets import QInputDialog
        panel=self.window.tasks_panel
        first=self.window.tasks.save(title='website one')
        second=self.window.tasks.save(title='website two')
        def choose(parent,title,prompt,options,*args):return options[1],True
        with patch.object(QInputDialog,'getItem',side_effect=choose) as select,patch.object(panel,'confirm',return_value=False) as confirm:
            panel.handle({'action':'complete','query':'website'})
        select.assert_called_once();confirm.assert_called_once()
        self.assertEqual(len(self.window.tasks.rows(view='Pending')),2)
        with patch.object(QInputDialog,'getItem',side_effect=choose),patch.object(panel,'confirm',return_value=True):
            panel.handle({'action':'complete','query':'website'})
        self.assertEqual(self.window.tasks.rows(view='Completed')[0]['id'],second)

    def test_speech_preferences_and_trusted_response_dispatch(self):
        from unittest.mock import Mock
        self.window.speech.speak=Mock()
        self.window.controller.ask=Mock(return_value={'answer':'Synthetic public answer.','speech_eligible':True})
        chat=self.window.chats['AI Chat'];chat['input'].setPlainText('Explain Python')
        self.window.send_chat('AI Chat');self.wait_idle()
        self.window.speech.speak.assert_not_called()
        self.window.speech_toggle.setChecked(True)
        chat['input'].setPlainText('Explain Python');self.window.send_chat('AI Chat');self.wait_idle()
        self.window.speech.speak.assert_called_once_with('Synthetic public answer.')
        self.window.speech.speak.reset_mock()
        self.window.controller.ask.return_value={'answer':'Private fixture','speech_eligible':False}
        chat['input'].setPlainText('Private question');self.window.send_chat('AI Chat');self.wait_idle()
        self.window.speech.speak.assert_not_called()

    def test_microphone_permission_denial_and_transcription_failure(self):
        from PySide6.QtWidgets import QMessageBox
        from unittest.mock import Mock
        self.window.capture=Mock(side_effect=RuntimeError('private backend message'))
        self.window.microphone_toggle.setChecked(True)
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.No):
            self.window.microphone()
        self.window.capture.assert_not_called()
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):
            self.window.microphone();self.wait_idle()
        self.window.capture.assert_called_once()
        self.assertEqual(self.window.interaction_state.text(),'ERROR')
        self.assertNotIn('private backend message',self.window.voice_progress.text())

    def test_transcript_can_be_corrected_or_cancelled_before_send(self):
        from PySide6.QtWidgets import QDialog,QPlainTextEdit,QMessageBox
        from unittest.mock import Mock
        self.window.controller.ask=Mock()
        self.window.capture=Mock(return_value='Uncertain transcription')
        self.window.microphone_toggle.setChecked(True)
        def correct(dialog):
            dialog.findChild(QPlainTextEdit).setPlainText('Corrected transcription')
            return QDialog.DialogCode.Accepted
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes),patch.object(QDialog,'exec',correct):
            self.window.microphone();self.wait_idle()
        self.assertEqual(self.window.chats['AI Chat']['input'].toPlainText(),'Corrected transcription')
        self.window.controller.ask.assert_not_called()
        self.window.chats['AI Chat']['input'].clear()
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes),patch.object(QDialog,'exec',return_value=QDialog.DialogCode.Rejected):
            self.window.microphone();self.wait_idle()
        self.assertEqual(self.window.chats['AI Chat']['input'].toPlainText(),'')
        self.window.controller.ask.assert_not_called()

    def test_analysis_failure_keeps_deterministic_report(self):
        from unittest.mock import Mock
        panel=self.window.operation_panel
        value={'operation_id':'system.health','observed_metrics':{'ram':92},'ai_analysis':None}
        panel.finished(value)
        self.window.controller.analyze_operation=Mock(side_effect=RuntimeError('private failure'))
        panel.analyze();self.wait_idle()
        self.assertEqual(panel.report,value)
        self.assertIn('92',panel.output.toPlainText())
        self.assertIn('retained',panel.status.text())

    def test_operation_permission_denial_never_executes(self):
        from PySide6.QtWidgets import QPushButton,QMessageBox
        from unittest.mock import Mock
        panel=self.window.operation_panel;panel.open_details('system.health')
        self.window.operations.run=Mock()
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.No):
            next(b for b in panel.dialog.findChildren(QPushButton) if b.text()=='Approve exact scope and Run…').click()
        self.window.operations.run.assert_not_called()
        self.assertFalse(self.window.busy)
        panel.dialog.close()

    def test_real_engine_gui_path_with_fixture_commands_and_console(self):
        from unittest.mock import Mock
        from PySide6.QtWidgets import QPushButton,QMessageBox
        from zorvyq.operations.contracts import StageResult
        panel=self.window.operation_panel
        runner=self.window.operations.runner
        planned=[]
        def execute(stage,cancel,emit):
            planned.append(runner.preview(stage))
            emit('stdout: fixture command output')
            emit('stderr: fixture warning')
            return StageResult(stage.stage_id,'COMPLETED',0,.01,'fixture command output','fixture warning',{'line_count':1})
        with patch.object(runner,'run',side_effect=execute),patch.dict('zorvyq.operations.engine.COLLECTORS',{'system':lambda *args:{'ram_used_percent':91}}):
            panel.open_details('system.health')
            preview=self.window.operations.preview(self.window.operations.registry.plan('system.health'))
            with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):
                next(b for b in panel.dialog.findChildren(QPushButton) if b.text()=='Approve exact scope and Run…').click()
            self.wait_idle()
        self.assertEqual(planned,[s['arguments'] for s in preview['stages'] if s['arguments']])
        self.assertEqual(panel.report['observed_metrics']['resources']['ram_used_percent'],91)
        self.assertIn('stdout: fixture command output',panel.console.toPlainText())
        self.assertIn('stderr: fixture warning',panel.console.toPlainText())
        self.assertIn('exit=0',panel.console.toPlainText())
        panel.dialog.close()

    def test_missed_reminder_notification_is_claimed_once(self):
        from datetime import timedelta
        from zorvyq.tasks import now
        from PySide6.QtWidgets import QDialog,QSystemTrayIcon
        self.window.tasks.save(title='Fixture reminder',reminder=(now()-timedelta(hours=1)).isoformat())
        with patch.object(QDialog,'show') as show,patch.object(QSystemTrayIcon,'isSystemTrayAvailable',return_value=False):
            self.window.reminders();self.window.reminders()
        show.assert_called_once()
        self.assertIsNotNone(self.window.tasks.rows()[0]['notified'])
        for dialog in self.window.findChildren(QDialog):
            if dialog.windowTitle()=='ZORVYQ task reminders':dialog.close()

    def decide_knowledge(self, allow):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication,QDialog,QPlainTextEdit
        documents={'source':{'title':'Reviewed title','source_url':'https://example.org/source','document_version':'v1'}}
        request=AuthorizationRequest(KnowledgePurpose.RETRIEVE,('source',),'a'*64)
        result=[]; observed=[]
        def close_dialog():
            dialog=QApplication.activeModalWidget()
            if isinstance(dialog,QDialog):
                observed.append(dialog.findChild(QPlainTextEdit).toPlainText())
                dialog.accept() if allow else dialog.reject()
        timer=QTimer();timer.setInterval(5);timer.timeout.connect(close_dialog);timer.start()
        worker=Thread(target=lambda:result.append(self.window.bridge.knowledge(documents)(request)))
        worker.start()
        deadline=monotonic()+3
        while worker.is_alive() and monotonic()<deadline:
            self.app.processEvents();sleep(.005)
        worker.join(timeout=.1);timer.stop()
        self.assertFalse(worker.is_alive())
        self.assertIn('a'*64,observed[0])
        self.assertIn('Reviewed title',observed[0])
        return result[0]

    def test_permission_deny_and_exact_allow_once(self):
        self.assertIs(self.decide_knowledge(False),KnowledgeDecision.DENY)
        self.assertIs(self.decide_knowledge(True),KnowledgeDecision.ALLOW_ONCE)

    def test_wrong_knowledge_scope_denied_without_dialog(self):
        approval=self.window.bridge.knowledge({'expected':{}})
        request=AuthorizationRequest(KnowledgePurpose.RETRIEVE,('other',),'b'*64)
        self.assertIs(approval(request),KnowledgeDecision.DENY)

    def test_owner_dialog_uses_masked_input_without_reading_credentials(self):
        from PySide6.QtWidgets import QInputDialog,QLineEdit
        result=[]
        with patch.object(QInputDialog,'getText',return_value=('test-fixture-passphrase',True)) as dialog:
            worker=Thread(target=lambda:result.append(self.window.bridge.secret('owner')))
            worker.start()
            deadline=monotonic()+3
            while worker.is_alive() and monotonic()<deadline:
                self.app.processEvents();sleep(.005)
            worker.join(timeout=.1)
            self.assertFalse(worker.is_alive())
            self.assertEqual(dialog.call_args.args[3],QLineEdit.EchoMode.Password)
        self.assertEqual(result,['test-fixture-passphrase'])

    def test_markdown_cannot_load_local_or_remote_resources(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtWidgets import QTextBrowser
        self.window.bubble('AI Chat','ZORVYQ','![x](https://example.org/private.png)')
        browser=self.window.chats['AI Chat']['turns'][-1].findChild(QTextBrowser)
        self.assertIsNone(browser.loadResource(2,QUrl('file:///private')))
        self.assertFalse(browser.openExternalLinks())

if __name__=='__main__':unittest.main()
