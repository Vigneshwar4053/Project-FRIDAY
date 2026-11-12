"""Additional desktop contracts. Temporary metadata and mocked side effects only."""
from datetime import datetime
from pathlib import Path
import json
import os
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from zorvyq.preferences import Preferences, generation_prompt
from zorvyq.projects import Projects, greeting
from zorvyq.security import Nmap, SPECIALIST, ScanScope, validate_target
from zorvyq.startup import Startup, LEGACY_EXEC
from zorvyq.voice import DesktopSpeech
from friday.voice.tts import SpeechError


class Temporary(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)


class ProjectTests(Temporary):
    def setUp(self):
        super().setUp()
        self.folders = self.root/'Projects'; self.folders.mkdir()
        for name in ('Zulu', 'a space', 'alpha', '.hidden'):
            (self.folders/name).mkdir()
        (self.folders/'file.txt').touch()
        self.projects = Projects(self.root/'memory.sqlite', self.folders)
        self.binary = patch('zorvyq.projects.shutil.which', return_value='/mock/code')
        self.launch = patch('zorvyq.projects.subprocess.run', return_value=Mock(returncode=0))
        self.binary.start(); self.run = self.launch.start()
        self.addCleanup(self.binary.stop); self.addCleanup(self.launch.stop)

    def test_direct_folders_sorted_and_number_maps_to_exact_space_path(self):
        rows = self.projects.enumerate()
        self.assertEqual([p.name for p in rows], ['a space', 'alpha', 'Zulu'])
        self.projects.select(1)
        self.assertEqual(self.run.call_args.args[0], ['/mock/code', '--new-window', str(self.folders/'a space')])
        self.assertIs(self.run.call_args.kwargs['shell'], False)
        self.assertEqual(len(self.projects.recent()), 1)

    def test_hidden_setting(self):
        self.projects.hidden = True
        self.assertEqual(self.projects.enumerate()[0].name, '.hidden')

    def test_invalid_cancel_expired_and_stale_selection(self):
        for value in (0, -1, 4, True, '1'):
            self.projects.enumerate()
            with self.assertRaises(ValueError): self.projects.select(value)
        self.projects.enumerate(); self.projects.cancel()
        with self.assertRaises(ValueError): self.projects.select(1)
        self.projects.enumerate(); self.projects.expires = 0
        with self.assertRaises(ValueError): self.projects.select(1)
        previous = self.projects.enumerate(); self.projects.enumerate()
        with self.assertRaises(ValueError): self.projects.select_snapshot(1, previous)
        self.run.assert_not_called()

    def test_symlink_escape_traversal_and_deeper_folder_rejected(self):
        (self.folders/'escape').symlink_to(self.root, target_is_directory=True)
        (self.folders/'alpha/deep').mkdir()
        self.assertNotIn('escape', [p.name for p in self.projects.enumerate()])
        for p in (self.folders/'escape', self.folders/'alpha/deep', self.folders/'../Projects/alpha'):
            with self.assertRaises(ValueError): self.projects.open(p)
        self.run.assert_not_called()

    def test_missing_binary_and_failed_launch_never_persist(self):
        with patch('zorvyq.projects.shutil.which', return_value=None):
            with self.assertRaises(ValueError): self.projects.enumerate()
        self.run.return_value.returncode = 1
        with self.assertRaises(ValueError): self.projects.open(self.folders/'alpha')
        self.assertFalse(self.projects.database.exists())
        self.run.side_effect = subprocess.TimeoutExpired('mock', 20)
        with self.assertRaises(subprocess.TimeoutExpired): self.projects.open(self.folders/'alpha')
        self.assertFalse(self.projects.database.exists())

    def test_restart_deduplicate_missing_remove_and_clear(self):
        p = self.folders/'alpha'
        self.projects.open(p); self.projects.open(p)
        restarted = Projects(self.projects.database, self.folders)
        self.assertEqual(len(restarted.recent()), 1)
        restarted.open(restarted.recent()[0][1]['path'])
        self.assertEqual(self.run.call_args.args[0][-1], str(p))
        p.rmdir()
        self.assertEqual(restarted.recent(), ())
        self.projects.open(self.folders/'Zulu')
        entry = self.projects.recent()[0][0]['entry_id']
        self.projects.remove(entry)
        self.assertEqual(self.projects.recent(), ())
        self.projects.open(self.folders/'a space'); self.projects.remove()
        self.assertEqual(self.projects.recent(), ())

    def test_history_bounded_to_ten_unique_projects(self):
        for i in range(12):
            p = self.folders/str(i); p.mkdir(); self.projects.open(p)
        self.assertEqual(len(self.projects.recent()), 10)
        self.assertEqual(Path(self.projects.recent()[0][1]['path']).name, '11')
        from friday.memory.manager import MemoryManager
        from friday.desktop.recent import RecentWorkQueue
        # A later legacy action keeps its three-row menu without erasing the
        # desktop's ten-row store.
        with MemoryManager(self.projects.database) as memory:
            row = memory.recent_work()[0]
            activity = {key: row[key] for key in ('activity_key','activity_type','application_id','target_identity','title','summary','resume_descriptor','safe_link','launch_status')}
            memory.record_recent_work(activity)
            self.assertEqual(len(RecentWorkQueue(memory).rows()),3)
        self.assertEqual(len(self.projects.recent()),10)

    def test_greetings_use_local_clock(self):
        for hour, expected in [(9,'morning'),(14,'afternoon'),(22,'evening')]:
            self.assertIn(expected, greeting(datetime(2026,1,1,hour)))


