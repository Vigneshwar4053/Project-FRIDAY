"""Bounded local Linux metrics. No command lines, socket peers or packet data."""
from pathlib import Path
from threading import Event
from zorvyq.operations.collector import processes, read


def snapshot(*, include_processes=False, include_network=False):
    result={'batteries':[], 'interfaces':[]}
    for path in list(Path('/sys/class/power_supply').glob('*'))[:16]:
        try:
            if read(path/'type',64).strip()=='Battery':
                result['batteries'].append({'capacity_percent':float(read(path/'capacity',64)),
                                           'status':read(path/'status',64).strip()})
        except (OSError,ValueError):pass
    for path in list(Path('/sys/class/net').glob('*'))[:64]:
        try:
            result['interfaces'].append({'name':path.name[:64], 'state':read(path/'operstate',32).strip()})
        except OSError:pass
    if include_processes:
        sampled=processes(Event(),limit=256)
        import os
        result['processes']=[{k:r[k] for k in ('pid','name','rss_bytes','cpu_percent')}
            for r in {r['pid']:r for r in sampled['top_cpu']+sampled['top_memory']}.values()
            if r['owner_uid']==os.getuid()]
    if include_network:
        counts={}
        for protocol in ('tcp','tcp6','udp','udp6'):
            try:
                lines=read('/proc/net/'+protocol,131072).splitlines()[1:]
                counts[protocol]={'observed_entries':len(lines),
                    'established':sum(len(x.split())>3 and x.split()[3]=='01' for x in lines),
                    'bounded_bytes':131072}
            except OSError:counts[protocol]={'available':False}
        result['network']=counts
    return result
