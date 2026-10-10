"""Synthetic metadata search and reviewed launch handoffs; GUI always mocked."""
import json
import os
from pathlib import Path
from unittest.mock import patch

from test_desktop import DesktopFixture
from friday.desktop.routing import DesktopIntentResolver
from friday.desktop.recent import RecentWorkQueue
from friday.tools.discovery import TargetDiscovery
from friday.tools.access import FilesystemAccess,FolderDecision
from friday.tools.filesystem import FileSystemPolicy
from friday.tools.grants import PermissionStore
from friday.tools.router import ToolRouter


class DiscoveryTests(DesktopFixture):
    def setUp(self):
        super().setUp()
        self.store=PermissionStore(self.root/'permissions/grants.json',self.adapter.sensitive)
        self.boundary=FileSystemPolicy([self.project],grant_store=self.store)
        self.access=FilesystemAccess(self.boundary,self.store,self.approval)
        self.discovery=TargetDiscovery(self.access,self.adapter.projects,self.adapter.locations)
        self.adapter.discovery=self.discovery
        self.router=ToolRouter(self.project,desktop_resolver=DesktopIntentResolver(self.apps,self.adapter.recent,None,self.discovery))
        self.portfolio=self.project/'portfolio';self.portfolio.mkdir()
    def command(self,text):
        route=self.router.route(text)
        self.assertTrue(route.matched)
        return self.invoke(route.tool_name,dict(route.arguments))
    def test_common_grammar_separates_target_scope_application(self):
        route=self.router.route('open portfolio from downloads in vs code')
        self.assertEqual(dict(route.arguments),{'action':'open','name':'portfolio','scope':'downloads','application_id':'vscode'})
        for text in ('find portfolio','where is portfolio','show portfolio location'):
            self.assertEqual(self.router.route(text).arguments['action'],'find')
    def test_named_target_never_immediately_launches(self):
        result=self.command('open portfolio')
        self.assertIn('[1] VS Code',result.data['message']);self.assertIn('[2] Ubuntu Files',result.data['message'])
        self.process.assert_not_called();self.approval.request.assert_not_called()
    def test_single_result_exact_project_approval(self):
        result=self.command('open portfolio in vs code')
        self.assertEqual(result.data['status'],'launch_accepted')
        self.assertEqual(self.approval.request.call_args.args[0].operation,'open_project_in_application')
        self.assertIn(str(self.portfolio),self.approval.request.call_args.args[0].target)
        self.assertEqual(self.approval.request.call_count,1)
        argv=self.process.call_args.args[0]
        self.assertEqual(argv[-2],'--');self.assertTrue(argv[-1].startswith('/proc/self/fd/'))
    def test_multiple_matches_need_selection_then_destination(self):
        other=self.project/'nested/portfolio';other.mkdir(parents=True)
        result=self.command('open portfolio')
        self.assertIn(str(other),result.data['message']);self.assertIn(str(self.portfolio),result.data['message'])
        self.process.assert_not_called()
        self.assertIn('Choose how',self.command('1').data['message'])
        self.assertEqual(self.command('2').data['status'],'launch_accepted')
        self.assertEqual(self.approval.request.call_count,1)
    def test_search_grant_is_metadata_only_and_not_persisted(self):
        folder=self.home/'Downloads/portfolio';folder.mkdir()
        result=self.command('find portfolio in downloads')
        self.assertIn(str(folder),result.data['message'])
        self.assertEqual(type(self.approval.request.call_args.args[0]).__name__,'SearchApproval')
        self.assertEqual(self.store.load(),())
        with self.assertRaises(ValueError): self.boundary.resolve(str(folder))
        self.process.assert_not_called()
    def test_search_denial_no_launch(self):
        self.approval.request.return_value=FolderDecision.DENY
        result=self.command('open portfolio in downloads')
        self.assertFalse(result.success);self.process.assert_not_called();self.assertEqual(self.memory.recent_work(),())
    def test_launch_denial_no_q(self):
        self.approval.request.return_value=FolderDecision.DENY
        self.assertFalse(self.command('open portfolio in vs code').success)
        self.process.assert_not_called();self.assertEqual(self.memory.recent_work(),())
    def test_symlinks_and_sensitive_paths_excluded(self):
        (self.project/'elsewhere').symlink_to(self.home/'Downloads',target_is_directory=True)
        hidden=self.project/'.aws/portfolio';hidden.mkdir(parents=True)
        found,_=self.discovery.search('portfolio',(self.project,))
        self.assertEqual([row['path'] for row in found],[str(self.portfolio)])
    def test_replaced_selection_is_rejected(self):
        self.command('open portfolio')
        self.portfolio.rename(self.project/'old');self.portfolio.mkdir()
        result=self.command('2')
        self.assertEqual(result.data['status'],'unavailable');self.process.assert_not_called()
    def test_invalid_numeric_and_context_isolation(self):
        self.command('open portfolio')
        self.assertEqual(self.command('99').data['status'],'invalid_selection')
        self.command('open portfolio');self.router.route('hello')
        expired=self.router.route('2')
        self.assertTrue(expired.matched)
        self.assertIsNone(expired.tool_name)
        self.assertIn('expired',expired.message)
        self.process.assert_not_called()
    def test_no_matches_report_search_scope(self):
        result=self.command('find missingportfolio')
        self.assertIn(str(self.project),result.data['message']);self.assertIn('No matching',result.data['message'])
        self.process.assert_not_called()
    def test_entry_and_result_limits(self):
        for i in range(5): (self.project/str(i)/'portfolio').mkdir(parents=True)
        self.discovery.MAX_RESULTS=2
        matches,truncated=self.discovery.search('portfolio',(self.project,))
        self.assertEqual(len(matches),2);self.assertTrue(truncated)
    def test_unsafe_names_and_system_scopes_rejected(self):
        for name in ('../portfolio','portfolio;whoami','--help'):
            with self.assertRaises(ValueError): self.discovery.search(name,(self.project,))
        for scope in ('/etc','/proc','/sys','/dev','/root','/'):
            with self.assertRaises(ValueError):
                with self.discovery.authorized(Path(scope)): pass
        self.process.assert_not_called()
    def test_resolved_folder_and_alias_deduplicate_and_resume(self):
        # A resolved named folder and its registered folder alias share one key.
        self.command('open portfolio in ubuntu files')
        row=self.memory.recent_work()[0];old_id=row['entry_id']
        self.command('open portfolio in ubuntu files')
        self.assertEqual(len(self.memory.recent_work()),1)
        self.assertEqual(self.memory.recent_work()[0]['entry_id'],old_id)
        self.command('show q');self.command('1')
        self.assertEqual(self.approval.request.call_count,3)
        self.assertEqual(len(self.memory.recent_work()),1)
        self.assertEqual(self.adapter.executor.launch_count,3)
    def test_simple_menu_and_diagnostics(self):
        self.command('open portfolio in vs code')
        plain=self.command('show q').data['message']
        self.assertIn('[1] portfolio — VS Code',plain)
        for text in ('Summary:','Activity type:','Alternative:','Status:'): self.assertNotIn(text,plain)
        self.assertIn('Window not verified',self.command('show q diagnostics').data['message'])
    def test_historical_alias_merge_keeps_id_and_archives_original(self):
        path=self.home/'Downloads';info=path.stat()
        old=RecentWorkQueue.activity('open_folder',{'folder_id':'downloads'},'files',path,(info.st_dev,info.st_ino),version=2)
        self.memory.record_recent_work({**old,'launch_status':'launch_accepted'})
        saved=self.memory.recent_work()[0]
        self.command('open downloads');new=self.memory.recent_work()[0]
        self.assertEqual(new['entry_id'],saved['entry_id']);self.assertEqual(len(self.memory.recent_work()),1)
        with self.memory._database.transaction() as db:
            archive=json.loads(db.execute('SELECT metadata FROM recent_work_legacy_archive').fetchone()[0])
        self.assertEqual(archive,saved)
    def test_legacy_default_browser_normalization_preserves_original(self):
        path=self.home/'Downloads';info=path.stat()
        legacy=RecentWorkQueue.activity('navigate_browser',{'folder_id':'downloads'},'friday_browser',path,(info.st_dev,info.st_ino),version=3)
        self.memory.record_recent_work({**legacy,'launch_status':'navigation_confirmed'})
        saved=self.memory.recent_work()[0]
        self.command('open downloads')
        rows=self.memory.recent_work();self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['entry_id'],saved['entry_id']);self.assertEqual(rows[0]['application_id'],'files')
        self.adapter.recent.decode(rows[0])
        with self.memory._database.transaction() as db:
            archived=json.loads(db.execute('SELECT metadata FROM recent_work_legacy_archive').fetchone()[0])
        self.assertEqual(archived,saved)
    def test_scope_replacement_refused_even_when_target_inode_is_same(self):
        self.command('open portfolio')
        self.project.rename(self.home/'old_project');self.project.mkdir(parents=True)
        (self.home/'old_project/portfolio').rename(self.portfolio)
        self.assertEqual(self.command('2').data['status'],'unavailable');self.process.assert_not_called()
    def test_old_duplicates_cannot_evict_third_distinct_activity(self):
        old=RecentWorkQueue.activity('launch_application',{'application_id':'firefox'},'firefox',None,None,version=2)
        self.memory.record_recent_work({**old,'launch_status':'launch_accepted'})
        path=self.home/'Downloads';info=path.stat()
        for op,app,version,status in [('open_folder','files',2,'launch_accepted'),('navigate_browser','friday_browser',3,'navigation_confirmed')]:
            old=RecentWorkQueue.activity(op,{'folder_id':'downloads'},app,path,(info.st_dev,info.st_ino),version=version)
            self.memory.record_recent_work({**old,'launch_status':status})
        self.command('open documents')
        rows=self.adapter.recent.rows()
        self.assertEqual(len(rows),3)
        self.assertEqual([row['application_id'] for row in rows],['files','friday_browser','firefox'])
        self.assertEqual(len(self.memory.recent_work()),3)
    def test_search_depth_is_bounded(self):
        (self.project/'a/b/c/portfolio').mkdir(parents=True)
        matches,_=self.discovery.search('portfolio',(self.project,))
        self.assertEqual([row['path'] for row in matches],[str(self.portfolio)])
    def test_regular_file_only_editor_choice_no_content_read(self):
        item=self.project/'notes';item.write_text('PRIVATE_FILE_BODY')
        result=self.command('open notes')
        self.assertIn('[1] VS Code',result.data['message']);self.assertNotIn('Ubuntu Files',result.data['message'])
        self.assertNotIn('PRIVATE_FILE_BODY',result.data['message'])
    def test_time_budget_excludes_permission_wait(self):
        (self.home/'Downloads/portfolio').mkdir()
        clock=[0.0]
        def approval(_): clock[0]=20.0;return FolderDecision.ALLOW_ONCE
        self.approval.request.side_effect=approval
        with patch('friday.tools.discovery.time.monotonic',side_effect=lambda:clock[0]):
            matches,truncated=self.discovery.search('portfolio',(self.home/'Downloads',))
        self.assertEqual(len(matches),1);self.assertFalse(truncated)