class VoiceTests(Temporary):
    def setUp(self):
        super().setUp()
        self.prefs = Preferences(self.root/'prefs.json')
        self.speech = DesktopSpeech(self.prefs)

    def test_inventory_is_actual_engine_output(self):
        output = 'Pty Language Age/Gender VoiceName File\n 2 en-gb --/M English gmw/en\n'
        with patch.object(self.speech, 'verify'), patch('zorvyq.voice.subprocess.run', return_value=Mock(stdout=output)) as run:
            self.assertEqual(self.speech.voices(), (('gmw/en','English'),))
        self.assertEqual(run.call_args.args[0][-1], '--voices')
        self.assertFalse(run.call_args.kwargs['shell'])

    def test_selection_and_preferences_persist_owner_only(self):
        self.prefs.save(voice='gmw/en', speed=160, volume=85, speech_enabled=True)
        reloaded = Preferences(self.prefs.path)
        self.assertEqual(reloaded.values, self.prefs.values)
        self.assertEqual(self.prefs.path.stat().st_mode & 0o777, 0o600)
        with patch.object(self.speech, 'voices', return_value=(('gmw/en','English'),)):
            self.assertEqual(self.speech.resolve_voice(), 'gmw/en')

    def test_missing_voice_fallback_and_empty_inventory(self):
        self.prefs.save(voice='missing')
        with patch.object(self.speech, 'voices', return_value=(('gmw/en','English'),)):
            self.assertEqual(self.speech.resolve_voice(), 'gmw/en')
        self.assertIn('fallback', self.speech.notice)
        self.assertEqual(Preferences(self.prefs.path).values['voice'], 'gmw/en')
        with patch.object(self.speech, 'voices', return_value=()):
            with self.assertRaises(SpeechError): self.speech.resolve_voice()

    def test_preview_mock_engine_receives_selected_settings(self):
        self.prefs.save(speech_enabled=True, voice='gmw/en', speed=150, volume=80)
        with patch.object(self.speech, 'voices', return_value=(('gmw/en','English'),)), patch('friday.voice.tts.EspeakNGBackend.speak') as speak:
            self.speech.speak('Hello, I am ZORVYQ, your local AI assistant.')
            speak.assert_called_once()
            self.assertEqual((self.speech.voice,self.speech.speed,self.speech.volume), ('gmw/en',150,80))
        self.assertEqual(self.speech.last_error,'None')

    def test_error_and_disabled_handling(self):
        with self.assertRaises(SpeechError): self.speech.speak('preview')
        self.assertEqual(self.speech.last_error, 'speech_disabled')
        self.prefs.save(speech_enabled=True)
        with patch.object(self.speech,'voices',return_value=(('gmw/en','English'),)), patch('friday.voice.tts.EspeakNGBackend.speak',side_effect=SpeechError('mock device failure')):
            with self.assertRaises(SpeechError): self.speech.speak('preview')
        self.assertEqual(self.speech.last_error, 'offline_playback_failed')
        with patch.object(self.speech,'verify',side_effect=SpeechError('missing')):
            self.assertEqual(self.speech.voices(), ())
        self.assertEqual(self.speech.last_error,'voice_inventory_unavailable')

    def test_preference_validation_and_symlink_protection(self):
        for args in ({'speed':True},{'volume':999},{'answer_length':'Huge'},{'unknown':'x'}):
            with self.assertRaises(ValueError): self.prefs.save(**args)
        target = self.root/'link.json';target.symlink_to(self.prefs.path)
        with self.assertRaises(ValueError): Preferences(target)


