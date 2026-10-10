"""Three explicit accepted launches, never application usage or resume authority."""
import hashlib
import json
import re
from datetime import datetime
from uuid import UUID

# Deliberately small reviewed link catalog. No credentials, query, fragments,
# arbitrary private URLs or browser-history import. Expand through code review.
ACCEPTED_LAUNCH_STATUSES = frozenset({'launch_accepted', 'launch_outcome_unverified'})
RECORDABLE_ACTIVITY_STATUSES=ACCEPTED_LAUNCH_STATUSES | {'navigation_confirmed'}

REVIEWED_URLS = frozenset({'https://github.com/'})


def reviewed_url(value):
    if type(value) is not str or value not in REVIEWED_URLS:
        raise ValueError('URL is not in the reviewed HTTPS link catalog.')
    return value


def display(value):
    # Single-line fields cannot create terminal controls or fake menu rows.
    return ''.join(c if c.isprintable() else json.dumps(c)[1:-1] for c in str(value))[:512]


class RecentWorkQueue:
    def __init__(self, memory):
        self.memory = memory
        self.menu_ids = ()

    @staticmethod
    def activity(operation, arguments, application_id, path, identity, url=None, *, version=4):
        args = dict(arguments)
        if operation == 'launch_application':
            args = {'application_id': application_id}
            if url is not None:
                args['url'] = reviewed_url(url)
            kind = 'website' if url else 'application'
            target = url or application_id
            title = {'vscode':'VS Code', 'firefox':'Firefox', 'files':'Ubuntu Files'}[application_id]
            if url: title += ' — github.com'
            summary = 'Opened ' + ('github.com in Firefox' if url else title) + '.'
        elif operation == 'open_project':
            kind = 'project'; target = str(path)
            title = 'VS Code — ' + args['project_id'].upper() + ' project'
            summary = 'Opened ' + args['project_id'].upper() + ' project in VS Code.'
        elif operation=='open_resolved_target':
            from pathlib import Path
            kind='project' if application_id=='vscode' else 'nautilus_location'
            target=str(path);title=Path(path).name+' — '+('VS Code' if application_id=='vscode' else 'Ubuntu Files')
            summary='FRIDAY started '+('VS Code' if application_id=='vscode' else 'Ubuntu Files')+' for the approved target.'
        elif operation in {'open_folder','navigate_browser'}:
            kind = ('friday_browser_location' if operation=='navigate_browser' else 'nautilus_location') if version>=3 else 'folder'; target = str(path)
            folder=args['folder_id']
            title = folder[8:].upper() + ' project folder' if folder.startswith('project_') else folder.title() + ' folder'
            summary = 'Opened ' + title + '.'
        else:
            raise ValueError('Unsupported queue operation.')
        if version >= 2:
            summary = RecentWorkQueue.launch_summary(operation, args, application_id)
        descriptor = {'version':version, 'operation':operation, 'arguments':args,
                      'path':str(path) if path is not None else None,
                      'identity':list(identity) if identity is not None else None}
        key = json.dumps(['folder' if operation in {'open_folder','navigate_browser'} else kind, application_id, target], separators=(',', ':'))
        if version>=4:
            key=json.dumps(['activity',application_id,target],separators=(',',':'))
        return dict(activity_key=hashlib.sha256(key.encode()).hexdigest(), activity_type=kind,
                    application_id=application_id, target_identity=json.dumps([target, descriptor['identity']]),
                    title=title, summary=summary, resume_descriptor=json.dumps(descriptor, sort_keys=True),
                    safe_link=str(path) if path is not None else url or '')

    @staticmethod
    def launch_summary(operation, arguments, application_id):
        name = {'vscode':'VS Code', 'firefox':'Firefox', 'files':'Ubuntu Files','friday_browser':'FRIDAY Browser'}[application_id]
        if operation == 'open_project':
            return 'FRIDAY started VS Code for ' + arguments['project_id'].upper() + ' project.'
        if operation=='open_resolved_target': return 'FRIDAY started '+name+' for the approved target.'
        if operation in {'open_folder','navigate_browser'}:
            folder=arguments['folder_id']
            label=folder[8:].upper()+' project folder' if folder.startswith('project_') else folder.title()+' folder'
            if operation=='navigate_browser': return 'FRIDAY Browser confirmed navigation to '+label+'.'
            return 'FRIDAY started Ubuntu Files for ' + label + '.'
        if arguments.get('url'):
            return 'FRIDAY started Firefox with an approved github.com launch request.'
        return 'FRIDAY started ' + name + '.'

    def record(self, lease, status):
        if status not in RECORDABLE_ACTIVITY_STATUSES or (status=='navigation_confirmed') != (lease['record_operation']=='navigate_browser'):
            raise ValueError('Only accepted launches or confirmed managed navigation can enter Q.')
        if self.memory is None: return False
        activity = self.activity(lease['record_operation'], lease['record_arguments'],
                                 lease['application_id'], lease['path'], lease['identity'], lease['url'])
        activity['launch_status'] = status
        semantic=self.semantic(activity)
        equivalents=[];groups=[]
        for row in self.memory.recent_work():
            try:
                self.decode(row)
                key=self.semantic(row);actual=self.actual(row)
                if key==semantic or actual==self.actual(activity): equivalents.append(row['entry_id'])
                group=next((group for group in groups if group[0]==key or group[1]==actual),None)
                if group is None: groups.append([key,actual,[row['entry_id']]])
                else: group[2].append(row['entry_id'])
            except (ValueError,KeyError,TypeError,RecursionError): pass
        self.memory.record_recent_work(activity,equivalent_ids=tuple(equivalents),
                                       duplicate_groups=tuple(tuple(group[2]) for group in groups if len(group[2])>1))
        return True

    @staticmethod
    def actual(row):
        descriptor=json.loads(row['resume_descriptor'])
        return row['application_id'],descriptor['path'] or descriptor['arguments'].get('url') or row['application_id']

    @staticmethod
    def semantic(row):
        from pathlib import Path
        descriptor=json.loads(row['resume_descriptor'])
        app=row['application_id'];target=descriptor['path'] or descriptor['arguments'].get('url') or app
        if app=='files' and descriptor['operation']=='launch_application': target=str(Path.home())
        # Legacy default-browser locations are equivalent to the native folder
        # workflow. New explicit FRIDAY Browser workflows remain distinct.
        if app=='friday_browser' and descriptor['version']<4: app='files'
        return app,target

    def rows(self):
        selected=[];seen=set();actual_seen=set()
        for row in self.memory.recent_work() if self.memory is not None else ():
            try:
                self.decode(row);key=self.semantic(row);actual=self.actual(row)
            except (ValueError,KeyError,TypeError,RecursionError):
                selected.append(row);continue
            if key not in seen and actual not in actual_seen:
                selected.append(row);seen.add(key);actual_seen.add(actual)
        return tuple(selected[:3])

    def decode(self, row):
        """Treat every database field as untrusted; reconstruct approved grammar."""
        UUID(row['entry_id'])
        if len(row['resume_descriptor']) > 8192: raise ValueError('Invalid descriptor.')
        d = json.loads(row['resume_descriptor'])
        if type(d) is not dict or set(d) != {'version','operation','arguments','path','identity'} or type(d['version']) is not int or d['version'] not in {1,2,3,4}:
            raise ValueError('Invalid descriptor.')
        args = d['arguments']; op = d['operation']
        if type(args) is not dict: raise ValueError('Invalid arguments.')
        if op == 'launch_application':
            if set(args) not in ({'application_id'}, {'application_id','url'}) or args['application_id'] not in {'vscode','files','firefox'}:
                raise ValueError('Invalid application.')
            if 'url' in args:
                if args['application_id'] != 'firefox': raise ValueError('Invalid URL application.')
                reviewed_url(args['url'])
            if d['path'] is not None or d['identity'] is not None: raise ValueError('Invalid target.')
            app = args['application_id']
        elif op in {'open_project','open_folder','navigate_browser','open_resolved_target'}:
            field = 'project_id' if op == 'open_project' else 'folder_id'
            if op=='open_resolved_target':
                from pathlib import Path
                if (d['version']!=4 or set(args)!={'application_id','scope','scope_identity','directory'} or args['application_id'] not in {'files','vscode'} or
                    type(args['directory']) is not bool or args['application_id']=='files' and not args['directory'] or
                    type(args['scope']) is not str or not args['scope'].startswith('/') or not Path(d['path']).is_relative_to(args['scope']) or
                    type(args['scope_identity']) is not list or len(args['scope_identity'])!=2 or
                    any(type(i) is not int or i<0 for i in args['scope_identity'])):
                    raise ValueError('Invalid resolved target.')
            elif set(args) != {field} or type(args[field]) is not str: raise ValueError('Invalid target alias.')
            if op == 'open_project' and not re.fullmatch(r'[a-z][a-z0-9_]{0,31}',args[field]):
                raise ValueError('Invalid project identity.')
            if op in {'open_folder','navigate_browser'} and args[field] not in {'downloads','documents','home'} and not re.fullmatch(r'project_[a-z][a-z0-9_]{0,31}',args[field]): raise ValueError('Invalid folder.')
            if (type(d['path']) is not str or len(d['path']) > 4096 or not d['path'].startswith('/') or
                    any(not c.isprintable() for c in d['path']) or
                    type(d['identity']) is not list or len(d['identity']) != 2 or
                    any(type(i) is not int or i < 0 for i in d['identity'])):
                raise ValueError('Invalid target identity.')
            from friday.tools.sensitive import SensitivePaths
            from friday.tools.grants import lexical_path
            if (str(lexical_path(d['path'])) != d['path'] or SensitivePaths().excluded(d['path']) or
                    SensitivePaths.excluded_content(d['path'].encode())):
                raise ValueError('Unsafe saved target.')
            app = args['application_id'] if op=='open_resolved_target' else 'vscode' if op == 'open_project' else 'friday_browser' if op=='navigate_browser' else 'files'
        else: raise ValueError('Invalid operation.')
        stamp = datetime.fromisoformat(row['launched_at'])
        if stamp.tzinfo is None: raise ValueError('Invalid timestamp.')
        if row['launch_status'] not in RECORDABLE_ACTIVITY_STATUSES or (row['launch_status']=='navigation_confirmed') != (op=='navigate_browser'):
            raise ValueError('Invalid saved launch outcome.')
        if d['version'] == 1 and row['launch_status'] != 'launch_accepted':
            raise ValueError('Invalid legacy outcome.')
        expected = self.activity(op, args, app, d['path'], d['identity'], args.get('url'), version=d['version'])
        # Display text is reconstructed too: poisoned titles/links are refused.
        if any(row[k] != v for k,v in expected.items()): raise ValueError('Modified activity metadata.')
        return d

    def show(self, *, projects=False,detailed=False):
        self.menu_ids = ()
        lines = ['YOUR RECENT WORK']
        selected = []
        for row in self.rows():
            try: descriptor = self.decode(row)
            except (ValueError, KeyError, TypeError, RecursionError):
                lines.append('A saved entry is invalid and cannot be resumed.'); continue
            if projects and row['activity_type'] != 'project': continue
            selected.append(row['entry_id'])
            if not detailed:
                from pathlib import Path
                app={'files':'Ubuntu Files','friday_browser':'FRIDAY Browser','vscode':'VS Code','firefox':'Firefox'}[row['application_id']]
                title=app
                if descriptor['path']:
                    label=Path(descriptor['path']).name
                    if descriptor['arguments'].get('folder_id')=='home': label='Home'
                    title=label+' — '+app
                elif descriptor['arguments'].get('url'): title+=' — github.com'
                lines.append(f'[{len(selected)}] {display(title)}')
                continue
            application={'files':'Ubuntu Files / Nautilus','friday_browser':'FRIDAY Browser','vscode':'VS Code','firefox':'Firefox'}[row['application_id']]
            activity_type=('friday_browser_location' if descriptor['operation']=='navigate_browser' else 'nautilus_location') if descriptor['operation'] in {'open_folder','navigate_browser'} else row['activity_type']
            lines += [f'[{len(selected)}] {display(row["title"])} [{application}]',
                      '    Activity type: '+activity_type,
                      '    Summary: ' + display(self.launch_summary(descriptor['operation'], descriptor['arguments'], row['application_id'])),
                      ('    Status: Managed location confirmed; compositor visibility not verified.' if descriptor['operation']=='navigate_browser' else '    Status: Window not verified.'),
                      '    Resume: ' + ('FRIDAY Browser — ' if descriptor['operation']=='navigate_browser' else '') + display(row['safe_link'] or 'Open ' + {'vscode':'VS Code', 'firefox':'Firefox', 'files':'Ubuntu Files'}[row['application_id']] + '.')]
        self.menu_ids = tuple(selected)
        if selected: lines.append('Choose ' + ', '.join(str(i+1) for i in range(len(selected))) + ' to resume.')
        else: lines.append('No saved project activities.' if projects else 'No recent work saved yet.')
        if detailed: lines.append('Saved FRIDAY-managed actions only; external application work and compositor visibility are unverified.')
        return '\n'.join(lines)

    def selection(self, text):
        if not self.menu_ids: return None
        ids = self.menu_ids
        self.menu_ids = ()  # One prompt context; any intervening input closes it.
        conversion=re.fullmatch(r'resume q ([123]) in friday browser',text.casefold())
        if conversion:
            if int(conversion[1])>len(ids): return 'invalid',{}
            return 'resume_activity',{'entry_id':ids[int(conversion[1])-1],'backend':'friday_browser'}
        if text.isdecimal():
            if text not in {'1','2','3'} or int(text) > len(ids):
                return 'invalid', {}
            return 'resume_activity', {'entry_id':ids[int(text)-1]}
        return None

    def get(self, entry_id=None):
        rows = self.rows()
        row = next((r for r in rows if r['entry_id'] == entry_id), None) if entry_id else next(iter(rows), None)
        if row is None: raise ValueError('No saved activity matches.')
        return row, self.decode(row)
