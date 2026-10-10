"""Managed browser regressions: fake renderer, real approvals/paths/SQLite."""
from contextlib import contextmanager,closing
import hashlib
import json
import io
from dataclasses import replace
from pathlib import Path
import socket
import sqlite3
from unittest.mock import Mock,patch

from test_desktop import DesktopFixture
from friday.desktop.browser import ManagedBrowser,BrowserTransport,BrowserHealthUnavailable,MAX_HISTORY,WORKER_SHA256
from friday.desktop.browser_worker import validate_command,MAX_PACKET
from friday.desktop.routing import DesktopIntentResolver
from friday.desktop.registry import Application,ApplicationRegistry
from friday.memory import MemoryManager
from friday.memory.database import _SCHEMA,MemoryStorageError
from friday.tools import ToolRequest
from friday.tools.access import FolderDecision,FilesystemAccess
from friday.tools.files import register_file_tools
from friday.tools.filesystem import FileSystemPolicy
from friday.tools.grants import PermissionStore
from friday.tools.router import ToolRouter
from friday.tools.sensitive import SensitivePaths


class Renderer:
    def __init__(self): self.running=False;self.starts=0;self.requests=[];self.fail=False;self.prepared=0
    @contextmanager
    def reviewed_launch(self): self.prepared+=1;yield 'reviewed'
    def alive(self): return self.running
    def start(self,prepared,environment):
        if self.running: raise ValueError('Duplicate renderer.')
        self.running=True;self.starts+=1
    def request(self,op,**fields):
        validate_command({'id':len(self.requests)+1,'op':op,**fields})
        if self.fail or not self.running: raise OSError('Closed renderer.')
        self.requests.append((op,fields))
    def failed(self): pass
    @property
    def current(self): return self.requests[-1][1].get("location") if self.requests else None
    def diagnostics(self): return {"process_state":"running" if self.running else "absent","events":[]}
    def close(self): self.running=False