class StartupTests(Temporary):
    def setUp(self):
        super().setUp(); self.startup = Startup(self.root)
        self.startup.directory.mkdir(parents=True)
        self.original = '[Desktop Entry]\nType=Application\nName=FRIDAY AI\n'+LEGACY_EXEC+'\nTerminal=true\nX-GNOME-Autostart-enabled=true\n'
        self.startup.legacy.write_text(self.original)
        self.launcher = self.root/'zorvyq'
        from scripts.install_zorvyq_desktop import ROOT
        self.launcher.write_text('#!/bin/sh\nexec '+str(ROOT/'bin/zorvyq')+' "$@"\n');self.launcher.chmod(0o755)
        self.startup.launcher.parent.mkdir(parents=True)
        self.startup.launcher.write_text('[Desktop Entry]\nType=Application\nName=ZORVYQ\nExec="'+str(self.launcher)+'"\nTerminal=false\n')

    def apply(self, on=True):
        self.startup.apply(on,approved=True,fingerprint=self.startup.inventory()['fingerprint'])

    def test_inventory_read_only_and_exact_identity(self):
        state = self.startup.inventory()
        self.assertTrue(state['identified']); self.assertTrue(state['legacy_enabled'])
        self.assertFalse(state['enabled']); self.assertEqual(self.startup.legacy.read_text(),self.original)
        self.assertFalse(self.startup.managed.exists())

    def test_approval_and_changed_fingerprint_required(self):
        state = self.startup.inventory()
        with self.assertRaises(PermissionError): self.startup.apply(True)
        self.startup.legacy.write_text(self.original+'# changed\n')
        with self.assertRaises(PermissionError): self.startup.apply(True,approved=True,fingerprint=state['fingerprint'])

    def test_migrate_disable_enable_no_duplicate_and_restore_exact(self):
        self.apply(); self.apply(False)
        self.assertFalse(self.startup.inventory()['enabled'])
        self.apply(); self.apply()
        self.assertTrue(self.startup.inventory()['enabled'])
        self.assertFalse(self.startup.inventory()['legacy_enabled'])
        self.assertEqual(len(list(self.startup.directory.glob('com.zorvyq*.desktop'))),1)
        self.startup.restore_legacy(approved=True)
        self.assertEqual(self.startup.legacy.read_text(),self.original)
        self.assertFalse(self.startup.inventory()['enabled'])

    def test_preflight_before_disabling_legacy(self):
        self.startup.launcher.write_text('[Desktop Entry]\nName=ZORVYQ\nTerminal=true\n')
        with self.assertRaises(ValueError): self.apply()
        self.assertEqual(self.startup.legacy.read_text(),self.original)

    def test_stale_installed_wrapper_refused_before_legacy_changes(self):
        self.launcher.write_text('#!/bin/sh\nexec /missing/FRIDAY/bin/zorvyq "$@"\n')
        with self.assertRaises(ValueError): self.apply()
        self.assertEqual(self.startup.legacy.read_text(),self.original)

    def test_unknown_legacy_and_symlink_refused(self):
        self.startup.legacy.write_text(self.original.replace(LEGACY_EXEC,'Exec=unrelated'))
        with self.assertRaises(ValueError): self.apply()
        self.startup.managed.symlink_to(self.startup.legacy)
        with self.assertRaises(ValueError): self.startup.inventory()

    def test_desktop_installation_isolated_terminal_false_correct_venv(self):
        from scripts.install_zorvyq_desktop import install, ROOT
        from scripts.verify_zorvyq_launcher import verify
        desktop, launcher = install(self.root/'install')
        self.assertTrue(all(verify(desktop).values()))
        self.assertIn(str(ROOT/'bin/zorvyq'),launcher.read_text())
        self.assertIn('Terminal=false',desktop.read_text())
        self.assertIn('.venv/bin/python', (ROOT/'bin/zorvyq').read_text())

    def test_manual_wrapper_needs_no_activated_environment_or_terminal(self):
        from scripts.install_zorvyq_desktop import ROOT
        checkout=self.root/'checkout';(checkout/'bin').mkdir(parents=True)
        (checkout/'.venv/bin').mkdir(parents=True)
        wrapper=checkout/'bin/zorvyq';wrapper.write_bytes((ROOT/'bin/zorvyq').read_bytes());wrapper.chmod(0o755)
        # A harmless stand-in interpreter confirms exact argv/cwd; no GUI/model
        # or terminal is spawned by this test.
        interpreter=checkout/'.venv/bin/python'
        interpreter.write_text('#!/bin/sh\nprintf "%s\\n" "$PWD" "$@"\n');interpreter.chmod(0o755)
        result=subprocess.run([str(wrapper)],shell=False,capture_output=True,text=True,check=True,env={'PATH':'/usr/bin:/bin'})
        self.assertEqual(result.stdout.splitlines(),[str(checkout),'-B','-m','zorvyq'])


