"""Unsupported target-window API fallback, headless; no synthetic GUI claims."""
import json
from unittest.mock import patch

from test_desktop import DesktopFixture
from friday.desktop.routing import DesktopIntentResolver
from friday.tools.access import FolderDecision
from friday.tools.router import ToolRouter
from friday.memory import MemoryManager


class FilesNavigationTests(DesktopFixture):
    def setUp(self):
        super().setUp()
        self.router=ToolRouter(self.project, desktop_resolver=DesktopIntentResolver(self.apps,self.adapter.recent))

    def command(self,text):
        route=self.router.route(text)
        return self.invoke(route.tool_name,dict(route.arguments))

    def test_first_files_requests_home_with_exact_navigation_permission(self):
        self.assertEqual(self.command('open ubuntu files').data['status'],'launch_accepted')
        permission=self.approval.request.call_args.args[0]
        self.assertEqual(permission.operation,'navigate_folder')
        self.assertEqual(permission.risk,'desktop_navigation')
        self.assertIn(str(self.home),permission.target)
        descriptor=json.loads(self.memory.recent_work()[0]['resume_descriptor'])
        self.assertEqual(descriptor['arguments'],{'folder_id':'home'})
        self.assertEqual(descriptor['path'],str(self.home))
        self.assertEqual(self.adapter.executor.launch_count,1)

    def test_owner_sequence_attempts_each_approved_location_and_respects_limit(self):
        for command in ('open files','open downloads','open documents','open files'):
            self.assertEqual(self.command(command).data['status'],'launch_accepted')
        self.assertEqual(self.command('open downloads').data['status'],'launch_limit_reached')
        self.assertEqual(self.process.call_count,4);self.assertEqual(self.approval.request.call_count,4)
        self.assertEqual(self.adapter.executor.launch_count,4)
        rows=self.memory.recent_work()
        self.assertEqual([r['title'] for r in rows],['Home folder','Documents folder','Downloads folder'])
        self.assertTrue(all(r['launch_status']=='launch_accepted' for r in rows))

    def test_state_does_not_claim_window_identity_or_verified_navigation(self):
        self.command('open ubuntu files')
        controller=self.adapter.file_navigation; state=controller.last_activity
        self.assertFalse(controller.supports_reuse)
        self.assertEqual(state.application_id,'files')
        self.assertEqual(state.requested_directory,str(self.home))
        self.assertIsNone(state.managed_window_identity)
        self.assertIsNone(state.verified_navigation_outcome)

    def test_exited_launcher_or_closed_window_is_never_evidence_of_reuse(self):
        self.child.poll.return_value=0
        for command in ('open files','open downloads','open files','open downloads'):
            result=self.command(command)
            self.assertEqual(result.data['status'],'launch_accepted')
            self.assertIn('not verified',result.data['message'])
            self.assertNotIn('focused',result.data['message'])
        self.assertEqual(self.process.call_count,4)
        self.child.terminate.assert_not_called();self.child.kill.assert_not_called()

    def test_no_bus_probe_monitor_or_shell_and_no_unrestricted_control(self):
        with patch('subprocess.run') as bus,patch('os.scandir') as scan:
            self.command('open ubuntu files');self.command('open downloads in ubuntu files')
        bus.assert_not_called();scan.assert_not_called()
        self.assertFalse(self.process.call_args.kwargs.get('shell',False))
        self.assertNotIn('--new-window',self.process.call_args.args[0])
        self.assertIsNone(self.adapter.file_navigation.last_activity.managed_window_identity)

    def test_retry_denied_does_not_modify_state_or_queue(self):
        self.command('open ubuntu files');state=self.adapter.file_navigation.last_activity
        before=self.memory.recent_work();self.approval.request.return_value=FolderDecision.DENY
        self.assertFalse(self.command('retry open downloads in ubuntu files').success)
        self.assertIs(self.adapter.file_navigation.last_activity,state)
        self.assertEqual(self.memory.recent_work(),before)
        self.assertEqual(self.process.call_count,1)

    def test_failed_launch_does_not_create_managed_activity(self):
        self.child.wait.return_value=1
        self.assertEqual(self.command('open ubuntu files').data['status'],'launch_failed')
        self.assertIsNone(self.adapter.file_navigation.last_activity)
        self.assertEqual(self.memory.recent_work(),())
        self.child.wait.return_value=0
        self.assertEqual(self.command('open downloads in ubuntu files').data['status'],'launch_accepted')

    def test_invalid_folder_and_identity_swap_rejected_before_retry(self):
        self.command('open ubuntu files')
        (self.home/'Downloads').rmdir()
        self.assertEqual(self.command('open downloads in ubuntu files').data['status'],'unavailable')
        self.assertEqual(self.invoke('open_folder',{'folder_id':'arbitrary'}).data['status'],'unavailable')
        self.assertEqual(self.process.call_count,1)

    def test_target_rechecked_after_exact_permission(self):
        def change(_):
            path=self.home/'Downloads';path.rename(self.home/'OldDownloads');path.mkdir()
            return FolderDecision.ALLOW_ONCE
        self.approval.request.side_effect=change
        self.assertFalse(self.command('open downloads in ubuntu files').success)
        self.process.assert_not_called()
        self.assertIsNone(self.adapter.file_navigation.last_activity)

    def test_q_resume_relaunches_exact_saved_location_with_fresh_approval(self):
        self.command('open downloads');saved=self.memory.recent_work()[0]
        self.command('show Q');self.assertEqual(self.command('1').data['status'],'launch_accepted')
        self.assertEqual(self.process.call_count,2);self.assertEqual(self.approval.request.call_count,2)
        self.assertIn(str(self.home/'Downloads'),self.approval.request.call_args.args[0].target)
        self.assertEqual(self.memory.recent_work()[0]['entry_id'],saved['entry_id'])
        self.assertEqual(len(self.memory.recent_work()),1)

    def test_restart_persists_q_but_never_window_state(self):
        self.command('open ubuntu files');rows=self.memory.recent_work()
        self.adapter.close()
        self.assertIsNone(self.adapter.file_navigation.last_activity)
        with MemoryManager(self.root/'memory.db') as restarted:
            self.assertEqual(restarted.recent_work(),rows)

    def test_three_locations_are_distinct_and_retries_keep_launch_limit(self):
        for text in ('open ubuntu files','retry open downloads in ubuntu files','retry open documents in ubuntu files'):
            self.assertEqual(self.command(text).data['status'],'launch_accepted')
        rows=self.memory.recent_work()
        self.assertEqual([row['title'] for row in rows],['Documents folder','Downloads folder','Home folder'])
        self.assertIn('Window not verified',self.adapter.recent.show(detailed=True))
        self.command('retry open ubuntu files')
        self.assertEqual(self.command('retry open downloads in ubuntu files').data['status'],'launch_limit_reached')
        self.assertEqual(self.process.call_count,4)
        self.assertEqual(len(self.memory.recent_work()),3)

    def test_registered_project_folder_uses_files_without_changing_editor_command(self):
        self.assertEqual(self.command('open my friday project folder in ubuntu files').data['status'],'launch_accepted')
        self.assertIn(str(self.project),self.approval.request.call_args.args[0].target)
        self.assertEqual(self.memory.recent_work()[0]['title'],'FRIDAY project folder')
        self.assertEqual(self.router.route('open my friday project').tool_name,'open_project')
        self.assertEqual(self.command('open my unregistered project folder in ubuntu files').data['status'],'unavailable')
        self.command('show Q');self.assertEqual(self.command('1').data['status'],'launch_accepted')
        self.assertEqual(self.process.call_count,2)

    def test_first_denied_action_never_arms_controller(self):
        self.approval.request.return_value=FolderDecision.DENY
        self.assertFalse(self.command('open ubuntu files').success)
        self.assertIsNone(self.adapter.file_navigation.last_activity)
        self.process.assert_not_called()

    def test_navigation_confers_no_filesystem_read_grant(self):
        self.command('open ubuntu files');self.command('open downloads in ubuntu files')
        self.assertFalse(list(self.project.rglob('grants.json')))
        self.assertEqual(self.memory.get_recent_messages(100),[])

    def test_legacy_application_queue_entry_resumes_exact_home(self):
        from friday.desktop.recent import RecentWorkQueue
        activity=RecentWorkQueue.activity('launch_application',{'application_id':'files'},'files',None,None)
        activity['launch_status']='launch_accepted';self.memory.record_recent_work(activity)
        saved=self.memory.recent_work()[0]
        self.invoke('resume_activity',{'entry_id':saved['entry_id']})
        permission=self.approval.request.call_args.args[0]
        self.assertEqual(permission.operation,'navigate_folder')
        self.assertIn(str(self.home),permission.target)
        self.assertEqual(self.process.call_count,1)

    def test_files_url_cannot_be_silently_discarded_or_executed(self):
        result=self.invoke('launch_application',{'application_id':'files','url':'https://github.com/'})
        self.assertEqual(result.data['status'],'unavailable')
        self.approval.request.assert_not_called();self.process.assert_not_called()
