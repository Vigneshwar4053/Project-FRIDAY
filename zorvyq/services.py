"""Transport-independent controller. No Qt/telemetry; no startup credential reads."""
from dataclasses import replace
from contextlib import closing
import http.client
import importlib.util
import json
from pathlib import Path
import sqlite3
from threading import Lock, Event
from time import monotonic, process_time
from urllib.parse import urlsplit

from zorvyq.preferences import Preferences, generation_prompt
from zorvyq.security import SPECIALIST
from zorvyq.model_modes import profile as mode_profile, MODE_LENGTH, LENGTH_MODE
from friday.config.settings import settings
from friday.core.assistant import FridayAssistant
from friday.models import ModelManager
from friday.providers.ollama import OllamaProvider
from friday.providers.base import ProviderError
from friday.sync import create_synchronization

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = 'qwen3:4b'

class LocalService:
    """Bounded loopback-only HTTP. Never inherits HTTP proxy configuration."""
    def __init__(self, base_url=settings.ollama_base_url, timeout=3):
        parsed = urlsplit(base_url)
        if (parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}
                or parsed.username or parsed.password or parsed.path not in {'', '/'}
                or parsed.query or parsed.fragment):
            raise ValueError('Desktop model service must use loopback HTTP.')
        self.host, self.port, self.timeout = parsed.hostname, parsed.port or 11434, timeout

    def request(self, path, payload=None):
        if path not in {'/api/tags', '/api/ps', '/api/show', '/api/generate'}:
            raise ValueError('Unsupported model metadata operation.')
        connection = http.client.HTTPConnection(self.host, self.port, timeout=self.timeout)
        try:
            body = None if payload is None else json.dumps(payload).encode()
            connection.request('GET' if body is None else 'POST', path, body,
                               {'Content-Type': 'application/json'})
            response = connection.getresponse()
            raw = response.read(1048577)
            if response.status != 200 or len(raw) > 1048576:
                raise ValueError('Model service unavailable.')
            result = json.loads(raw)
            if type(result) is not dict or 'error' in result:
                raise ValueError('Invalid model metadata.')
            return result
        except (OSError, ValueError, http.client.HTTPException):
            raise ProviderError('Local model service unavailable.', category='connection_failure') from None
        finally:
            connection.close()

    def models(self):
        installed = self.request('/api/tags').get('models')
        loaded = self.request('/api/ps').get('models')
        if (type(installed) is not list or type(loaded) is not list or
                any(type(m) is not dict or type(m.get('name')) is not str for m in installed + loaded)):
            raise ProviderError('Invalid model inventory.')
        return {'installed': installed, 'loaded': loaded}

class DesktopProvider(OllamaProvider):
    """Checks residency while ModelManager holds the actual inference gate."""
    def __init__(self, service, configuration, model=DEFAULT_MODEL):
        super().__init__(configuration.ollama_base_url, model,
                         timeout=configuration.ollama_timeout, think=False)
        self.service = service
        self.keep_alive = 0
        self.supports_thinking_control = model == DEFAULT_MODEL
        self.desktop_profile = None
        self.residency = None

    def chat(self, messages):
        loaded = self.service.request('/api/ps').get('models')
        if (type(loaded) is not list or any(type(m) is not dict or m.get('name') != self.model for m in loaded)):
            raise ProviderError('Another model is resident. Review AI Models; no model was evicted.', category='residency_conflict')
        if loaded and self.residency is not None and any(
                self.residency.leases.get(self.model) != self.residency.identity(row) or self.residency.identity(row) is None for row in loaded):
            raise ProviderError('Shared model ownership is unconfirmed. Review AI Models and approve an exact unload before retrying.',category='residency_conflict')
        try:
            if self.desktop_profile is not None and not (self._profile and self._profile.json_output):
                with self.inference_profile(self.desktop_profile):
                    return super().chat(messages)
            return super().chat(messages)
        finally:
            if self.residency is not None and not loaded:
                self.residency.observe(self.model)


