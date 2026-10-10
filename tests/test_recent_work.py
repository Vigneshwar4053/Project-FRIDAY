"""Headless startup/Q acceptance: fake native files and mocked GUI/audio only."""
from contextlib import closing
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import subprocess
import time
import unittest
from unittest.mock import Mock, patch

from test_desktop import DesktopFixture
from friday.desktop.recent import RecentWorkQueue, reviewed_url
from friday.desktop.registry import ApplicationRegistry
from friday.desktop.routing import DesktopIntentResolver
from friday.tools.router import ToolRouter
from friday.tools.access import FolderDecision
from friday.voice.startup import StartupGreeting, local_greeting
from friday.voice.tts import SpeechController, EspeakNGBackend
from friday.memory import MemoryManager


class GreetingTests(unittest.TestCase):
    def setUp(self):
        original = os.environ.get('TZ')
        os.environ['TZ'] = 'UTC'; time.tzset()
        def restore():
            if original is None: os.environ.pop('TZ', None)
            else: os.environ['TZ'] = original
            time.tzset()
        self.addCleanup(restore)

    def test_time_boundaries(self):
        for hour, minute, word in [(5,0,'morning'),(11,59,'morning'),(12,0,'afternoon'),
                                   (16,59,'afternoon'),(17,0,'evening'),(4,59,'evening'),(0,0,'evening')]:
            with self.subTest(hour=hour,minute=minute):
                self.assertEqual(local_greeting(datetime(2026,10,10,hour,minute,tzinfo=timezone.utc)),
                                 f'Good {word}! Welcome back.')

    def test_system_local_timezone(self):
        os.environ['TZ'] = 'Asia/Kolkata'; time.tzset()
        self.assertEqual(local_greeting(datetime(2026,10,9,23,30,tzinfo=timezone.utc)),
                         'Good morning! Welcome back.')

    def test_once_print_and_speak_using_safe_provenance(self):
        backend=Mock(); output=[]; speech=SpeechController(backend,write=output.append)
        startup=StartupGreeting()
        for _ in range(2): startup.greet(speech,interactive=True,write=output.append)
        self.assertEqual(len(output),1);backend.speak.assert_called_once_with(output[0])

    def test_disabled_print_only(self):
        backend=Mock(); speech=SpeechController(backend);speech.enabled=False;output=[]
        StartupGreeting().greet(speech,interactive=True,write=output.append)
        self.assertEqual(len(output),1);backend.speak.assert_not_called()

    def test_missing_tts_continues(self):
        with patch.object(EspeakNGBackend,'verify',side_effect=OSError()),patch('friday.voice.tts.subprocess.Popen') as process:
            speech=SpeechController(write=lambda _:None);output=[]
            StartupGreeting().greet(speech,interactive=True,write=output.append)
        self.assertEqual(len(output),1);process.assert_not_called()

    def test_noninteractive_and_diagnostics_do_not_play_or_print(self):
        speech=Mock();write=Mock()
        for interactive,diagnostics in [(False,False),(True,True)]:
            self.assertFalse(StartupGreeting().greet(speech,interactive=interactive,diagnostics=diagnostics,write=write))
        speech.speak_safe_response.assert_not_called();write.assert_not_called()

    def test_help_and_voice_diagnostics_skip_assistant_startup(self):
        from friday.main import cli_main
        with patch('friday.main.main') as main, patch('sys.stdout',io.StringIO()):
            with self.assertRaises(SystemExit): cli_main(['--help'])
            cli_main(['--check-voice-config','--voice-config','/nonexistent/friday/voice.json'])
        main.assert_not_called()

    def test_startup_speech_timeout_is_five_seconds_and_restored(self):
        backend=EspeakNGBackend(); speech=SpeechController(backend,write=lambda _:None)
        speech.enabled=True
        child=Mock();child.communicate.return_value=(b'',b'');child.returncode=0;child.poll.return_value=0
        with patch.object(backend,'verify'),patch('friday.voice.tts.subprocess.Popen',return_value=child):
            StartupGreeting().greet(speech,interactive=True,write=lambda _:None)
        self.assertEqual(child.communicate.call_args_list[0].kwargs['timeout'],5)
        self.assertEqual(backend.timeout,60)


