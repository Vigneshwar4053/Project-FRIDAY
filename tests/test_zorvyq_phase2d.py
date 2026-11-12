"""Synthetic events only. No real watchers, desktop launches, browser history or inference."""
from contextlib import closing
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch
from zorvyq.awareness.store import ActivityStore, stamp, EMPTY
from zorvyq.awareness.adapter import ActivityWatch, Unavailable
from zorvyq.awareness.monitor import MonitoringManager, intersection
from zorvyq.awareness.privacy import browser_metadata, safe_title
from zorvyq.awareness.intelligence import answer, intent, summarize, ActivityQueries
from zorvyq.operations.permissions import Permissions
from zorvyq.tasks import TaskStore

T=datetime(2026,11,3,10,tzinfo=timezone.utc)

def event(i,seconds,length=10,app='code',**data):
    return dict(id=i,start=T+timedelta(seconds=seconds),end=T+timedelta(seconds=seconds+length),data={'app':app,**data})

def record(i,start=1,end=11,state='completed',**values):
    return dict(dict(id=str(i),kind='application',app='code',name='VS Code',start=T+timedelta(seconds=start),
        end=T+timedelta(seconds=end),category='Programming',state=state,title='',domain='',url='',project=''),**values)

class StoreFixture:
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)/'activity.sqlite3'
        self.store=ActivityStore(self.path)
    def enable(self,**values):
        with patch('zorvyq.awareness.store.now',return_value=T):self.store.configure(consent=True,enabled=True,**values)
class StoreTests(StoreFixture,unittest.TestCase):
    def test_default_off_and_denied_consent(self):
        self.assertFalse(self.store.preferences()['enabled']);self.assertFalse(self.store.preferences()['browser'])
        self.assertFalse(self.store.insert(record(1)))
        for k in ('enabled','browser','titles','urls','metrics'):
            with self.assertRaises(PermissionError):self.store.configure(**{k:True})
        self.assertEqual(self.store.last_three(),[])
    def test_last_three_zero_one_two_three_many_order_ties_restart(self):
        self.enable()
        for i in range(6):
            self.assertTrue(self.store.insert(record(i)))
            expected=[str(x) for x in range(i,max(-1,i-3),-1)]
            self.assertEqual([r['id'] for r in ActivityStore(self.path).last_three()],expected)
        self.store.insert(record('new',end=12));self.assertEqual(self.store.last_three()[0]['id'],'new')
    def test_duplicate_delete_tombstone_and_clear(self):
        self.enable();self.assertTrue(self.store.insert(record(1)));self.assertFalse(self.store.insert(record(1)))
        self.store.delete(['1']);self.assertEqual(self.store.last_three(),[]);self.assertFalse(self.store.insert(record(1)))
        self.store.insert(record(2));self.store.delete();self.assertEqual(ActivityStore(self.path).last_three(),[])
    def test_interrupted_excluded_and_can_be_completed(self):
        self.enable();self.store.insert(record(1,state='interrupted'));self.assertEqual(self.store.last_three(),[])
        self.assertTrue(self.store.insert(record(1)));self.assertEqual(len(self.store.last_three()),1)
    def test_utc_ordering_validation_and_duration(self):
        self.enable();r=record(1);r['start']=r['start'].astimezone(timezone(timedelta(hours=5,minutes=30)))
        self.store.insert(r);self.assertEqual(self.store.last_three()[0]['duration'],10)
        with self.assertRaises(ValueError):self.store.insert({**r,'start':datetime.now()})
    def test_persistence_schema_migration_and_permissions(self):
        self.enable();self.store.insert(record(1));os.chmod(self.path,0o644)
        with self.store.db() as db:
            db.execute('DROP TABLE system_metrics');db.execute('DROP TABLE monitoring_events');db.execute('DROP INDEX activity_source');db.execute('ALTER TABLE activities DROP COLUMN source');db.execute('PRAGMA user_version=1')
        migrated=ActivityStore(self.path)
        self.assertEqual(migrated.last_three()[0]['id'],'1');self.assertEqual(self.path.stat().st_mode&0o777,0o600)
        with migrated.db() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],5)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            self.assertIn('activity_end',str([tuple(r) for r in db.execute("EXPLAIN QUERY PLAN SELECT * FROM activities ORDER BY end DESC,id DESC LIMIT 3")]))
        link=self.path.parent/'link';link.symlink_to(self.path)
        with self.assertRaises(OSError):ActivityStore(link)
    def test_retention_separate_metrics_and_bounds(self):
        self.enable();self.store.insert(record(1));self.store.cleanup(T+timedelta(days=31));self.assertEqual(self.store.last_three(),[])
        with self.assertRaises(ValueError):self.store.configure(retention=0)
        with self.assertRaises(ValueError):self.store.configure(since=stamp(T))
    def test_search_export_and_title_revocation(self):
        self.enable(titles=True,urls=True)
        self.store.insert(record(1,title='Fixture title',url='https://example.org/path'))
        self.assertEqual(len(self.store.search(query='fixture',app='code',category='Programming',start=T,end=T+timedelta(hours=1))),1)
        self.assertEqual(self.store.search(query="' OR 1=1 --"),[])
        out=self.path.parent/'selected.json';self.store.export(out,self.store.last_three())
        self.assertEqual(out.stat().st_mode&0o777,0o600);self.assertEqual(len(json.loads(out.read_text())),1)
        with self.assertRaises(FileExistsError):self.store.export(out,[])
        self.store.configure(titles=False,urls=False)
        self.assertEqual(self.store.last_three()[0]['title'],'');self.assertEqual(self.store.last_three()[0]['url'],'')
    def test_pause_and_disable_prevent_writes(self):
        self.enable();self.store.configure(paused=True);self.assertFalse(self.store.insert(record(1)))
        self.store.configure(enabled=False,paused=False);self.assertFalse(self.store.insert(record(2)))
    def test_totals_clip_time_range_and_exclude_browser_overlap(self):
        self.enable();self.store.insert(record(1,start=1,end=11))
        rows=self.store.totals(T+timedelta(seconds=5),T+timedelta(seconds=10))
        self.assertAlmostEqual(rows[0]['seconds'],5,places=3)