class Residency:
    """Conservative app-created residency leases, never authority over foreign clients."""
    def __init__(self, service):
        self.service, self.leases = service, {}
        self.status = 'No app-owned resident models'

    @staticmethod
    def identity(row):
        if not isinstance(row.get('digest'),str) or not isinstance(row.get('expires_at'),str):
            return None
        return (row['digest'],row['expires_at'],row.get('size'),row.get('size_vram'))

    def observe(self, model):
        try:
            rows = self.service.request('/api/ps').get('models',[])
            for row in rows:
                if row.get('name') == model and self.identity(row):
                    self.leases[model] = self.identity(row)
        except Exception:
            self.status = 'Residency ownership unconfirmed; no foreign unload permitted'

    def release(self):
        if not self.leases:
            return
        try:
            rows = self.service.request('/api/ps').get('models',[])
            for row in rows:
                model = row.get('name')
                if model in self.leases and self.identity(row) == self.leases[model]:
                    self.service.request('/api/generate',{'model':model,'keep_alive':0,'stream':False})
            remaining = self.service.request('/api/ps').get('models',[])
            self.status = ('Unload unconfirmed or residency changed; review AI Models' if any(r.get('name') in self.leases for r in remaining)
                           else 'App-owned generation models unloaded')
        except Exception:
            self.status = 'Unload unavailable; no Ollama service or foreign process was stopped'
        finally:
            self.leases.clear()

class ProtectedActionsUnavailable:
    """Never touches .env. Existing gateway still requires authentication."""
    def authenticate(self, request):
        from friday.security.owner import OwnerAuthenticationError
        raise OwnerAuthenticationError('Owner-protected desktop actions are unavailable in this desktop checkpoint.')