class ManagedBrowserTests(DesktopFixture):
    def setUp(self):
        super().setUp()
        self.renderer=Renderer();self.adapter.browser=ManagedBrowser(self.renderer)
        self.router=ToolRouter(self.project,desktop_resolver=DesktopIntentResolver(self.apps,self.adapter.recent,self.adapter.browser))
        boundary=FileSystemPolicy([self.project],sensitive_paths=SensitivePaths())
        store=PermissionStore(self.root/'private/grants.json')
        self.manager.filesystem_access=FilesystemAccess(boundary,store,self.approval)
        register_file_tools(self.registry,boundary)
        self.adapter.list_contents=lambda request:self.manager.execute(request,persist_metadata=False)

    def command(self,text):
        route=self.router.route(text)
        return self.invoke(route.tool_name,dict(route.arguments))

    def test_home_downloads_documents_one_window_and_budget(self):
        for command in ('open friday browser','open downloads in friday browser','open documents in friday browser'):
            self.assertEqual(self.command(command).data['status'],'navigation_confirmed')
        self.assertEqual(self.renderer.starts,1)
        self.assertEqual(self.adapter.executor.launch_count,1)
        self.assertEqual([item[1]['location'] for item in self.renderer.requests],
                         [str(self.home),str(self.home/'Downloads'),str(self.home/'Documents')])
        self.assertEqual([call.args[0].operation for call in self.approval.request.call_args_list],
                         ['launch_browser','navigate_browser','navigate_browser','navigate_browser'])
        self.process.assert_not_called()

    def test_back_forward_confirm_then_commit_history_and_q(self):
        for command in ('open friday browser','open downloads in friday browser','open documents in friday browser','go back','go back','go forward'):
            self.assertEqual(self.command(command).data['status'],'navigation_confirmed')
        self.assertEqual(self.renderer.requests[-1][1]['location'],str(self.home/'Downloads'))
        self.assertEqual(len(self.adapter.browser.history),3)
        self.assertEqual(self.adapter.browser.cursor,1)
        self.assertEqual(self.renderer.starts,1)
        self.assertEqual(self.memory.recent_work()[0]['title'],'Downloads folder')

    def test_no_backward_or_forward_history_does_not_prompt(self):
        self.command('open friday browser');before=self.approval.request.call_count
        self.assertEqual(self.command('go back').data['status'],'no_history')
        self.assertEqual(self.command('go forward').data['status'],'no_history')
        self.assertEqual(self.approval.request.call_count,before)

    def test_repeated_location_keeps_single_window_and_history_and_q_id(self):
        self.command('open friday browser');saved=self.memory.recent_work()[0]
        self.command('open friday browser')
        self.assertEqual(self.renderer.starts,1);self.assertEqual(len(self.adapter.browser.history),1)
        self.assertEqual(self.memory.recent_work()[0]['entry_id'],saved['entry_id'])
        self.assertEqual(self.approval.request.call_count,3)

    def test_closed_window_reopens_with_two_fresh_approvals(self):
        self.command('open friday browser');self.renderer.running=False
        self.command('open downloads in friday browser')
        self.assertEqual(self.renderer.starts,2);self.assertEqual(self.adapter.executor.launch_count,2)
        self.assertEqual(self.approval.request.call_count,4)

    def test_launch_denied_no_navigation_approval_or_process(self):
        self.approval.request.return_value=FolderDecision.DENY
        self.assertFalse(self.command('open friday browser').success)
        self.assertEqual(self.approval.request.call_count,1)
        self.assertEqual(self.renderer.starts,0);self.assertEqual(self.memory.recent_work(),())

    def test_navigation_denied_after_launch_approval_no_process_started(self):
        self.approval.request.side_effect=[FolderDecision.ALLOW_ONCE,FolderDecision.DENY]
        self.assertFalse(self.command('open friday browser').success)
        self.assertEqual(self.renderer.starts,0);self.assertEqual(self.adapter.executor.launch_count,0)
        self.assertEqual(self.adapter.browser.history,[])

    def test_existing_navigation_denied_no_history_q_refresh(self):
        self.command('open friday browser');before=self.memory.recent_work()
        self.approval.request.return_value=FolderDecision.DENY
        self.assertFalse(self.command('open downloads in friday browser').success)
        self.assertEqual(self.memory.recent_work(),before)
        self.assertEqual(len(self.renderer.requests),1)

    def test_persistent_desktop_choice_not_accepted(self):
        self.approval.request.return_value=FolderDecision.ALLOW_PERSISTENT
        self.assertFalse(self.command('open friday browser').success);self.assertEqual(self.renderer.starts,0)

    def test_failure_no_history_or_q_but_real_start_counts(self):
        self.renderer.fail=True
        self.assertEqual(self.command('open friday browser').data['status'],'browser_failed')
        self.assertEqual(self.adapter.executor.launch_count,1)
        self.assertEqual(self.adapter.browser.history,[]);self.assertEqual(self.memory.recent_work(),())
        self.assertTrue(self.renderer.running)

    def test_existing_window_failure_preserves_previous_history_and_q(self):
        self.command('open friday browser');before=self.memory.recent_work();self.renderer.fail=True
        self.assertEqual(self.command('open downloads in friday browser').data['status'],'browser_failed')
        self.assertEqual(self.memory.recent_work(),before);self.assertEqual(self.adapter.browser.cursor,0)

    def test_invalid_symlink_and_unregistered_paths_rejected(self):
        for alias in ('../Downloads','/etc','project_unknown'):
            self.assertNotEqual(self.invoke('navigate_browser',{'folder_id':alias}).data['status'],'navigation_confirmed')
        (self.home/'Downloads').rmdir();(self.home/'Downloads').symlink_to(self.project)
        self.assertNotEqual(self.command('open downloads in friday browser').data['status'],'navigation_confirmed')
        self.assertEqual(self.renderer.starts,0);self.approval.request.assert_not_called()

    def test_target_swapped_during_approval_is_rejected(self):
        def swap(approval):
            if approval.operation=='navigate_browser':
                folder=self.home/'Downloads';folder.rename(self.home/'OldDownloads');folder.mkdir()
            return FolderDecision.ALLOW_ONCE
        self.approval.request.side_effect=swap
        self.assertFalse(self.command('open downloads in friday browser').success)
        self.assertEqual(self.renderer.starts,0)

    def test_stale_back_target_revalidated(self):
        self.command('open friday browser');self.command('open downloads in friday browser')
        home=self.home;home.rename(self.root/'OldHome');home.mkdir()
        before=self.approval.request.call_count
        self.assertEqual(self.command('go back').data['status'],'invalid_target')
        self.assertEqual(self.approval.request.call_count,before)

    def test_history_bounded_forward_branch_discarded(self):
        browser=self.adapter.browser
        for i in range(40):browser.commit({'folder_id':'home','path':'/fixture/'+str(i),'identity':[1,i]})
        self.assertEqual(len(browser.history),MAX_HISTORY)
        browser.commit(browser.history[-2],len(browser.history)-2)
        browser.commit({'folder_id':'documents','path':'/other','identity':[2,1]})
        with self.assertRaises(ValueError):browser.history_target('forward')

    def test_navigation_continues_at_limit_but_reopen_does_not(self):
        self.command('open friday browser');self.adapter.executor.launch_count=4
        self.assertEqual(self.command('open downloads in friday browser').data['status'],'navigation_confirmed')
        self.renderer.running=False;before=self.approval.request.call_count
        self.assertEqual(self.command('open documents in friday browser').data['status'],'launch_limit_reached')
        self.assertEqual(self.approval.request.call_count,before);self.assertEqual(self.renderer.starts,1)

    def test_q_three_slots_repeat_persistence_resume_fresh_approval(self):
        for text in ('open friday browser','open downloads in friday browser','open documents in friday browser','open downloads in friday browser'):
            self.command(text)
        rows=self.memory.recent_work();self.assertEqual(len(rows),3)
        self.assertEqual(rows[0]['launch_status'],'navigation_confirmed')
        self.assertEqual(rows[0]['application_id'],'friday_browser')
        self.assertIn('Managed location confirmed',self.adapter.recent.show(detailed=True))
        with MemoryManager(self.root/'memory.db') as reopened:self.assertEqual(reopened.recent_work(),rows)
        before=self.approval.request.call_count
        self.command('show Q');self.assertEqual(self.command('1').data['status'],'navigation_confirmed')
        self.assertEqual(self.approval.request.call_count,before+1)
        self.assertEqual(self.renderer.starts,1)

    def test_resume_directory_identity_changed_rejected(self):
        self.command('open downloads in friday browser');saved=self.memory.recent_work()[0]
        folder=self.home/'Downloads';folder.rename(self.home/'OldDownloads');folder.mkdir()
        self.assertEqual(self.invoke('resume_activity',{'entry_id':saved['entry_id']}).data['status'],'invalid_target')
        self.assertEqual(self.renderer.starts,1)

    def test_navigation_never_scans_or_opens_contents(self):
        with patch('os.scandir') as scan:
            self.command('open friday browser');self.command('open downloads in friday browser')
        scan.assert_not_called()
        self.assertFalse((self.root/'private/grants.json').exists())
        self.assertEqual(self.memory.get_recent_messages(100),[])
        self.assertEqual([op for op,_ in self.renderer.requests],['navigate','navigate'])

    def test_contents_separate_exact_filesystem_permission_and_no_file_read(self):
        (self.home/'Downloads'/'notes.txt').write_text('must never be read')
        self.command('open downloads in friday browser');before=self.approval.request.call_count
        self.command('list browser contents')
        self.assertEqual(self.approval.request.call_count,before+1)
        permission=self.approval.request.call_args.args[0]
        self.assertEqual(permission.operation,'list_directory');self.assertEqual(permission.target,self.home/'Downloads')
        self.assertEqual(self.renderer.requests[-1][0],'contents')
        self.assertIn('notes.txt',str(self.renderer.requests[-1]))
        self.assertNotIn('must never be read',str(self.renderer.requests[-1]))
        self.assertFalse((self.root/'private/grants.json').exists())

    def test_listing_denial_leaves_gui_contents_hidden_and_q_unchanged(self):
        self.command('open downloads in friday browser');before=self.memory.recent_work()
        self.approval.request.return_value=FolderDecision.DENY
        self.assertEqual(self.command('list browser contents').data['status'],'listing_denied')
        self.assertEqual([op for op,_ in self.renderer.requests],['navigate'])
        self.assertEqual(self.memory.recent_work(),before)

    def test_home_navigation_does_not_bypass_home_read_restriction(self):
        self.command('open friday browser')
        self.assertEqual(self.command('list browser contents').data['status'],'listing_denied')
        self.assertEqual(len(self.renderer.requests),1)

    def test_project_and_ubuntu_compatibility_routes(self):
        self.command('open my friday project folder in friday browser')
        self.assertEqual(self.renderer.requests[-1][1]['location'],str(self.project))
        self.assertEqual(self.router.route('open my friday project').tool_name,'open_project')
        self.assertEqual(self.router.route('open ubuntu files').tool_name,'launch_application')
        self.assertEqual(self.router.route('open downloads in ubuntu files').tool_name,'open_folder')
        self.assertEqual(self.router.route('list downloads').tool_name,'list_directory')

    def test_no_arbitrary_execution_and_worker_cannot_authorize(self):
        for args in ({'folder_id':'home','command':'sh'}, {'folder_id':'home','flags':'--anything'}):
            self.assertFalse(self.invoke('navigate_browser',args).success)
        for text in ('open files && echo x','open downloads --new-window'):
            self.assertIsNone(self.router.route(text).tool_name)
        self.renderer.request('navigate',location='/safe') if self.renderer.running else None
        with self.assertRaises(PermissionError):self.adapter.execute('navigate_browser',{'folder_id':'home'})
        self.process.assert_not_called()

    def test_voice_navigation_excluded_from_q(self):
        result=self.invoke('navigate_browser',{'folder_id':'downloads'},persist_metadata=False)
        self.assertEqual(result.data['status'],'navigation_confirmed')
        self.assertEqual(self.memory.recent_work(),())

    def test_fourth_browser_location_evicts_oldest_without_another_launch(self):
        for text in ('open friday browser','open downloads in friday browser','open documents in friday browser','open my friday project folder in friday browser'):
            self.command(text)
        self.assertEqual([row['title'] for row in self.memory.recent_work()],
                         ['FRIDAY project folder','Documents folder','Downloads folder'])
        self.assertEqual(self.renderer.starts,1)

    def test_restart_resume_needs_new_launch_and_navigation_approval(self):
        self.command('open downloads in friday browser');saved=self.memory.recent_work()[0]
        self.adapter.browser.close()
        self.adapter.browser=ManagedBrowser(self.renderer)
        before=self.approval.request.call_count
        self.invoke('resume_activity',{'entry_id':saved['entry_id']})
        self.assertEqual(self.approval.request.call_count,before+2)
        self.assertEqual(self.renderer.starts,2)
        self.assertEqual(self.memory.recent_work()[0]['entry_id'],saved['entry_id'])

    def test_actual_cli_command_permission_navigation_q_sequence_no_gui(self):
        from friday.config.settings import settings
        from friday.main import main
        config=replace(settings,project_root=self.project,database_path=self.root/'cli.db',
                       filesystem_permission_store_path=self.root/'private/grants.json')
        output=io.StringIO();renderer=Renderer()
        inputs=['open friday browser','1','1','open downloads in friday browser','1','open documents in friday browser','1','go back','1','go back','1',
                'go forward','1','Show Q diagnostics','1','1','quit']
        with patch('friday.main.settings',config),patch('friday.main.OllamaProvider') as provider,\
             patch('friday.desktop.browser.BrowserTransport',return_value=renderer),\
             patch('builtins.input',side_effect=inputs),patch('sys.stdout',output),\
             patch('sys.stdin.isatty',return_value=True),patch.object(output,'isatty',return_value=True):
            main(adaptive=True,speech_backend=Mock())
        text=output.getvalue()
        self.assertEqual(renderer.starts,1)
        self.assertEqual(text.count('Operation: launch_browser'),1)
        self.assertEqual(text.count('Operation: navigate_browser'),7)
        self.assertIn('Managed location confirmed',text)
        self.process.assert_not_called();provider.return_value.chat.assert_not_called()
        with MemoryManager(config.database_path) as memory:
            self.assertEqual(len(memory.recent_work()),3)

    def test_failed_backward_navigation_does_not_move_history_cursor(self):
        self.command('open friday browser');self.command('open downloads in friday browser');before=self.memory.recent_work()
        self.renderer.fail=True
        self.assertEqual(self.command('go back').data['status'],'browser_failed')
        self.assertEqual(self.adapter.browser.cursor,1)
        self.assertEqual(self.memory.recent_work(),before)

    def test_gui_rows_escape_terminal_controls_and_do_not_follow_symlink(self):
        directory=self.home/'Downloads'
        (directory/'\x1b[2J.txt').write_text('secret body')
        (directory/'link').symlink_to(self.project)
        self.command('open downloads in friday browser');self.command('list browser contents')
        rows=self.renderer.requests[-1][1]['rows']
        self.assertTrue(all('\x1b' not in row for row in rows))
        self.assertIn('link [symlink]',rows)


