"""One sequential scheduler; exact approval precedes every operation."""
from dataclasses import replace
import json
from threading import Event,Lock
from time import monotonic
from .contracts import StageResult
from .collector import COLLECTORS
from .permissions import Permissions
from .registry import Registry
from .reporting import report,sanitize,sanitize_tree
from .runner import Runner

class Engine:
    def __init__(self,registry=None,runner=None):
        self.registry=registry or Registry();self.runner=runner or Runner()
        self.permissions=Permissions();self.cancelled=Event();self.lock=Lock()
        self.last_verified={};self.status='Idle';self.closed=False
    def preview(self,plan):
        operation=self.registry.validate(plan)
        return {'operation_id':plan.operation_id,'target':plan.target,'purpose':plan.purpose,
            'permissions':str(plan.permission),'fingerprint':plan.fingerprint,'privacy':operation.privacy,
            'required_tools':operation.required_tools,'input_schema':operation.input_schema,
            'side_effects':operation.side_effects,'limits':{'seconds':operation.time_limit,'bytes':operation.output_limit,'resources':operation.resource_budget},
            'stages':[{'id':s.stage_id,'purpose':s.purpose,'arguments':self.runner.preview(s) if s.tool else None,
                       'collector':s.collector,'timeout':s.timeout,'output_limit':s.output_limit} for s in plan.stages]}
    def approve(self,plan,*,confirmed=False,authorized_target=False):
        self.registry.validate(plan)
        if self.closed or self.lock.locked():raise RuntimeError('Operation engine is busy or closed.')
        self.cancelled.clear()
        return self.permissions.approve(plan,confirmed=confirmed,authorized_target=authorized_target)
    def run(self,plan,ticket,emit=lambda text:None):
        if self.closed:raise RuntimeError('Operation engine closed.')
        if not self.lock.acquire(blocking=False):raise RuntimeError('An operation is already running.')
        results=[]
        try:
            operation=self.registry.validate(plan)
            self.permissions.consume(plan,ticket)
            self.status='Running'
            deadline=monotonic()+operation.time_limit
            used=0
            scope_valid=True
            for stage in plan.stages:
                if scope_valid:
                    try:self.registry.validate(plan)
                    except (ValueError,OSError):scope_valid=False
                if not scope_valid:
                    results.append(StageResult(stage.stage_id,'NOT CHECKED',limitation='Approved path scope changed; remaining stages refused'))
                    continue
                if self.cancelled.is_set() or monotonic()>=deadline or used>=operation.output_limit:
                    reason='Cancelled' if self.cancelled.is_set() else 'Operation budget exhausted'
                    results.append(StageResult(stage.stage_id,'NOT CHECKED',limitation=reason))
                    continue
                emit(sanitize(stage.stage_id+' — '+stage.purpose,1024))
                if stage.tool:
                    bounded=replace(stage,timeout=min(stage.timeout,max(.01,deadline-monotonic())),output_limit=min(stage.output_limit,operation.output_limit-used))
                    try:
                        result=self.runner.run(bounded,self.cancelled,emit)
                    except Exception:
                        result=StageResult(stage.stage_id,'FAILED',limitation='Command runner failure; no raw exception retained')
                else:
                    started=monotonic()
                    try:
                        metrics=COLLECTORS[stage.collector](self.cancelled,plan.target)
                        result=StageResult(stage.stage_id,'CANCELLED' if self.cancelled.is_set() else 'COMPLETED',elapsed=round(monotonic()-started,3),metrics=sanitize_tree(metrics))
                        # Prevent unexpectedly large collector dictionaries reaching UI/AI.
                        if len(json.dumps(result.metrics).encode())>stage.output_limit:
                            result.metrics={};result.status='OUTPUT LIMIT'
                        emit(sanitize(json.dumps(result.metrics),stage.output_limit))
                    except (OSError,ValueError,KeyError,IndexError):
                        result=StageResult(stage.stage_id,'NOT CHECKED',limitation='Bounded collector data unavailable')
                emit(stage.stage_id+': '+result.status+' · exit='+str(result.exit_code)+' · elapsed='+str(result.elapsed)+'s'+(' · '+result.limitation if result.limitation else ''))
                results.append(result)
                used+=len(json.dumps(sanitize_tree(result.__dict__)).encode())
            value=report(plan,results)
            self.status=('Cancelled' if self.cancelled.is_set() else
                         'Failed' if not value['checks_completed'] and value['check_failures'] else
                         'Partial' if value['checks_skipped'] or value['check_failures'] else 'Completed')
            value['execution_status']=self.status
            if value['checks_completed']:
                self.last_verified[plan.operation_id]=value['timestamp']+' — actual execution; inspect skipped checks'
            return value
        finally:
            self.permissions.clear();self.lock.release()
    def cancel(self):self.cancelled.set()
    def close(self):
        self.cancel()
        if self.lock.locked():raise RuntimeError('Wait for cancellation before closing operation engine.')
        self.permissions.clear();self.closed=True
