"""Phase 7A headless fixtures; every launch mocked, no real GUI/audio access."""
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime,timezone
import io
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock,patch

from friday.config.settings import settings
from friday.core.assistant import FridayAssistant
from friday.desktop.registry import Application,ApplicationRegistry
from friday.desktop.routing import DesktopIntentResolver,DESKTOP_TOOLS
from friday.desktop.runtime import (DesktopPermissionAdapter,DesktopExecutor,DesktopApproval,
                                   desktop_environment,register_desktop_tools)
from friday.desktop.sessions import DesktopSessionStore,yesterday_window
from friday.memory import MemoryManager
from friday.providers.base import ModelProvider
from friday.tools import ToolRegistry,ToolManager,ToolRequest,ToolStatus,RiskPermissionPolicy,PermissionDecision,RiskLevel
from friday.tools.access import CLIFileApproval,FolderDecision
from friday.tools.router import ToolRouter
from friday.tools.sensitive import SensitivePaths
from friday.voice.tts import automatic_speech_allowed


class DesktopFixture(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.home=self.root/'home';self.home.mkdir()
        self.project=self.home/'Projects/FRIDAY';self.project.mkdir(parents=True)
        for name in ('Downloads','Documents'): (self.home/name).mkdir()
        self.app_root=self.root/'native';self.app_root.mkdir(mode=0o700)
        self.paths={}
        entries=[]
        for identity,aliases in [('vscode',('vs code','visual studio code','code')),('files',('files','ubuntu files','file manager')),('firefox',('firefox',))]:
            path=self.app_root/identity;path.write_bytes(b'\x7fELFfixture');path.chmod(0o700);self.paths[identity]=path
            entries.append(Application(identity,identity,aliases,(path,),identity+'.desktop'))
        self.apps=ApplicationRegistry(tuple(entries),trusted_root=self.app_root,trusted_uid=os.getuid())
        self.memory=MemoryManager(self.root/'memory.db');self.addCleanup(self.memory.close)
        self.approval=Mock(spec=CLIFileApproval);self.approval.request.return_value=FolderDecision.ALLOW_ONCE
        from friday.desktop.firefox_url_handoff import UnavailableFirefoxUrlAdapter
        self.adapter=DesktopPermissionAdapter(project_root=self.project,sensitive=SensitivePaths(),approval=self.approval,
                                              memory=self.memory,applications=self.apps,
                                              firefox_url_adapter=UnavailableFirefoxUrlAdapter())
        self.addCleanup(self.adapter.close)
        self.registry=ToolRegistry();register_desktop_tools(self.registry,self.adapter)
        self.manager=ToolManager(self.registry,desktop_access=self.adapter)
        self.router=ToolRouter(self.project,desktop_resolver=DesktopIntentResolver(self.apps))
        self.env=patch.dict(os.environ,{'XDG_SESSION_TYPE':'x11','DISPLAY':':0','XDG_CONFIG_HOME':str(self.home/'.config')},clear=True)
        self.env.start();self.addCleanup(self.env.stop)
        self.home_patch=patch('pathlib.Path.home',return_value=self.home);self.home_patch.start();self.addCleanup(self.home_patch.stop)
        self.child=Mock();self.child.wait.return_value=0;self.child.poll.return_value=0
        self.process=patch('friday.desktop.runtime.subprocess.Popen',return_value=self.child).start()
        self.addCleanup(patch.stopall)
    def invoke(self,name='launch_application',arguments=None,**kwargs):
        return self.manager.execute(ToolRequest(name,arguments if arguments is not None else {'application_id':'vscode'}),**kwargs)
    def seed(self,project_id='friday',path=None,status='launch_accepted',stamp=None):
        path=path or self.project;info=path.stat()
        start,end=yesterday_window()
        self.memory.record_project_interaction(project_id,str(path),(info.st_dev,info.st_ino),'vscode',status,
                                              opened_at=stamp or start)
    def assistant(self,adaptive=True):
        provider=Mock(spec=ModelProvider);provider.chat.return_value='Ordinary answer'
        provider.supports_inference_profiles=True;provider.inference_profile=Mock(side_effect=lambda _:nullcontext())
        assistant=FridayAssistant(provider,'System',tool_manager=self.manager,tool_router=self.router,memory=self.memory,
                                 workload_configuration=replace(settings,adaptive_workloads=adaptive))
        self.addCleanup(assistant.end_session);self.addCleanup(assistant.model_manager.close)
        return assistant,provider


class RegistryTests(DesktopFixture):
    def test_explicit_initial_registry(self):
        self.assertEqual(set(ApplicationRegistry().entries),{'vscode','files','firefox'})
    def test_aliases_exact(self):
        for alias in ('vs code','VS Code','visual studio code','code'): self.assertEqual(self.apps.resolve(alias),'vscode')
        self.assertIsNone(self.apps.resolve('vscode --disable-sandbox'));self.assertIsNone(self.apps.resolve('cod'))
    def test_availability_checks_do_not_launch(self):
        self.assertTrue(self.apps.availability('vscode'));self.process.assert_not_called()
    def test_missing_application(self):
        self.paths['vscode'].unlink();result=self.invoke()
        self.assertEqual(result.data['status'],'unavailable');self.approval.request.assert_not_called();self.process.assert_not_called()
    def test_non_native_wrapper_refused(self):
        self.paths['vscode'].write_bytes(b'#!/bin/sh\necho no')
        self.assertFalse(self.apps.availability('vscode'));self.process.assert_not_called()
    def test_group_writable_executable_refused(self):
        self.paths['vscode'].chmod(0o720);self.assertFalse(self.apps.availability('vscode'))
    def test_untrusted_owner_refused(self):
        apps=ApplicationRegistry(tuple(self.apps.entries.values()),trusted_root=self.app_root,trusted_uid=os.getuid()+1)
        self.assertFalse(apps.availability('vscode'))
    def test_ambiguous_alias_refused(self):
        entries=tuple(self.apps.entries.values())+(Application('other','other',('code',),(self.paths['vscode'],),'other.desktop'),)
        apps=ApplicationRegistry(entries,trusted_root=self.app_root,trusted_uid=os.getuid())
        self.assertIsNone(apps.resolve('code'))
    def test_registry_is_immutable(self):
        with self.assertRaises(TypeError): self.apps.entries['other']=self.apps.entries['vscode']
    def test_user_desktop_file_is_never_read(self):
        folder=self.home/'.local/share/applications';folder.mkdir(parents=True)
        (folder/'code.desktop').write_text('[Desktop Entry]\nExec=touch /tmp/forbidden\n')
        self.assertTrue(self.apps.availability('vscode'));self.process.assert_not_called()


class PermissionTests(DesktopFixture):
    def test_exact_approval_required(self):
        result=self.invoke();self.assertEqual(result.data['status'],'launch_accepted')
        approval=self.approval.request.call_args.args[0]
        self.assertEqual(approval.operation,'launch_application');self.assertEqual(approval.risk,'execute')
        self.assertIn('Intended side effect:',approval.prompt());self.assertNotIn('[2]',approval.prompt())
    def test_denied_permission_no_launch(self):
        self.approval.request.return_value=FolderDecision.DENY
        result=self.invoke();self.assertFalse(result.success);self.process.assert_not_called()
    def test_always_allow_does_not_authorize_desktop(self):
        self.approval.request.return_value=FolderDecision.ALLOW_PERSISTENT
        self.assertFalse(self.invoke().success);self.process.assert_not_called()
    def test_allow_once_expires(self):
        self.approval.request.side_effect=[FolderDecision.ALLOW_ONCE,FolderDecision.DENY]
        self.assertTrue(self.invoke().success);self.assertFalse(self.invoke().success);self.assertEqual(self.process.call_count,1)
    def test_risk_override_cannot_bypass_typed_approval(self):
        self.manager.policy=RiskPermissionPolicy({RiskLevel.EXECUTE:PermissionDecision.ALLOW})
        self.approval.request.return_value=FolderDecision.DENY
        self.assertFalse(self.invoke().success);self.process.assert_not_called()
    def test_policy_deny_prevents_even_approval(self):
        self.manager.policy=RiskPermissionPolicy({RiskLevel.EXECUTE:PermissionDecision.DENY})
        self.assertEqual(self.invoke().status,ToolStatus.DENIED);self.approval.request.assert_not_called()
    def test_no_adapter_fails_closed(self):
        manager=ToolManager(self.registry)
        self.assertEqual(manager.execute(ToolRequest('launch_application',{'application_id':'vscode'})).status,ToolStatus.APPROVAL_REQUIRED)
        self.process.assert_not_called()
    def test_direct_tool_execution_without_lease_denied(self):
        with self.assertRaises(PermissionError): self.registry.get('launch_application').tool.execute({'application_id':'vscode'})
    def test_spoken_or_model_label_cannot_approve(self):
        self.approval.request.return_value='allow_once'
        self.assertFalse(self.invoke().success);self.process.assert_not_called()
    def test_noninteractive_cli_denies(self):
        with patch('sys.stdin.isatty',return_value=False),patch('builtins.input') as read:
            self.assertEqual(CLIFileApproval().request(DesktopApproval('open_folder','fixture','open','execute')),FolderDecision.DENY)
        read.assert_not_called()
    def test_binary_substitution_after_prompt_refused(self):
        def replace_binary(_):
            self.paths['vscode'].rename(self.app_root/'old');self.paths['vscode'].write_bytes(b'\x7fELFnew');self.paths['vscode'].chmod(0o700)
            return FolderDecision.ALLOW_ONCE
        self.approval.request.side_effect=replace_binary
        self.assertFalse(self.invoke().success);self.process.assert_not_called()
    def test_deny_on_approval_exception(self):
        self.approval.request.side_effect=RuntimeError('PRIVATE')
        result=self.invoke();self.assertFalse(result.success);self.assertNotIn('PRIVATE',result.error)


class ExecutionTests(DesktopFixture):
    def test_fixed_argument_array_no_shell_or_sensitive_environment(self):
        with patch.dict(os.environ,{'LD_PRELOAD':'PRIVATE','NODE_OPTIONS':'PRIVATE','TOKEN':'PRIVATE'}): result=self.invoke()
        self.assertEqual(result.data['status'],'launch_accepted')
        args=self.process.call_args.args[0];options=self.process.call_args.kwargs
        self.assertIsInstance(args,list);self.assertNotIn('--disable-sandbox',args)
        self.assertFalse(options.get('shell',False));self.assertTrue(options['close_fds'])
        self.assertTrue(options['start_new_session']);self.assertEqual(options['cwd'],'/')
        self.assertNotIn('PRIVATE',str(options['env']));self.assertEqual(len(options['pass_fds']),2)
        self.assertTrue(options['executable'].startswith('/proc/self/fd/'))
    def test_project_directory_pinned_through_descriptor(self):
        target=self.project.stat()
        def launch(args,**options):
            self.project.rename(self.home/'MovedAfterApproval')
            self.project.mkdir()
            fd=options['pass_fds'][-1];info=os.fstat(fd)
            self.assertEqual((info.st_dev,info.st_ino),(target.st_dev,target.st_ino))
            self.assertEqual(args[-1],f'/proc/self/fd/{fd}')
            self.assertEqual(args[-2],'--');return self.child
        self.process.side_effect=launch
        self.assertEqual(self.invoke('open_project',{'project_id':'friday'}).data['status'],'launch_accepted')
    def test_launch_timeout_is_outcome_unverified_not_fake_success(self):
        self.child.wait.side_effect=subprocess.TimeoutExpired('app',1);self.child.poll.return_value=None
        result=self.invoke();self.assertEqual(result.data['status'],'launch_outcome_unverified')
        self.child.wait.assert_called_once_with(timeout=1)
    def test_launch_nonzero(self):
        self.child.wait.return_value=1
        self.assertEqual(self.invoke().data['status'],'launch_failed')
    def test_launch_oserror_redacted(self):
        self.process.side_effect=OSError('PRIVATE executable path')
        result=self.invoke();self.assertFalse(result.success);self.assertNotIn('PRIVATE',result.error)
    def test_launch_limit_bounded(self):
        for _ in range(4): self.assertEqual(self.invoke().data['status'],'launch_accepted')
        self.assertEqual(self.invoke().data['status'],'launch_limit_reached');self.assertEqual(self.process.call_count,4)
    def test_shutdown_does_not_terminate_approved_apps(self):
        self.child.wait.side_effect=subprocess.TimeoutExpired('app',1);self.child.poll.return_value=None
        self.invoke();self.adapter.close();self.child.kill.assert_not_called();self.child.terminate.assert_not_called()
    def test_private_profile_disables_automatic_tasks_and_extensions(self):
        self.invoke();args=self.process.call_args.args[0]
        self.assertTrue(args[args.index('--user-data-dir')+1].startswith('/proc/self/fd/'))
        profile=next(self.adapter.executor.profile_root.glob('code-*'))
        import json
        saved=json.loads((profile/'User/settings.json').read_text())
        self.assertEqual(saved['task.allowAutomaticTasks'],'off');self.assertTrue(saved['security.workspace.trust.enabled'])
        self.assertEqual(saved['files.hotExit'],'off');self.assertIn('--disable-extensions',args)
    def test_unapproved_argument_fields_rejected(self):
        result=self.invoke(arguments={'application_id':'vscode','flags':'--disable-sandbox'})
        self.assertEqual(result.status,ToolStatus.INVALID_ARGUMENTS);self.process.assert_not_called()


class FolderProjectTests(DesktopFixture):
    def test_downloads_and_documents_resolved(self):
        for alias in ('downloads','documents'):
            result=self.invoke('open_folder',{'folder_id':alias,'retry':alias=='documents'});self.assertEqual(result.data['status'],'launch_accepted')
            self.assertIn(str(self.home/alias.title()),self.approval.request.call_args.args[0].target)
    def test_xdg_folder_mapping_respected(self):
        config=self.home/'.config';config.mkdir();target=self.home/'Transfers';target.mkdir()
        (config/'user-dirs.dirs').write_text('XDG_DOWNLOAD_DIR="$HOME/Transfers"\n')
        self.invoke('open_folder',{'folder_id':'downloads'})
        self.assertIn(str(target),self.approval.request.call_args.args[0].target)
    def test_home_open_is_not_a_read_grant(self):
        self.assertEqual(self.invoke('open_folder',{'folder_id':'home'}).data['status'],'launch_accepted')
        self.assertEqual(self.approval.request.call_args.args[0].operation,'navigate_folder')
        self.assertEqual(self.memory.get_recent_messages(100),[])
    def test_missing_folder(self):
        (self.home/'Downloads').rmdir()
        self.assertEqual(self.invoke('open_folder',{'folder_id':'downloads'}).data['status'],'unavailable');self.process.assert_not_called()
    def test_symlink_folder(self):
        path=self.home/'Downloads';path.rmdir();path.symlink_to(self.project,target_is_directory=True)
        self.assertEqual(self.invoke('open_folder',{'folder_id':'downloads'}).data['status'],'unavailable');self.process.assert_not_called()
    def test_folder_substitution_at_prompt(self):
        def swap(_):
            path=self.home/'Downloads';path.rename(self.home/'Old');path.mkdir();return FolderDecision.ALLOW_ONCE
        self.approval.request.side_effect=swap
        self.assertFalse(self.invoke('open_folder',{'folder_id':'downloads'}).success);self.process.assert_not_called()
    def test_sensitive_xdg_folder_rejected(self):
        config=self.home/'.config';config.mkdir();(self.home/'.ssh').mkdir()
        (config/'user-dirs.dirs').write_text('XDG_DOWNLOAD_DIR="$HOME/.ssh"\n')
        self.assertEqual(self.invoke('open_folder',{'folder_id':'downloads'}).data['status'],'unavailable');self.process.assert_not_called()
    def test_project_registered_only(self):
        self.assertEqual(self.invoke('open_project',{'project_id':'arbitrary'}).data['status'],'unavailable');self.process.assert_not_called()
    def test_project_path_injection_is_not_lookup(self):
        self.assertEqual(self.invoke('open_project',{'project_id':'../../etc/shadow'}).data['status'],'unavailable');self.process.assert_not_called()
    def test_no_project_script_runs(self):
        (self.project/'setup.sh').write_text('touch /tmp/forbidden')
        self.invoke('open_project',{'project_id':'friday'})
        self.assertEqual(self.process.call_count,1);self.assertNotIn('setup.sh',str(self.process.call_args))
    def test_no_filesystem_grant_created(self):
        self.invoke('open_folder',{'folder_id':'downloads'})
        self.assertFalse(list(self.project.rglob('grants.json')))


class RoutingTests(DesktopFixture):
    def test_required_intents(self):
        phrases={'Open VS Code.':'launch_application','Launch Visual Studio Code.':'launch_application',
                 'Start Firefox.':'launch_application','Open my Downloads folder.':'open_folder',
                 'Open my Documents folder.':'open_folder','Open my home folder.':'open_folder',
                 'Open my FRIDAY project.':'open_project','Show running applications.':'inspect_running_applications',
                 "Resume yesterday's project.":'resume_project'}
        for phrase,name in phrases.items(): self.assertEqual(self.router.route(phrase).tool_name,name)
    def test_instructional_question_is_not_action(self):
        for phrase in ('How do I open VS Code?','Explain how to launch Firefox.'):
            self.assertFalse(self.router.route(phrase).matched)
        self.assertFalse(self.router.route('Start explaining Python.').matched)
    def test_malicious_requests_rejected_before_model(self):
        assistant,provider=self.assistant()
        phrases=['Open VS Code; rm -rf ~/Documents','Open Firefox && curl example.com',
                 'Open /bin/bash -c ...','Open ../../../etc/shadow','Launch an application named $(command)',
                 "Resume yesterday's project and run its setup script",'Open my project with --disable-sandbox']
        for phrase in phrases: self.assertIn('not supported',assistant.respond(phrase))
        provider.chat.assert_not_called();self.approval.request.assert_not_called();self.process.assert_not_called()
    def test_legacy_browsing_retained(self):
        self.assertEqual(self.router.route('list downloads').tool_name,'list_directory')
        self.assertEqual(self.router.route('read tests/test_tools.py').tool_name,'read_file')
        self.assertIsNone(self.router.route('open tests/test_tools.py').tool_name)
    def test_desktop_route_l1_no_model_and_no_chat_history(self):
        assistant,provider=self.assistant();response=assistant.respond('Open VS Code.')
        self.assertIn('Launch request accepted',response);self.assertEqual(assistant.last_performance.level,'L1')
        provider.chat.assert_not_called();self.assertEqual(self.memory.get_recent_messages(100),[])
        self.assertFalse(automatic_speech_allowed(assistant.last_response_metadata))
    def test_voice_turn_suppresses_project_metadata(self):
        assistant,provider=self.assistant();assistant.respond('Open my FRIDAY project.',persist=False)
        start='2000-01-01T00:00:00.000000+00:00';end='2100-01-01T00:00:00.000000+00:00'
        self.assertEqual(self.memory.project_interactions_between(start,end),());provider.chat.assert_not_called()
    def test_desktop_tool_not_in_model_translator_allowlist(self):
        from friday.tools.intent_translator import APPROVED_TOOLS
        self.assertFalse(DESKTOP_TOOLS & APPROVED_TOOLS)
    def test_no_microphone_or_cloud_from_action(self):
        with patch('friday.voice.backend.LocalVoiceBackend.capture') as capture,patch('socket.create_connection') as network:
            self.invoke();capture.assert_not_called();network.assert_not_called()


class SessionTests(DesktopFixture):
    def test_explicit_project_metadata_persisted_without_content(self):
        self.invoke('open_project',{'project_id':'friday'})
        rows=self.memory.project_interactions_between('2000','2100');self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['project_id'],'friday');self.assertEqual(rows[0]['source'],'friday_managed')
        self.assertEqual(rows[0]['schema_version'],1);self.assertEqual(rows[0]['status'],'launch_accepted')
        self.assertNotIn('transcript',rows[0]);self.assertEqual(self.memory.get_recent_messages(100),[])
    def test_non_project_launch_not_recorded(self):
        self.invoke();self.assertEqual(self.memory.project_interactions_between('2000','2100'),())
    def test_failed_launch_not_recorded(self):
        self.child.wait.return_value=1;self.invoke('open_project',{'project_id':'friday'})
        self.assertEqual(self.memory.project_interactions_between('2000','2100'),())
    def test_invalid_metadata_rejected(self):
        for project,path,identity,app,status in [('bad;id',str(self.project),(1,1),'vscode','launch_accepted'),
              ('friday','../../etc',(1,1),'vscode','launch_accepted'),('friday',str(self.project),(-1,1),'vscode','launch_accepted'),
              ('friday',str(self.project),(1,1),'shell','launch_accepted'),('friday',str(self.project),(1,1),'vscode','opened')]:
            with self.assertRaises(ValueError): self.memory.record_project_interaction(project,path,identity,app,status)
    def test_schema_constraints(self):
        self.seed()
        with self.assertRaises(Exception):
            with self.memory._database.transaction() as db: db.execute("UPDATE desktop_project_sessions SET source='editor_surveillance'")
    def test_no_session(self):
        self.assertEqual(self.invoke('resume_project',{}).data['status'],'no_session');self.process.assert_not_called()
    def test_one_yesterday_session_requests_typed_resume(self):
        self.seed();result=self.invoke('resume_project',{})
        self.assertEqual(result.data['status'],'launch_accepted')
        self.assertEqual(self.approval.request.call_args.args[0].operation,'resume_project')
        self.assertIn(str(self.project),self.approval.request.call_args.args[0].target)
    def test_resume_denial(self):
        self.seed();self.approval.request.return_value=FolderDecision.DENY
        self.assertFalse(self.invoke('resume_project',{}).success);self.process.assert_not_called()
    def test_multiple_requires_explicit_selection(self):
        other=self.home/'Other';other.mkdir();self.adapter.projects={'friday':self.project,'other':other}
        self.seed();self.seed('other',other)
        result=self.invoke('resume_project',{})
        self.assertEqual(result.data['status'],'needs_selection');self.process.assert_not_called()
        result=self.invoke('resume_project',{'project_id':'other'});self.assertEqual(result.data['status'],'launch_accepted')
    def test_stale_project_inode_refused(self):
        self.seed();self.project.rename(self.home/'OldProject');self.project.mkdir()
        self.assertEqual(self.invoke('resume_project',{}).data['status'],'unavailable');self.process.assert_not_called()
    def test_unverified_launch_not_resume_eligible(self):
        self.seed(status='launch_outcome_unverified')
        self.assertEqual(self.invoke('resume_project',{}).data['status'],'no_session');self.process.assert_not_called()
    def test_today_not_yesterday(self):
        self.seed(stamp=datetime.now(timezone.utc).isoformat())
        self.assertEqual(self.invoke('resume_project',{}).data['status'],'no_session')
    def test_registry_path_not_database_path_authoritative(self):
        other=self.home/'Other';other.mkdir();self.seed(path=other)
        self.assertEqual(self.invoke('resume_project',{}).data['status'],'no_session');self.process.assert_not_called()


