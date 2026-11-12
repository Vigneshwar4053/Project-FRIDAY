"""Bounded Linux metadata collectors and parsers. Never read cmdline/environ/log messages."""
from collections import Counter
import json
import os
from pathlib import Path
import re
import shutil
import time


def read(path,limit=16384):
    with Path(path).open('rb') as f:
        return f.read(limit).decode(errors='replace')

def meminfo():
    return {key:int(value.split()[0])*1024 for key,value in (line.split(':',1) for line in read('/proc/meminfo').splitlines()) if value.split() and value.split()[0].isdigit()}

def processes(cancel,limit=512):
    entries=[]
    def sample(path):
        value=read(path/'stat',4096); close=value.rfind(')'); fields=value[close+2:].split()
        return int(fields[11])+int(fields[12]),int(fields[21])*os.sysconf('SC_PAGE_SIZE')
    # Bounded PID enumeration; no source files or process argument strings.
    import itertools
    with os.scandir('/proc') as directory:
        pids=[Path(e.path) for e in itertools.islice((e for e in directory if e.name.isdecimal()),limit)]
    before={}
    for path in pids:
        if cancel.is_set(): break
        try: before[path]=sample(path)
        except (OSError,ValueError,IndexError): pass
    started=time.monotonic(); cancel.wait(.2); elapsed=max(.001,time.monotonic()-started)
    for path,(ticks,_) in before.items():
        if cancel.is_set(): break
        try:
            after,rss=sample(path)
            name=read(path/'comm',256).strip()
            try: executable=os.readlink(path/'exe')[:512]
            except OSError: executable='Unavailable'
            entries.append({'pid':int(path.name),'name':name,'owner_uid':path.stat().st_uid,
                'rss_bytes':rss,'cpu_percent':round(max(0,after-ticks)/os.sysconf('SC_CLK_TCK')/elapsed*100,1),
                'executable':executable})
        except (OSError,ValueError,IndexError): pass
    top_cpu=sorted(entries,key=lambda r:r['cpu_percent'],reverse=True)[:10]
    top_ram=sorted(entries,key=lambda r:r['rss_bytes'],reverse=True)[:10]
    return {'sampled_processes':len(entries),'enumeration_limit':limit,'top_cpu':top_cpu,'top_memory':top_ram,
        'limitation':'Short sampling interval; CPU percent is per core. No historical growth or malware conclusion.'}

def disk():
    d=shutil.disk_usage('/')
    return {'root_total_bytes':d.total,'root_used_bytes':d.used,'root_free_bytes':d.free,'root_used_percent':round(100*d.used/d.total,1)}

def system(cancel,target):
    first=[int(x) for x in read('/proc/stat',1024).splitlines()[0].split()[1:9]]
    cancel.wait(.2)
    second=[int(x) for x in read('/proc/stat',1024).splitlines()[0].split()[1:9]]
    total=sum(second)-sum(first); idle=sum(second[3:5])-sum(first[3:5])
    memory=meminfo(); total_mem=memory.get('MemTotal',0); total_swap=memory.get('SwapTotal',0)
    cpu_model=next((line.split(':',1)[1].strip() for line in read('/proc/cpuinfo').splitlines() if line.startswith('model name')),'Unavailable')
    result={'cpu_model':cpu_model,'cpu_percent':round(100*(1-idle/total),1) if total else None,
        'ram_total_bytes':total_mem,'ram_used_percent':round(100*(1-memory.get('MemAvailable',0)/total_mem),1) if total_mem else None,
        'swap_total_bytes':total_swap,'swap_used_bytes':total_swap-memory.get('SwapFree',0),**disk()}
    result['processes']=processes(cancel)
    result['batteries']=[];result['temperatures_c']=[]
    for path in list(Path('/sys/class/power_supply').glob('*'))[:16]:
        try:
            if read(path/'type',64).strip()=='Battery':
                result['batteries'].append({'capacity_percent':float(read(path/'capacity',64)),'status':read(path/'status',64).strip()})
        except (OSError,ValueError): pass
    for path in list(Path('/sys/class/thermal').glob('thermal_zone*'))[:16]:
        try:
            temperature=float(read(path/'temp',64))/1000
            if -50<=temperature<=150: result['temperatures_c'].append(temperature)
        except (OSError,ValueError): pass
    result['not_checked']=['GPU health','SMART health','Memory faults','Historical measurements']
    if not result['batteries']:result['not_checked'].append('Battery status')
    if not result['temperatures_c']:result['not_checked'].append('Temperature sensors')
    return result