class BrowserTransportTests(DesktopFixture):
    def transport(self):
        entry=Application('browser_runtime','runtime',(),(self.paths['vscode'],),'')
        apps=ApplicationRegistry((entry,),trusted_root=self.app_root,trusted_uid=self.apps.uid)
        return BrowserTransport(apps,profile_root=self.project/'data/browser-profiles')

    def test_reviewed_source_hash_and_isolated_pinned_interpreter_private_ipc(self):
        transport=self.transport();self.child.stderr=None
        self.assertEqual(hashlib.sha256(Path('friday/desktop/browser_worker.py').read_bytes()).hexdigest(),WORKER_SHA256)
        with transport.reviewed_launch() as prepared:transport.start(prepared,{'PATH':'/usr/bin:/bin'})
        argv=self.process.call_args.args[0];options=self.process.call_args.kwargs
        self.assertEqual(argv[1:4],['-I','-B','-c'])
        self.assertEqual(argv[4],Path('friday/desktop/browser_worker.py').read_text())
        self.assertTrue(options['executable'].startswith('/proc/self/fd/'))
        self.assertFalse(options.get('shell',False));self.assertEqual(len(options['pass_fds']),3)
        self.assertEqual(options['env']['GIO_USE_VFS'],'local')
        self.assertEqual(options['env']['GSETTINGS_BACKEND'],'memory')
        self.assertTrue(options['env']['HOME'].startswith('/proc/self/fd/'))
        self.assertEqual(options['env']['HOME'],options['env']['XDG_CONFIG_HOME'])
        self.assertEqual(transport.channel.family,socket.AF_UNIX)
        self.assertEqual(transport.channel.type,socket.SOCK_SEQPACKET)
        transport.close()

    def test_untrusted_interpreter_rejected_before_process(self):
        self.paths['vscode'].chmod(0o777)
        with self.assertRaises(FileNotFoundError):
            with self.transport().reviewed_launch():pass
        self.process.assert_not_called()

    def test_unreviewed_source_rejected(self):
        with patch('friday.desktop.browser.WORKER_SHA256','invalid'):
            with self.assertRaises(ValueError):
                with self.transport().reviewed_launch():pass
        self.process.assert_not_called()

    def test_changed_interpreter_rejected_before_start(self):
        transport=self.transport()
        with transport.reviewed_launch() as prepared:
            self.paths['vscode'].write_bytes(b'\x7fELFchanged')
            with self.assertRaises(ValueError):transport.start(prepared,{})
        self.process.assert_not_called()

    def test_unauthorized_ipc_operations_fields_and_replays_rejected(self):
        for value in ({'id':1,'op':'read','path':'/etc/passwd'}, {'id':1,'op':'navigate','location':'/safe','shell':'x'},
                      {'id':True,'op':'ping'}, {'id':0,'op':'ping'}, {'id':1,'op':'contents','location':'/safe','rows':['\x1b[2J']}):
            with self.assertRaises(ValueError):validate_command(value)
        for operation in ('open_file','write','spawn','list'):
            with self.assertRaises(ValueError):validate_command({'id':1,'op':operation})
        with self.assertRaises(ValueError):validate_command({'id':1,'op':'ping'},previous_id=1)

    def test_unverified_response_rejected_no_location_commit(self):
        transport=self.transport();transport.child=Mock();transport.child.stderr=None;transport.child.poll.return_value=None
        transport.channel=Mock()
        correct={'id':1,'op':'navigate','window':'managed','location':'/safe','mapped':True}
        for override in ({'id':2},{'id':True},{'op':'read'},{'location':'/other'},{'mapped':False},{'window':'nautilus'}):
            transport.sequence=0;transport.broken=False;transport.pending_command=None;transport.channel.recv.return_value=json.dumps({**correct,**override}).encode()
            with self.assertRaises(ValueError):transport.request('navigate',location='/safe')
            self.assertIsNone(transport.current)
        transport.broken=False;transport.pending_command=None
        transport.channel.recv.return_value=b'x'*(MAX_PACKET+1)
        with self.assertRaises(ValueError):transport.request('navigate',location='/safe')

    def test_verified_response_commits_location_and_health_checks_exact_window(self):
        transport=self.transport();transport.child=Mock();transport.child.stderr=None;transport.child.poll.return_value=None;transport.channel=Mock()
        transport.channel.recv.return_value=json.dumps({'id':1,'op':'navigate','window':'managed','location':'/safe','mapped':True}).encode()
        transport.request('navigate',location='/safe');self.assertEqual(transport.current,'/safe')
        transport.channel.recv.return_value=json.dumps({'id':2,'op':'ping','window':'managed','location':'/safe','mapped':True}).encode()
        self.assertTrue(transport.alive())

    def test_closed_channel_reaped_before_reopen(self):
        transport=self.transport();transport.child=Mock();child=transport.child
        child.poll.return_value=None;child.stderr=None;transport.channel=Mock();transport.channel.recv.return_value=b''
        with self.assertRaises(BrowserHealthUnavailable):transport.alive()
        child.terminate.assert_not_called();child.wait.assert_not_called()
        self.assertIs(transport.child,child)

    def test_old_sqlite_queue_constraint_migrates_without_losing_stable_entries(self):
        path=self.root/'old.db'
        self.invoke('launch_application',{'application_id':'firefox'})
        row=self.memory.recent_work()[0]
        old_sql=_SCHEMA[_SCHEMA.index('CREATE TABLE IF NOT EXISTS recent_work'):].replace(", 'navigation_confirmed'",'')
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(old_sql)
            fields=list(row);db.execute('INSERT INTO recent_work ('+','.join(fields)+') VALUES ('+','.join('?' for _ in fields)+')',[row[k] for k in fields])
        with MemoryManager(path) as reopened:self.assertEqual(reopened.recent_work()[0],row)
        with closing(sqlite3.connect(path)) as db, db:
            self.assertIn('navigation_confirmed',db.execute("SELECT sql FROM sqlite_master WHERE name='recent_work'").fetchone()[0])

    def test_unknown_schema_objects_fail_closed_without_partial_migration(self):
        path=self.root/'old.db';old_sql=_SCHEMA[_SCHEMA.index('CREATE TABLE IF NOT EXISTS recent_work'):].replace(", 'navigation_confirmed'",'')
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(old_sql);db.execute('CREATE TRIGGER custom BEFORE DELETE ON recent_work BEGIN SELECT 1; END')
        with self.assertRaises(MemoryStorageError):MemoryManager(path)
        with closing(sqlite3.connect(path)) as db, db:
            self.assertNotIn('navigation_confirmed',db.execute("SELECT sql FROM sqlite_master WHERE name='recent_work'").fetchone()[0])
            self.assertIsNone(db.execute("SELECT 1 FROM sqlite_master WHERE name='recent_work_before_browser'").fetchone())
