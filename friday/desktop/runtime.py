"""Exact-target leases around the existing typed gateway; fixed native launches."""
from contextlib import contextmanager,ExitStack
from contextvars import ContextVar
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import subprocess
from uuid import uuid4
from types import MappingProxyType
from threading import Event
from time import monotonic
from friday.desktop.handoffs import HandoffOperation, HandoffRequest, HandoffTarget, HandoffProof, HandoffVerifier, HANDOFF_TOOLS
from friday.desktop.accessibility import Deadline, DesktopFailure

from friday.desktop.registry import ApplicationRegistry
from friday.desktop.snap import ReviewedSnap
from friday.desktop.guard import RecentLaunchGuard
from friday.desktop.navigation import FileManagerNavigationController
from friday.desktop.browser import ManagedBrowser, BrowserHealthUnavailable
from friday.desktop.routing import DESKTOP_TOOLS
from friday.desktop.sessions import DesktopSessionStore
from friday.desktop.recent import RecentWorkQueue, reviewed_url, ACCEPTED_LAUNCH_STATUSES
from friday.tools.access import FolderDecision, FilesystemAuthorizationDenied
from friday.tools.base import Tool
from friday.tools.grants import approved_folder,directory_descriptor,lexical_path
from friday.tools.locations import SemanticLocationResolver
from friday.tools.models import ArgumentSpec,ArgumentType,RiskLevel,ToolSpec


def desktop_environment():
    """No inherited loader/interpreter variables, tokens or arbitrary bus address."""
    kind=os.environ.get('XDG_SESSION_TYPE','')
    display=os.environ.get('DISPLAY','')
    wayland=os.environ.get('WAYLAND_DISPLAY','')
    if kind not in {'x11','wayland'}: return kind,None
    env={'HOME':str(Path.home()),'PATH':'/usr/bin:/bin','LANG':'C.UTF-8','XDG_SESSION_TYPE':kind}
    if re.fullmatch(r':[0-9]+(?:\.[0-9]+)?',display): env['DISPLAY']=display
    runtime=os.environ.get('XDG_RUNTIME_DIR','')
    if runtime:
        try:
            with directory_descriptor(lexical_path(runtime)) as fd:
                info=os.fstat(fd)
                if info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700: raise ValueError('Unsafe runtime.')
            env['XDG_RUNTIME_DIR']=runtime
            env['DBUS_SESSION_BUS_ADDRESS']='unix:path='+str(Path(runtime)/'bus')
            if re.fullmatch(r'wayland-[0-9]+',wayland): env['WAYLAND_DISPLAY']=wayland
            auth=os.environ.get('XAUTHORITY','')
            if auth and Path(auth).is_relative_to(Path(runtime)):
                with directory_descriptor(Path(auth).parent) as parent:
                    auth_fd=os.open(Path(auth).name,os.O_PATH|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent)
                    try:
                        auth_info=os.fstat(auth_fd)
                        if stat.S_ISREG(auth_info.st_mode) and auth_info.st_uid==os.getuid() and stat.S_IMODE(auth_info.st_mode)==0o600:
                            env['XAUTHORITY']=auth  # Path only; never read authentication cookies.
                    finally: os.close(auth_fd)
        except (OSError,ValueError): pass
    if kind=='x11' and 'DISPLAY' not in env or kind=='wayland' and 'WAYLAND_DISPLAY' not in env: return kind,None
    return kind,env


@dataclass(frozen=True)
class DesktopApproval:
    operation: str
    target: str
    effect: str
    risk: str
    def prompt(self):
        return ('Permission required:\nOperation: '+self.operation+'\nTarget: '+json.dumps(self.target,ensure_ascii=True)+
                '\nRisk: '+self.risk+'\nIntended side effect: '+self.effect+
                '\nExact operation/target only. No filesystem read grant or persistent desktop grant.\n'
                '[1] Allow once\n[3] Deny')


