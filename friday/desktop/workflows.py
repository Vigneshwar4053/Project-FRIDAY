"""Deterministic plans only: this module has no dispatcher, model or I/O."""
from dataclasses import dataclass
from enum import StrEnum
import ipaddress
import re
from urllib.parse import urlsplit
from friday.tools.locations import command_text
from friday.desktop.websites import WEBSITES, site_destination, search_url, site_search_query


class WorkflowAction(StrEnum):
    LAUNCH = 'launch_application'
    VERIFY_WINDOW = 'verify_window'
    ADDRESS = 'focus_address_bar'
    SEARCH = 'enter_search_query'
    URL = 'enter_url'
    SUBMIT = 'submit_navigation'
    VERIFY_NAVIGATION = 'verify_navigation'
    DISCOVER = 'discover_target'
    OPEN_DISCOVERED = 'open_discovered_target'
    OPEN_FOLDER = 'open_folder'
    OPEN_PROJECT = 'open_project'
    UNSUPPORTED = 'unsupported_request'


class Capability(StrEnum):
    AVAILABLE = 'supported_via_gateway'
    UNAVAILABLE = 'planned_not_executable'
    RESTRICTED = 'conditional_native_snap_handoff_blocked'


CAPABILITIES = {
    WorkflowAction.LAUNCH: Capability.AVAILABLE,
    WorkflowAction.DISCOVER: Capability.AVAILABLE,
    WorkflowAction.OPEN_FOLDER: Capability.AVAILABLE,
    WorkflowAction.OPEN_DISCOVERED: Capability.RESTRICTED,
    WorkflowAction.OPEN_PROJECT: Capability.RESTRICTED,
}
SITES = WEBSITES


def bounded_value(value):
    if type(value) is not str or not value or len(value.encode('utf-8'))>512 or any(
            ord(c)<32 or ord(c)==127 for c in value) or any(c in value for c in (';', '|', '`', '$', '\\')):
        raise ValueError('Unsafe or oversized workflow value.')
    if re.search(r'\b(?:and|then)\s+(?:run|execute|delete|install|upload|send|open|read|search|find)\b',value,re.I):
        raise ValueError('Extra workflow steps are unsupported.')
    return value


@dataclass(frozen=True)
class WorkflowStep:
    action: WorkflowAction
    application: str | None = None
    value: str | None = None
    scope: str | None = None

    def __post_init__(self):
        if type(self.action) is not WorkflowAction:
            raise ValueError('Typed workflow action required.')
        if self.application not in {None,'firefox','vscode','files'} or self.scope not in {None,'downloads','documents'}:
            raise ValueError('Unreviewed workflow target.')
        if self.value is not None: bounded_value(self.value)
        if self.action is WorkflowAction.LAUNCH and (self.application is None or self.value is not None or self.scope is not None):
            raise ValueError('Exact application-only launch plan required.')
        if self.action in {WorkflowAction.ADDRESS,WorkflowAction.SEARCH,WorkflowAction.URL,
                           WorkflowAction.SUBMIT,WorkflowAction.VERIFY_NAVIGATION}:
            if self.application!='firefox' or self.scope is not None:
                raise ValueError('Browser plan requires Firefox.')
            if self.action in {WorkflowAction.SEARCH,WorkflowAction.URL}:
                if self.value is None: raise ValueError('Exact navigation value required.')
                if self.action is WorkflowAction.URL and website(self.value)!=self.value:
                    raise ValueError('Exact HTTPS URL required.')
            elif self.value is not None:
                raise ValueError('Unexpected navigation payload.')
        if self.action is WorkflowAction.DISCOVER and (self.value is None or
                not re.fullmatch(r'[\w][\w .-]{0,99}',self.value) or '..' in self.value or self.application is not None):
            raise ValueError('Bounded discovery name required.')
        if self.action is WorkflowAction.OPEN_FOLDER and (self.application!='files' or self.value not in {'downloads','documents'} or self.scope is not None):
            raise ValueError('Registered folder alias required.')
        if self.action is WorkflowAction.OPEN_DISCOVERED and (self.value!='unique_discovery_result' or self.application is not None or self.scope is not None):
            raise ValueError('Unresolved unique discovery binding required.')
        if self.action is WorkflowAction.OPEN_PROJECT and (self.application!='vscode' or self.value!='unique_discovery_result' or self.scope is not None):
            raise ValueError('Verified project binding required.')
        if self.action in {WorkflowAction.VERIFY_WINDOW,WorkflowAction.UNSUPPORTED} and (self.value is not None or self.scope is not None):
            raise ValueError('Unexpected action payload.')
        if self.action is WorkflowAction.UNSUPPORTED and self.application is not None:
            raise ValueError('Unsupported step cannot select an application.')

    @property
    def capability(self):
        return CAPABILITIES.get(self.action,Capability.UNAVAILABLE)


