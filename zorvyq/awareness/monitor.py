"""One bounded in-process consumer. No daemon, watcher launch, model or desktop hooks."""
from datetime import timedelta
import hashlib
import json
import os
import fcntl
import uuid
from threading import Event, RLock, Thread
from time import monotonic
from .adapter import ActivityWatch, Unavailable
from .privacy import browser_metadata, safe_title, excluded, NAMES, CATEGORIES
from .store import now, stamp, utc


def intersection(start,end,spans):
    # Merge overlapping active evidence so idle fragments cannot double-count.
    pieces=sorted((max(start,a),min(end,b)) for a,b in spans if a<end and b>start)
    merged=[]
    for a,b in pieces:
        if a>=b:continue
        if merged and a<=merged[-1][1]:merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
        else:merged.append((a,b))
    return merged

class MonitoringManager:
    def __init__(self,store,adapter=None,clock=now,runtime=None):
        self.store=store;self.adapter=adapter or ActivityWatch();self.clock=clock
        self.lock=RLock();self.halt=Event();self.thread=None
        self.current_activity='Unknown activity'
        self.application_state='Collection unavailable';self.browser_state='Collection unavailable'
        self.revision=0;self.last_metrics=0;self.last_cleanup=0;self.resources=None;self.lease=None
        # Resume boundaries never bridge process downtime or reboot.
        self.boundary=self.clock()
        self.session=None;self.current_application=None;self.current_website=None
        self.runtime=runtime;self.state='OFF';self.metrics={};self.idle=None;self.observed=None
        self.seen_preferences=self.store.preferences();self.published=False

    def snapshot(self):
        with self.lock:
            p=self.store.preferences()
            state='PAUSED' if p['paused'] else 'OFF' if not (p['enabled'] or p['metrics']) else self.state
            active=state=='ON' and p==self.seen_preferences and self.observed is not None and timedelta(0)<=self.clock()-self.observed<=timedelta(seconds=20)
            if state=='ON' and not active:state='WATCHER UNAVAILABLE'
            metrics=dict(self.metrics) if p['metrics'] and not p['paused'] else {}
            if not p['processes']:metrics.pop('processes',None)
            if not p['network']:metrics.pop('network',None)
            result=dict(state=state,application=self.current_application if active else None,
                website=self.current_website if active and p['browser'] else None,
                idle=self.idle if active else None,metrics=metrics,
                revision=self.revision,browser=('Browser monitoring OFF' if not p['browser'] or not p['enabled'] else
                    'Browser monitoring PAUSED' if p['paused'] else self.browser_state if active else 'Browser watcher unavailable'),
                at=stamp(self.clock()),scope=p['since'])
            if self.lease is None and not p['paused'] and (p['enabled'] or p['metrics']):
                with self.store.db() as db:row=db.execute('SELECT value FROM monitoring_status WHERE id=1').fetchone()
                if row:
                    shared=json.loads(row[0])
                    if shared['scope']==p['since'] and timedelta(0)<=self.clock()-utc(shared['at'])<=timedelta(seconds=20):return shared
            return result

    def publish(self):
        if self.lease is None:return
        value=self.snapshot()
        with self.store.db() as db:
            db.execute('INSERT INTO monitoring_status VALUES (1,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value',(json.dumps(value),))
        self.published=True

    @property
    def status(self):
        p=self.store.preferences()
        if p['paused']:state='Monitoring PAUSED'
        elif not p['enabled']:state='Monitoring OFF'
        else:state=self.application_state+(' · '+self.current_activity if self.application_state=='Monitoring ON' else '')
        browser='Browser monitoring OFF' if not p['browser'] else ('Browser monitoring PAUSED' if p['paused'] or not p['enabled'] else self.browser_state)
        live=self.snapshot()['state']
        prefix={'SERVICE UNAVAILABLE':'Service unavailable','WATCHER UNAVAILABLE':'Watcher unavailable',
                'ERROR':'Monitoring ERROR','STARTING':'Monitoring STARTING','OFF':'Monitoring OFF'}.get(live)
        suffix=' (another controller)' if 'another controller' in self.application_state else ''
        return (prefix or state)+suffix+' · '+browser

    def configure(self,**changes):
        with self.lock:
            self.store.configure(**changes);self.boundary=self.clock()
            self.application_state=self.browser_state='Collection unavailable'
            self.current_application=self.current_website=None
            self.state='STARTING' if changes.get('enabled') else self.state
            self.revision+=1
        p=self.store.preferences()
        if p['paused'] or not (p['enabled'] or p['metrics']):self.stop()
        else:self.start()

    def delete(self,identities=None):
        with self.lock:
            self.store.delete(identities);self.revision+=1

    def start(self):
        with self.lock:
            p=self.store.preferences()
            if self.thread is not None and self.thread.is_alive():return
            if not (p['enabled'] or p['metrics']) or p['paused']:return
            if self.lease is None:
                fd=os.open(str(self.store.path)+'.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
                try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                except OSError:
                    os.close(fd);self.application_state='Collection unavailable (another controller)';return
                self.lease=fd
            self.session=uuid.uuid4().hex
            self.state='STARTING'
            with self.store.db() as db:
                db.execute("UPDATE activity_sessions SET end=?,state='interrupted' WHERE end IS NULL",(stamp(self.clock()),))
                db.execute("INSERT INTO activity_sessions VALUES (?,?,NULL,'running')",(self.session,stamp(self.clock())))
            self.halt.clear();self.thread=Thread(target=self._run,name='zorvyq-awareness',daemon=True);self.thread.start()

    def stop(self):
        self.halt.set()
        if self.thread is not None:self.thread.join(timeout=12)
        with self.lock:
            if self.runtime is not None:self.runtime.stop()
            self.state='OFF';self.current_application=self.current_website=None;self.observed=None
            if self.lease is not None and (self.thread is None or not self.thread.is_alive()):
                with self.store.db() as db:
                    db.execute("UPDATE activity_sessions SET end=?,state='stopped' WHERE id=?",(stamp(self.clock()),self.session))
                self.publish()
                os.close(self.lease);self.lease=None

    def _run(self):
        while not self.halt.is_set():
            try:self.tick()
            except Exception:
                # Never log raw events, titles, paths or server error bodies.
                with self.lock:
                    self.application_state=self.browser_state='Collection unavailable'
                    self.state='ERROR';self.current_application=self.current_website=None
            try:self.publish()
            except Exception:pass
            self.halt.wait(3)

    def tick(self):
        with self.lock:
            p=self.store.preferences();boundary=self.boundary
            if p!=self.seen_preferences:
                self.boundary=max(self.boundary,utc(p['since'])) if p['since'] else self.boundary
                boundary=self.boundary;self.seen_preferences=p
                self.current_application=self.current_website=None
        if p['paused'] or not (p['enabled'] or p['metrics']):
            if self.runtime is not None:self.runtime.stop()
            self.state='PAUSED' if p['paused'] else 'OFF';return
        if self.runtime is not None:self.runtime.ensure(p)
        at=self.clock()
        if monotonic()-self.last_cleanup>=3600:
            with self.lock:self.store.cleanup(at);self.last_cleanup=monotonic();self.revision+=1
        if p['metrics'] and monotonic()-self.last_metrics>=60:
            from zorvyq.services import ResourceMonitor
            from zorvyq.operations.collector import disk, read
            if self.resources is None:self.resources=ResourceMonitor()
            metrics=self.resources.snapshot();metrics.update(disk());metrics['uptime_seconds']=float(read('/proc/uptime',128).split()[0])
            from .system_monitor import snapshot
            metrics.update(snapshot(include_processes=p['processes'],include_network=p['network']))
            # Recheck opt-in after the collector, before the write.
            with self.lock:
                current=self.store.preferences()
                if current==p and not current['paused'] and self.boundary==boundary and not self.halt.is_set():
                    with self.store.db() as db:db.execute('INSERT OR IGNORE INTO system_metrics VALUES (?,?)',(stamp(at),json.dumps(metrics)))
                    self.last_metrics=monotonic()
                    self.metrics=dict(at=stamp(at),**metrics)
        if not p['enabled']:return
        authorized_start=max(utc(p['since']),boundary,at-timedelta(days=p['retention']))
        start=max(authorized_start,at-timedelta(hours=1))
        try:
            buckets=self.adapter.buckets()
            # One canonical foreground and idle stream. Multiple devices/sources fail closed.
            windows=[k for k,v in buckets.items() if v['type']=='currentwindow']
            afks=[k for k,v in buckets.items() if v['type']=='afkstatus']
            browsers=[k for k,v in buckets.items() if v['type']=='web.tab.current' and 'firefox' in k.casefold()]
            if len(windows)!=1 or len(afks)!=1:raise Unavailable('watcher_selection_required')
            events=self.adapter.events(windows[0],start,at)
            browser_events=self.adapter.events(browsers[0],start,at) if p['browser'] and len(browsers)==1 else []
            # A long foreground interval may begin before the ordinary overlap.
            # Fetch its actual idle evidence rather than lose it or invent duration.
            evidence_start=max(authorized_start,min((r['start'] for r in events+browser_events),default=start))
            idle=self.adapter.events(afks[0],min(start,evidence_start),at)
            if any(r['data'].get('status') not in ('afk','not-afk') for r in idle):raise Unavailable('unknown_idle_state')
            # ON requires recent foreground AND idle heartbeats, not an HTTP response alone.
            fresh=lambda rows:bool(rows and -timedelta(seconds=5)<=at-rows[-1]['end']<timedelta(seconds=15))
            active=[(r['start'],r['end']) for r in idle if r['data'].get('status')=='not-afk']
            inactive=[(r['start'],r['end']) for r in idle if r['data'].get('status')=='afk']
            if any(intersection(a,b,inactive) for a,b in active):raise Unavailable('ambiguous_idle')
            with self.lock:
                if self.halt.is_set() or self.store.preferences()!=p or self.boundary!=boundary:return
                current_app=events[-1]['data'].get('app') if events else None
                self.current_application=None;self.current_website=None
                present=fresh(events) and fresh(idle) and idle[-1]['data'].get('status')=='not-afk'
                if (present and isinstance(current_app,str) and current_app in p['applications']
                        and not excluded(current_app,p) and not excluded(str(events[-1]['data'].get('title','')),p)):
                    self.current_application=dict(app=current_app,name=NAMES.get(current_app.casefold(),current_app),
                        start=stamp(max(events[-1]['start'],authorized_start)),observed_at=stamp(events[-1]['end']),
                        elapsed=sum((b-a).total_seconds() for a,b in intersection(max(events[-1]['start'],authorized_start),events[-1]['end'],active)))
                    if current_app.casefold()=='firefox' and fresh(browser_events):
                        self.current_website=browser_metadata(browser_events[-1]['data'],p)
                        if self.current_website is not None:
                            current=browser_events[-1]
                            foreground=[(r['start'],r['end']) for r in events if str(r['data'].get('app','')).casefold()=='firefox']
                            spans=[span for a,b in foreground for span in intersection(a,b,active)]
                            self.current_website.update(start=stamp(max(current['start'],authorized_start)),
                                observed_at=stamp(current['end']),category=self.store.website_category(self.current_website['domain']),
                                elapsed=sum((b-a).total_seconds() for a,b in intersection(max(current['start'],authorized_start),current['end'],spans)))
                self.current_activity=('Idle' if idle and idle[-1]['data'].get('status')=='afk' else
                    'Active application: '+self.current_application['name'] if self.current_application else 'Unknown activity')
                self.application_state='Monitoring ON' if fresh(events) and fresh(idle) else 'Collection unavailable (stale watcher)'
                self.state='ON' if fresh(events) and fresh(idle) else 'WATCHER UNAVAILABLE'
                self.idle=idle[-1]['data']['status']=='afk' if idle else None;self.observed=at
                self.browser_state='Browser monitoring ON' if fresh(browser_events) and fresh(events) and fresh(idle) else 'Browser collection unavailable'
                covered=max((r['end'] for r in idle),default=start)
                changed=self.ingest(windows[0],events,active,p,authorized_start,at,completed_until=covered)
                if browser_events:
                    foreground=[(r['start'],r['end']) for r in events if str(r['data'].get('app','')).casefold()=='firefox']
                    browser_active=[]
                    for a,b in foreground:browser_active.extend(intersection(a,b,active))
                    changed+=self.ingest(browsers[0],browser_events,browser_active,p,authorized_start,at,browser=True,completed_until=covered)
                if changed:self.revision+=1
        except Unavailable as failure:
            with self.lock:
                self.application_state=self.browser_state='Collection unavailable'
                self.current_application=self.current_website=None
                self.state='SERVICE UNAVAILABLE' if str(failure).startswith('activitywatch_unavailable') else 'WATCHER UNAVAILABLE'

    def ingest(self,bucket,events,active,p,start,at,browser=False,completed_until=None):
        count=0
        # The last heartbeat can still be extended: only a successor proves completion.
        for index,event in enumerate(events):
            latest=index==len(events)-1
            if latest and at-event['end']<=timedelta(seconds=90):continue
            if not latest and event['end']>events[index+1]['start']:continue
            if event['end']<=start or event['end']>at:continue
            if completed_until is not None and event['end']>completed_until:continue

            data=event['data'];app='firefox' if browser else data.get('app')
            if type(app) is not str or app not in p['applications'] or excluded(app,p) or excluded(str(data.get('title','')),p):continue
            fields=dict(title='',domain='',url='')
            if browser:
                fields=browser_metadata(data,p)
                if fields is None:continue
            elif p['titles'] and app.casefold()!='firefox':fields['title']=safe_title(data.get('title',''))
            # No inferred project from titles or process arguments. Explicit association only.
            records=[]
            source=hashlib.sha256(f'{bucket}:{event["id"]}'.encode()).hexdigest()
            for a,b in intersection(max(event['start'],start),event['end'],active):
                identity=hashlib.sha256(f'{source}:{stamp(a)}'.encode()).hexdigest()
                record=dict(id=identity,kind='browser' if browser else 'application',app=app,
                    name='Firefox — '+fields['domain'] if browser else NAMES.get(app.casefold(),app),start=a,end=b,
                    category=self.store.website_category(fields['domain']) if browser else CATEGORIES.get(app.casefold(),'Other'),state='interrupted' if latest else 'completed',project='',**fields)
                records.append(record)
            count+=self.store.reconcile(source,records)
        return count
