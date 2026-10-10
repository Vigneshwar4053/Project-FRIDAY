"""Exact desktop grammar, before existing browse routing; no model proposals."""
import re
from friday.desktop.registry import ApplicationRegistry
from friday.tools.locations import command_text, instructional_question
from friday.tools.discovery import FOLLOWUPS, NO_REFERENCE
from friday.desktop.workflows import parse_workflow
from friday.desktop.handoffs import HANDOFF_TOOLS

DESKTOP_TOOLS=frozenset({'launch_application','open_folder','open_project',
                         'inspect_running_applications','resume_project','show_recent_work','resume_activity',
                         'navigate_browser','browser_history','browser_contents','browser_status',
                         'discover_target','discovery_selection'}) | HANDOFF_TOOLS


class DesktopIntentResolver:
    def __init__(self, applications=None, recent=None, browser=None, discovery=None):
        self.applications=applications or ApplicationRegistry()
        self.recent=recent
        self.browser=browser
        self.discovery=discovery

    def resolve(self, message):
        text=' '.join(command_text(message).casefold().strip().rstrip('.').split())
        text=re.sub(r'^please\s+','',text)
        qualified=re.fullmatch(r'(open (?:that|it|this file|the found file)) in (?:vs code|visual studio code)',text)
        if qualified:
            # The existing file-open destination is VS Code; no new handoff.
            return self.discovery.followup(qualified[1],'vscode') if self.discovery else ('reference_message',{'message':NO_REFERENCE})
        if text in FOLLOWUPS:
            return self.discovery.followup(text) if self.discovery is not None else ('reference_message',{'message':NO_REFERENCE})
        if text not in {'open that file','open that folder'} and re.match(
                r'^(?:open|show)\s+(?:that|it|this file|the found file|its folder)(?:\s|$|[;/|`$])',text):
            return 'reference_message',{'message':'Unsupported discovery follow-up. Use an exact supported reference command without paths, flags or extra actions.'}
        if text in {'stop','/stop'}:
            if self.discovery is not None: self.discovery.clear()
            return 'reference_message',{'message':'Pending discovery references and workflow plans cleared.'}
        filename=re.fullmatch(r'open ([\w][\w .-]{0,99}?)(?: in (?:vs code|visual studio code))?',text)
        if self.discovery is not None and filename and '.' in filename[1] and '..' not in filename[1]:
            recent=self.discovery.matching_filename(filename[1])
            if recent is not None: return recent
        if self.discovery is not None and re.match(r'^(?:open|find|where is|show|read|list|launch|start|resume)\b',text):
            self.discovery.clear()
        workflow=parse_workflow(message)
        if workflow is not None: return 'workflow',{'plan':workflow}
        return self._resolve_single(message)

    def _resolve_single(self, message):
        text=' '.join(command_text(message).casefold().strip().rstrip('.').split())
        if self.discovery is not None and (self.discovery.pending is not None or not (self.recent and self.recent.menu_ids)):
            selection=self.discovery.selection(message.strip())
            if selection is not None:
                if self.recent is not None: self.recent.menu_ids=()
                return selection
        if self.recent is not None:
            selection=self.recent.selection(message.strip())
            if selection is not None: return selection
        if instructional_question(text): return None
        text=re.sub(r'^please\s+','',text)
        if text.startswith('retry '):
            original=text[6:]
            if not original.startswith(('open ', 'resume ')): return 'unsupported', {}
            route=self.resolve(original)
            if route is None or route[0] not in {'launch_application','open_folder','open_project','resume_activity','resume_project'}:
                return 'unsupported', {}
            return route[0], {**route[1], 'retry':True}
        if re.match(r'^(open|launch|start|resume)\b',text) and (
                any(token in text for token in (';','&&','|','`','$(','--','../')) or
                re.search(r'\b(and|then)\b|\s-[A-Za-z]|^open\s+/(?:bin|sbin|usr/bin)/',text)):
            return 'unsupported',{}
        if text=='show q diagnostics': return 'show_recent_work',{'detailed':True}
        if text in {'show my recent work','show q','what was i working on?','what was i working on'}:
            return 'show_recent_work', {}
        if text == 'resume my last work': return 'resume_activity', {}
        if text == 'resume previous projects': return 'show_recent_work', {'projects':True}
        if text in {'go back','go forward'} and self.browser is not None and self.browser.active:
            return 'browser_history',{'direction':text.split()[1]}
        if text=='show browser status': return 'browser_status',{}
        if text=='list browser contents': return 'browser_contents',{}
        if text=='open friday browser':
            return 'navigate_browser',{'folder_id':'home'}
        if text in {'open files','open file manager'}: return 'open_folder',{'folder_id':'home'}
        if text in {'open github.com in firefox', 'open https://github.com/ in firefox'}:
            return 'launch_application', {'application_id':'firefox','url':'https://github.com/'}
        if text=='show running applications': return 'inspect_running_applications',{}
        if text=="resume yesterday's project": return 'resume_project',{}
        match=re.fullmatch(r"resume yesterday's ([a-z0-9_]+) project",text)
        if match: return 'resume_project',{'project_id':match[1]}
        if text=='open my friday project': return 'open_project',{'project_id':'friday'}
        match=re.fullmatch(r'open my ([a-z][a-z0-9_]{0,31}) project folder( in (?:ubuntu files|friday browser))?',text)
        if match: return ('navigate_browser' if match[2]==' in friday browser' else 'open_folder'),{'folder_id':'project_'+match[1]}
        match=re.fullmatch(r'(?:open|resume) (?:my |the )?(downloads|documents|home)(?: folder)?( in (?:ubuntu files|friday browser))?',text)
        if match: return ('navigate_browser' if match[2]==' in friday browser' else 'open_folder'),{'folder_id':match[1]}
        match=re.fullmatch(r'(open|launch|start) (.+)',text)
        if match:
            identity=self.applications.resolve(match[2])
            if identity: return 'launch_application',{'application_id':identity}
            if self.discovery is not None and match[1]=='open':
                if self.locations_known(message): return None
                route=self.discovery.parse(text)
                if route: return route
            if match[1] == 'launch' or re.search(r'\b(project|application|app|firefox|code|terminal)\b',match[2]):
                return 'unsupported',{}
        if self.discovery is not None:
            if self.locations_known(message): return None
            route=self.discovery.parse(text)
            if route: return route
        if text.startswith('resume '): return 'unsupported',{}
        return None

    @staticmethod
    def locations_known(message):
        from friday.tools.locations import SemanticLocationResolver
        return SemanticLocationResolver().fast_location(message) is not None
