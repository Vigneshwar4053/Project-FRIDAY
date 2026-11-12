"""Reviewed operation definitions. Fixed tools/flags; no shell or model input."""
from pathlib import Path
import ipaddress
import os
from .contracts import Operation, Stage, Plan, Permission
from zorvyq.projects import PROJECT_ROOT
from zorvyq.security import validate_target, discovery_arguments

# Resolve only known OS installations; never search an owner-controlled PATH.
TOOLS = {
 'ip':('/usr/sbin/ip','/usr/bin/ip','/sbin/ip'), 'nmcli':('/usr/bin/nmcli',),
 'ss':('/usr/bin/ss','/usr/sbin/ss'), 'systemctl':('/usr/bin/systemctl',),
 'ufw':('/usr/sbin/ufw',), 'journalctl':('/usr/bin/journalctl',),
 'git':('/usr/bin/git',), 'python':('/usr/bin/python3',), 'node':('/usr/bin/node',),
 'docker':('/usr/bin/docker','/snap/bin/docker'), 'nmap':('/usr/bin/nmap',),
 'free':('/usr/bin/free',), 'df':('/usr/bin/df',), 'uptime':('/usr/bin/uptime',),
 'prlimit':('/usr/bin/prlimit',),
}

def resolve_tool(name):
    for value in TOOLS.get(name,()):
        if Path(value).is_file() and os.access(value,os.X_OK): return value
    return None

def command(identity,purpose,tool,*args,parser='text',expected_codes=(0,)):
    return Stage(identity,purpose,tool,tuple(args),parser=parser,expected_codes=expected_codes)

def metric(identity, collector, purpose):
    return Stage(identity,purpose,collector=collector)

HEALTH=(metric('resources','system','Sample CPU, memory, swap, root filesystem, battery and temperature'),
 command('memory-summary','Memory and swap summary','free','-h'),
 command('disk-summary','Filesystem usage summary','df','-h'),
 command('uptime','Uptime and load averages','uptime'))
NETWORK=(command('interfaces','Interface state and local addresses','ip','-j','address','show',parser='json'),
 command('routes','Local routing table and gateways','ip','-j','route','show',parser='json'),
 command('wifi','NetworkManager device connection state; no passwords or SSIDs','nmcli','-t','-f','DEVICE,TYPE,STATE','device','status'),
 command('dns','Configured DNS servers only','nmcli','-g','IP4.DNS,IP6.DNS','device','show'),
 command('network-listeners','Listening socket summary; no probes','ss','-tuln'))
SECURITY=(command('firewall','Read firewall status without elevation','ufw','status'),
 command('listeners','Listening transport endpoints; a listener is not a vulnerability','ss','-H','-lntu'),
 command('failed-services','Failed system services','systemctl','--failed','--no-legend','--no-pager'),
 command('ssh','SSH service activity only; no configuration content','systemctl','is-active','ssh.service','sshd.service',expected_codes=(0,3,4)),
 metric('security-metadata','security','Cached update counts and audit-tool availability'))
LOGS=(command('error-counts','Last-hour error metadata only (no message text)','journalctl','--since=-1h','--priority=0..3','-n','80','--no-pager','-o','json','--output-fields=PRIORITY,SYSLOG_IDENTIFIER,_SYSTEMD_UNIT',parser='journal'),
 command('kernel-counts','Last-hour kernel warning metadata only','journalctl','-k','--since=-1h','--priority=0..4','-n','80','--no-pager','-o','json','--output-fields=PRIORITY,SYSLOG_IDENTIFIER,_SYSTEMD_UNIT',parser='journal'))
STORAGE=(metric('storage','storage','Root disk usage and optional approved-directory metadata (no recursion)'),)
PROCESS=(metric('processes','processes','At most 512 /proc entries; names, ownership, executable metadata, sampled CPU/RAM'),
 command('connections','Local connection endpoint metadata where accessible','ss','-H','-nt'))
DEV=(command('git','Git availability/version','git','--version'),command('python','System Python version','python','--version'),
 command('node','Node.js availability/version','node','--version'),command('docker','Docker CLI version only; no daemon contact','docker','--version'),
 metric('project','project','Optional selected project metadata; no scripts or source contents'),
 command('dev-ports','Local listeners; parser retains common development ports only','ss','-H','-lnt',parser='dev_ports'))

OPERATIONS = (
 Operation('system.health','System Health','Inspect measured resource snapshots.',stages=HEALTH),
 Operation('network.overview','Network Overview','Inspect existing local connection metadata; no probes.',stages=NETWORK),
 Operation('network.discovery','Authorized Network Discovery','Explicit bounded private/lab host discovery.',Permission.NETWORK,
    input_schema='target: private IP/CIDR <=256 addresses; purpose: 1..512 printable characters',target_scope='Exact authorized private/lab target; public targets unsupported',side_effects=('Sends bounded host-discovery probes to the exact authorized target',)),
 Operation('security.overview','System Security Overview','Read-only posture metadata; inaccessible checks are NOT CHECKED.',stages=SECURITY),
 Operation('process.monitor','Process Monitor','Resource observations are not proof of malware.',stages=PROCESS),
 Operation('logs.overview','Log Overview','Bounded error counts and service metadata; no raw message bodies.',stages=LOGS),
 Operation('storage.overview','Storage Overview','Space and pressure; no SMART health or deletion.',stages=STORAGE,input_schema='Optional approved direct project directory'),
 Operation('developer.environment','Developer Environment','Installed tool versions and selected project metadata only.',stages=DEV,input_schema='Optional approved direct project directory'),
 Operation('system.diagnosis','Full System Diagnosis','Bounded read-only orchestration; never includes discovery.',stages=HEALTH+STORAGE+SECURITY+NETWORK+PROCESS+LOGS,time_limit=120),
 Operation('investigate.slow','Why is my laptop slow?','Correlate snapshots; no repair or unsupported root-cause assertion.',stages=HEALTH+STORAGE+PROCESS+LOGS,time_limit=90),
)