@dataclass(frozen=True)
class WorkflowPlan:
    steps: tuple[WorkflowStep, ...]
    clarification: str | None = None

    def __post_init__(self):
        if type(self.steps) is not tuple or not 1<=len(self.steps)<=8 or any(type(s) is not WorkflowStep for s in self.steps):
            raise ValueError('A bounded typed workflow plan is required.')
        if self.clarification is not None: bounded_value(self.clarification)

    def response(self):
        if self.clarification:
            return self.clarification+' No workflow steps were executed.'
        browser=any(s.action in {WorkflowAction.SEARCH,WorkflowAction.URL} for s in self.steps)
        opening=('I understand the request, but browser search/navigation automation is not available yet. '
                 "I haven't opened Firefox, searched, or navigated. No workflow steps were executed." if browser else
                 'I understand the workflow. Multi-step execution is not enabled; no steps were executed.')
        return opening+'\nPlan only:\n'+'\n'.join(
            str(i+1)+'. '+s.action.value+(' ['+s.application+']' if s.application else '')+
            (': '+s.value if s.value else '')+(' in '+s.scope if s.scope else '')+
            ' ('+s.capability.value+')' for i,s in enumerate(self.steps))


def website(value):
    bounded_value(value)
    destination=site_destination(value)
    if destination is not None: return destination
    if value.casefold() in SITES: return SITES[value.casefold()]
    if not value.startswith('https://'): return None
    parsed=urlsplit(value)
    if (parsed.scheme!='https' or not parsed.hostname or parsed.username is not None or
            parsed.password is not None or parsed.fragment or parsed.port not in {None,443}):
        raise ValueError('Unsupported website URL.')
    host=parsed.hostname
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if '.' not in host or host.endswith(('.local','.localhost')) or not re.fullmatch(r'[A-Za-z0-9.-]+',host):
            raise ValueError('Unsupported website hostname.')
    else:
        raise ValueError('IP address navigation is not planned.')
    return value


