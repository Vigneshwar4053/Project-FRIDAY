"""Synthetic live integration. Never launch watchers or read desktop activity."""
from datetime import timedelta
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from tests.test_zorvyq_phase2d import StoreFixture,T,event,record
from zorvyq.awareness.adapter import Unavailable
from zorvyq.awareness.monitor import MonitoringManager
from zorvyq.awareness.runtime import LocalRuntime,discover,watcher_config,gnome_ready
from zorvyq.awareness.intelligence import ActivityQueries,intent
from zorvyq.operations.permissions import Permissions


class RuntimeTests(unittest.TestCase):
    def test_discover_checksum_and_tamper(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);(root/'third_party').mkdir();exe=root/'fake';exe.write_bytes(b'fixture');exe.chmod(0o700)
            manifest={'executables':{'server':{'path':'fake','sha256':hashlib.sha256(b'fixture').hexdigest()}}}
            (root/'third_party/activitywatch-manifest.json').write_text(json.dumps(manifest))
            self.assertEqual(discover(root)['server'],exe)
            exe.write_bytes(b'tampered')
            with self.assertRaises(ValueError):discover(root)

    def test_runtime_never_launches_without_consent(self):
        from zorvyq.awareness.store import DEFAULTS
        runtime=LocalRuntime('/not-used')
        with patch.object(runtime,'_spawn') as spawn:
            runtime.ensure(DEFAULTS)
            runtime.ensure({**DEFAULTS,'enabled':True,'managed_runtime':True,'paused':True})
            spawn.assert_not_called()

    def test_gnome_probe_uses_introspection_not_focus_data(self):
        with patch('zorvyq.awareness.runtime.subprocess.run',return_value=Mock(returncode=0,stdout=b'org.gnome.shell.extensions.FocusedWindow')) as run:
            self.assertTrue(gnome_ready())
            self.assertIn('introspect',run.call_args.args[0]);self.assertNotIn('Get',run.call_args.args[0])
            self.assertEqual(run.call_args.kwargs['timeout'],2)

    def test_upstream_filters_valid_and_drop_all_unapproved(self):
        import tomllib
        from zorvyq.awareness.store import DEFAULTS
        value=tomllib.loads(watcher_config({**DEFAULTS,'exclusions':['sensitive.example']}))
        self.assertEqual(value['server'],{'host':'127.0.0.1','port':5600})
        rules=value['awatcher']['filters']
        self.assertEqual(rules[-1],{'match-app-id':'.*','replace-app-id':'__zorvyq_excluded__','replace-title':''})
        for rule in rules:
            if 'replace-app-id' in rule:self.assertEqual(rule['replace-title'],'')

    def test_managed_start_missing_extension_and_shutdown(self):
        from zorvyq.awareness.store import DEFAULTS
        with TemporaryDirectory() as directory:
            aw=Mock();aw.buckets.side_effect=[Unavailable('activitywatch_unavailable'),{}]
            runtime=LocalRuntime(directory,aw);child=Mock();child.poll.return_value=None
            p={**DEFAULTS,'enabled':True,'managed_runtime':True}
            with patch('zorvyq.awareness.runtime.discover',return_value={'server':Path('/fixture/server'),'wayland':Path('/fixture/wayland')}),patch.object(runtime,'_spawn',return_value=child) as spawn,patch('zorvyq.awareness.runtime.session_type',return_value='wayland'),patch.dict('os.environ',{'XDG_CURRENT_DESKTOP':'GNOME'}),patch('zorvyq.awareness.runtime.external_watcher_present',return_value=False),patch('zorvyq.awareness.runtime.gnome_ready',return_value=False):
                runtime.ensure(p);self.assertEqual(spawn.call_count,1)
                runtime.last_attempt=0;runtime.ensure(p)
                self.assertEqual(runtime.state,'WATCHER UNAVAILABLE');self.assertEqual(spawn.call_count,1)
                runtime.stop();child.terminate.assert_called_once();self.assertIsNone(runtime.lease)

    def test_no_duplicate_server_or_external_watcher(self):
        from zorvyq.awareness.store import DEFAULTS
        with TemporaryDirectory() as directory:
            runtime=LocalRuntime(directory,Mock());runtime.adapter.buckets.return_value={}
            try:
                with patch('zorvyq.awareness.runtime.discover',return_value={}),patch('zorvyq.awareness.runtime.external_watcher_present',return_value=True),patch.object(runtime,'_spawn') as spawn:
                    runtime.ensure({**DEFAULTS,'enabled':True,'managed_runtime':True});spawn.assert_not_called()
            finally:runtime.stop()