class DesktopExecutor:
    """Launch approved native identities; no arbitrary arguments or shell strings."""
    def __init__(self,applications,profile_root):
        self.applications=applications;self.profile_root=Path(profile_root)
        self.children=[];self.launch_count=0
        self.folder_pins={}
    def close(self):
        # Do not terminate GUI applications that the owner explicitly launched.
        for child in self.children: child.poll()  # Reap finished children.
        self.children.clear()
        for fd in self.folder_pins.values(): os.close(fd)
        self.folder_pins.clear()
    @contextmanager
    def _profile(self):
        # Every write is descriptor-relative beneath a private verified root.
        # A fresh profile never inherits existing workspace trust/extensions.
        with directory_descriptor(self.profile_root,create=True) as directory:
            info=os.fstat(directory)
            if info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700:
                raise ValueError('Private profile directory unavailable.')
            name='code-'+uuid4().hex
            os.mkdir(name,0o700,dir_fd=directory)
            profile=os.open(name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=directory)
            try:
                os.mkdir('User',0o700,dir_fd=profile)
                user=os.open('User',os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=profile)
                try:
                    fd=os.open('settings.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW|os.O_CLOEXEC,0o600,dir_fd=user)
                    settings={'security.workspace.trust.enabled':True,'security.workspace.trust.startupPrompt':'always',
                              'task.allowAutomaticTasks':'off','files.hotExit':'off','window.restoreWindows':'none',
                              'telemetry.telemetryLevel':'off','extensions.autoUpdate':False,'update.mode':'none'}
                    with os.fdopen(fd,'w') as stream: json.dump(settings,stream)
                finally: os.close(user)
                yield profile
            finally: os.close(profile)

    def launch(self,lease):
        if self.launch_count>=4:
            return {'status':'unavailable','message':'Desktop launch limit reached for this session; restart FRIDAY before more launches.'}
        with ExitStack() as resources:
            argv=[str(lease['executable'])]; fds=[lease['binary_fd']]
            if lease.get('snap'):
                if lease['snap_backend'].review(lease['application_id'])!=lease['snap_identity']:
                    raise ValueError('Snap metadata changed before execution.')
                argv+=ReviewedSnap.arguments(lease['application_id'],path=lease['path'],url=lease['url'])
                lease['environment']['SNAP_REEXEC']='0'
            if lease['application_id']=='vscode':
                profile=resources.enter_context(self._profile())
                fds.append(profile)
                profile_path=os.readlink(f'/proc/self/fd/{profile}') if lease.get('snap') else f'/proc/self/fd/{profile}'
                argv+=['--new-window','--disable-extensions','--skip-add-to-recently-opened','--user-data-dir',profile_path]
            if lease['url'] is not None:
                argv += ['--new-window', reviewed_url(lease['url'])]
            new_pin=None
            if lease['directory_fd'] is not None:
                if lease['application_id']=='files':
                    # Nautilus can forward arguments over D-Bus to an existing
                    # process. Its /proc/self is NOT this launcher. Keep a stable
                    # parent descriptor through this session, shared by retries.
                    key=(str(lease['path']),lease['identity'])
                    if key not in self.folder_pins:
                        self.folder_pins[key]=os.dup(lease['directory_fd']);new_pin=key
                    pin=self.folder_pins[key]
                    info=os.fstat(pin)
                    if (info.st_dev,info.st_ino)!=lease['identity']: raise ValueError('Pinned folder changed.')
                    argv+=['--',f'/proc/{os.getpid()}/fd/{pin}']
                else:
                    fds.append(lease['directory_fd'])
                    argv+=['--',f'/proc/self/fd/{lease["directory_fd"]}']
            try:
                child=subprocess.Popen(argv,executable=f'/proc/self/fd/{lease["binary_fd"]}',
                                       stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                       close_fds=True,pass_fds=tuple(fds),env=lease['environment'],cwd='/',start_new_session=True)
            except OSError:
                if new_pin is not None: os.close(self.folder_pins.pop(new_pin))
                raise
            self.launch_count+=1
            self.children=[item for item in self.children if item.poll() is None]
            try:
                code=child.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.children.append(child)
                return {'status':'launch_outcome_unverified','message':'Launch attempted; application process is running after the bounded wait. Window visibility and requested target are not verified.'}
            except KeyboardInterrupt:
                self.children.append(child)
                raise
            if code!=0:
                return {'status':'launch_failed','message':'Application launch failed; no desktop state was confirmed.'}
            return {'status':'launch_accepted','message':'Launch request accepted by the OS; the launcher process exited normally. Window visibility and requested target are not verified.'}


class DesktopPermissionAdapter:
    """A request-local exact lease; never reuse/read/store filesystem grants."""
    def __init__(self,*,project_root,sensitive,approval=None,memory=None,applications=None,projects=None,executor=None,duplicate_window_seconds=20,owner_auth=None,handoff_verifier=None,clock=monotonic,browser_backend=None,firefox_url_adapter=None):
        self.applications=applications or ApplicationRegistry()
        from friday.security.owner import OwnerAuthenticator
        # Synthetic application registries are injected only by mock tests.
        self.owner_auth=owner_auth or (OwnerAuthenticator(Path(project_root)/'.env') if self.applications.production else None)
        self.snap=ReviewedSnap()
        self.projects=MappingProxyType(dict(projects or {'friday':lexical_path(str(project_root))}))
        if any(not re.fullmatch(r'[a-z][a-z0-9_]{0,31}',key) or not Path(value).is_absolute() for key,value in self.projects.items()):
            raise ValueError('Invalid trusted project registry.')
        self.sensitive=sensitive;self.approval=approval;self.sessions=DesktopSessionStore(memory)
        self.recent=RecentWorkQueue(memory)
        self.duplicate_guard=RecentLaunchGuard(duplicate_window_seconds)
        self.file_navigation=FileManagerNavigationController()
        self.browser=ManagedBrowser(profile_root=Path(project_root)/'data/browser-profiles');self.list_contents=None
        self.executor=executor or DesktopExecutor(self.applications,Path(project_root)/'data/desktop-profiles')
        self.locations=SemanticLocationResolver();self._lease=ContextVar('desktop_exact_lease',default=None)
        self.discovery=None
        self.handoff_verifier=handoff_verifier or HandoffVerifier()
        self.handoff_cancelled=Event();self.handoff_clock=clock
        from friday.desktop.browser_execution import BrowserExecution
        self.browser_execution=BrowserExecution(self.handoff_cancelled,clock,browser_backend)
        from friday.desktop.firefox_url_handoff import FirefoxUrlHandoff
        self.firefox_url_handoff=FirefoxUrlHandoff(self.handoff_cancelled,clock,firefox_url_adapter)

    def browser_available(self,target):
        return self.browser_execution.available(target) or self.firefox_url_handoff.available(target)
    def handles(self,request): return request.tool_name in DESKTOP_TOOLS
    def _blocked(self,message,status='unavailable'): return {'result':{'status':status,'message':message}}
    def _directory(self,path,*,home=False):
        path=lexical_path(str(path))
        if any(not c.isprintable() for c in str(path)) or self.sensitive.excluded_content(str(path).encode()):
            raise ValueError('Unsafe target display or sensitive content.')
        if home:
            if path!=Path.home() or self.sensitive.excluded(path): raise ValueError('Invalid home identity.')
            with directory_descriptor(path) as fd: info=os.fstat(fd)
            return path,(info.st_dev,info.st_ino)
        grant=approved_folder(path,self.sensitive)
        return path,(grant.device,grant.inode)
    def _prepare(self,request,stack):
        operation=request.tool_name;arguments=dict(request.arguments)
        if operation in HANDOFF_TOOLS: return self._prepare_handoff(request,stack)
        retry=arguments.pop('retry',False)
        if operation == 'show_recent_work':
            return {'result':{'status':'recent_work', 'message':self.recent.show(projects=arguments.get('projects',False),detailed=arguments.get('detailed',False))}}
        if operation == 'browser_status':
            diagnostics=self.browser.transport.diagnostics()
            return {'result':{'status':'browser_status','message':'FRIDAY Browser diagnostics: '+json.dumps(diagnostics,sort_keys=True)}}
        stored = None
        resolved=None
        if operation in {'discover_target','discovery_selection'}:
            if self.discovery is None: return self._blocked('Filesystem discovery is unavailable.')
            resolved=self.discovery.prepare(arguments,selection=operation=='discovery_selection')
            if 'result' in resolved: return resolved
            operation='open_resolved_target'
            arguments={'application_id':resolved['application_id'],'scope':resolved['scope'],'scope_identity':resolved['scope_identity'],'directory':resolved['directory']}
        backend=arguments.get('backend','original')
        if operation=='resume_activity' and backend not in {'original','friday_browser'}:
            return self._blocked('Unknown resume application.','invalid_target')
        if operation == 'resume_activity' and 'entry_id' not in arguments:
            # "Last work" offers the most recent currently viable activity.
            # An explicit numbered ID never falls back to another entry.
            from friday.tools.models import ToolRequest
            first_error = None
            skipped = 0
            for row in self.recent.rows():
                with ExitStack() as candidate_stack:
                    candidate = self._prepare(ToolRequest('resume_activity', {'entry_id':row['entry_id'], 'retry':retry, 'backend':backend}), candidate_stack)
                    if 'result' in candidate:
                        if candidate['result']['status'] in {'duplicate_suppressed','navigation_unsupported','launch_limit_reached','browser_health_unverified'}: return candidate
                        first_error = first_error or candidate
                        skipped += 1
                        continue
                    stack.enter_context(candidate_stack.pop_all())
                    if skipped:
                        candidate['effect'] = 'Earlier saved activities are invalid or unavailable. Offer the most recent currently valid activity. ' + candidate['effect']
                    return candidate
            return first_error or self._blocked('No valid saved activity matches; no recent work saved yet.', 'no_session')
        if operation == 'resume_activity':
            try:
                _, stored = self.recent.get(arguments.get('entry_id'))
            except (ValueError, KeyError, TypeError, RecursionError):
                return self._blocked('No valid saved activity matches; saved metadata may be invalid or absent.', 'no_session')
            operation = stored['operation']; arguments = stored['arguments']
            if operation=='open_resolved_target':
                resolved={**arguments,'path':stored['path'],'identity':stored['identity']}
            if backend=='friday_browser':
                if operation not in {'open_folder','navigate_browser'}:
                    return self._blocked('This saved activity has no approved browser folder; choose an explicit location.','invalid_target')
                operation='navigate_browser'
        if operation in {'navigate_browser','browser_history','browser_contents','browser_status'}:
            return self._prepare_browser(operation,arguments,stored,stack)
        # Legacy application-only Files entries resume through an exact Home
        # target approval too. They never supply authority over a window.
        if operation == 'launch_application' and arguments.get('application_id') == 'files':
            if 'url' in arguments: return self._blocked('Only Firefox supports reviewed links.')
            operation='open_folder';arguments={'folder_id':'home'}
        kind,environment=desktop_environment()
        if operation=='inspect_running_applications':
            return {'operation':operation,'target':'current desktop session','risk':'read_only',
                    'effect':'Check session capability only; no process/window/title/environment enumeration.',
                    'result':{'status':'unsupported','message':f'Reliable running-application inspection is unsupported in this {kind if kind in {"x11","wayland"} else "unknown/headless"} session; no application list was collected.'},
                    'requires_approval':True}
        if environment is None: return self._blocked('No supported local graphical session is available.')
        project_id=None;path=None;expected=None;home=False;url=None
        if operation=='launch_application':
            application_id=arguments['application_id']
            if 'url' in arguments:
                if application_id != 'firefox': return self._blocked('Only Firefox supports reviewed links.')
                try: url=reviewed_url(arguments['url'])
                except ValueError: return self._blocked('URL refused: use an explicitly reviewed HTTPS link without credentials, query or fragment.', 'invalid_target')
        elif operation=='open_folder':
            folder=arguments['folder_id']
            application_id='files';home=folder=='home'
            if folder.startswith('project_'):
                path=self.projects.get(folder[8:])
                if path is None: return self._blocked('Project folder is not registered; no path was inferred.')
            elif folder in {'downloads','documents','home'}:
                path=Path.home() if home else Path(self.locations.resolve(folder))
            else: return self._blocked('Folder alias is not supported.')
        elif operation in {'open_project','resume_project'}:
            project_id=arguments.get('project_id')
            if operation=='resume_project':
                candidates=self.sessions.yesterday(self.projects)
                if project_id is not None: candidates=tuple(item for item in candidates if item[0]==project_id)
                if not candidates: return self._blocked('No verified FRIDAY-managed project launch from yesterday is available.','no_session')
                if len(candidates)>1:
                    return self._blocked('Multiple verified projects match. Choose by typing "Resume yesterday\'s <project_id> project": '+', '.join(sorted(item[0] for item in candidates)), 'needs_selection')
                project_id,expected=candidates[0]
            path=self.projects.get(project_id)
            if path is None: return self._blocked('Project is not registered; no path was inferred.')
            application_id='vscode'
        elif operation=='open_resolved_target':
            if self.discovery is None: return self._blocked('Filesystem discovery is unavailable.')
            path=self.discovery.validate(resolved)
            expected=tuple(resolved['identity']);application_id=arguments['application_id']
        else: raise ValueError('Unsupported desktop operation.')
        if stored is not None and stored['path'] is not None and path is not None:
            if str(path) != stored['path']: return self._blocked('Saved target mapping changed; resume refused.')
            expected=tuple(stored['identity'])
        if application_id not in self.applications.entries: return self._blocked('Application identity is not approved.')
        snap_identity=None
        try:
            entry,executable,binary_fd,binary_identity=stack.enter_context(self.applications.executable(application_id))
        except (OSError,ValueError):
            if not self.applications.production or application_id not in {'vscode','firefox'}:
                return self._blocked(self.applications.unavailable_reason(application_id))
            if path is not None or url is not None:
                message='Installed Snap application supports the owner-authorized app-only policy. Exact project/file/URL handoff is not supported; no launch attempted.'
                if resolved is not None and not resolved['directory']:
                    message+=' Direct file opening is unsupported here. Use "open its folder" for the containing folder. Reading contents requires a separate read request.'
                return self._blocked(message,'unsupported_target')
            try:
                _,executable,binary_fd,binary_identity,snap_identity=stack.enter_context(self.snap.executable(application_id))
                entry=self.applications.entries[application_id]
            except (OSError,ValueError,KeyError,TypeError):
                return self._blocked('Reviewed Snap package identity or installation validation failed; no launch attempted.')
        directory_fd=None;identity=None
        if path is not None:
            try:
                if resolved is not None and not resolved['directory']:
                    identity=tuple(resolved['identity'])
                else: path,identity=self._directory(path,home=home)
            except FileNotFoundError: return self._blocked('Approved directory/project is missing; no launch attempted.')
            except (OSError,ValueError): return self._blocked('Approved directory/project is inaccessible, sensitive or untrusted; no launch attempted.')
            if expected is not None and expected!=identity: return self._blocked('Recorded target identity changed; resume was refused.')
            if resolved is not None and not resolved['directory']:
                parent=stack.enter_context(directory_descriptor(path.parent))
                directory_fd=os.open(path.name,os.O_PATH|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent)
                stack.callback(os.close,directory_fd)
            else: directory_fd=stack.enter_context(directory_descriptor(path))
            if (os.fstat(directory_fd).st_dev,os.fstat(directory_fd).st_ino)!=identity: raise ValueError('Target changed.')
        lease={'operation':operation,'target':entry.application_id+' : '+entry.display_name+' / '+str(executable)+(' / '+str(path) if path is not None else '')+(' / '+url if url else ''),
                'risk':'desktop_navigation' if application_id=='files' else 'execute','effect':('Reopen a registered project from an accepted FRIDAY-managed launch yesterday. ' if operation=='resume_project' else '')+
                ('Saved activity uses Ubuntu Files / Nautilus, not FRIDAY Browser. ' if stored is not None and application_id=='files' else '')+'Launch '+entry.display_name+(' with the exact verified folder/project. No FRIDAY read permission.' if path else '.')+
                (' Uses a fresh private editor profile, extensions disabled, automatic tasks off, workspace trust required.' if application_id=='vscode' else ''),
                'application_id':application_id,'project_id':project_id,'path':path,'identity':identity,'home':home,'url':url,
                'record_operation':'open_project' if operation=='resume_project' else operation,
                'record_arguments':{'project_id':project_id} if project_id else dict(arguments),
                'directory_fd':directory_fd,'binary_fd':binary_fd,'binary_identity':binary_identity,
                'executable':executable,'environment':environment,'requires_approval':True}
        if snap_identity is not None:
            lease.update(snap=True,snap_backend=self.snap,snap_identity=snap_identity)
            lease['effect']+=' Owner-authorized Snap startup-file trust exception for this exact application only.'
        if application_id=='files':
            lease['operation']='navigate_folder'
        if operation=='open_resolved_target':
            lease['operation']='open_project_in_application' if application_id=='vscode' else 'navigate_folder'
            lease['resolved']=resolved
        # Native opening deliberately attempts each freshly approved request.
        # Q deduplication is independent of process/window state. No speculative
        # window receipt or cooldown can suppress a requested location.
        if self.executor.launch_count>=4:
            return self._blocked('Desktop launch limit reached: four processes have been started this session. No new process was started; restart FRIDAY before another launch.',
                                 'launch_limit_reached')
        if retry: lease['effect']='Explicit retry may create another window. '+lease['effect']
        if self.applications.production and application_id=='vscode' and path is not None:
            operation=(HandoffOperation.FILE if resolved is not None and not resolved['directory'] else HandoffOperation.PROJECT)
            return self._bind_handoff(lease,operation)
        if self.applications.production and application_id=='firefox' and url is not None:
            return self._blocked('Firefox navigation remains disabled: exact attributed window and navigation verification are unavailable. No launch attempted.','unsupported_capability')
        return lease

    def _prepare_handoff(self,request,stack):
        handoff=HandoffRequest.from_arguments(request.tool_name,request.arguments)
        if self.handoff_cancelled.is_set():
            return self._blocked('Handoff cancelled; no action attempted.','cancelled')
        if handoff.operation in {HandoffOperation.NAVIGATE,HandoffOperation.SEARCH}:
            from friday.desktop.browser_execution import BrowserTarget
            try: target=BrowserTarget.from_request(handoff)
            except ValueError: return self.browser_execution.prepare(handoff)
            if self.browser_execution.available(target):
                return self.browser_execution.prepare(handoff)
            from friday.desktop.firefox_url_handoff import FirefoxSnapUrlAdapter
            if (self.firefox_url_handoff.available(target) or
                    isinstance(self.firefox_url_handoff.adapter,FirefoxSnapUrlAdapter)):
                # A failed real-adapter preflight must retain its fixed stage;
                # an unavailable page verifier is a separate capability result.
                return self.firefox_url_handoff.prepare(handoff,stack)
            return self.browser_execution.prepare(handoff)
        if self.handoff_verifier.supports(handoff.operation) is not True:
            return self._blocked('VS Code handoff is disabled: exact displayed target verification is unavailable. Owner authentication cannot enable it. Snap remains app-only; no launch attempted.','unsupported_capability')
        from friday.tools.models import ToolRequest
        underlying=(ToolRequest('open_project',{'project_id':handoff.project_id}) if handoff.project_id else
                    ToolRequest('discovery_selection',{'token':handoff.token}))
        lease=self._prepare(underlying,stack)
        if 'result' in lease: return lease
        return self._bind_handoff(lease,handoff.operation)

    def _bind_handoff(self,lease,operation):
        if self.handoff_cancelled.is_set():
            return self._blocked('Handoff cancelled; no action attempted.','cancelled')
        if self.handoff_verifier.supports(operation) is not True:
            return self._blocked('VS Code handoff is disabled: exact displayed target verification is unavailable. No launch attempted.','unsupported_capability')
        if lease.get('snap') or lease.get('application_id')!='vscode' or lease.get('path') is None:
            return self._blocked('No reviewed native VS Code target adapter; Snap app-only policy is unchanged.','unsupported_capability')
        info=os.fstat(lease['directory_fd'])
        directory=stat.S_ISDIR(info.st_mode)
        if directory!=(operation is HandoffOperation.PROJECT):
            return self._blocked('File and project handoff types do not match; no action attempted.','invalid_target')
        lease['handoff']=HandoffTarget(operation,str(lease['path']),tuple(lease['identity']),
            (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns),tuple(lease['binary_identity']))
        lease['operation']=operation.value
        lease['effect']='Open this exact '+('project directory' if directory else 'file')+' in reviewed native VS Code; no content-read grant. Preserve private profile, workspace trust and task/extension restrictions. Require exact displayed-target verification.'
        lease['used']=False
        return lease

    def _prepare_browser(self, operation, arguments, stored, stack):
        kind,environment=desktop_environment()
        if environment is None: return self._blocked('No supported local graphical session is available.')
        position=None;expected=None
        if operation=='browser_history':
            try: target,position=self.browser.history_target(arguments['direction'])
            except ValueError: return self._blocked('No managed-browser history in that direction.','no_history')
            arguments={'folder_id':target['folder_id']};expected=tuple(target['identity'])
        elif operation=='browser_contents':
            if not self.browser.active or not self.browser.transport.alive():
                return self._blocked('FRIDAY Browser is closed; open an approved location first.','browser_closed')
            target=self.browser.history[self.browser.cursor]
            arguments={'folder_id':target['folder_id']};expected=tuple(target['identity'])
        folder=arguments['folder_id'];home=folder=='home'
        if folder in {'home','downloads','documents'}:
            path=Path.home() if home else Path(self.locations.resolve(folder))
        elif folder.startswith('project_') and folder[8:] in self.projects:
            path=self.projects[folder[8:]]
        else: return self._blocked('Browser folder is not registered; no path was inferred.','invalid_target')
        path,identity=self._directory(path,home=home)
        if operation in {'browser_history','browser_contents'} and target['path']!=str(path):
            return self._blocked('Browser target mapping changed; action refused.','invalid_target')
        if stored is not None:
            if stored['path']!=str(path): return self._blocked('Saved browser target mapping changed.','invalid_target')
            expected=tuple(stored['identity'])
        if expected is not None and expected!=identity:
            return self._blocked('Browser target identity changed; navigation refused.','invalid_target')
        stack.enter_context(directory_descriptor(path))
        if operation=='browser_contents':
            return {'browser':True,'contents':True,'path':path,'identity':identity,'home':home,'requires_approval':False}
        lease={'browser':True,'contents':False,'operation':'navigate_browser',
               'target':'FRIDAY Browser / '+str(path),'risk':'desktop_navigation',
               'effect':'Display this exact approved location in the one FRIDAY Browser window. Directory contents remain hidden; no read/open/modify grant.',
               'path':path,'identity':identity,'home':home,'application_id':'friday_browser',
               'record_operation':'navigate_browser','record_arguments':{'folder_id':folder},
               'url':None,'project_id':None,'position':position,'environment':environment,
               'requires_approval':True,'prepared':None}
        if stored is not None and stored['operation']=='open_folder':
            lease['effect']='Resume the saved Nautilus location in the separate FRIDAY Browser. The saved Nautilus record is not rewritten; a confirmed Browser activity enters the three-slot Q. '+lease['effect']
        if not self.browser.transport.alive():
            if self.executor.launch_count>=4:
                return self._blocked('Desktop launch limit reached: four processes started this session; FRIDAY Browser cannot be reopened.','launch_limit_reached')
            try: lease['prepared']=stack.enter_context(self.browser.transport.reviewed_launch())
            except (OSError,ValueError): return self._blocked('Reviewed FRIDAY Browser runtime is unavailable or untrusted; no unsafe fallback.','unavailable')
            lease['launch_approval']=DesktopApproval('launch_browser','FRIDAY Browser','Start one isolated GTK renderer. No folder read permission.','execute')
        return lease

    @contextmanager
    def execution(self,request,*,persist_metadata=True):
        with ExitStack() as stack:
            try: lease=self._prepare(request,stack)
            except FilesystemAuthorizationDenied: raise PermissionError('Filesystem search denied.') from None
            except BrowserHealthUnavailable: lease=self._blocked('FRIDAY Browser has not exited, but its health is unconfirmed. No replacement was launched. Close its window manually before reopening; use show browser status for diagnostics.','browser_health_unverified')
            except (OSError,ValueError): lease=self._blocked('Desktop target is unavailable, sensitive or changed; no launch attempted.')
            if lease.get('browser_target'):
                self.browser_execution.authorize(lease,self.owner_auth,self.approval,DesktopApproval)
            if lease.get('url_handoff_target'):
                self.firefox_url_handoff.authorize(lease,self.owner_auth,self.approval,DesktopApproval)
            if lease.get('launch_approval'):
                try: launch_decision=self.approval.request(lease['launch_approval']) if self.approval is not None else FolderDecision.DENY
                except (Exception,KeyboardInterrupt): launch_decision=FolderDecision.DENY
                if launch_decision is not FolderDecision.ALLOW_ONCE: raise PermissionError('Browser launch denied.')
            if lease.get('requires_approval'):
                approval=DesktopApproval(lease['operation'],lease['target'],lease['effect'],lease['risk'])
                if lease.get('handoff') and self.owner_auth is None:
                    from friday.security.owner import OwnerAuthenticationError
                    raise OwnerAuthenticationError('Owner authentication is required for this handoff.')
                if self.owner_auth is not None and 'result' not in lease:
                    from friday.security.owner import OwnerRequest, SensitiveOperation
                    sensitive_operation=None
                    if lease.get('url'):
                        sensitive_operation=SensitiveOperation.BROWSER_NAVIGATION
                    elif lease.get('application_id')=='vscode' and lease.get('path') is not None:
                        sensitive_operation=(SensitiveOperation.OPEN_FILE if
                            lease.get('resolved',{}).get('directory') is False else SensitiveOperation.OPEN_PROJECT)
                    if sensitive_operation is not None:
                        try: self.owner_auth.authenticate(OwnerRequest(sensitive_operation,lease['application_id'],approval.target))
                        except PermissionError:
                            if self.discovery is not None: self.discovery.clear()
                            raise
                try: decision=self.approval.request(approval) if self.approval is not None else FolderDecision.DENY
                except (Exception,KeyboardInterrupt): decision=FolderDecision.DENY
                if decision is not FolderDecision.ALLOW_ONCE:
                    if self.discovery is not None: self.discovery.clear()
                    raise PermissionError('Desktop approval denied.')
                if 'result' not in lease:
                    if lease.get('browser'):
                        if self._directory(lease['path'],home=lease['home'])[1]!=lease['identity']: raise ValueError('Browser folder changed.')
                    # Re-check the name as well as the held descriptors AFTER
                    # approval. Execution forwards pinned FDs, never user flags.
                    else:
                        registry=self.snap if lease.get('snap') else self.applications
                        with registry.executable(lease['application_id']) as current:
                            if current[1]!=lease['executable'] or current[3]!=lease['binary_identity']: raise ValueError('Executable changed.')
                            if lease.get('snap') and current[4]!=lease['snap_identity']: raise ValueError('Snap metadata changed.')
                        info=os.fstat(lease['binary_fd'])
                        if (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)!=lease['binary_identity']: raise ValueError('Executable changed.')
                        if lease['path'] is not None:
                            if lease.get('resolved'):
                                self.discovery.validate(lease['resolved'])
                            elif self._directory(lease['path'],home=lease['home'])[1]!=lease['identity']: raise ValueError('Folder changed.')
            lease['request']=request
            # Conversational discovery references never create SQLite/Q state.
            lease['persist_metadata']=persist_metadata and not lease.get('resolved',{}).get('reference_only',False)
            if lease.get('handoff') or lease.get('browser_target') or lease.get('url_handoff_target'): lease['persist_metadata']=False
            token=self._lease.set(lease)
            try: yield
            finally: self._lease.reset(token)
    def execute(self,operation,arguments):
        lease=self._lease.get()
        if lease is None or lease['request'].tool_name!=operation or dict(lease['request'].arguments)!=dict(arguments):
            raise PermissionError('No exact desktop authorization lease.')
        if 'result' in lease: return lease['result']
        if lease.get('url_handoff_target'): return self.firefox_url_handoff.execute(lease)
        if lease.get('browser_target'): return self.browser_execution.execute(lease)
        if lease.get('handoff'): return self._execute_handoff(lease)
        if lease.get('browser'): return self._execute_browser(lease)
        result=self.executor.launch(lease)
        if lease['application_id']=='files' and result['status'] in ACCEPTED_LAUNCH_STATUSES:
            self.duplicate_guard.record(lease)
            self.file_navigation.record_launch(lease,result['status'])
        if lease['persist_metadata'] and result['status'] in ACCEPTED_LAUNCH_STATUSES:
            try: result['recent_work_recorded']=self.recent.record(lease, result['status'])
            except Exception:
                result['recent_work_recorded']=False
                result['message']+=' Recent work could not be saved.'
        if lease['project_id'] is not None and lease['persist_metadata'] and result['status'] in {'launch_accepted','launch_outcome_unverified'}:
            try:
                result['session_recorded']=self.sessions.record(lease['project_id'],lease['path'],lease['identity'],lease['application_id'],result['status'])
            except Exception:
                result['session_recorded']=False
                result['message']+=' Project-session metadata was not saved.'
        return result

    def _execute_handoff(self,lease):
        if lease['used']: raise PermissionError('Handoff authorization already consumed.')
        lease['used']=True
        deadline=Deadline(self.handoff_clock()+5,self.handoff_cancelled,self.handoff_clock)
        try:
            deadline.check()
            target=lease['handoff']
            if self.handoff_verifier.supports(target.operation) is not True or lease.get('snap'):
                raise ValueError('Handoff capability changed.')
            self._revalidate_handoff(lease)
            outcome=self.executor.launch(lease)
            deadline.check()
            if outcome.get('status') not in {'launch_accepted','launch_outcome_unverified'}:
                return {'status':'handoff_failed','message':'VS Code handoff launch failed; no displayed target was verified.'}
            proof=self.handoff_verifier.verify(target,deadline)
            deadline.check()
            self._revalidate_handoff(lease)
            if type(proof) is not HandoffProof or not proof.matches(target):
                return {'status':'handoff_unverified','message':'VS Code launch was attempted, but the exact displayed target was not verified. Task stopped; completion is not claimed.'}
            return {'status':'verified','message':'Verified: reviewed VS Code window displays the exact approved '+('project directory.' if target.operation is HandoffOperation.PROJECT else 'file. No file contents were read by FRIDAY.')}
        except DesktopFailure as failure:
            return {'status':failure.status.value,'message':'VS Code handoff stopped on cancellation or timeout; no target completion is claimed.'}
        except (Exception,KeyboardInterrupt):
            return {'status':'handoff_failed','message':'VS Code handoff failed safely; no exact displayed target was verified.'}

    def _revalidate_handoff(self,lease):
        target=lease['handoff']
        if lease.get('resolved'): self.discovery.validate(lease['resolved'])
        elif self._directory(lease['path'])[1]!=target.identity: raise ValueError('Project changed.')
        info=os.fstat(lease['directory_fd'])
        current=(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)
        if (current!=target.fingerprint if target.operation is HandoffOperation.FILE else current[:2]!=target.identity):
            raise ValueError('Target changed.')
        with self.applications.executable('vscode') as executable:
            if tuple(executable[3])!=target.executable_identity: raise ValueError('Executable changed.')
        binary=os.fstat(lease['binary_fd'])
        if (binary.st_dev,binary.st_ino,binary.st_size,binary.st_mtime_ns)!=target.executable_identity:
            raise ValueError('Pinned executable changed.')

    def stop_handoffs(self):
        self.handoff_cancelled.set()

    def _execute_browser(self,lease):
        transport=self.browser.transport
        if lease['contents']:
            from friday.tools.models import ToolRequest,DirectoryIdentity,DirectoryGuard
            if self.list_contents is None: return {'status':'unavailable','message':'Filesystem listing gateway is unavailable.'}
            guard=DirectoryGuard(DirectoryIdentity(str(lease['path']),*lease['identity']))
            listing=self.list_contents(ToolRequest('list_directory',{'path':str(lease['path'])},directory_guard=guard))
            if not listing.success: return {'status':'listing_denied','message':'Directory contents were not displayed: filesystem access was denied or unavailable.'}
            if self._directory(lease['path'],home=lease['home'])[1]!=lease['identity']: raise ValueError('Listing target changed.')
            rows=[str(item['name'])[:450]+' ['+str(item['type'])+']' for item in listing.data['entries'][:100]]
            try: transport.request('contents',location=str(lease['path']),rows=rows)
            except (OSError,ValueError,TypeError):
                transport.failed();return {'status':'browser_failed','message':'Browser closed or listing presentation failed.'}
            return {'status':'contents_displayed','message':'Authorized bounded directory listing displayed in FRIDAY Browser. No files were opened or modified.'}
        try:
            if lease['prepared'] is not None:
                transport.start(lease['prepared'],lease['environment'])
                self.executor.launch_count+=1  # Actual Popen success, even if GTK subsequently fails.
            already_selected=transport.current==str(lease['path'])
            transport.request('navigate',location=str(lease['path']))
            if self._directory(lease['path'],home=lease['home'])[1]!=lease['identity']: raise ValueError('Navigation target changed.')
        except (OSError,ValueError,TypeError):
            transport.failed()
            return {'status':'browser_failed','message':'FRIDAY Browser navigation failed or its window closed. No navigation activity was saved.'}
        self.browser.commit({'folder_id':lease['record_arguments']['folder_id'],
                             'path':str(lease['path']),'identity':list(lease['identity'])},lease['position'])
        result={'status':'navigation_confirmed','message':('FRIDAY Browser confirmed the location is already selected. ' if already_selected else 'FRIDAY Browser confirmed the requested location in its managed window. ')+'Contents require separate read permission; compositor visibility is not independently verified.'}
        if lease['persist_metadata']:
            try: result['recent_work_recorded']=self.recent.record(lease,'navigation_confirmed')
            except Exception:
                result['recent_work_recorded']=False;result['message']+=' Recent work could not be saved.'
        return result
    def close(self):
        self.stop_handoffs()
        if self.discovery is not None: self.discovery.clear()
        self.browser.close()
        self.file_navigation.clear()
        self.duplicate_guard.clear()
        self.executor.close()


class DesktopTool(Tool):
    def __init__(self,name,adapter):
        arguments={
            'open_project_in_vscode':{'project_id':ArgumentSpec(ArgumentType.STRING,required=False),'token':ArgumentSpec(ArgumentType.STRING,required=False)},
            'open_file_in_vscode':{'token':ArgumentSpec(ArgumentType.STRING)},
            'navigate_firefox_to_exact_url':{'url':ArgumentSpec(ArgumentType.STRING)},
            'search_firefox_for_query':{'query':ArgumentSpec(ArgumentType.STRING)},
            'launch_application':{'application_id':ArgumentSpec(ArgumentType.STRING), 'url':ArgumentSpec(ArgumentType.STRING,required=False)},
            'show_recent_work':{'projects':ArgumentSpec(ArgumentType.BOOLEAN,required=False),'detailed':ArgumentSpec(ArgumentType.BOOLEAN,required=False)},
            'discover_target':{'action':ArgumentSpec(ArgumentType.STRING),'name':ArgumentSpec(ArgumentType.STRING),'scope':ArgumentSpec(ArgumentType.STRING,required=False),'application_id':ArgumentSpec(ArgumentType.STRING,required=False)},
            'discovery_selection':{'token':ArgumentSpec(ArgumentType.STRING)},
            'resume_activity':{'entry_id':ArgumentSpec(ArgumentType.STRING,required=False),'backend':ArgumentSpec(ArgumentType.STRING,required=False)},
            'open_folder':{'folder_id':ArgumentSpec(ArgumentType.STRING)},
            'open_project':{'project_id':ArgumentSpec(ArgumentType.STRING)},
            'resume_project':{'project_id':ArgumentSpec(ArgumentType.STRING,required=False)},
            'inspect_running_applications':{},
            'navigate_browser':{'folder_id':ArgumentSpec(ArgumentType.STRING)},
            'browser_history':{'direction':ArgumentSpec(ArgumentType.STRING)},
            'browser_contents':{},
            'browser_status':{},
        }[name]
        if name not in HANDOFF_TOOLS and name not in {'show_recent_work','inspect_running_applications','navigate_browser','browser_history','browser_contents','browser_status','discover_target','discovery_selection'}:
            arguments['retry']=ArgumentSpec(ArgumentType.BOOLEAN,required=False)
        super().__init__(ToolSpec(name,'Typed-owner-authorized deterministic desktop operation.',arguments,
                                 RiskLevel.READ_ONLY if name in {'inspect_running_applications','show_recent_work','browser_status'} else RiskLevel.EXECUTE))
        self.adapter=adapter
    def execute(self,arguments): return self.adapter.execute(self.spec.name,arguments)


def register_desktop_tools(registry,adapter):
    for name in sorted(DESKTOP_TOOLS): registry.register(DesktopTool(name,adapter))