class Controller:
    """Single worker owner. Busy calls fail closed; no parallel model scheduling."""
    def __init__(self, approval, knowledge_approval_factory, configuration=settings):
        self.configuration = replace(configuration, assistant_name='ZORVYQ', ollama_model=DEFAULT_MODEL)
        self.service = LocalService(self.configuration.ollama_base_url)
        self.approval, self.knowledge_approval_factory = approval, knowledge_approval_factory
        self._lock = Lock()
        self.assistant = self.manager = self.synchronization = None
        self.last_error = None
        self.resources = ResourceMonitor()
        self.preferences = None
        self.residency = Residency(self.service)
        self.closed = False
        self.knowledge_cancelled = Event()

    def _initialize(self):
        if self.assistant is not None:
            return
        from friday.main import create_tool_runtime
        from friday.intelligence.rag import live_orchestrator
        from zorvyq.chroma_bridge import CompatibleChromaIndex
        self.synchronization = create_synchronization(self.configuration.sync_library_path)
        provider = DesktopProvider(self.service, self.configuration)
        provider.residency = self.residency
        self.manager = ModelManager(provider, DEFAULT_MODEL, synchronization=self.synchronization)
        try:
            # Construction does not open credentials. Only an explicit protected
            # tool operation may invoke the original authenticator later.
            from friday.security.owner import OwnerAuthenticator
            owner = (OwnerAuthenticator(self.configuration.project_root/'.env', reader=self.approval.secret)
                     if callable(getattr(self.approval, 'secret', None)) else ProtectedActionsUnavailable())
            tools, router = create_tool_runtime(self.configuration, filesystem_approval=self.approval,
                                               owner_authentication=owner)
            self.assistant = FridayAssistant(self.manager, self.configuration.system_prompt,
                tool_manager=tools, tool_router=router, workload_configuration=self.configuration)
            self.assistant.knowledge = live_orchestrator(self.manager, self.configuration,
                approval_factory=self.knowledge_approval_factory, index_factory=CompatibleChromaIndex,
                cancelled=self.knowledge_cancelled)
        except BaseException:
            self.manager.close()
            self.synchronization.close()
            self.manager = self.synchronization = None
            raise

    def ask(self, text, approved_knowledge=False, model=DEFAULT_MODEL, answer_length=None, mode=None, progress=None):
        if not isinstance(text, str) or not text.strip() or len(text.encode()) > 8192:
            raise ValueError('Enter a question of at most 8192 UTF-8 bytes.')
        if not self._lock.acquire(blocking=False):
            raise ProviderError('A request is already running.')
        try:
            if self.closed:
                raise ProviderError('Desktop controller is closed.', category='gui_worker_failure')
            self.knowledge_cancelled.clear()
            self._initialize()
            from friday.intelligence.rag import explicit_question
            is_knowledge = approved_knowledge or explicit_question(text) is not None
            if model not in {DEFAULT_MODEL, SPECIALIST}:
                raise ValueError('Unsupported desktop generation model.')
            mode = mode or LENGTH_MODE[answer_length or (self.preferences.values['answer_length'] if self.preferences else 'Short')]
            length = MODE_LENGTH[mode]
            prompt = generation_prompt(model, self.configuration.system_prompt, length)
            selected_profile = mode_profile(model, mode, text)
            notify = progress or (lambda value: None)
            notify('Checking model residency; loading selected model on demand')
            # Only prior app-created leases may be released automatically.
            with self.synchronization:
                self.residency.release()
            self.manager.provider.desktop_profile = selected_profile
            self.assistant.knowledge.stage_callback = notify
            if model == SPECIALIST:
                if is_knowledge:
                    raise ProviderError('Specialist RAG compatibility awaits owner acceptance. Select Qwen for approved knowledge.', category='model_mismatch')
                installed = {m['name'] for m in self.service.models()['installed']}
                if model not in installed:
                    raise ProviderError('Specialist unavailable. Select Qwen explicitly; no silent fallback.', category='model_unavailable')
                provider = DesktopProvider(self.service, self.configuration, model)
                provider.desktop_profile = selected_profile
                provider.residency = self.residency
                # Separate immutable manager shares the original native inference gate.
                with ModelManager(provider, model, synchronization=self.synchronization) as manager:
                    try:
                        answer = manager.generate([
                            {'role': 'system', 'content': prompt},
                            {'role': 'user', 'content': text}], private=True, profile=selected_profile)
                        from friday.core.response import public_conversation_request
                        return {'answer': answer, 'knowledge_status': None, 'speech_eligible': public_conversation_request(text)}
                    finally:
                        if manager.last_job:
                            manager.last_job.messages = []
                            manager.last_job.result = None
                            manager.last_job.error = None
            self.assistant.messages[0]['content'] = prompt
            self.assistant.knowledge.system_prompt = prompt
            request = 'answer using approved knowledge: '+text if approved_knowledge else text
            answer = self.assistant.respond(request, persist=False)
            status = self.assistant.knowledge.last_status if is_knowledge else None
            from zorvyq.rag_runtime import runtime_status
            if status and status.get('failure_category') == 'backend_failure' and not runtime_status()['available']:
                status = {**status, 'failure_category':'dependency_unavailable'}
            self.last_error = status.get('failure_category') if status else None
            return {'answer': answer, 'knowledge_status': status,
                    'speech_eligible': not is_knowledge and self.assistant.last_response_metadata.speech_eligible}
        finally:
            # Desktop never persists chat or leaves model jobs holding private text.
            if self.assistant is not None and self.assistant.knowledge is not None:
                self.assistant.knowledge.stage_callback = None
            if self.manager is not None and self.manager.last_job is not None:
                self.manager.last_job.messages = []
                self.manager.last_job.result = None
                self.manager.last_job.error = None
            self._lock.release()

    def cancel_knowledge(self):
        """Cancel vector/embedding waits; synchronous generation still finishes boundedly."""
        self.knowledge_cancelled.set()

    def tool_inventory(self):
        self._initialize()
        return self.assistant.tool_manager.registry.list_tools()

    def summarize_activity(self, aggregates, model=DEFAULT_MODEL):
        """Optional local inference on numeric category totals only; no tools or raw history."""
        allowed={'Programming','Browsing','Terminal','Files','Studying','Other'}
        if (type(aggregates) is not list or len(aggregates)>6 or any(
                type(r) is not dict or set(r)!={'category','seconds','count'} or r['category'] not in allowed or
                type(r['seconds']) not in (int,float) or not 0<=r['seconds']<=86400*100 or
                type(r['count']) is not int or not 0<=r['count']<=1000000 for r in aggregates)):
            raise ValueError('Invalid aggregate activity input')
        if model not in (DEFAULT_MODEL,SPECIALIST):raise ValueError('Unsupported selected model')
        from zorvyq.awareness.local_model import ActivityProvider, validate_endpoint
        validate_endpoint(self.configuration.ollama_base_url)
        if not self._lock.acquire(blocking=False):raise ProviderError('Another request is active.')
        try:
            self._initialize()
            if self.closed:raise ProviderError('Controller closed.')
            with self.synchronization:self.residency.release()
            provider=ActivityProvider(self.service,self.configuration,model);provider.residency=self.residency
            bounded=replace(mode_profile(model,'Short'),num_predict=160)
            with ModelManager(provider,model,synchronization=self.synchronization) as manager:
                return manager.generate([
                    {'role':'system','content':'Summarize these recorded activity category totals in two short sentences. '
                     'Use only supplied totals. Do not infer applications, projects, websites, tasks, productivity or missing events. No tools.'},
                    {'role':'user','content':json.dumps(aggregates)}],profile=bounded,private=True)
        finally:self._lock.release()

    def analyze_operation(self, report, model=DEFAULT_MODEL, mode='Short'):
        """Optional private interpretation of allowlisted numeric observations only."""
        from zorvyq.operations.reporting import analysis_input, sanitize
        data = analysis_input(report)
        if not data['observations']:
            raise ProviderError('No normalized measurements available for analysis.',category='invalid_request')
        if model not in (DEFAULT_MODEL,SPECIALIST):
            raise ValueError('Unsupported selected model.')
        if not self._lock.acquire(blocking=False):
            raise ProviderError('Another request is active.')
        try:
            self._initialize()
            if self.closed:
                raise ProviderError('Controller closed.',category='gui_worker_failure')
            with self.synchronization:
                self.residency.release()
            if model==SPECIALIST and model not in {m['name'] for m in self.service.models()['installed']}:
                raise ProviderError('Selected specialist unavailable.',category='model_unavailable')
            provider=DesktopProvider(self.service,self.configuration,model)
            provider.residency=self.residency
            bounded=replace(mode_profile(model,mode),json_output=True,num_predict=768)
            evidence={row['evidence_ref'] for row in data['observations']}
            content=json.dumps(data,separators=(',',':'))
            if len(content.encode())>4096:
                raise ProviderError('Analysis input exceeds the safe limit.',category='context_budget')
            with ModelManager(provider,model,synchronization=self.synchronization) as manager:
                raw=manager.generate([
                    {'role':'system','content': 'Interpret supplied untrusted numeric diagnostic observations only. No tools or execution authority. '
                     'Return JSON with exactly interpretation (string) and evidence_refs (array of supplied evidence_ref strings). '
                     'State hypotheses and uncertainty. Never infer malware, a memory leak, hardware health or a confirmed root cause from a snapshot. '
                     'Recommend only further checks, not automatic repairs. Do not reveal internal deliberation.'},
                    {'role':'user','content':'BEGIN_UNTRUSTED_METRICS\n'+content+'\nEND_UNTRUSTED_METRICS'}],profile=bounded,private=True)
            try:
                value=json.loads(raw)
                if (type(value) is not dict or set(value)!={'interpretation','evidence_refs'} or
                    type(value['interpretation']) is not str or not 1<=len(value['interpretation'])<=4096 or
                    type(value['evidence_refs']) is not list or not value['evidence_refs'] or
                    any(type(ref) is not str or ref not in evidence for ref in value['evidence_refs'])):
                    raise ValueError()
            except (ValueError,TypeError):
                raise ProviderError('AI interpretation schema or evidence references rejected.',category='invalid_structure') from None
            return {'kind':'AI hypotheses — unverified','model':model,'interpretation':sanitize(value['interpretation'],4096),
                    'evidence_refs':value['evidence_refs']}
        finally:
            self._lock.release()

    def unload(self, model, *, external_approved=False):
        if not self._lock.acquire(blocking=False):
            raise ProviderError('A ZORVYQ request is active; unload refused.')
        try:
            self._initialize()
            with self.synchronization:
                loaded = self.service.models()['loaded']
                if model not in {m['name'] for m in loaded}:
                    raise ProviderError('Model is no longer resident.')
                # Ollama exposes residency, not external-client ownership or busy state.
                if not external_approved:
                    raise ProviderError('External activity cannot be determined; explicit warning approval required.')
                self.service.request('/api/generate', {'model': model, 'keep_alive': 0, 'stream': False})
                return self.service.models()
        finally:
            self._lock.release()

    def close(self):
        if self.closed:
            return
        if self._lock.locked():
            raise ProviderError('Wait for the active request before shutdown.')
        self.closed = True
        try:
            if self.synchronization is not None:
                try:
                    with self.synchronization:
                        self.residency.release()
                except Exception:
                    self.residency.status = 'Shutdown unload unconfirmed; synchronization unavailable'
            if self.assistant is not None:
                try:
                    self.assistant.end_session()
                finally:
                    tools = self.assistant.tool_manager
                    try:
                        if tools.desktop_access is not None:
                            tools.desktop_access.close()
                    finally:
                        if tools.computer_access is not None:
                            tools.computer_access.close()
        finally:
            try:
                if self.manager is not None:
                    self.manager.close()
            finally:
                if self.synchronization is not None:
                    self.synchronization.close()


