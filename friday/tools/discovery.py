"""Bounded metadata discovery; selections are session-local, never model paths."""
from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import stat
import time
from uuid import uuid4

from friday.tools.access import FolderDecision, FilesystemAuthorizationDenied
from friday.tools.filesystem import OutsideRoots
from friday.tools.grants import approved_folder, directory_descriptor

NO_REFERENCE = "I don't have a specific recent file or folder to open. Find it first."
FOLLOWUPS = {'open that':'open', 'open it':'open', 'open this file':'open',
             'open the found file':'open', 'show that in files':'files',
             'open its folder':'parent'}


@dataclass(frozen=True)
class DiscoveryReference:
    path: str
    directory: bool
    scope: str
    identity: tuple
    scope_identity: tuple
    parent_identity: tuple
    fingerprint: tuple | None
    unique: bool
    created: float

    def target(self):
        return {key:getattr(self,key) for key in ('path','directory','scope','identity',
                'scope_identity','parent_identity','fingerprint')}


@dataclass(frozen=True)
class SearchApproval:
    target: Path
    def prompt(self):
        return ('Permission required:\nOperation: search_directory\nTarget: '+json.dumps(str(self.target),ensure_ascii=True)+
                '\nAccess: bounded names/type metadata only, within this exact tree. No file-content read grant.\n'
                '[1] Allow once\n[3] Deny')