class AdapterTests(unittest.TestCase):
    def test_external_endpoints_rejected(self):
        for endpoint in ('http://example.com:5600','http://localhost:5600','https://127.0.0.1:5600','http://127.0.0.1:5600/evil','http://user:pass@127.0.0.1:5600','http://127.0.0.1:5601'):
            with self.assertRaises(ValueError):ActivityWatch(endpoint)
        with self.assertRaises(ValueError):ActivityWatch(timeout=float('inf'))
    def test_connection_local_timeout_no_redirect_and_unavailable(self):
        with patch('zorvyq.awareness.adapter.http.client.HTTPConnection') as connection:
            connection.return_value.getresponse.return_value=Mock(status=200,read=Mock(return_value=b'{}'))
            self.assertEqual(ActivityWatch().buckets(),{});connection.assert_called_with('127.0.0.1',5600,timeout=2)
            connection.return_value.getresponse.return_value.status=302
            with self.assertRaises(Unavailable):ActivityWatch().buckets()
            connection.return_value.request.side_effect=OSError('offline')
            with self.assertRaises(Unavailable):ActivityWatch().buckets()
    def test_malformed_responses_and_event_validation(self):
        aw=ActivityWatch()
        for value in ([],None,'bad'):
            with patch.object(aw,'_get',return_value=value),self.assertRaises(Unavailable):aw.buckets()
        for raw in ([{}],[dict(id=1,timestamp='bad',duration=10,data={})], [dict(id=1,timestamp=stamp(T),duration=-1,data={})], [dict(id=1,timestamp=stamp(T),duration=float('nan'),data={})], [{}]*512):
            with patch.object(aw,'_get',return_value=raw),self.assertRaises(Unavailable):aw.events('window',T,T+timedelta(seconds=60))
        raw=[dict(id=1,timestamp=stamp(T),duration=10,data={'app':'code'})]
        with patch.object(aw,'_get',return_value=raw):self.assertEqual(aw.events('window',T,T+timedelta(seconds=60))[0]['end'],T+timedelta(seconds=10))

class PrivacyTests(unittest.TestCase):
    def setUp(self):
        from zorvyq.awareness.store import DEFAULTS
        self.p={**DEFAULTS,'domains':['example.org'],'browser':True,'urls':True,'titles':True}
    def test_browser_optin_private_sensitive_domains_and_credentials(self):
        for url in ('https://bank.example.org','https://example.org/login','https://example.org/health','https://user:password@example.org','https://example.org/?token=secret','https://elsewhere.org','file:///tmp/private','https://example.org/search?q=test'):
            self.assertIsNone(browser_metadata({'url':url,'incognito':False},self.p))
        self.assertIsNone(browser_metadata({'url':'https://example.org'},self.p))
        self.assertIsNone(browser_metadata({'url':'https://example.org','incognito':True},self.p))
        self.assertIsNone(browser_metadata({'url':'https://example.org','incognito':False},{**self.p,'browser':False}))
    def test_url_sanitization_and_exclusions(self):
        value=browser_metadata({'url':'https://example.org/docs?ref=hello#fragment','incognito':False,'title':'Docs'},self.p)
        self.assertEqual(value,dict(domain='example.org',url='https://example.org/docs',title='Docs'))
        self.assertEqual(browser_metadata({'url':'https://example.org','incognito':False},{**self.p,'urls':False})['url'],'')
        self.assertIsNone(browser_metadata({'url':'https://example.org','incognito':False},{**self.p,'exclusions':['example.org']}))
    def test_safe_titles_no_secrets(self):
        for title in ('password=fixture','Authorization Bearer fixture','https://example.org/private','token:fixture','Search private words'):
            self.assertEqual(safe_title(title),'')
        self.assertEqual(safe_title('Fixture project'),'Fixture project')