class SecurityTests(unittest.TestCase):
    def test_target_validation(self):
        for target in ('192.0.2.1','192.0.2.0/24','2001:db8::1','example.test'):
            self.assertEqual(validate_target(target),target)
        for target in ('-oN','x;id','x y','192.0.0.0/16','999.1.2.3','0.0.0.0','224.0.0.1','::','example.test\n','192.0.2.1/24','$(id)'):
            with self.subTest(target=target), self.assertRaises(ValueError): validate_target(target)

    def test_inventory_unavailable_no_install(self):
        with patch('zorvyq.security.shutil.which',return_value=None):
            adapter=Nmap(); self.assertFalse(adapter.inventory()['installed'])
            with self.assertRaises(ValueError): adapter.prepare('192.0.2.1','lab')

    def test_exact_scope_permission_denial_no_process(self):
        with patch('zorvyq.security.shutil.which',side_effect=lambda name:'/mock/'+name), patch('zorvyq.security.subprocess.Popen') as child:
            adapter=Nmap();scope=adapter.prepare('192.0.2.1','Owner lab')
            with self.assertRaises(PermissionError):adapter.execute(scope,authorized=False,confirmed=True)
            scope=adapter.prepare('192.0.2.1','Owner lab')
            forged=ScanScope(scope.target,scope.purpose,('/bin/sh','-c','bad'))
            with self.assertRaises(PermissionError):adapter.execute(forged,authorized=True,confirmed=True)
            child.assert_not_called()

    def test_bounded_constructed_arguments_and_single_use(self):
        process=Mock();process.poll.return_value=0;process.returncode=0
        with patch('zorvyq.security.shutil.which',side_effect=lambda name:'/mock/'+name), patch('zorvyq.security.subprocess.Popen',return_value=process) as child:
            adapter=Nmap();scope=adapter.prepare('192.0.2.1','Owner lab')
            self.assertIn('--cpu=15',scope.arguments);self.assertIn('-sn',scope.arguments)
            adapter.execute(scope,authorized=True,confirmed=True)
            self.assertEqual(child.call_args.args[0],list(scope.arguments))
            self.assertIs(child.call_args.kwargs['shell'],False)
            with self.assertRaises(PermissionError):adapter.execute(scope,authorized=True,confirmed=True)

    def test_mock_cancellation_and_expiry(self):
        process=Mock();process.poll.side_effect=[None,0];process.returncode=0
        with patch('zorvyq.security.shutil.which',side_effect=lambda name:'/mock/'+name), patch('zorvyq.security.subprocess.Popen',return_value=process):
            adapter=Nmap();scope=adapter.prepare('192.0.2.1','Owner lab');adapter.deadline=0
            with self.assertRaises(PermissionError):adapter.execute(scope,authorized=True,confirmed=True)
            scope=adapter.prepare('192.0.2.1','Owner lab')
            with patch.object(adapter.cancelled,'wait',return_value=True):
                self.assertIn('Cancelled',adapter.execute(scope,authorized=True,confirmed=True))
            process.terminate.assert_called_once()