class TargetDiscovery:
    MAX_DEPTH=3
    MAX_ENTRIES=1000
    MAX_RESULTS=20
    TIMEOUT=2

    def __init__(self, access, projects, locations):
        self.access=access;self.projects=projects;self.locations=locations
        self.pending=None;self.receipts={}
        self.reference=None;self.candidates=()
        self.selection_consumed=False

    def clear(self):
        consumed=self.selection_consumed or self.pending is not None
        self.reference=None;self.candidates=();self.pending=None;self.receipts={}
        self.selection_consumed=consumed

    def matching_filename(self, name):
        """Resolve only metadata from this discovery conversation, never text."""
        recent=tuple(item for item in ((self.reference,) if self.reference else self.candidates)
                     if Path(item.path).name.casefold()==name.casefold())
        if not recent: return None
        if any(time.monotonic()-item.created>120 for item in recent):
            self.clear()
            return 'reference_message',{'message':NO_REFERENCE}
        # Validate even ambiguous matches before presenting a selection.
        try:
            for item in recent: self.validate(item.target())
        except (OSError,ValueError):
            return 'reference_message',{'message':'Recent discovery target is unavailable or changed. Find it again.'}
        self.reference=recent[0] if len(recent)==1 and recent[0].unique else None
        self.candidates=() if self.reference else recent
        return self.followup('open that')

    def remember(self,targets,unique):
        references=tuple(DiscoveryReference(item['path'],item['directory'],item['scope'],
            tuple(item['identity']),tuple(item['scope_identity']),tuple(item['parent_identity']),
            tuple(item['fingerprint']) if item.get('fingerprint') is not None else None,
            unique,time.monotonic()) for item in targets[:self.MAX_RESULTS])
        self.reference=references[0] if unique and len(references)==1 else None
        self.candidates=() if self.reference else references

    def followup(self,text,application_id=None):
        operation=FOLLOWUPS.get(text)
        if application_id is not None:
            if application_id!='vscode' or operation!='open': raise ValueError('Unsupported reference destination.')
            operation='vscode'
        if operation is None: return None
        if self.reference is not None and time.monotonic()-self.reference.created>120:
            self.clear()
        if self.reference is not None:
            target={**self.reference.target(),'reference_operation':operation}
            expires=self.reference.created+120
        elif self.candidates and all(time.monotonic()-item.created<=120 for item in self.candidates):
            target={'reference_prompt':operation}
            expires=min(item.created+120 for item in self.candidates)
        else:
            self.clear()
            return 'reference_message',{'message':NO_REFERENCE}
        token=uuid4().hex;self.receipts={token:{**target,'expires':expires}}
        return 'discovery_selection',{'token':token}

    def reference_target(self,target,operation):
        target={key:value for key,value in target.items() if key!='reference_operation'}
        target['reference_only']=True
        path=self.validate(target)
        if operation=='parent':
            parent=path.parent
            with directory_descriptor(parent) as fd:
                info=os.fstat(fd)
                identity=(info.st_dev,info.st_ino)
            if identity!=tuple(target['parent_identity']):
                self.clear();raise ValueError('Containing folder changed.')
            target={**target,'path':str(parent),'identity':identity,'directory':True,'fingerprint':None}
            target.pop('parent_identity',None)
            # Preserve original scope; opening its root is explicitly scoped.
            self.validate(target)
            return self.destination(target,'files')
        if operation=='files':
            if not target['directory']:
                return {'result':{'status':'unsupported_target','message':
                    'Selecting a file in Ubuntu Files is unsupported. Use "open its folder" to open the containing folder; reading contents requires a separate read request.'}}
            return self.destination(target,'files')
        if operation=='vscode': return self.destination(target,'vscode')
        if operation!='open': raise ValueError('Unsupported reference operation.')
        return self.destination(target,None if target['directory'] else 'vscode')

    @staticmethod
    def parse(text):
        if text.startswith('show ') and not text.endswith(' location'): return None
        match=re.fullmatch(r'(open|find|where is|show) (.+?)(?: location)?',text)
        if not match: return None
        action,name=match.groups();app=None;scope=None
        destination=re.search(r' in (vs code|visual studio code|ubuntu files)$',name)
        if destination:
            app='files' if destination[1]=='ubuntu files' else 'vscode'
            name=name[:destination.start()]
        context=re.search(r' (?:in|from) (downloads|documents)$',name)
        if context: scope=context[1];name=name[:context.start()]
        if name in {'this file','that file','this folder','that folder','a folder'} or re.search(r'\b(application|app|viewer|player)\b',name): return None
        if not re.fullmatch(r'[\w][\w .-]{0,99}',name) or name in {'.','..'} or '..' in name:
            return None
        return 'discover_target',dict(action='open' if action=='open' else 'find',name=name,
                                     **({'scope':scope} if scope else {}),**({'application_id':app} if app else {}))

    def selection(self,text):
        pending=self.pending;self.pending=None
        if pending is None:
            if text.isdecimal() and self.selection_consumed:
                return 'reference_message',{'message':'That selection has expired or was already completed. Repeat the request to choose again.'}
            return None
        if not text.isdecimal(): return None
        self.selection_consumed=True
        if time.monotonic()>pending['expires'] or text not in {str(i+1) for i in range(len(pending['options']))}:
            return 'discovery_selection',{'token':'invalid'}
        option=pending['options'][int(text)-1]
        token=uuid4().hex
        self.receipts={token:{**option,'expires':pending['expires']}}
        return 'discovery_selection',{'token':token}

    def scopes(self,scope=None):
        if scope:
            if scope not in {'downloads','documents'}: raise ValueError('Unknown search scope.')
            return (Path(self.locations.resolve(scope)),)
        return tuple(dict.fromkeys((*self.access.boundary.allowed_roots,
                                   *(grant.folder for grant in self.access.boundary.persistent_grants()))))

    @contextmanager
    def authorized(self,path):
        boundary=self.access.boundary
        if path==Path('/') or any(path==root or path.is_relative_to(root) for root in map(Path,('/etc','/proc','/sys','/dev','/root'))):
            raise ValueError('System search scope is forbidden.')
        grant=approved_folder(path,boundary.sensitive)
        with boundary.request_access('list_directory'):
            try:
                boundary.resolve(str(path))
            except OutsideRoots:
                if self.access._decision(SearchApproval(path)) is not FolderDecision.ALLOW_ONCE:
                    raise FilesystemAuthorizationDenied('Search scope denied.')
                with directory_descriptor(path) as fd:
                    if (os.fstat(fd).st_dev,os.fstat(fd).st_ino)!=(grant.device,grant.inode):
                        raise ValueError('Search scope changed after approval.')
                    yield fd
            else:
                # Reuse descriptor traversal and persisted-root inode checks.
                with boundary.open(str(path),os.O_RDONLY|os.O_DIRECTORY) as (fd,_):
                    yield fd

    def search(self,name,roots):
        if type(name) is not str or not re.fullmatch(r'[\w][\w .-]{0,99}',name) or '..' in name:
            raise ValueError('Invalid search name.')
        matches=[];examined=0;deadline=time.monotonic()+self.TIMEOUT;truncated=False
        scope_identities={}
        def walk(fd,path,depth,scope):
            nonlocal examined,truncated
            with os.scandir(fd) as entries:
                for entry in entries:
                    if examined>=self.MAX_ENTRIES or len(matches)>=self.MAX_RESULTS or time.monotonic()>=deadline:
                        truncated=True;return
                    examined+=1;target=path/entry.name
                    if entry.name.startswith('.'): continue  # No hidden-directory scanning.
                    if not all(c.isprintable() for c in str(target)) or self.access.boundary.sensitive.excluded(target): continue
                    try: info=entry.stat(follow_symlinks=False)
                    except OSError: continue
                    if stat.S_ISLNK(info.st_mode): continue
                    directory=stat.S_ISDIR(info.st_mode)
                    regular=stat.S_ISREG(info.st_mode) and info.st_nlink==1
                    if (directory or regular) and entry.name.casefold()==name.casefold():
                        matches.append({'path':str(target),'identity':(info.st_dev,info.st_ino),
                                        'directory':directory,'scope':str(scope),'scope_identity':scope_identities[str(scope)],
                                        'parent_identity':(os.fstat(fd).st_dev,os.fstat(fd).st_ino),
                                        'fingerprint':None if directory else (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)})
                    if directory and depth+1<self.MAX_DEPTH:
                        try: child=os.open(entry.name,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
                        except OSError: continue
                        try:
                            actual=os.fstat(child)
                            if (actual.st_dev,actual.st_ino)==(info.st_dev,info.st_ino): walk(child,target,depth+1,scope)
                        finally: os.close(child)
            # Depth limit is explicit; do not imply an unrestricted search.
        for root in roots:
            approval_start=time.monotonic()
            with self.authorized(root) as fd:
                deadline+=time.monotonic()-approval_start
                scope_identities[str(root)]=[os.fstat(fd).st_dev,os.fstat(fd).st_ino]
                walk(fd,root,0,root)
            if truncated: break
        unique={item['path']:item for item in matches}
        return list(unique.values()),truncated

    def prompt(self,options,message):
        self.pending={'options':options,'expires':time.monotonic()+120}
        return {'result':{'status':'needs_selection','message':message}}

    def destination(self,target,application_id=None):
        if application_id:
            if application_id not in {'files','vscode'} or application_id=='files' and not target['directory']:
                raise ValueError('Unsupported file destination.')
            return {**target,'application_id':application_id}
        options=[{**target,'application_id':'vscode'}]
        labels=['[1] VS Code']
        if target['directory']:
            options.append({**target,'application_id':'files'});labels.append('[2] Ubuntu Files')
        return self.prompt(options,'Choose how to open '+json.dumps(target['path'],ensure_ascii=True)+':\n'+'\n'.join(labels))

    def prepare(self,arguments,selection=False):
        if selection:
            target=self.receipts.pop(arguments['token'],None)
            if target is None: return {'result':{'status':'invalid_selection','message':'No active discovery choice matches.'}}
            if time.monotonic()>target.pop('expires',0):
                self.clear()
                return {'result':{'status':'invalid_selection','message':NO_REFERENCE}}
            if 'reference_prompt' in target:
                operation=target['reference_prompt']
                return self.prompt([{**item.target(),'reference_operation':operation} for item in self.candidates],
                    'Multiple recent results exist. Choose the exact target:\n'+
                    '\n'.join('['+str(i+1)+'] '+json.dumps(item.path,ensure_ascii=True) for i,item in enumerate(self.candidates)))
            if 'reference_operation' in target:
                self.validate(target)
                self.remember([target],True)
                return self.reference_target(target,target['reference_operation'])
            if target.get('find_only'):
                self.validate(target);self.remember([target],True)
                return {'result':{'status':'found','message':json.dumps(target['path'],ensure_ascii=True)}}
            self.validate(target);self.remember([target],True)
            return self.destination(target,target.get('application_id'))
        self.clear()
        if arguments['action'] not in {'open','find'} or arguments.get('application_id') not in {None,'vscode','files'}:
            raise ValueError('Unreviewed discovery action.')
        roots=self.scopes(arguments.get('scope'))
        matches,truncated=self.search(arguments['name'],roots)
        self.remember(matches,len(matches)==1 and not truncated)
        scope_text=', '.join(json.dumps(str(root),ensure_ascii=True) for root in roots)
        bounds='Search bounds: depth 3, 1,000 entries, 20 matches, 2 seconds. '+('Limit reached; results are incomplete. ' if truncated else '')
        if not matches:
            return {'result':{'status':'not_found','message':'No matching target in '+scope_text+'. '+bounds+'Try "find NAME in downloads" or "find NAME in documents" to request another scope.'}}
        if arguments['action']=='find':
            return {'result':{'status':'found','message':'Found in '+scope_text+':\n'+'\n'.join(json.dumps(item['path'],ensure_ascii=True) for item in matches)+'\n'+bounds}}
        for item in matches: item['application_id']=arguments.get('application_id')
        if len(matches)==1 and not truncated: return self.destination(matches[0],arguments.get('application_id'))
        return self.prompt(matches,'Found:\n'+'\n'.join('['+str(i+1)+'] '+json.dumps(item['path'],ensure_ascii=True) for i,item in enumerate(matches))+'\nChoose the exact target. '+bounds)

    def validate(self,target):
        try:
            return self._validate(target)
        except (OSError,ValueError,KeyError,TypeError):
            self.clear()
            raise

    def _validate(self,target):
        path=Path(target['path']);scope=Path(target['scope'])
        if scope==Path('/') or any(scope==root or scope.is_relative_to(root) for root in map(Path,('/etc','/proc','/sys','/dev','/root'))):
            raise ValueError('System search scope is forbidden.')
        # Loaded resume metadata never establishes a new approved root.
        available=(*self.scopes(),*self.scopes('downloads'),*self.scopes('documents'))
        if scope not in available or not path.is_relative_to(scope) or (path==scope and
                (not target['directory'] or tuple(target['identity'])!=tuple(target['scope_identity']))):
            raise ValueError('Saved search scope is no longer approved.')
        with directory_descriptor(scope) as fd:
            if (os.fstat(fd).st_dev,os.fstat(fd).st_ino)!=tuple(target['scope_identity']):
                raise ValueError('Search scope identity changed.')
        if self.access.boundary.sensitive.excluded(path): raise ValueError('Sensitive target.')
        with directory_descriptor(path.parent) as parent:
            parent_info=os.fstat(parent)
            if target.get('parent_identity') is not None and (parent_info.st_dev,parent_info.st_ino)!=tuple(target['parent_identity']):
                raise ValueError('Discovered target parent changed.')
            fd=os.open(path.name,os.O_PATH|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=parent)
            try:
                info=os.fstat(fd)
                if (info.st_dev,info.st_ino)!=tuple(target['identity']) or (not stat.S_ISDIR(info.st_mode) if target['directory'] else not stat.S_ISREG(info.st_mode) or info.st_nlink!=1):
                    raise ValueError('Resolved target identity changed.')
                if target.get('fingerprint') is not None and (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)!=tuple(target['fingerprint']):
                    raise ValueError('Discovered file changed.')
            finally: os.close(fd)
        return path