class LiveManagerTests(StoreFixture,unittest.TestCase):
    def setUp(self):
        super().setUp();self.enable();self.aw=Mock();self.clock=T+timedelta(seconds=60)
        self.manager=MonitoringManager(self.store,self.aw,clock=lambda:self.clock);self.manager.boundary=T
        self.aw.buckets.return_value={'window':{'type':'currentwindow'},'idle':{'type':'afkstatus'}}
        self.windows=[event(1,1,29),event(2,31,29,app='firefox')]
        self.idle=[event(10,0,60,status='not-afk')]
        self.aw.events.side_effect=lambda bucket,*_:self.windows if bucket=='window' else self.idle

    def test_switch_live_elapsed_completed_duration_dedupe_and_staleness(self):
        self.manager.tick();live=self.manager.snapshot()
        self.assertEqual(live['state'],'ON');self.assertEqual(live['application']['name'],'Firefox')
        self.assertEqual(live['application']['elapsed'],29)
        rows=self.store.last_three();self.assertEqual(len(rows),1);self.assertEqual(rows[0]['name'],'VS Code');self.assertEqual(rows[0]['duration'],29)
        self.manager.tick();self.assertEqual(len(self.store.search()),1)
        self.clock+=timedelta(seconds=30);self.assertIsNone(self.manager.snapshot()['application'])
        self.manager.tick();self.assertEqual(self.manager.snapshot()['state'],'WATCHER UNAVAILABLE')

    def test_successor_proves_completion_even_if_idle_heartbeat_lags(self):
        self.idle=[event(10,0,59,status='not-afk')]
        self.manager.tick();self.assertEqual(self.store.last_three()[0]['name'],'VS Code')

    def test_neutral_excluded_switch_closes_approved_activity_without_recording_it(self):
        self.windows[-1]['data']['app']='__zorvyq_excluded__'
        self.manager.tick()
        self.assertEqual(self.store.last_three()[0]['name'],'VS Code')
        self.assertEqual(len(self.store.search()),1)
        self.assertIsNone(self.manager.snapshot()['application'])

    def test_long_application_interval_uses_full_idle_evidence(self):
        self.clock=T+timedelta(hours=2)
        self.windows=[event(1,1,7190),event(2,7192,8,app='firefox')]
        self.idle=[event(10,0,7200,status='not-afk')]
        self.manager.tick()
        self.assertEqual(self.store.last_three()[0]['duration'],7190)
        idle_calls=[call for call in self.aw.events.call_args_list if call.args[0]=='idle']
        self.assertEqual(idle_calls[0].args[1],T+timedelta(seconds=1))

    def test_service_vs_watcher_state_and_reconnect(self):
        self.aw.buckets.side_effect=Unavailable('activitywatch_unavailable')
        self.manager.tick();self.assertEqual(self.manager.snapshot()['state'],'SERVICE UNAVAILABLE')
        self.aw.buckets.side_effect=None;self.aw.buckets.return_value={}
        self.manager.tick();self.assertEqual(self.manager.snapshot()['state'],'WATCHER UNAVAILABLE')
        self.aw.buckets.return_value={'window':{'type':'currentwindow'},'idle':{'type':'afkstatus'}}
        self.manager.tick();self.assertEqual(self.manager.snapshot()['state'],'ON')

    def test_future_heartbeats_and_ambiguous_idle_fail_closed(self):
        self.windows[-1]['end']=self.clock+timedelta(seconds=30)
        self.manager.tick();self.assertIsNone(self.manager.snapshot()['application'])
        self.windows[-1]['end']=self.clock
        self.idle.append(event(11,20,20,status='afk'))
        self.manager.tick();self.assertEqual(self.manager.snapshot()['state'],'WATCHER UNAVAILABLE')

    def test_disabled_paused_stopped_no_calls_and_no_current(self):
        self.manager.tick();self.assertIsNotNone(self.manager.snapshot()['application'])
        self.store.configure(paused=True);self.aw.reset_mock();self.manager.tick()
        self.assertEqual(self.manager.snapshot()['state'],'PAUSED');self.assertIsNone(self.manager.snapshot()['application']);self.aw.buckets.assert_not_called()
        self.store.configure(enabled=False,paused=False);self.manager.tick();self.assertEqual(self.manager.snapshot()['state'],'OFF')
        self.manager.stop();self.assertIsNone(self.manager.snapshot()['application'])

    def test_offline_ingestion_history_recovery_no_internet(self):
        import socket
        original=socket.socket.connect
        def local_only(sock,address):
            if isinstance(address,tuple) and address[0] not in ('127.0.0.1','::1'):raise AssertionError('External network denied')
            return original(sock,address)
        with patch('socket.getaddrinfo',side_effect=AssertionError('DNS denied')),patch('socket.socket.connect',local_only):
            self.manager.tick();self.assertEqual(len(self.store.last_three()),1)
            self.aw.buckets.side_effect=Unavailable('activitywatch_unavailable');self.manager.tick()
            self.aw.buckets.side_effect=None;self.manager.tick()
            self.assertEqual(len(self.store.last_three()),1)
            permissions=Permissions();queries=ActivityQueries(self.store,None,permissions,self.manager)
            plan=queries.plan('recent');ticket=permissions.approve(plan,confirmed=True)
            self.assertIn('VS Code',queries.run(plan,ticket))

    def test_current_question_exact_permission_and_no_fabrication(self):
        permissions=Permissions();queries=ActivityQueries(self.store,None,permissions,self.manager)
        self.assertEqual(intent('What application am I using?'),'current')
        for kind in ('current','recent','yesterday','programming','websites','apps'):
            plan=queries.plan(kind)
            with self.assertRaises(PermissionError):queries.run(plan,None)
        self.manager.tick();plan=queries.plan('current');ticket=permissions.approve(plan,confirmed=True)
        self.assertIn('Firefox',queries.run(plan,ticket))
        with self.assertRaises(PermissionError):queries.run(plan,ticket)
        self.manager.stop();ticket=permissions.approve(plan,confirmed=True)
        self.assertIn('unavailable',queries.run(plan,ticket))

    def test_shared_status_expires_and_privacy_scope_invalidates(self):
        self.store.configure(consent=True,background=True)
        self.manager.tick();self.manager.lease=123 # fixture marker; no real file lock
        try:self.manager.publish()
        finally:self.manager.lease=None
        follower=MonitoringManager(self.store,clock=lambda:self.clock)
        self.assertEqual(follower.snapshot()['state'],'ON')
        self.clock+=timedelta(seconds=25)
        self.assertNotEqual(follower.snapshot()['state'],'ON')
        self.store.configure(paused=True)
        self.assertEqual(follower.snapshot()['state'],'PAUSED')

    def test_atomic_reconcile_rolls_back_invalid_replacement(self):
        self.store.reconcile('source',[record(1)])
        with self.assertRaises(ValueError):self.store.reconcile('source',[dict(record(2),start=__import__('datetime').datetime.now())])
        self.assertEqual([r['id'] for r in self.store.search()],['1'])

    def test_website_rules_migration_retention_and_strict_local(self):
        self.assertEqual(self.store.website_category('github.com'),'Programming')
        self.store.set_website_category('github.com','Coursework')
        self.assertEqual(self.store.website_category('docs.github.com'),'Coursework')
        self.store.set_website_category('docs.github.com','Education')
        self.assertEqual(self.store.website_category('docs.github.com'),'Education')
        with self.assertRaises(ValueError):self.store.configure(strict_local_only=False)
        for key in ('managed_runtime','background','start_at_login','network','processes'):
            with self.assertRaises(PermissionError):self.store.configure(**{key:True})
        with self.store.db() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],5)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertTrue(db.execute("SELECT name FROM sqlite_master WHERE name='browser_activity'").fetchone())


