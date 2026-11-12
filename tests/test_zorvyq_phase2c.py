"""Phase 2C fixtures: never open audio, execute diagnostics, or invoke models."""
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import Mock, patch
from zorvyq.tasks import TaskStore, intent, now
from zorvyq.voice import VoiceInteraction, VoiceState, DesktopSpeech, speech_summary
from zorvyq.preferences import Preferences
from friday.voice.tts import SpeechError, EspeakNGBackend
from friday.voice.backend import LocalVoiceBackend, VoiceConfiguration, VoiceError
from friday.voice.configuration import TINY_EN_SHA256
from zorvyq.operations.reporting import markdown, export_markdown

class TasksTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'tasks.sqlite3';self.store=TaskStore(self.path)
    def test_create_update_complete_delete_and_restart(self):
        identity=self.store.save(title='Review',description='Private task',priority='High',project='local project')
        row=TaskStore(self.path).rows()[0]
        self.assertEqual(row['id'],identity);self.assertEqual(row['status'],'Pending')
        self.store.change_status(row,'In progress');self.assertEqual(len(self.store.rows(view='Active')),1)
        self.store.change_status(self.store.rows()[0],'Completed')
        row=TaskStore(self.path).rows()[0];self.assertIsNotNone(row['completed'])
        self.assertEqual(len(self.store.rows(view='Completed')),1)
        self.store.delete(identity);self.assertEqual(TaskStore(self.path).rows(),[])
    def test_due_filters_search_and_validation(self):
        at=now()
        self.store.save(title='Today',due=at.isoformat())
        self.store.save(title='Tomorrow',due=(at+timedelta(days=1)).isoformat())
        self.store.save(title='Yesterday',due=(at-timedelta(days=1)).isoformat())
        for view in ('Today','Upcoming','Overdue'):
            self.assertEqual(len(self.store.rows(view=view)),1)
        self.assertEqual(len(self.store.rows('tomorrow')),1)
        with self.assertRaises(ValueError):self.store.save(title='Bad',reminder='not a time')
        with self.assertRaises(ValueError):self.store.save(title='')
        with self.assertRaises(ValueError):self.store.save(title='x',status='Invented')
    def test_reminders_persist_missed_delivery_no_duplicates_and_reschedule(self):
        at=now();due=(at-timedelta(days=1)).isoformat()
        self.store.save(title='Missed reminder',reminder=due)
        self.assertEqual(len(TaskStore(self.path).claim_reminders(at)),1)
        self.assertEqual(TaskStore(self.path).claim_reminders(at),[])
        row=self.store.rows()[0];self.store.save(identity=row['id'],title=row['title'],reminder=(at+timedelta(hours=1)).isoformat())
        self.assertEqual(self.store.claim_reminders(at),[])
        self.assertEqual(len(self.store.claim_reminders(at+timedelta(hours=2))),1)
    def test_completed_tasks_do_not_remind(self):
        self.store.save(title='Complete',status='Completed',reminder=(now()-timedelta(days=1)).isoformat())
        self.assertEqual(self.store.claim_reminders(),[])
    def test_structured_intents_never_write_and_preserve_ambiguity(self):
        self.assertEqual(intent('Show my pending tasks.'),{'action':'list'})
        add=intent('Add a task to review my project tomorrow.')
        self.assertEqual(add['title'],'review my project');self.assertIsNotNone(add['due'])
        self.assertEqual(intent('Mark the website task complete')['query'],'website')
        delete=intent('Delete the completed test task.')
        self.assertTrue(delete['completed_only']);self.assertEqual(delete['query'],'test')
        self.store.save(title='Website first');self.store.save(title='Website second')
        self.assertEqual(len(self.store.rows(query='website')),2)
        self.assertIsNone(intent('Run arbitrary command'))
        self.assertEqual(len(self.store.rows()),2)
    def test_database_is_separate_and_private(self):
        self.assertEqual(self.path.stat().st_mode & 0o777,0o600)
        from contextlib import closing
        with closing(self.store.connect()) as db:
            self.assertEqual([r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")],['tasks'])

class VoiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.preferences=Preferences(Path(self.temp.name)/'prefs.json')
        self.speech=DesktopSpeech(self.preferences)
    def test_defaults_disabled_welcome_once_no_capture(self):
        controller=VoiceInteraction()
        self.assertEqual(controller.state,VoiceState.IDLE)
        self.assertFalse(self.preferences.values['speak_welcome'])
        self.assertFalse(controller.welcome(self.preferences.values))
        self.preferences.save(speech_enabled=True,speak_welcome=True)
        self.assertFalse(controller.welcome(self.preferences.values))
        other=VoiceInteraction();self.assertTrue(other.welcome(self.preferences.values));self.assertFalse(other.welcome(self.preferences.values))
    def test_disabled_missing_voice_fallback_and_playback_failure(self):
        with patch.object(EspeakNGBackend,'speak') as speak:
            with self.assertRaises(SpeechError):self.speech.speak('Hello')
            speak.assert_not_called()
        self.preferences.save(speech_enabled=True,voice='missing')
        with patch.object(self.speech,'voices',return_value=()):
            with self.assertRaises(SpeechError):self.speech.speak('Hello')
        with patch.object(self.speech,'voices',return_value=(('gmw/en','English'),)),patch.object(EspeakNGBackend,'speak') as speak:
            self.speech.speak('Hello');self.assertEqual(self.preferences.values['voice'],'gmw/en');speak.assert_called_once()
        with patch.object(self.speech,'voices',return_value=(('gmw/en','English'),)),patch.object(EspeakNGBackend,'speak',side_effect=SpeechError('failed')):
            with self.assertRaises(SpeechError):self.speech.speak('Hello')
            self.assertEqual(self.speech.last_error,'offline_playback_failed')
    def test_states_and_cancellation(self):
        controller=VoiceInteraction();controller.begin(VoiceState.LISTENING)
        with self.assertRaises(ValueError):controller.begin(VoiceState.LISTENING)
        controller.cancelled.set()
        config=VoiceConfiguration(Path('/fake/whisper'),Path('/fake/model'),TINY_EN_SHA256)
        backend=LocalVoiceBackend(config,controller.cancelled)
        with patch('friday.voice.backend.subprocess.Popen') as start:
            with self.assertRaises(VoiceError) as error:backend.transcribe(Path('/fake/audio'))
            self.assertEqual(error.exception.category,'cancelled');start.assert_not_called()
    def test_summaries_are_short_and_private_structures_suppressed(self):
        self.assertIn('on screen',speech_summary('```python\ncode\n```'))
        self.assertLess(len(speech_summary('Long sentence. '*100)),500)
        self.assertIsNone(speech_summary('password=secret'))
    def test_stop_signals_only_owned_playback(self):
        speech=EspeakNGBackend();speech._child=Mock(pid=54321);speech._child.poll.return_value=None
        with patch('os.killpg') as kill:
            speech.stop();self.assertTrue(speech.cancelled.is_set());kill.assert_called_once()

class ExportTests(unittest.TestCase):
    def test_markdown_preserves_fixture_output_and_optional_analysis(self):
        value={'operation_id':'fixture.health','execution_status':'Partial','observed_metrics':{'ram':90},
               'stages':[{'stdout':'FIXTURE','stderr':'fixture error','exit_code':1}],
               'findings':[],'ai_analysis':None,'recommended_next_steps':['Review'],'limitations':['Snapshot only']}
        rendered=markdown(value)
        self.assertIn('FIXTURE',rendered);self.assertIn('fixture error',rendered);self.assertIn('Not requested',rendered)
        with TemporaryDirectory() as temp:
            path=Path(temp)/'report.md';export_markdown(value,path)
            self.assertEqual(path.read_text(),rendered)
            with self.assertRaises(FileExistsError):export_markdown(value,path)

if __name__=='__main__':unittest.main()