def knowledge_inventory(root=ROOT):
    """Read approved metadata only. Never select document/chunk text or embed."""
    from friday.intelligence.models import fingerprint
    from scripts.phase1e_index_preflight import APPROVED
    artifact = json.loads((root/'docs/FRIDAY_PHASE1E_CORPUS.json').read_text())
    scope = artifact['approval_scope']
    if fingerprint(scope) != artifact['approval_sha256'] or artifact['approval_sha256'] != APPROVED:
        raise ValueError('Approved metadata scope could not be verified.')
    path = root/'data/intelligence/phase1e/knowledge/knowledge.sqlite3'
    rows = []
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as connection:
        connection.execute('PRAGMA query_only=ON')
        for doc in scope['documents']:
            record = connection.execute('''SELECT r.source_json, r.document_revision,
                r.content_sha256, r.ingested_at, r.revision_id FROM sources s JOIN revisions r
                ON r.revision_id=s.current_revision WHERE s.source_id=? AND s.state='active' ''',
                (doc['knowledge_source_id'],)).fetchone()
            if record is None or record[1] != doc['document_version'] or record[2] != doc['processed_sha256']:
                continue
            source = json.loads(record[0])
            if source['identifier'] != doc['source_url']:
                continue
            chunks = connection.execute('SELECT count(*) FROM chunks WHERE revision_id=?', (record[4],)).fetchone()[0]
            indexed = connection.execute('''SELECT count(DISTINCT c.chunk_id) FROM chunks c
                JOIN indexed_chunks i ON i.chunk_id=c.chunk_id WHERE c.revision_id=?''', (record[4],)).fetchone()[0]
            rows.append({'title': source['title'], 'url': source['identifier'],
                         'topics': source.get('topics', []), 'revision': record[1],
                         'source_id': doc['knowledge_source_id'], 'chunks': chunks,
                         'indexed': indexed, 'ingested_at': record[3]})
    from zorvyq.rag_runtime import runtime_status
    return {'documents': rows, 'sources': len(rows), 'chunks': sum(d['indexed'] for d in rows),
            'database': 'Available (read-only metadata)',
            'index': 'SQLite index records only; live vector integrity checked on authorized retrieval',
            'chroma_dependency': importlib.util.find_spec('chromadb') is not None,
            'rag_runtime': runtime_status(root)}