class SessionEnvironmentTests(DesktopFixture):
    def test_wayland_reports_unsupported_without_enumerating_processes(self):
        with patch.dict(os.environ,{'XDG_SESSION_TYPE':'wayland'}),patch('os.scandir') as enumerate_processes:
            result=self.invoke('inspect_running_applications',{})
        self.assertEqual(result.data['status'],'unsupported');self.assertIn('wayland',result.data['message'])
        enumerate_processes.assert_not_called();self.process.assert_not_called()
    def test_x11_reports_unsupported_without_private_titles(self):
        result=self.invoke('inspect_running_applications',{})
        self.assertEqual(result.data['status'],'unsupported');self.assertNotIn('cmdline',str(result.data))
    def test_headless_launch_unavailable(self):
        with patch.dict(os.environ,{},clear=True): result=self.invoke()
        self.assertEqual(result.data['status'],'unavailable');self.process.assert_not_called()
    def test_read_only_inspection_still_requires_approval(self):
        self.approval.request.return_value=FolderDecision.DENY
        self.assertFalse(self.invoke('inspect_running_applications',{}).success)
    def test_remote_display_refused(self):
        with patch.dict(os.environ,{'DISPLAY':'remote.example:0'}): self.assertIsNone(desktop_environment()[1])
    def test_wayland_runtime_and_bus_are_owner_scoped(self):
        runtime=self.root/'runtime';runtime.mkdir(mode=0o700)
        with patch.dict(os.environ,{'XDG_SESSION_TYPE':'wayland','WAYLAND_DISPLAY':'wayland-0','XDG_RUNTIME_DIR':str(runtime),
                                    'DBUS_SESSION_BUS_ADDRESS':'tcp:host=PRIVATE'}):
            _,env=desktop_environment()
        self.assertEqual(env['DBUS_SESSION_BUS_ADDRESS'],'unix:path='+str(runtime/'bus'));self.assertNotIn('PRIVATE',str(env))


