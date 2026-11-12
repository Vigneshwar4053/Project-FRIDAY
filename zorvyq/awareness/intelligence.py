"""Deterministic grounded answers; no SQL, browser titles or URLs given to a model."""
from datetime import datetime, timedelta
import re
from .store import EMPTY

QUERIES={
 'what were my last three activities':'recent', 'what were my last 3 activities':'recent',
 'what was i working on yesterday':'yesterday', 'which applications did i use today':'apps',
 'how long was i programming':'programming', 'what websites did i visit':'websites',
 'how much time did i spend studying':'studying', 'what did i complete today':'tasks',
 'which project should i continue':'continue',
 'what application am i using':'current',
 'what was i doing yesterday':'yesterday',
 'how much time did i spend programming':'programming',
 'which websites did i visit today':'websites',
 "summarize today's activity":'apps',
 'summarize my activity today':'apps',
}

def intent(text):
    text=re.sub(r'^(?:zorvyq|friday)[, ]+','',text.strip().casefold()).rstrip('.!?')
    return QUERIES.get(text)

def answer(kind,store,tasks=None,*,authorized=False,at=None,manager=None):
    if kind not in set(QUERIES.values()):raise ValueError('Unsupported activity query')
    if not authorized:raise PermissionError('Allow-once activity access required')
    at=at or datetime.now().astimezone();start=at.replace(hour=0,minute=0,second=0,microsecond=0);end=at
    if kind=='current':
        live=manager.snapshot() if manager is not None else {}
        app=live.get('application')
        return ('Current observed application: '+app['name']+'.') if app else 'Current application unavailable. No fresh approved foreground activity is recorded.'
    if kind=='recent':
        rows=store.last_three()
        return ('Your last recorded completed activities were '+', '.join(r['name'] for r in rows)+'.') if rows else EMPTY
    if kind=='continue':
        rows=[r for r in store.last_three() if r['project']]
        if not rows:return 'No approved project association is recorded. Choose an approved project from the dashboard.'
        return 'Your most recent recorded project was '+rows[0]['project']+'. Resume it intentionally from activity details.'
    if kind=='tasks':
        if tasks is None:return 'Task records are unavailable.'
        rows=[r for r in tasks.rows(view='Completed') if r['completed'] and start<=datetime.fromisoformat(r['completed'])<=end]
        return ('Completed today: '+', '.join(r['title'] for r in rows[:50])+'.') if rows else 'No completed tasks recorded today.'
    if kind=='yesterday':end=start;start-=timedelta(days=1)
    if kind=='websites' and not store.preferences()['browser']:
        return 'Browser monitoring is off. No browsing records were accessed.'
    rows=store.totals(start,end,category={'programming':'Programming','studying':'Studying'}.get(kind,''),browser=kind=='websites')
    if not rows:return 'No authorized completed activity recorded for that time range.'
    return 'Recorded active time: '+ '; '.join(f"{r['name']}: {max(0,round(r['seconds']))} seconds ({r['count']} intervals)" for r in rows)+'.'

def summarize(kind,store,controller,*,authorized=False,model_authorized=False,model='qwen3:4b'):
    """Optional exact-consent local model interpretation of numeric categories only."""
    if not authorized or not model_authorized:raise PermissionError('Separate local summary consent required')
    if kind not in ('apps','programming','studying','yesterday'):raise ValueError('Private summary scope refused')
    facts=answer(kind,store,authorized=True)
    at=datetime.now().astimezone();start=at.replace(hour=0,minute=0,second=0,microsecond=0);end=at
    if kind=='yesterday':end=start;start-=timedelta(days=1)
    aggregates=[]
    for category in ('Programming','Browsing','Terminal','Files','Studying','Other'):
        rows=store.totals(start,end,category=category)
        if rows:aggregates.append(dict(category=category,seconds=max(0,round(sum(r['seconds'] for r in rows))),count=sum(r['count'] for r in rows)))
    if not aggregates:return facts+' Optional local summary unavailable: no aggregate records.'
    try:interpretation=controller.summarize_activity(aggregates,model=model)
    except Exception:return facts+' Optional local summary unavailable.'
    return facts+'\nOptional model interpretation (unverified): '+str(interpretation)[:1000]

class ActivityQueries:
    """Reuse existing exact-plan, expiring, one-use operation permissions."""
    def __init__(self,store,tasks,permissions,manager=None):
        self.store=store;self.tasks=tasks;self.permissions=permissions
        self.manager=manager
    def plan(self,kind):
        from zorvyq.operations.contracts import Plan, Permission
        if kind not in set(QUERIES.values()):raise ValueError('Unsupported activity query')
        return Plan('activity.'+kind,str(self.store.path),kind,(),Permission.LOCAL)
    def run(self,plan,ticket):
        kind=plan.purpose
        if plan!=self.plan(kind):raise PermissionError('Activity query scope changed')
        self.permissions.consume(plan,ticket)
        return answer(kind,self.store,self.tasks,authorized=True,manager=self.manager)

    def summary_plan(self):
        from zorvyq.operations.contracts import Plan, Permission
        return Plan('activity.summary',str(self.store.path),'Today: numeric category totals only',(),Permission.LOCAL)
    def summarize(self,plan,ticket,controller,model):
        if plan!=self.summary_plan():raise PermissionError('Summary scope changed')
        self.permissions.consume(plan,ticket)
        return summarize('apps',self.store,controller,authorized=True,model_authorized=True,model=model)