class QueueTests(DesktopFixture):
    def setUp(self):
        super().setUp()
        self.router=ToolRouter(self.project,desktop_resolver=DesktopIntentResolver(self.apps,self.adapter.recent))

    def test_empty_queue(self):
        self.assertIn('No recent work saved yet.',self.adapter.recent.show())
        self.assertEqual(self.adapter.recent.menu_ids,())

    def test_one_two_three_then_eviction(self):
        operations=[('open_project',{'project_id':'friday'}),
                    ('launch_application',{'application_id':'firefox','url':'https://github.com/'}),
                    ('open_folder',{'folder_id':'documents'}),
                    ('open_folder',{'folder_id':'downloads','retry':True})]
        for index,(op,args) in enumerate(operations):
            self.assertEqual(self.invoke(op,args).data['status'],'launch_accepted')
            rows=self.memory.recent_work();self.assertEqual(len(rows),min(index+1,3))
            menu=self.adapter.recent.show(detailed=True)
            self.assertEqual(len(self.adapter.recent.menu_ids),min(index+1,3))
            self.assertIn('[1] '+rows[0]['title'],menu)
        self.assertEqual([r['title'] for r in rows],['Downloads folder','Documents folder','Firefox — github.com'])

    def test_repeated_activity_keeps_id_moves_front_and_updates_time(self):
        self.invoke('open_project',{'project_id':'friday'}); original=self.memory.recent_work()[0]
        self.invoke('open_folder',{'folder_id':'documents'})
        self.invoke('open_project',{'project_id':'friday'})
        rows=self.memory.recent_work()
        self.assertEqual(len(rows),2);self.assertEqual(rows[0]['entry_id'],original['entry_id'])
        self.assertGreaterEqual(rows[0]['launched_at'],original['launched_at'])

    def test_persistence_after_reopen(self):
        self.invoke('open_project',{'project_id':'friday'})
        expected=self.memory.recent_work();self.memory.close()
        with MemoryManager(self.root/'memory.db') as restarted:
            self.assertEqual(restarted.recent_work(),expected)
            self.assertIn('FRIDAY project',RecentWorkQueue(restarted).show(detailed=True))

    def test_denied_and_failed_never_update_queue(self):
        self.approval.request.return_value=FolderDecision.DENY;self.invoke()
        self.approval.request.return_value=FolderDecision.ALLOW_ONCE
        self.child.wait.return_value=1;self.invoke()
        self.assertEqual(self.memory.recent_work(),())

    def test_success_and_voice_provenance_exclusion(self):
        self.invoke('open_project',{'project_id':'friday'},persist_metadata=False)
        self.assertEqual(self.memory.recent_work(),())
        self.invoke();self.assertEqual(len(self.memory.recent_work()),1)

    def test_invalid_selection_and_context_isolation(self):
        self.assertFalse(self.router.route('1').matched)
        self.invoke();self.adapter.recent.show()
        self.assertIn('Invalid',self.router.route('2').message)
        self.assertFalse(self.router.route('1').matched)
        self.adapter.recent.show();self.router.route('hello')
        self.assertFalse(self.router.route('1').matched)

    def test_stable_selection_not_current_position(self):
        self.invoke('open_project',{'project_id':'friday'})
        self.invoke('open_folder',{'folder_id':'documents'})
        self.adapter.recent.show();expected=self.adapter.recent.menu_ids[1]
        # A queue reorder between display and selection must not retarget a slot.
        self.invoke('open_project',{'project_id':'friday'})
        route=self.router.route('2');self.assertEqual(route.arguments['entry_id'],expected)
        self.invoke(route.tool_name,dict(route.arguments))
        self.assertEqual(self.approval.request.call_args.args[0].operation,'open_project')

    def test_resume_requires_fresh_exact_approval_and_respects_denial(self):
        self.invoke('open_project',{'project_id':'friday'})
        self.approval.request.return_value=FolderDecision.DENY
        before=self.memory.recent_work()
        result=self.invoke('resume_activity',{})
        self.assertFalse(result.success);self.assertEqual(self.approval.request.call_count,2)
        self.assertEqual(self.process.call_count,1);self.assertEqual(self.memory.recent_work(),before)

    def test_missing_project_refused_before_approval(self):
        self.invoke('open_project',{'project_id':'friday'});self.project.rename(self.home/'gone')
        result=self.invoke('resume_activity',{})
        self.assertEqual(result.data['status'],'unavailable');self.assertEqual(self.process.call_count,1)
        self.assertEqual(self.approval.request.call_count,1)

    def test_modified_target_identity_refused(self):
        self.invoke('open_project',{'project_id':'friday'});self.project.rename(self.home/'old');self.project.mkdir()
        result=self.invoke('resume_activity',{})
        self.assertIn('identity changed',result.data['message']);self.assertEqual(self.process.call_count,1)

    def test_folder_mapping_change_refused(self):
        self.invoke('open_folder',{'folder_id':'documents'})
        other=self.home/'Other';other.mkdir()
        with patch.object(self.adapter.locations,'resolve',return_value=str(other)):
            result=self.invoke('resume_activity',{})
        self.assertIn('mapping changed',result.data['message']);self.assertEqual(self.process.call_count,1)

    def test_untrusted_executable_on_resume(self):
        self.invoke();self.paths['vscode'].chmod(0o777)
        self.assertEqual(self.invoke('resume_activity',{}).data['status'],'unavailable')
        self.assertEqual(self.process.call_count,1)

    def test_unsafe_sensitive_and_unreviewed_urls(self):
        for url in ('javascript:alert(1)','data:text/html,x','file:///etc/passwd','http://github.com/',
                    'https://user:password@github.com/','https://github.com/?token=secret',
                    'https://github.com/#secret','https://github.com/private-secret-path','https://example.com/'):
            with self.subTest(url=url):
                with self.assertRaises(ValueError): reviewed_url(url)
                result=self.invoke('launch_application',{'application_id':'firefox','url':url})
                self.assertEqual(result.data['status'],'invalid_target')
        self.process.assert_not_called();self.approval.request.assert_not_called()
        self.assertEqual(self.memory.recent_work(),())

    def test_reviewed_url_exact_permission_and_fixed_argv(self):
        self.invoke('launch_application',{'application_id':'firefox','url':'https://github.com/'})
        self.assertIn('https://github.com/',self.approval.request.call_args.args[0].target)
        args=self.process.call_args.args[0]
        self.assertEqual(args[1:],['--new-window','https://github.com/'])
        self.assertFalse(self.process.call_args.kwargs.get('shell',False))
        self.assertEqual(self.memory.recent_work()[0]['safe_link'],'https://github.com/')

    def test_terminal_escape_and_modified_descriptor_refused(self):
        self.invoke()
        with self.memory._database.transaction() as db:
            db.execute('UPDATE recent_work SET title=?', ('\x1b[2J\nFORGED',))
        menu=self.adapter.recent.show(detailed=True)
        self.assertNotIn('\x1b',menu);self.assertNotIn('FORGED',menu)
        self.assertIn('invalid',menu)
        self.assertEqual(self.invoke('resume_activity',{}).data['status'],'no_session')
        self.assertEqual(self.process.call_count,1)

    def test_descriptor_cannot_add_shell_flags(self):
        self.invoke();row=self.memory.recent_work()[0];d=json.loads(row['resume_descriptor'])
        d['arguments']['flags']='--disable-sandbox'
        with self.memory._database.transaction() as db:
            db.execute('UPDATE recent_work SET resume_descriptor=?',(json.dumps(d),))
        self.assertEqual(self.invoke('resume_activity',{}).data['status'],'no_session')
        self.assertEqual(self.process.call_count,1)

    def test_required_natural_language_and_project_filter(self):
        for phrase in ('Show my recent work.','Show Q.','What was I working on?'):
            self.assertEqual(self.router.route(phrase).tool_name,'show_recent_work')
        self.assertEqual(self.router.route('Resume my last work.').tool_name,'resume_activity')
        self.assertEqual(self.router.route("Resume yesterday's project.").tool_name,'resume_project')
        self.invoke('open_project',{'project_id':'friday'});self.invoke('open_folder',{'folder_id':'documents'})
        result=self.invoke('show_recent_work',{'projects':True})
        self.assertIn('FRIDAY — VS Code',result.data['message']);self.assertNotIn('Documents folder',result.data['message'])
        self.assertEqual(len(self.adapter.recent.menu_ids),1)

    def test_empty_resume_explains_no_match(self):
        self.assertEqual(self.invoke('resume_activity',{}).data['status'],'no_session')
        self.assertIn('No saved project',self.invoke('show_recent_work',{'projects':True}).data['message'])
        self.process.assert_not_called()

    def test_required_bare_folder_commands(self):
        for phrase in ('Open Downloads.','Open Documents.'):
            self.assertEqual(self.router.route(phrase).tool_name,'open_folder')

    def test_symlink_executable_and_writable_parent_refused(self):
        target=self.paths['vscode'];target.rename(self.app_root/'original');target.symlink_to(self.app_root/'original')
        self.assertFalse(self.apps.availability('vscode'));self.process.assert_not_called()
        target.unlink();target.write_bytes(b'\x7fELFfixture');target.chmod(0o700)
        self.app_root.chmod(0o777)
        self.assertFalse(self.apps.availability('vscode'))

    def test_production_snap_diagnostic_has_no_unsafe_fallback(self):
        apps=ApplicationRegistry()
        with patch.object(Path,'exists',return_value=False),patch.object(Path,'is_symlink',return_value=True):
            reason=apps.unavailable_reason('vscode')
        self.assertIn('Snap launcher detected',reason);self.assertIn('Owner action',reason)
        self.process.assert_not_called()

    def test_last_work_offers_most_recent_viable_entry_but_number_never_falls_back(self):
        self.invoke('open_project',{'project_id':'friday'})
        self.invoke('open_folder',{'folder_id':'documents'})
        latest=self.memory.recent_work()[0]['entry_id']
        (self.home/'Documents').rmdir()
        result=self.invoke('resume_activity',{'entry_id':latest})
        self.assertEqual(result.data['status'],'unavailable');self.assertEqual(self.process.call_count,2)
        result=self.invoke('resume_activity',{})
        self.assertEqual(result.data['status'],'launch_accepted')
        approval=self.approval.request.call_args.args[0]
        self.assertEqual(approval.operation,'open_project')
        self.assertIn('most recent currently valid',approval.effect)

    def cli(self, inputs, *, database_path=None):
        from dataclasses import replace
        from friday.config.settings import settings
        from friday.main import main
        configuration=replace(settings,project_root=self.project,database_path=database_path or self.root/'memory.db',
                              filesystem_permission_store_path=self.root/'permissions/grants.json')
        speech=Mock();output=io.StringIO()
        from friday.security.owner import OwnerAuthenticator
        self.cli_owner=Mock(spec=OwnerAuthenticator)
        with patch('friday.main.settings',configuration),patch('friday.main.OllamaProvider') as provider, \
             patch('friday.security.owner.OwnerAuthenticator',return_value=self.cli_owner), \
             patch('friday.desktop.runtime.ApplicationRegistry',return_value=self.apps), \
             patch('builtins.input',side_effect=inputs),patch('sys.stdout',output), \
             patch('sys.stdin.isatty',return_value=True),patch.object(output,'isatty',return_value=True):
            main(adaptive=True,speech_backend=speech)
        return output.getvalue(),speech,provider.return_value

    def test_cli_startup_menu_then_number_still_requires_typed_approval(self):
        self.invoke('open_project',{'project_id':'friday'})
        output,speech,provider=self.cli(['1','3','Show Q.','1','1','quit'])
        self.assertEqual(output.count('Welcome back.'),1)
        self.assertIn('YOUR RECENT WORK',output);self.assertIn('[1] FRIDAY — VS Code',output)
        self.assertEqual(output.count('Permission required:'),2)
        self.assertEqual(self.cli_owner.authenticate.call_count,2)
        self.assertIn('Desktop permission denied',output)
        self.assertIn('Launch request accepted',output)
        self.assertEqual(self.process.call_count,2);provider.chat.assert_not_called()
        speech.speak.assert_called_once()

    def test_cli_slash_command_closes_numeric_menu(self):
        self.invoke()
        output,_,provider=self.cli(['/q','1','quit'])
        self.assertNotIn('Permission required:',output)
        self.assertEqual(self.process.call_count,1)
        self.assertNotIn('[Tool: resume_activity]',output)

    def test_numeric_punctuation_cannot_select_menu_entry(self):
        self.invoke();self.adapter.recent.show()
        self.assertFalse(self.router.route('1.').matched)
        self.assertEqual(self.adapter.recent.menu_ids,())

    def test_deeply_nested_untrusted_descriptor_fails_closed(self):
        self.invoke()
        poisoned = '[' * 1100 + '0' + ']' * 1100
        with self.memory._database.transaction() as db:
            db.execute('UPDATE recent_work SET resume_descriptor=?', (poisoned,))
        self.assertIn('invalid',self.adapter.recent.show())
        self.assertEqual(self.invoke('resume_activity',{}).data['status'],'no_session')
        self.assertEqual(self.process.call_count,1)

    def test_live_files_sequence_records_running_process_with_honest_status(self):
        self.child.wait.side_effect=subprocess.TimeoutExpired('files',1)
        self.child.poll.return_value=None
        with patch.object(self.memory,'record_recent_work',wraps=self.memory.record_recent_work) as write:
            output,_,provider=self.cli(['Show Q','open ubuntu files','1','show Q','show Q diagnostics','quit'])
        self.assertIn('No recent work saved yet.',output)
        self.assertIn('Operation: navigate_folder',output)
        self.assertIn('Launch attempted; application process is running',output)
        self.assertIn('[1] Home — Ubuntu Files',output)
        self.assertIn('Summary: FRIDAY started Ubuntu Files for Home folder.',output)
        self.assertIn('Status: Window not verified.',output)
        self.assertIn('Resume: '+str(self.home),output)
        # CLI creates a separate manager at the same configured database path.
        write.assert_not_called()
        rows=self.memory.recent_work();self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['launch_status'],'launch_outcome_unverified')
        self.assertEqual(rows[0]['activity_type'],'nautilus_location')
        self.assertEqual(json.loads(rows[0]['resume_descriptor'])['path'],str(self.home))
        provider.chat.assert_not_called()

    def test_running_process_records_once_with_correct_metadata(self):
        self.child.wait.side_effect=subprocess.TimeoutExpired('files',1)
        with patch.object(self.adapter.recent,'record',wraps=self.adapter.recent.record) as record:
            result=self.invoke('launch_application',{'application_id':'files'})
        self.assertTrue(result.data['recent_work_recorded']);record.assert_called_once()
        lease,status=record.call_args.args
        self.assertEqual(status,'launch_outcome_unverified')
        self.assertEqual(lease['record_arguments'],{'folder_id':'home'})
        self.assertIsNone(lease['project_id']);self.assertEqual(lease['path'],self.home)

    def test_running_files_repeat_reorders_and_updates_status_without_duplicate(self):
        self.invoke('launch_application',{'application_id':'files'})
        original=self.memory.recent_work()[0]
        self.invoke('launch_application',{'application_id':'firefox'})
        self.child.wait.side_effect=subprocess.TimeoutExpired('files',1)
        self.invoke('launch_application',{'application_id':'files','retry':True})
        rows=self.memory.recent_work();self.assertEqual(len(rows),2)
        self.assertEqual(rows[0]['entry_id'],original['entry_id'])
        self.assertEqual(rows[0]['application_id'],'files')
        self.assertEqual(rows[0]['launch_status'],'launch_outcome_unverified')

    def test_running_files_persists_after_restart_and_resume_needs_new_approval(self):
        self.child.wait.side_effect=subprocess.TimeoutExpired('files',1)
        self.cli(['open ubuntu files','1','quit'])
        saved=self.memory.recent_work()[0]
        output,_,provider=self.cli(['Show Q','Show Q diagnostics','1','3','quit'])
        self.assertIn('[1] Home — Ubuntu Files',output)
        self.assertIn('Status: Window not verified.',output)
        self.assertIn('Permission required:',output)
        self.assertIn('Desktop permission denied',output)
        self.assertEqual(self.memory.recent_work()[0],saved)
        self.assertEqual(self.process.call_count,1);provider.chat.assert_not_called()

    def test_denied_and_failed_files_cli_do_not_record(self):
        output,_,_=self.cli(['open ubuntu files','3','show Q','quit'])
        self.assertIn('Desktop permission denied',output)
        self.assertEqual(self.memory.recent_work(),());self.process.assert_not_called()
        self.child.wait.return_value=1
        output,_,_=self.cli(['open ubuntu files','1','show Q','quit'])
        self.assertIn('Application launch failed',output)
        self.assertEqual(self.memory.recent_work(),())

    def test_running_voice_provenance_still_excluded(self):
        self.child.wait.side_effect=subprocess.TimeoutExpired('files',1)
        result=self.invoke('launch_application',{'application_id':'files'},persist_metadata=False)
        self.assertEqual(result.data['status'],'launch_outcome_unverified')
        self.assertEqual(self.memory.recent_work(),())

    def test_different_cli_database_paths_keep_queue_isolated(self):
        self.child.wait.side_effect=subprocess.TimeoutExpired('files',1)
        self.cli(['open ubuntu files','1','quit'])
        other=self.root/'other.db'
        output,_,_=self.cli(['Show Q','quit'],database_path=other)
        self.assertIn('No recent work saved yet.',output)
        self.assertNotIn('[1] Home — Ubuntu Files',output)
        with MemoryManager(other) as memory:
            self.assertEqual(memory.recent_work(),())
        output,_,_=self.cli(['Show Q','quit'])
        self.assertIn('[1] Home — Ubuntu Files',output)
        self.assertEqual(len(self.memory.recent_work()),1)

    def test_sqlite_write_failure_is_reported_and_transaction_rolled_back(self):
        for app in ('files','firefox','vscode'):
            self.invoke('launch_application',{'application_id':app})
        before=self.memory.recent_work()
        with self.memory._database.transaction() as db:
            db.execute("CREATE TRIGGER block_eviction BEFORE DELETE ON recent_work "
                       "BEGIN SELECT RAISE(ABORT, 'PRIVATE SQLite detail'); END")
        self.child.wait.side_effect=subprocess.TimeoutExpired('files',1)
        result=self.invoke('open_folder',{'folder_id':'documents','retry':True})
        self.assertFalse(result.data['recent_work_recorded'])
        self.assertIn('Recent work could not be saved.',result.data['message'])
        self.assertNotIn('PRIVATE',str(result.data))
        self.assertEqual(self.memory.recent_work(),before)

    def test_legacy_queue_migration_preserves_ids_and_resumes_safely(self):
        import sqlite3
        from uuid import uuid4
        legacy=self.root/'legacy.db'
        activity=RecentWorkQueue.activity('launch_application',{'application_id':'files'},'files',None,None,version=1)
        entry_id=str(uuid4());stamp=datetime.now(timezone.utc).isoformat()
        with closing(sqlite3.connect(legacy)) as db, db:
            db.execute('CREATE TABLE recent_work (entry_id TEXT PRIMARY KEY, activity_key TEXT NOT NULL UNIQUE, '
                       'activity_type TEXT NOT NULL, application_id TEXT NOT NULL, target_identity TEXT NOT NULL, '
                       'title TEXT NOT NULL, summary TEXT NOT NULL, resume_descriptor TEXT NOT NULL, '
                       'launched_at TEXT NOT NULL, safe_link TEXT NOT NULL, launch_order INTEGER NOT NULL)')
            db.execute('INSERT INTO recent_work VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (entry_id,activity['activity_key'],activity['activity_type'],activity['application_id'],
                        activity['target_identity'],activity['title'],activity['summary'],activity['resume_descriptor'],
                        stamp,activity['safe_link'],1))
        for _ in range(2):  # Migration is idempotent across restarts.
            with MemoryManager(legacy) as memory:
                row=memory.recent_work()[0]
                self.assertEqual(row['entry_id'],entry_id)
                self.assertEqual(row['launch_status'],'launch_accepted')
                queue=RecentWorkQueue(memory)
                self.assertIn('Summary: FRIDAY started Ubuntu Files.',queue.show(detailed=True))
                self.assertIn('Status: Window not verified.',queue.show(detailed=True))
                self.assertEqual(queue.get(entry_id)[1]['arguments'],{'application_id':'files'})
        output,_,_=self.cli(['Show Q','1','3','quit'],database_path=legacy)
        self.assertIn('Desktop permission denied',output);self.process.assert_not_called()

    def test_invalid_launch_status_cannot_be_recorded(self):
        activity=RecentWorkQueue.activity('launch_application',{'application_id':'files'},'files',None,None)
        activity['launch_status']='launch_failed'
        with self.assertRaises(ValueError): self.memory.record_recent_work(activity)
        with self.assertRaises(ValueError): self.adapter.recent.record({},'launch_failed')
        self.assertEqual(self.memory.recent_work(),())