def storage(cancel,target):
    result=disk()
    result['not_checked']=['SMART health','Filesystem integrity','Recursive directory sizes','Cleanup safety']
    if target!='Local system metadata':
        result.update(project(cancel,target))
    result['cleanup_candidates']=['Review owner-selected build/cache areas manually; no deletion is proposed automatically.']
    return result

def project(cancel,target):
    if target=='Local system metadata':return {'not_checked':['Project-specific inspection — select a project first']}
    rows=[]
    flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC
    parent=os.open(Path(target).parent,flags)
    directory=None
    try:
        directory=os.open(Path(target).name,flags,dir_fd=parent)
        with os.scandir(directory) as entries:
            for index,entry in enumerate(entries):
                if index>=256 or cancel.is_set(): break
                if entry.name.startswith('.') or entry.is_symlink(): continue
                try:
                    st=entry.stat(follow_symlinks=False)
                    rows.append({'name':entry.name,'directory':entry.is_dir(follow_symlinks=False),'entry_bytes':st.st_size})
                except OSError:pass
    finally:
        if directory is not None:os.close(directory)
        os.close(parent)
    return {'project_exists':True,'visible_entries':rows[:100],
        'limitation':'Direct entry metadata only, bounded to 256 entries; directory entry size is not recursive content size. No scripts or source files read.'}

def security(cancel,target):
    from .registry import resolve_tool
    result={'audit_tools':{tool:bool(resolve_tool(tool)) for tool in ('nmap','ufw','ss')},'not_checked':['Current security update status (no package refresh)','SSH configuration contents','Firewall changes']}
    try:
        cache=read('/var/lib/update-notifier/updates-available',4096)
        counts=re.findall(r'\b(\d+)\s+updates?\b',cache)
        result['cached_update_counts']=[int(x) for x in counts[:5]]
        result['update_limitation']='Cached counts only; age and security classification unverified'
    except OSError:
        result['not_checked'].append('Cached update counts')
    return result

COLLECTORS={'system':system,'storage':storage,'processes':lambda cancel,target:processes(cancel),'security':security,'project':project}

def parse(kind,output):
    if kind=='json':
        value=json.loads(output)
        if type(value) is not list or len(value)>256:raise ValueError('Invalid bounded command schema')
        return {'records':value}
    if kind=='journal':
        rows=[json.loads(line) for line in output.splitlines() if line.strip().startswith('{')]
        if len(rows)>80:raise ValueError('Log metadata exceeds budget')
        priorities=Counter()
        for row in rows:
            if type(row) is not dict:raise ValueError('Invalid log metadata')
            priority=str(row.get('PRIORITY','unknown'))
            priorities[priority if priority in tuple(map(str,range(8))) else 'unknown']+=1
        return {'metadata_entries':len(rows),'priority_counts':dict(priorities),'not_checked':['Authentication failure counts (message access not authorized)','Private application log contents'],
            'limitation':'At most 80 visible metadata entries in the last hour; absence is not proof of no errors.'}
    if kind=='dev_ports':
        ports=Counter()
        for port in (3000,5000,5173,8000,8080,5432,6379):
            ports[str(port)]=len(re.findall(r':'+str(port)+r'\s',output))
        return {'common_development_listener_counts':dict(ports)}
    return {'line_count':len(output.splitlines())}