class BackgroundAndModelTests(unittest.TestCase):
    def test_system_metadata_separate_scopes_and_no_peer_addresses(self):
        from zorvyq.awareness.system_monitor import snapshot
        import os
        own={'pid':1,'name':'fixture','rss_bytes':4096,'cpu_percent':1,'owner_uid':os.getuid(),'executable':'/private/path'}
        foreign={**own,'pid':2,'owner_uid':os.getuid()+1}
        with patch('zorvyq.awareness.system_monitor.Path.glob',return_value=[]),patch('zorvyq.awareness.system_monitor.processes',return_value={'top_cpu':[own,foreign],'top_memory':[own]}) as processes,patch('zorvyq.awareness.system_monitor.read',return_value='header\n 0: 0100007F:0001 01020304:0050 01\n') as read:
            result=snapshot();self.assertNotIn('processes',result);self.assertNotIn('network',result);processes.assert_not_called();read.assert_not_called()
            result=snapshot(include_processes=True,include_network=True)
            self.assertEqual(result['processes'],[{k:own[k] for k in ('pid','name','rss_bytes','cpu_percent')}])
            self.assertEqual(result['network']['tcp']['established'],1)
            self.assertNotIn('01020304',json.dumps(result));self.assertNotIn('/private/path',json.dumps(result))

    def test_user_service_is_optin_and_preserves_gui_autostart(self):
        from zorvyq.awareness.background import BackgroundService,unit_text
        with TemporaryDirectory() as directory:
            service=BackgroundService(directory)
            with self.assertRaises(PermissionError):service.apply(True)
            with patch.object(service,'run') as run:
                service.apply(True,approved=True)
                self.assertIn('UMask=0077',service.path.read_text());self.assertIn('PartOf=graphical-session.target',unit_text())
                self.assertNotIn('autostart',unit_text())
                run.assert_any_call('enable','--now','zorvyq-awareness.service')
                service.apply(False,approved=True);run.assert_any_call('disable','--now','zorvyq-awareness.service')

    def test_model_endpoint_and_redirects_cannot_escape(self):
        from zorvyq.awareness.local_model import validate_endpoint,NoRedirect,ActivityProvider
        validate_endpoint('http://127.0.0.1:11434')
        for url in ('http://example.org:11434','http://localhost:11434','http://127.0.0.1:8080','https://127.0.0.1:11434'):
            with self.assertRaises(ValueError):validate_endpoint(url)
        with self.assertRaises(ValueError):NoRedirect().redirect_request(None,None,None,None,None,None)
        provider=object.__new__(ActivityProvider)
        with self.assertRaises(ValueError):provider._open_request(Mock(full_url='https://example.org/api/chat'),2)