def resource_snapshot():
    """Bounded Linux metadata; no environment, process arguments, paths or prompts."""
    import os
    mem = {}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key, value = line.split(':', 1)
        if key in {'MemTotal', 'MemAvailable'}:
            mem[key] = int(value.strip().split()[0])
    rss = int(Path('/proc/self/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')
    return {'system_memory_used_percent': round(100*(1-mem['MemAvailable']/mem['MemTotal']), 1),
            'gui_process_rss_mib': round(rss/1024**2, 1),
            'system_load_1m': os.getloadavg()[0],
            'ollama_memory': 'Shared service; model residency sizes shown on AI Models'}


class ResourceMonitor:
    """Sample CPU counters without a blocking utilization measurement."""
    def __init__(self):
        self.previous = None

    def snapshot(self):
        result = resource_snapshot()
        ticks = [int(v) for v in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
        current = (sum(ticks), ticks[3]+ticks[4], monotonic(), process_time())
        if self.previous is None:
            result.update(system_cpu_used_percent='Awaiting second sample', gui_cpu_percent='Awaiting second sample')
        else:
            total = current[0]-self.previous[0]
            idle = current[1]-self.previous[1]
            wall = current[2]-self.previous[2]
            result['system_cpu_used_percent'] = round(100*(1-idle/total), 1) if total > 0 else 'Unavailable'
            result['gui_cpu_percent'] = round(100*(current[3]-self.previous[3])/wall, 1) if wall > 0 else 'Unavailable'
        self.previous = current
        return result