def _parse_workflow(message):
    # URL/query punctuation is data; never trim it into a different destination.
    raw=command_text(message).strip()
    raw=re.sub(r'^please\s+','',raw,flags=re.I)
    # Only registered aliases become standalone browser workflows; keep folder,
    # application and file discovery grammar separate. URL punctuation is data.
    single=re.fullmatch(r'open (.+)',raw,re.I)
    if single and site_destination(single[1]) is not None:
        return _browser_plan(site_destination(single[1]),WorkflowAction.URL)
    # Explicit website intent never enters local file/project discovery.
    explicit_site = re.fullmatch(
        r'open (?:the )?(?:website|site) (.+)|open (.+) (?:website|site)|open (.+) in firefox',raw,re.I)
    if explicit_site:
        destination = site_destination(explicit_site[1] or explicit_site[2] or explicit_site[3])
        if destination is not None:
            return _browser_plan(destination,WorkflowAction.URL)
        return WorkflowPlan((WorkflowStep(WorkflowAction.UNSUPPORTED),),
            'That website is not registered. Provide its exact HTTPS URL for review.')
    if single and single[1].startswith(('https://','http://')):
        if single[1] in WEBSITES.values():
            return _browser_plan(single[1],WorkflowAction.URL)
        return WorkflowPlan((WorkflowStep(WorkflowAction.UNSUPPORTED),),
            'That website URL is not registered. Provide its exact HTTPS URL for review.')
    search = re.fullmatch(r'(?:search (?:firefox|google) for|search for|google) (.+)',raw,re.I)
    scoped_search = re.fullmatch(r'search (.+?) for (.+)',raw,re.I) if search is None else None
    compound_search = re.fullmatch(r'open firefox (?:and|then) search(?: for)? (.+)',raw,re.I)
    if search or scoped_search or compound_search:
        try:
            if search:
                query = search[1]
            elif compound_search:
                query = compound_search[1]
            else:
                query = site_search_query(scoped_search[1],scoped_search[2])
            bounded_value(query)
            search_url(query)
            return _browser_plan(query,WorkflowAction.SEARCH)
        except ValueError:
            return WorkflowPlan((WorkflowStep(WorkflowAction.UNSUPPORTED),),
                'Search query or site is outside the reviewed policy. Unknown websites require an exact HTTPS URL for review.')
    if not re.search(r'\s+(?:and|then)\s+',raw,re.I): return None
    def step(action,app=None,value=None,scope=None):
        return WorkflowStep(action,app,value,scope)
    if len(raw.encode('utf-8'))>1024 or any(ord(c)<32 or ord(c)==127 for c in raw) or any(c in raw for c in (';','|','`','$','\\')):
        return WorkflowPlan((step(WorkflowAction.UNSUPPORTED),),'Unsafe or oversized workflow request.')
    match=re.fullmatch(r'open firefox (?:and|then) (search(?: for)?|go to|open|navigate to) (.+)',raw,re.I)
    if match:
        verb,value=match.groups()
        try:
            bounded_value(value)
            if verb.casefold().startswith('search'):
                action=WorkflowAction.SEARCH;target=value
            else:
                action=WorkflowAction.URL;target=website(value)
                if target is None:
                    return WorkflowPlan((step(WorkflowAction.LAUNCH,'firefox'),),
                        'That site name is unrecognized or ambiguous. Provide its exact HTTPS URL, or ask to search for the name.')
            return _browser_plan(target,action)
        except ValueError:
            return WorkflowPlan((step(WorkflowAction.UNSUPPORTED),),'Unsupported or unsafe browser workflow.')
    match=re.fullmatch(r'find ([\w][\w .-]{0,99}?)(?: in (downloads|documents))? (?:and|then) open (?:it|that|the found file)',raw,re.I)
    if match:
        name,scope=match.groups()
        if '..' not in name:
            return WorkflowPlan((step(WorkflowAction.DISCOVER,value=name,scope=scope.casefold() if scope else None),
                step(WorkflowAction.OPEN_DISCOVERED,value='unique_discovery_result'),step(WorkflowAction.VERIFY_WINDOW)))
    match=re.fullmatch(r'open (downloads|documents)(?: folder)? (?:and|then) find ([\w][\w .-]{0,99})',raw,re.I)
    if match and '..' not in match[2]:
        scope=match[1].casefold()
        return WorkflowPlan((step(WorkflowAction.OPEN_FOLDER,'files',scope),
            step(WorkflowAction.DISCOVER,value=match[2],scope=scope)))
    match=re.fullmatch(r'open (?:vs code|visual studio code|vscode) (?:and|then) open (?:my )?([\w][\w .-]{0,99}) project',raw,re.I)
    if match and '..' not in match[1]:
        return WorkflowPlan((step(WorkflowAction.LAUNCH,'vscode'),step(WorkflowAction.DISCOVER,value=match[1]),
            step(WorkflowAction.OPEN_PROJECT,'vscode','unique_discovery_result'),step(WorkflowAction.VERIFY_WINDOW,'vscode')))
    # Only intercept action-shaped compounds; ordinary conversation stays chat.
    if re.match(r'^(?:open|find|launch|start)\b',raw,re.I):
        return WorkflowPlan((step(WorkflowAction.UNSUPPORTED),),'Unsupported or ambiguous desktop workflow; use one of the reviewed patterns.')
    return None


def _browser_plan(target,action):
    return WorkflowPlan(tuple(WorkflowStep(kind,'firefox',target if kind is action else None)
        for kind in (WorkflowAction.LAUNCH,WorkflowAction.VERIFY_WINDOW,WorkflowAction.ADDRESS,
                     action,WorkflowAction.SUBMIT,WorkflowAction.VERIFY_NAVIGATION)))


def parse_workflow(message):
    try:
        return _parse_workflow(message)
    except ValueError:
        return WorkflowPlan((WorkflowStep(WorkflowAction.UNSUPPORTED),),'Unsupported or unsafe desktop workflow.')