FUTURE_GROUPS = {
 'hardware':('CPU diagnostics','RAM diagnostics','GPU diagnostics','Storage SMART health','Battery health','Firmware inventory','USB device status','Audio diagnostics'),
 'os':('Boot diagnostics','Kernel diagnostics','Driver status','Service diagnostics','Package diagnostics','Permission diagnostics','Environment diagnostics','Filesystem diagnostics'),
 'network':('DNS diagnostics','Wi-Fi diagnostics','Routing','Firewall inspection','Listening ports','Bandwidth','Network stability','VPN status','Certificate expiry','Bluetooth status'),
 'developer':('Python environments','Node.js environments','Git status','Docker health','Database connectivity','Port conflicts','Dependency auditing','Project diagnostics','API health'),
 'advanced':('Bottleneck analysis','Crash investigation','Memory-growth monitoring','Power consumption','Thermal throttling','Startup optimization','Security posture','Defensive malware investigation','Intrusion investigation','Configuration baseline comparison'),
 'maintenance':('Storage cleanup previews','Versioned backups','Backup verification','Restore previews','Update checks','Package maintenance','Service repair proposals'),
}

def future_operations():
    return tuple(Operation('future.'+group+'.'+str(i),title,'Design review and individual approval required.',
        Permission.CHANGE if group=='maintenance' else Permission.LOCAL,implemented=False,verification='Unavailable — not implemented')
        for group, names in FUTURE_GROUPS.items() for i,title in enumerate(names,1))

class Registry:
    def __init__(self, project_root=PROJECT_ROOT):
        self.project_root=Path(project_root).resolve()
        self.operations={o.operation_id:o for o in OPERATIONS+future_operations()}
    def project(self,path):
        lexical=Path(path)
        if '..' in lexical.parts or any(not c.isprintable() for c in str(lexical)):
            raise ValueError('Invalid project path.')
        resolved=lexical.resolve(strict=True)
        if lexical.parent!=self.project_root or resolved.parent!=self.project_root or not resolved.is_dir() or lexical.name.startswith('.'):
            raise ValueError('Select a visible direct project folder inside the approved root.')
        return resolved
    def projects(self):
        rows=[]
        try:
            for p in self.project_root.iterdir():
                try: rows.append(self.project(p))
                except (ValueError,OSError): pass
        except OSError: pass
        return tuple(sorted(set(rows),key=lambda p:(p.name.casefold(),p.name)))
    def plan(self,operation_id,inputs=None):
        operation=self.operations[operation_id]
        if not operation.implemented: raise ValueError('Operation is not implemented.')
        inputs=dict(inputs or {})
        target='Local system metadata'
        purpose=operation.purpose
        stages=operation.stages
        if operation_id=='network.discovery':
            if set(inputs)!={'target','purpose'}: raise ValueError('Target and purpose required.')
            target=validate_target(inputs['target'])
            try: network=ipaddress.ip_network(target,strict=True)
            except ValueError: raise ValueError('Use an exact private IP/CIDR; hostname resolution and public scans are unsupported here.') from None
            if not network.is_private or network.is_loopback or network.is_link_local or network.is_reserved:
                raise ValueError('Only private/lab targets are supported; no public scope.')
            purpose=inputs['purpose']
            if type(purpose) is not str or not purpose.strip() or len(purpose)>512 or any(not c.isprintable() for c in purpose):
                raise ValueError('Enter a printable assessment purpose.')
            args=discovery_arguments(target)
            stages=(Stage('discovery',purpose,'nmap',args,timeout=30,output_limit=65536),)
        elif inputs:
            if operation_id not in ('storage.overview','developer.environment') or set(inputs)!={'project'}:
                raise ValueError('Unexpected operation inputs.')
            target=str(self.project(inputs['project']))
        return Plan(operation_id,target,purpose,stages,operation.permission)
    def validate(self,plan):
        if plan.operation_id=='network.discovery': inputs={'target':plan.target,'purpose':plan.purpose}
        elif plan.target!='Local system metadata': inputs={'project':plan.target}
        else: inputs={}
        if self.plan(plan.operation_id,inputs)!=plan: raise ValueError('Operation plan changed or contains unapproved commands.')
        return self.operations[plan.operation_id]
    def availability(self,operation_id):
        operation=self.operations[operation_id]
        if not operation.implemented: return 'Unavailable — not implemented'
        stages=operation.stages
        if operation_id=='network.discovery': stages=(Stage('discovery','','nmap'),)
        missing={s.tool for s in stages if s.tool and not resolve_tool(s.tool)}
        if any(s.tool for s in stages) and not resolve_tool('prlimit'): missing.add('prlimit')
        if missing: return 'Partial / NOT CHECKED: '+', '.join(sorted(missing))
        return 'Available — experimental, owner acceptance pending'
