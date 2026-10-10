"""Headless Files launch-guard and forwarding tests. Never invoke GUI binaries."""
import os
from pathlib import Path
import subprocess
from unittest.mock import patch, Mock

from test_desktop import DesktopFixture
from friday.desktop.guard import RecentLaunchGuard
from friday.desktop.registry import ApplicationRegistry
from friday.desktop.routing import DesktopIntentResolver
from friday.tools.access import FolderDecision
from friday.tools.router import ToolRouter
from friday.tools.models import ToolRequest, ToolStatus
from friday.memory import MemoryManager
from friday.config.settings import Settings


class DesktopRepairTests(DesktopFixture):
    def setUp(self):
        super().setUp()
        self.clock=Mock(return_value=100.0)
        self.adapter.duplicate_guard=RecentLaunchGuard(20,clock=self.clock)
        self.router=ToolRouter(self.project,desktop_resolver=DesktopIntentResolver(self.apps,self.adapter.recent))

    def files(self, **arguments):
        return self.invoke('launch_application',{'application_id':'files',**arguments})

    def test_repeated_files_requires_one_fresh_prompt_each_and_refreshes_one_q_row(self):
        self.assertEqual(self.files().data['status'],'launch_accepted');saved=self.memory.recent_work()[0]
        self.clock.return_value=101
        self.assertEqual(self.files().data['status'],'launch_accepted')
        self.assertEqual(self.process.call_count,2);self.assertEqual(self.approval.request.call_count,2)
        self.assertEqual(self.adapter.executor.launch_count,2)
        rows=self.memory.recent_work();self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['entry_id'],saved['entry_id']);self.assertGreater(rows[0]['launch_order'],saved['launch_order'])

    def test_running_process_does_not_suppress_approved_launch_or_claim_a_window(self):
        self.child.wait.side_effect=subprocess.TimeoutExpired('files',1);self.child.poll.return_value=None
        self.files();result=self.files()
        self.assertEqual(result.data['status'],'launch_outcome_unverified')
        self.assertIn('not verified',result.data['message']);self.assertNotIn('focused',result.data['message'])
        self.assertEqual(self.process.call_count,2);self.assertEqual(self.approval.request.call_count,2)
        self.assertEqual(len(self.memory.recent_work()),1)

    def test_retry_is_exact_routed_action_and_needs_fresh_approval(self):
        self.files()
        route=self.router.route('retry open ubuntu files')
        self.assertEqual(route.tool_name,'launch_application')
        self.assertEqual(dict(route.arguments),{'application_id':'files','retry':True})
        self.invoke(route.tool_name,dict(route.arguments))
        self.assertEqual(self.approval.request.call_count,2);self.assertEqual(self.process.call_count,2)
        self.assertIn('Explicit retry',self.approval.request.call_args.args[0].effect)
        self.assertEqual(len(self.memory.recent_work()),1)
        self.assertNotIn('retry',self.memory.recent_work()[0]['resume_descriptor'])

    def test_retry_denied_does_not_launch_refresh_q_or_budget(self):
        self.files();before=self.memory.recent_work()
        self.approval.request.return_value=FolderDecision.DENY
        self.assertFalse(self.files(retry=True).success)
        self.assertEqual(self.approval.request.call_count,2);self.assertEqual(self.process.call_count,1)
        self.assertEqual(self.adapter.executor.launch_count,1);self.assertEqual(self.memory.recent_work(),before)

    def test_old_cooldown_has_no_effect_on_fresh_approved_launches(self):
        self.files();self.clock.return_value=119;self.files();self.clock.return_value=120
        self.assertEqual(self.files().data['status'],'launch_accepted')
        self.assertEqual(self.approval.request.call_count,3);self.assertEqual(self.process.call_count,3)

    def test_files_downloads_documents_and_unrelated_application_are_distinct(self):
        self.files()
        for folder in ('downloads','documents'):
            self.assertEqual(self.invoke('open_folder',{'folder_id':folder,'retry':True}).data['status'],'launch_accepted')
        self.assertEqual(self.invoke('launch_application',{'application_id':'firefox'}).data['status'],'launch_accepted')
        self.assertEqual(self.process.call_count,4)

    def test_repeated_downloads_refreshes_and_documents_remains_distinct(self):
        self.invoke('open_folder',{'folder_id':'downloads'});saved=self.memory.recent_work()[0]
        self.assertEqual(self.invoke('open_folder',{'folder_id':'downloads'}).data['status'],'launch_accepted')
        self.assertEqual(self.memory.recent_work()[0]['entry_id'],saved['entry_id'])
        self.assertEqual(self.invoke('open_folder',{'folder_id':'documents'}).data['status'],'launch_accepted')
        self.assertEqual([r['title'] for r in self.memory.recent_work()],['Documents folder','Downloads folder'])
        self.assertEqual(self.process.call_count,3);self.assertEqual(self.approval.request.call_count,3)

    def test_exact_target_identity_change_requires_explicit_retry(self):
        self.invoke('open_folder',{'folder_id':'downloads'})
        path=self.home/'Downloads';old=path.stat();path.rename(self.home/'OldDownloads');path.mkdir()
        self.assertEqual(self.invoke('open_folder',{'folder_id':'downloads','retry':True}).data['status'],'launch_accepted')
        self.assertEqual(self.process.call_count,2)
        pins=self.adapter.executor.folder_pins
        self.assertIn((str(path),(old.st_dev,old.st_ino)),pins)
        self.assertEqual(len(pins),2)

    def test_invalid_and_symlink_folder_are_refused_even_after_recent_launch(self):
        self.invoke('open_folder',{'folder_id':'downloads'})
        path=self.home/'Downloads';path.rename(self.home/'OriginalDownloads');path.symlink_to(self.project)
        self.assertEqual(self.invoke('open_folder',{'folder_id':'downloads'}).data['status'],'unavailable')
        self.assertEqual(self.invoke('open_folder',{'folder_id':'arbitrary'}).data['status'],'unavailable')
        self.assertEqual(self.process.call_count,1);self.assertEqual(self.approval.request.call_count,1)

    def test_budget_remains_four_actual_starts_and_no_prompt_when_exhausted(self):
        for index in range(4):
            self.files(retry=bool(index))
        self.assertEqual(self.files().data['status'],'launch_limit_reached')
        result=self.files(retry=True)
        self.assertEqual(result.data['status'],'launch_limit_reached')
        self.assertIn('four processes',result.data['message'])
        self.assertEqual(self.approval.request.call_count,4);self.assertEqual(self.process.call_count,4)
        self.assertEqual(self.adapter.executor.launch_count,4)

    def test_failed_or_denied_launch_does_not_arm_guard(self):
        self.approval.request.return_value=FolderDecision.DENY;self.files()
        self.approval.request.return_value=FolderDecision.ALLOW_ONCE
        self.child.wait.return_value=1;self.files()
        self.child.wait.return_value=0
        self.assertEqual(self.files().data['status'],'launch_accepted')
        self.assertEqual(self.approval.request.call_count,3);self.assertEqual(self.process.call_count,2)
        self.assertEqual(len(self.memory.recent_work()),1)

    def test_spawn_exception_does_not_consume_budget_or_leave_new_pin(self):
        self.process.side_effect=OSError('private')
        self.assertFalse(self.invoke('open_folder',{'folder_id':'downloads'}).success)
        self.assertEqual(self.adapter.executor.launch_count,0)
        self.assertEqual(self.adapter.executor.folder_pins,{})
        self.assertEqual(self.adapter.duplicate_guard.receipts,{})
        self.assertEqual(self.memory.recent_work(),())

    def test_forwarded_folder_uses_stable_parent_fd_and_no_shell_or_new_window(self):
        original=(self.home/'Downloads').stat()
        self.invoke('open_folder',{'folder_id':'downloads'})
        argv=self.process.call_args.args[0]
        self.assertEqual(argv[-2],'--');self.assertNotIn('--new-window',argv)
        self.assertFalse(self.process.call_args.kwargs.get('shell',False))
        self.assertTrue(argv[-1].startswith(f'/proc/{os.getpid()}/fd/'))
        pin=int(argv[-1].rsplit('/',1)[1]); info=os.stat(argv[-1])
        self.assertEqual((info.st_dev,info.st_ino),(original.st_dev,original.st_ino))
        self.assertFalse(os.get_inheritable(pin))
        # Pretend an existing process receives the same string after launch.
        (self.home/'Downloads').rename(self.home/'MovedDownloads');(self.home/'Downloads').mkdir()
        info=os.stat(argv[-1]);self.assertEqual(info.st_ino,original.st_ino)
        self.adapter.close()
        with self.assertRaises(OSError): os.fstat(pin)

    def test_explicit_retry_of_same_folder_reuses_pinned_uri(self):
        self.invoke('open_folder',{'folder_id':'downloads'});uri=self.process.call_args.args[0][-1]
        self.invoke('open_folder',{'folder_id':'downloads','retry':True})
        self.assertEqual(self.process.call_args.args[0][-1],uri)
        self.assertEqual(len(self.adapter.executor.folder_pins),1)

    def test_resume_uses_exact_selected_activity_without_suppression_or_fallback(self):
        self.invoke('open_project',{'project_id':'friday'});self.files();saved=self.memory.recent_work()[0]
        self.adapter.recent.show();route=self.router.route('1')
        self.assertEqual(route.tool_name,'resume_activity')
        self.assertEqual(self.invoke(route.tool_name,dict(route.arguments)).data['status'],'launch_accepted')
        self.assertEqual(self.invoke('resume_activity',{}).data['status'],'launch_accepted')
        self.assertEqual(self.process.call_count,4);self.assertEqual(self.approval.request.call_count,4)
        self.assertEqual(self.memory.recent_work()[0]['entry_id'],saved['entry_id'])
        self.assertEqual(len(self.memory.recent_work()),2)

    def test_resume_needs_fresh_approval_without_retry_even_inside_cooldown(self):
        self.invoke('open_folder',{'folder_id':'downloads'});self.clock.return_value=101
        self.adapter.recent.show();route=self.router.route('1')
        self.assertEqual(self.invoke(route.tool_name,dict(route.arguments)).data['status'],'launch_accepted')
        self.assertEqual(self.approval.request.call_count,2);self.assertEqual(self.process.call_count,2)
        self.assertEqual(self.approval.request.call_args.args[0].operation,'navigate_folder')

    def test_retry_resume_requires_fresh_approval_and_does_not_store_retry(self):
        self.files();route=self.router.route('retry resume my last work')
        self.assertEqual(dict(route.arguments),{'retry':True})
        self.invoke(route.tool_name,dict(route.arguments))
        self.assertEqual(self.process.call_count,2);self.assertEqual(self.approval.request.call_count,2)
        self.assertNotIn('retry',self.memory.recent_work()[0]['resume_descriptor'])

    def test_accepted_retry_reorders_q_keeps_id_and_three_slots_persist(self):
        self.files();entry=self.memory.recent_work()[0]['entry_id']
        self.invoke('open_folder',{'folder_id':'downloads','retry':True})
        self.invoke('open_folder',{'folder_id':'documents','retry':True})
        self.files(retry=True)
        rows=self.memory.recent_work();self.assertEqual(len(rows),3);self.assertEqual(rows[0]['entry_id'],entry)
        self.memory.close()
        with MemoryManager(self.root/'memory.db') as memory:
            self.assertEqual(memory.recent_work(),rows)

    def test_suppressed_request_leaves_filesystem_grants_empty(self):
        self.files();self.files()
        self.assertFalse(list(self.project.rglob('grants.json')))
        self.assertEqual(self.memory.get_recent_messages(100),[])

    def test_bounded_guard_config_and_session_clear(self):
        for value in (0,121,True,float('nan'),float('inf'),'20'):
            with self.assertRaises(ValueError): Settings(desktop_duplicate_window_seconds=value)
        guard=self.adapter.duplicate_guard
        for i in range(40):
            guard.record({'record_operation':'open_folder','application_id':'files','path':f'/fixture/{i}',
                          'identity':(1,i),'url':None})
        self.assertEqual(len(guard.receipts),32)
        self.adapter.close();self.assertEqual(len(guard.receipts),0)
        self.assertEqual(Settings(desktop_duplicate_window_seconds=5).desktop_duplicate_window_seconds,5)

    def test_retry_rejects_shell_flags_arbitrary_names_and_nesting(self):
        for text in ('retry open ubuntu files --new-window','retry open downloads in ubuntu files && echo X',
                     'retry open /bin/bash -c X','retry retry open ubuntu files','retry launch files'):
            self.assertIn('not supported',self.router.route(text).message)
        self.process.assert_not_called();self.approval.request.assert_not_called()
        self.assertEqual(self.files(retry='yes').status,ToolStatus.INVALID_ARGUMENTS)

    def test_no_monitor_or_automatic_probe_during_guard(self):
        with patch('os.scandir') as scan, patch('subprocess.run') as run:
            self.files();self.files()
        scan.assert_not_called();run.assert_not_called();self.assertEqual(self.process.call_count,2)

    def test_snap_ids_paths_and_unexpected_arguments_fail_closed(self):
        for identity in ('snap.code','snap.firefox','/usr/bin/snap','/snap/bin/code','/snap/bin/firefox'):
            self.assertEqual(self.invoke('launch_application',{'application_id':identity}).data['status'],'unavailable')
        self.assertEqual(self.invoke('launch_application',{'application_id':'vscode','revision':'264'}).status,ToolStatus.INVALID_ARGUMENTS)
        self.process.assert_not_called();self.approval.request.assert_not_called()

    def test_snap_wrapper_and_metadata_never_replace_missing_native_identity(self):
        apps=ApplicationRegistry();self.adapter.applications=apps
        for app in ('vscode','firefox'):
            with patch.object(apps,'executable',side_effect=FileNotFoundError()), \
                 patch.object(apps,'_trusted_path',side_effect=ValueError('Untrusted ownership.')), \
                 patch.object(Path,'is_symlink',return_value=True),patch.object(Path,'exists',return_value=True), \
                 patch.object(self.adapter.snap,'executable',side_effect=ValueError('Invalid package registration.')):
                result=self.invoke('launch_application',{'application_id':app})
            self.assertEqual(result.data['status'],'unavailable')
            self.assertIn('Snap package identity or installation validation failed',result.data['message'])
        self.process.assert_not_called();self.approval.request.assert_not_called()

    def test_user_writable_native_or_script_substitution_refused_even_on_retry(self):
        self.paths['files'].chmod(0o777)
        self.assertEqual(self.files(retry=True).data['status'],'unavailable')
        self.paths['files'].chmod(0o700);self.paths['files'].write_bytes(b'#!/bin/sh\nsnap run files\n')
        self.assertEqual(self.files(retry=True).data['status'],'unavailable')
        self.process.assert_not_called();self.approval.request.assert_not_called()

    def test_cli_each_repeated_launch_requires_an_exact_prompt_and_explicit_answer(self):
        import io
        from dataclasses import replace
        from friday.config.settings import settings
        from friday.main import main
        configuration=replace(settings,project_root=self.project,database_path=self.root/'cli.db',filesystem_permission_store_path=self.root/'permissions/grants.json')
        output=io.StringIO()
        with patch('friday.main.settings',configuration),patch('friday.main.OllamaProvider') as provider, \
             patch('friday.desktop.runtime.ApplicationRegistry',return_value=self.apps), \
             patch('builtins.input',side_effect=['open files','1','open files','1','Show Q','open files','3','quit']), \
             patch('sys.stdout',output),patch('sys.stdin.isatty',return_value=True),patch.object(output,'isatty',return_value=True):
            main(adaptive=True,speech_backend=Mock())
        text=output.getvalue()
        self.assertEqual(text.count('Permission required:'),3);self.assertIn('[1] Home — Ubuntu Files',text)
        self.assertNotIn('Same-window Files navigation is unavailable',text)
        self.assertIn('Desktop permission denied',text);self.assertEqual(self.process.call_count,2)
        provider.return_value.chat.assert_not_called()
        with MemoryManager(configuration.database_path) as memory:self.assertEqual(len(memory.recent_work()),1)