class MonitoringTests(StoreFixture,unittest.TestCase):
    def setUp(self):
        super().setUp();self.enable();self.aw=Mock();self.manager=MonitoringManager(self.store,self.aw,clock=lambda:T+timedelta(seconds=60));self.manager.boundary=T
        self.aw.buckets.return_value={'window':{'type':'currentwindow'},'afk':{'type':'afkstatus'}}
        self.windows=[event(1,1),event(2,20,app='firefox'),event(3,40,20,app='gnome-terminal')]
        self.idle=[event(10,0,30,status='not-afk'),event(11,30,10,status='afk'),event(12,40,20,status='not-afk')]
        self.aw.events.side_effect=lambda bucket,start,end:self.windows if bucket=='window' else self.idle
    def test_start_switch_complete_idle_dedupe_and_status(self):
        self.manager.tick();self.assertEqual(len(self.store.last_three()),2)
        rows=self.store.last_three();self.assertEqual([r['name'] for r in rows],['Firefox','VS Code'])
        self.assertEqual([r['duration'] for r in rows],[10,10]);self.assertIn('Monitoring ON',self.manager.status)
        self.manager.tick();self.assertEqual(len(self.store.search()),2)
    def test_idle_only_and_missing_idle_fail_closed(self):
        self.idle=[event(10,0,60,status='afk')];self.manager.tick();self.assertEqual(self.store.last_three(),[])
        self.aw.buckets.return_value={'window':{'type':'currentwindow'}};self.manager.tick();self.assertIn('unavailable',self.manager.status)
    def test_reconnection_no_external_calls_when_off_or_paused(self):
        self.aw.buckets.side_effect=Unavailable();self.manager.tick();self.assertIn('unavailable',self.manager.status)
        self.aw.buckets.side_effect=None;self.manager.tick();self.assertEqual(len(self.store.last_three()),2)
        self.store.configure(paused=True);self.aw.reset_mock();self.manager.tick();self.aw.buckets.assert_not_called()
        self.store.configure(enabled=False,paused=False);self.manager.tick();self.aw.buckets.assert_not_called()
    def test_unknown_and_current_activity_not_completed(self):
        self.windows=[event(1,1,50,app='unapproved')];self.manager.tick();self.assertEqual(self.store.last_three(),[])
        self.windows=[event(1,1,50)];self.manager.tick();self.assertEqual(self.store.last_three(),[])
    def test_browser_separate_consent_and_foreground(self):
        with patch('zorvyq.awareness.store.now',return_value=T):self.store.configure(consent=True,browser=True,domains=['example.org'])
        self.aw.buckets.return_value['aw-watcher-web-firefox']={'type':'web.tab.current'}
        web=[event(21,20,5,url='https://example.org/docs',incognito=False),event(22,26,2,url='https://example.org/other',incognito=False)]
        self.aw.events.side_effect=lambda bucket,start,end:self.windows if bucket=='window' else self.idle if bucket=='afk' else web
        self.manager.tick();rows=self.store.search(kind='browser');self.assertEqual(len(rows),1);self.assertEqual(rows[0]['domain'],'example.org')
        self.assertEqual(rows[0]['url'],'');self.assertEqual(len(self.store.last_three()),2)
    def test_idle_corrections_replace_intervals_and_deleted_source_stays_deleted(self):
        self.manager.tick();self.assertEqual(len(self.store.search()),2)
        self.idle=[event(10,0,5,status='not-afk'),event(11,5,35,status='afk'),event(12,40,20,status='not-afk')]
        self.manager.tick();rows=self.store.last_three()
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['duration'],4)
        self.manager.delete([rows[0]['id']]);self.manager.tick();self.assertEqual(self.store.search(),[])

    def test_single_controller_and_stop(self):
        other=MonitoringManager(self.store,self.aw,clock=lambda:T)
        self.manager._run=lambda:self.manager.halt.wait(5)
        try:
            self.manager.start();other.start()
            self.assertIsNone(other.thread);self.assertIn('another controller',other.status)
        finally:self.manager.stop();other.stop()
        self.assertFalse(self.manager.thread.is_alive())

    def test_metrics_are_independent_optin_and_bounded(self):
        with patch('zorvyq.awareness.store.now',return_value=T):self.store.configure(consent=True,metrics=True,enabled=False)
        with patch('zorvyq.awareness.system_monitor.snapshot',return_value={}),patch('zorvyq.services.ResourceMonitor') as resources,patch('zorvyq.operations.collector.disk',return_value={}),patch('zorvyq.operations.collector.read',return_value='100 0'):
            resources.return_value.snapshot.return_value={'system_memory_used_percent':50}
            self.manager.tick();self.manager.tick();resources.return_value.snapshot.assert_called_once()
        self.aw.buckets.assert_not_called()
        with self.store.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM system_metrics').fetchone()[0],1)

    def test_intersections_merge_and_split_idle(self):
        pieces=intersection(T,T+timedelta(seconds=40),[(T,T+timedelta(seconds=10)),(T+timedelta(seconds=5),T+timedelta(seconds=15)),(T+timedelta(seconds=30),T+timedelta(seconds=50))])
        self.assertEqual(sum((b-a).total_seconds() for a,b in pieces),25)