class ModelStyleTests(Temporary):
    def setUp(self):
        super().setUp()
        from friday.config.settings import Settings
        from zorvyq.services import Controller
        from friday.intelligence.permissions import KnowledgeDecision
        self.controller = Controller(Mock(),Mock(return_value=Mock(return_value=KnowledgeDecision.DENY)),
            Settings(project_root=self.root,database_path=self.root/'memory.db',filesystem_permission_store_path=self.root/'permissions/grants.json'))
        self.controller._initialize()
        self.addCleanup(self.controller.close)

    def test_both_model_templates_all_length_modes(self):
        from zorvyq.services import DEFAULT_MODEL
        for model in (DEFAULT_MODEL,SPECIALIST):
            for length,expected in [('Short','1–3 sentences'),('Balanced','few relevant details'),('Detailed','comprehensive')]:
                with self.subTest(model=model,length=length), patch.object(self.controller.service,'models',return_value={'installed':[{'name':SPECIALIST}]}), patch('zorvyq.services.DesktopProvider.chat',return_value='Safe answer') as chat:
                    result=self.controller.ask('What is a firewall?',model=model,answer_length=length)
                    messages=chat.call_args.args[0]
                    self.assertIn(expected,messages[0]['content'])
                    self.assertEqual(messages[-1],{'role':'user','content':'What is a firewall?'})
                    self.assertEqual(result['answer'],'Safe answer')

    def test_explicit_detail_override_and_complete_code_preserved(self):
        output='Complete detailed answer\n```python\nprint("complete")\n```'
        with patch('zorvyq.services.DesktopProvider.chat',return_value=output) as chat:
            self.assertEqual(self.controller.ask('Explain everything in detail')['answer'],output)
        self.assertIn('honor an explicit request for more detail',chat.call_args.args[0][0]['content'])

    def test_no_auto_specialist_routing(self):
        with patch('zorvyq.services.DesktopProvider.chat',return_value='answer') as chat, patch.object(self.controller.service,'models') as inventory:
            self.controller.ask('What is SQL injection?')
        inventory.assert_not_called()
        self.assertEqual(self.controller.manager.provider_model,'qwen3:4b')

    def test_unavailable_specialist_and_incompatible_rag_no_fallback(self):
        from friday.providers.base import ProviderError
        with patch.object(self.controller.service,'models',return_value={'installed':[]}), patch('zorvyq.services.DesktopProvider.chat') as chat:
            with self.assertRaises(ProviderError):self.controller.ask('question',model=SPECIALIST)
            with self.assertRaises(ProviderError):self.controller.ask('question',model=SPECIALIST,approved_knowledge=True)
            chat.assert_not_called()

    def test_citations_not_truncated_by_short_mode(self):
        answer='A cited statement [C1]\n\nVerified sources:\n[C1] synthetic source'
        knowledge=self.controller.assistant.knowledge
        knowledge.answer=Mock(return_value=answer)
        knowledge.last_status={'citation_validation_status':'verified'}
        result=self.controller.ask('synthetic question',approved_knowledge=True,answer_length='Short')
        self.assertEqual(result['answer'],answer)
        self.assertEqual(result['knowledge_status']['citation_validation_status'],'verified')


if __name__ == '__main__': unittest.main()