class LocalCalendarTests(unittest.TestCase):
    def zone(self,value):
        original=os.environ.get('TZ')
        os.environ['TZ']=value;time.tzset()
        def restore():
            if original is None: os.environ.pop('TZ',None)
            else: os.environ['TZ']=original
            time.tzset()
        self.addCleanup(restore)
    def test_local_calendar_kolkata_not_utc(self):
        self.zone('Asia/Kolkata')
        start,end=yesterday_window(datetime(2026,10,9,20,0,tzinfo=timezone.utc))
        self.assertEqual(start,'2026-10-08T18:30:00.000000+00:00')
        self.assertEqual(end,'2026-10-09T18:30:00.000000+00:00')
    def test_dst_midnights_not_fixed_24_hours(self):
        self.zone('America/New_York')
        start,end=yesterday_window(datetime(2026,3,9,12,0,tzinfo=timezone.utc))
        self.assertEqual((datetime.fromisoformat(end)-datetime.fromisoformat(start)).total_seconds(),23*3600)
    def test_naive_clock_rejected(self):
        with self.assertRaises(ValueError): yesterday_window(datetime(2026,10,9))


class CLIIntegrationTests(DesktopFixture):
    def run_cli(self,inputs,voice=None):
        from friday.main import main
        configuration=replace(settings,project_root=self.project,database_path=self.root/'cli.db',
                              filesystem_permission_store_path=self.root/'permissions/grants.json')
        speech=Mock();provider=Mock(spec=ModelProvider)
        from friday.security.owner import OwnerAuthenticator
        self.cli_owner=Mock(spec=OwnerAuthenticator)
        provider.supports_inference_profiles=True;provider.inference_profile=Mock(side_effect=lambda _:nullcontext())
        output=io.StringIO()
        with patch('friday.main.settings',configuration),patch('friday.main.OllamaProvider',return_value=provider), \
             patch('friday.security.owner.OwnerAuthenticator',return_value=self.cli_owner), \
             patch('friday.desktop.runtime.ApplicationRegistry',return_value=self.apps), \
             patch('builtins.input',side_effect=inputs),patch('sys.stdout',output), \
             patch('sys.stdin.isatty',return_value=True),patch.object(output,'isatty',return_value=True):
            main(adaptive=True,speech_backend=speech,voice_backend=voice)
        with MemoryManager(configuration.database_path) as memory:
            messages=memory.get_recent_messages(100);rows=memory.project_interactions_between('2000','2100')
        return output.getvalue(),speech,provider,messages,rows
    def test_keyboard_project_real_typed_gateway_and_q_usage(self):
        output,speech,provider,messages,rows=self.run_cli(['Open my FRIDAY project.','1','/q hello','quit'])
        self.assertIn('Operation: open_project',output);self.assertIn('Risk: execute',output)
        self.assertIn('Launch request accepted',output);self.assertIn('Usage: /q',output)
        self.assertEqual(len(rows),1);self.assertEqual(messages,[])
        self.cli_owner.authenticate.assert_called_once()
        provider.chat.assert_not_called();speech.speak.assert_called_once()
        self.assertRegex(speech.speak.call_args.args[0], r'^Good (morning|afternoon|evening)! Welcome back\.$')
    def test_confirmed_voice_still_needs_separate_typed_desktop_approval(self):
        voice=Mock();voice.transcribe.return_value='Open my FRIDAY project.'
        output,speech,provider,messages,rows=self.run_cli(['/voice','','y','1','quit'],voice)
        self.assertIn('Recognized transcript:',output);self.assertIn('Operation: open_project',output)
        self.assertIn('Launch request accepted',output);self.assertEqual(rows,());self.assertEqual(messages,[])
        self.cli_owner.authenticate.assert_called_once()
        provider.chat.assert_not_called();speech.speak.assert_called_once()
        self.assertRegex(speech.speak.call_args.args[0], r'^Good (morning|afternoon|evening)! Welcome back\.$')
    def test_confirmed_voice_does_not_supply_operation_approval(self):
        voice=Mock();voice.transcribe.return_value='Open my FRIDAY project.'
        output,speech,provider,messages,rows=self.run_cli(['/voice','','y','3','quit'],voice)
        self.assertIn('Desktop permission denied',output);self.process.assert_not_called()
        self.cli_owner.authenticate.assert_called_once()
        self.assertEqual(rows,());self.assertEqual(messages,[]);speech.speak.assert_called_once()
        self.assertRegex(speech.speak.call_args.args[0], r'^Good (morning|afternoon|evening)! Welcome back\.$')
    def test_cancelled_voice_never_requests_desktop_permission(self):
        voice=Mock();voice.transcribe.return_value='Open my FRIDAY project.'
        output,speech,provider,messages,rows=self.run_cli(['/voice','','n','quit'],voice)
        self.assertNotIn('Operation: open_project',output);self.process.assert_not_called()
        self.assertEqual(rows,());self.assertEqual(messages,[])
    def test_persistent_read_grant_does_not_authorize_folder_open(self):
        from friday.main import create_tool_runtime
        from friday.tools.grants import approved_folder
        configuration=replace(settings,project_root=self.project,database_path=self.root/'runtime.db',
                              filesystem_permission_store_path=self.root/'permissions/grants.json')
        approval=Mock(spec=CLIFileApproval);approval.request.return_value=FolderDecision.DENY
        with patch('friday.desktop.runtime.ApplicationRegistry',return_value=self.apps):
            manager,_=create_tool_runtime(configuration,filesystem_approval=approval)
        self.addCleanup(manager.desktop_access.close)
        manager.filesystem_access.store.add(approved_folder(self.home/'Downloads',manager.filesystem_access.boundary.sensitive))
        result=manager.execute(ToolRequest('open_folder',{'folder_id':'downloads'}))
        self.assertFalse(result.success);self.process.assert_not_called()
        self.assertEqual(approval.request.call_args.args[0].operation,'navigate_folder')
