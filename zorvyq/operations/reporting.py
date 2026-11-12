"""Session-only reports, sanitized display and conservative AI input."""
from dataclasses import asdict
from datetime import datetime,timezone
import json
import re

ANSI=re.compile(r'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|$))')

def sanitize(value,limit=32768):
    value=ANSI.sub('',str(value))
    value=''.join(c for c in value if c in '\n\t' or c.isprintable())
    value=re.sub(r'(?i)\b(password|passwd|token|secret|api[_-]?key|authorization)\s*[:=]\s*[^\s,;]+',r'\1=[REDACTED]',value)
    value=re.sub(r'(?i)\bBearer\s+\S+','Bearer [REDACTED]',value)
    value=re.sub(r'/home/[^/\s]+','/home/[USER]',value)
    value=re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b','[EMAIL]',value)
    return value[:limit]

def sanitize_tree(value):
    if isinstance(value,dict):return {sanitize(k,128):('[REDACTED]' if re.search(r'(?i)password|passwd|token|secret|api.?key|authorization',str(k)) else sanitize_tree(v)) for k,v in list(value.items())[:256]}
    if isinstance(value,(tuple,list)):return [sanitize_tree(v) for v in value[:256]]
    if isinstance(value,str):return sanitize(value)
    if value is None or type(value) in (int,float,bool):return value
    return None

def report(plan,results):
    metrics={r.stage_id:r.metrics for r in results if r.status=='COMPLETED'}
    completed=[r.stage_id for r in results if r.status=='COMPLETED']
    skipped=[r.stage_id for r in results if r.status=='NOT CHECKED']
    for stage,metric in metrics.items():
        skipped.extend(stage+': '+str(item) for item in metric.get('not_checked',[])[:32])
    failures=[r.stage_id for r in results if r.status not in ('COMPLETED','NOT CHECKED')]
    findings=[]
    for stage,metric in metrics.items():
        for key,threshold in (('ram_used_percent',85),('cpu_percent',85),('root_used_percent',90)):
            value=metric.get(key)
            if type(value) in (int,float) and value>=threshold:
                findings.append({'kind':'observed','severity':'warning','description':key+' elevated at this sample',
                    'value':value,'evidence_ref':stage+'.'+key,'confidence':'Snapshot only; repeat measurements before diagnosing a cause.'})
    for stage in failures:
        findings.append({'kind':'observed','severity':'information','description':'Check did not complete','evidence_ref':stage,'confidence':'No healthy conclusion for this check.'})
    hypotheses=[]
    for stage,metric in metrics.items():
        ram=metric.get('ram_used_percent'); swap=metric.get('swap_used_bytes')
        if type(ram) in (int,float) and ram>=85 and type(swap) in (int,float) and swap>0:
            hypotheses.append({'kind':'hypothesis','description':'Memory pressure may contribute to slowness.',
                'evidence_refs':[stage+'.ram_used_percent',stage+'.swap_used_bytes'],
                'limitation':'Swap occupancy does not measure current swapping; repeat samples and inspect process usage. No memory leak is established.'})
    return sanitize_tree({'schema':'zorvyq.operation-report.v1','operation_id':plan.operation_id,
        'timestamp':datetime.now(timezone.utc).isoformat(),'target':plan.target,
        'purpose':plan.purpose,
        'summary':f'{len(completed)} command/collector stages completed; {len(skipped)} checks NOT CHECKED; {len(failures)} stage failures. Inspect scope and limitations.',
        'checks_attempted':[r.stage_id for r in results], 'checks_completed':completed,'checks_skipped':skipped,'check_failures':failures,
        'observed_metrics':metrics,'stages':[asdict(r) for r in results],'findings':findings,'hypotheses':hypotheses,
        'severity':'warning' if any(f['severity']=='warning' for f in findings) else 'information',
        'limitations':['NOT CHECKED is never HEALTHY. No stress tests, repairs, traffic probes or configuration changes were performed unless this is explicitly the network discovery operation.',
            'No historical trend data; a single reading cannot establish a memory leak, malware, or root cause.',
            'Disk space observations do not establish hardware health. Redaction is best effort; review before exporting.'],
        'recommended_next_steps':['Review skipped and failed checks; request a separately approved follow-up if needed.',
            'Repeat elevated measurements and inspect the identified processes before considering changes.'],
        'ai_analysis':None})

def analysis_input(value):
    """Numeric observations only. No raw stdout/logs/paths/process names to the LLM."""
    rows=[]
    for stage,metrics in value.get('observed_metrics',{}).items():
        for key,metric in metrics.items():
            if key in {'cpu_percent','ram_total_bytes','ram_used_percent','swap_total_bytes','swap_used_bytes','root_total_bytes','root_used_bytes','root_free_bytes','root_used_percent','sampled_processes','enumeration_limit','metadata_entries','line_count'} and type(metric) in (int,float) and len(rows)<40:
                rows.append({'evidence_ref':stage+'.'+key,'value':metric})
    return {'operation_id':value['operation_id'],'observations':rows,
        'completed_count':len(value['checks_completed']),'skipped_count':len(value['checks_skipped']),
        'failure_count':len(value['check_failures']),'limitations':['Snapshot only; no root cause confirmed.']}

def export_json(value,path):
    from pathlib import Path
    import os
    path=Path(path)
    if path.is_symlink():raise ValueError('Export symlinks are not allowed.')
    # A new owner-selected file only. Never silently overwrite another report.
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as stream:
        json.dump(sanitize_tree(value),stream,indent=2);stream.flush();os.fsync(stream.fileno())


def markdown(value):
    value=sanitize_tree(value)
    sections=[('# OPERATION',value.get('operation_id','Unknown')),
              ('## STATUS',value.get('execution_status','Unknown')),
              ('## OBSERVATIONS',json.dumps(value.get('observed_metrics',{}),indent=2)),
              ('## FINDINGS',json.dumps(value.get('findings',[]),indent=2)),
              ('## AI INTERPRETATION',json.dumps(value.get('ai_analysis') or 'Not requested; no AI interpretation performed.',indent=2)),
              ('## RECOMMENDATIONS','\n'.join(value.get('recommended_next_steps',[]))),
              ('## LIMITATIONS','\n'.join(value.get('limitations',[]))),
              ('## COMMAND RESULTS',json.dumps(value.get('stages',[]),indent=2))]
    return '\n\n'.join(title+'\n\n'+text for title,text in sections)+'\n'


def export_markdown(value,path):
    import os
    from pathlib import Path
    path=Path(path)
    if path.is_symlink():raise ValueError('Export symlinks are not allowed.')
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(fd,'w') as stream:
        stream.write(markdown(value));stream.flush();os.fsync(stream.fileno())