class CompletedTasksTests(unittest.TestCase):
    def test_existing_phase2c_completion_order_reopen_delete_restart(self):
        with TemporaryDirectory() as temp:
            path=Path(temp)/'tasks.sqlite3';store=TaskStore(path)
            self.assertEqual(store.recent_completed(),[])
            ids=[]
            for i in range(5):
                ids.append(store.save(title='Fixture '+str(i),status='Completed',project='Fixture project'))
                with closing(store.connect()) as db,db:db.execute('UPDATE tasks SET completed=? WHERE id=?',(stamp(T+timedelta(seconds=i)),ids[-1]))
                self.assertEqual(len(store.recent_completed()),min(3,i+1))
            self.assertEqual([r['id'] for r in TaskStore(path).recent_completed()],ids[::-1][:3])
            store.change_status(store.recent_completed()[0],'Pending');self.assertEqual(store.recent_completed()[0]['id'],ids[-2])
            store.delete(ids[-2]);self.assertEqual(store.recent_completed()[0]['id'],ids[-3])
            with closing(store.connect()) as db,db:db.execute("UPDATE tasks SET completed=? WHERE status='Completed'",(stamp(T),))
            self.assertEqual([r['id'] for r in store.recent_completed()],sorted(ids[:3],reverse=True))

    def test_exact_microseconds_and_offset_ordering(self):
        with TemporaryDirectory() as temp:
            store=TaskStore(Path(temp)/'tasks.sqlite3')
            older=store.save(title='Older',status='Completed');newer=store.save(title='Newer',status='Completed')
            with closing(store.connect()) as db,db:
                db.execute('UPDATE tasks SET completed=? WHERE id=?',('2026-11-03T15:30:00.000001+05:30',older))
                db.execute('UPDATE tasks SET completed=? WHERE id=?',('2026-11-03T10:00:00.000002+00:00',newer))
            self.assertEqual([r['id'] for r in store.recent_completed()],[newer,older])

class IntelligenceTests(StoreFixture,unittest.TestCase):
    def test_grounded_permission_missing_records_and_no_model(self):
        with self.assertRaises(PermissionError):answer('recent',self.store)
        self.assertEqual(answer('recent',self.store,authorized=True),EMPTY)
        self.enable();self.store.insert(record(1));self.assertIn('VS Code',answer('recent',self.store,authorized=True))
        self.assertEqual(intent('What were my last three activities?'),'recent')
        self.assertIsNone(intent('execute SQL'))
        self.assertIn('off',answer('websites',self.store,authorized=True))
    def test_one_use_exact_scope_permissions(self):
        permissions=Permissions();queries=ActivityQueries(self.store,None,permissions);plan=queries.plan('recent')
        with self.assertRaises(PermissionError):permissions.approve(plan)
        ticket=permissions.approve(plan,confirmed=True);self.assertEqual(queries.run(plan,ticket),EMPTY)
        with self.assertRaises(PermissionError):queries.run(plan,ticket)
        ticket=permissions.approve(plan,confirmed=True)
        with self.assertRaises(PermissionError):queries.run(queries.plan('apps'),ticket)
    def test_optional_summary_denied_or_model_unavailable(self):
        model=Mock();model.summarize_activity.side_effect=RuntimeError('offline')
        with self.assertRaises(PermissionError):summarize('apps',self.store,model,authorized=True)
        model.assert_not_called()
        with patch.object(self.store,'totals',return_value=[{'name':'Fixture','seconds':10,'count':1}]):
            reply=summarize('apps',self.store,model,authorized=True,model_authorized=True)
        self.assertIn('unavailable',reply)
        model.summarize_activity.assert_called_once()
        self.assertNotIn('Fixture',str(model.summarize_activity.call_args))

if __name__=='__main__':unittest.main()
