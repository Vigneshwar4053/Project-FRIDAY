"""Central capability evidence. Availability never implies live owner acceptance."""
from dataclasses import dataclass
from enum import StrEnum

class Status(StrEnum):
    WORKING = 'WORKING'
    AVAILABLE = 'AVAILABLE'
    EXPERIMENTAL = 'EXPERIMENTAL'
    PARTIAL = 'PARTIALLY IMPLEMENTED'
    UNAVAILABLE = 'UNAVAILABLE'
    PLANNED = 'PLANNED'

@dataclass(frozen=True)
class Feature:
    feature_id: str
    name: str
    description: str
    implementation: str
    status: Status
    permission: str
    action: str
    verification: str

def features(runtime=None):
    registry = (
        Feature('chat', 'AI conversation', 'Manual Qwen/Foundation-Sec selection and composer response-depth controls; session-only conversation.',
                'friday.core.assistant.FridayAssistant', Status.AVAILABLE, 'Explicit send', 'AI Chat',
                'Historical live evidence: docs/FRIDAY_FULL_FEATURE_AUDIT.md; current service probe required'),
        Feature('rag', 'Approved cybersecurity RAG', 'Exact-scope permission, pinned sources and verified citations.',
                'friday.intelligence.rag.live_orchestrator', Status.EXPERIMENTAL, 'Allow once per question', 'Cybersecurity',
                'Existing RAG environment via read-only Chroma bridge; import checked; desktop live retrieval acceptance pending'),
        Feature('provenance', 'Knowledge provenance', 'SQLite metadata inventory; document content remains protected.',
                'friday.intelligence.repository.KnowledgeRepository', Status.AVAILABLE, 'Metadata only', 'Knowledge',
                'Phase 2A read-only SQLite inspection'),
        Feature('vectors', 'ChromaDB retrieval', 'Existing Nomic embeddings and vector index; no inventory inference.',
                'zorvyq.chroma_bridge.CompatibleChromaIndex', Status.EXPERIMENTAL, 'Exact RAG approval', 'Knowledge',
                'Pinned existing ChromaDB 1.5.9 worker; network denied; live vector open acceptance pending'),
        Feature('specialist', 'Foundation-Sec-8B', 'Experimental manual questions; specialist RAG and automatic routing blocked pending owner acceptance.',
                'tests/test_phase1g_specialist_contract.py', Status.EXPERIMENTAL, 'No production routing', 'AI Models',
                'Historical manual benchmark; not approved for production'),
        Feature('tts', 'Offline speech output', 'Explicit speech; intermittent audio failures remain device dependent.',
                'friday.voice.tts.EspeakNGBackend', Status.EXPERIMENTAL, 'Explicit speech text only', 'Voice',
                'Source and voice regression tests; no current audible acceptance'),
        Feature('microphone', 'Confirmed microphone input', 'Bounded local capture, transcript review and separate send.',
                'friday.voice.backend.LocalVoiceBackend', Status.EXPERIMENTAL, 'Activate once, then confirm transcript', 'Voice',
                'Capture/confirmation tests; physical microphone acceptance required'),
        Feature('desktop', 'Approved desktop tools', 'Registered typed tools; exact operation permissions retained.',
                'friday.main.create_tool_runtime', Status.PARTIAL, 'Existing tool gateway; owner authentication for protected actions', 'Desktop Tools',
                'docs/FRIDAY_FULL_FEATURE_AUDIT.md; mocks do not verify visible windows'),
        Feature('recent', 'Recent project memory', 'Up to ten validated activities in the existing local SQLite store; deduplicated and removable.',
                'zorvyq.projects.Projects', Status.AVAILABLE, 'Intentional accepted launch', 'Dashboard',
                'Mocked persistence/restart tests; visible VS Code acceptance pending'),
        Feature('projects', 'VS Code project chooser', 'Numbered direct folders under /home/vigneshwar/Projects; two-minute selection expiry.',
                'zorvyq.projects.Projects', Status.AVAILABLE, 'Explicit click or current numbered reply', 'Dashboard',
                'Mocked safe launch/path tests; no real VS Code session opened'),
        Feature('greeting', 'Personalized greetings', 'Local-time greeting with approved recent work and optional resume.',
                'zorvyq.projects.greeting', Status.AVAILABLE, 'No automatic application reopening', 'Dashboard',
                'Clock fixtures and offscreen GUI tests'),
        Feature('voice_settings', 'Voice customization', 'Installed eSpeak voices, speed, volume and explicit preview; device selectors unsupported.',
                'zorvyq.voice.DesktopSpeech', Status.EXPERIMENTAL, 'Explicit speech action', 'Voice',
                'Mocked audio/preferences tests; audible acceptance pending'),
        Feature('launcher', 'Desktop application launcher', 'Terminal=false launcher using the existing project environment.',
                'scripts/install_zorvyq_desktop.py', Status.AVAILABLE, 'User-local installation requires approval', 'Settings',
                'Isolated installation tests; existing installed wrapper needs current-path repair'),
        Feature('startup', 'Login startup integration', 'Exact-entry fingerprint and reversible backup; legacy login behavior preserved.',
                'zorvyq.startup.Startup', Status.PARTIAL, 'Explicit owner migration approval', 'Settings',
                'Temporary-home tests; real login migration pending approval'),
        Feature('model_control', 'Model status and unloading', 'Metadata probes, single-generation gate, warned shared unload and conservative app-owned exit cleanup.',
                'zorvyq.services.Controller', Status.AVAILABLE, 'Explicit shared-workload warning', 'AI Models',
                'Mocked residency/unload tests; external clients can race snapshots'),
        Feature('operations', 'Ubuntu operation engine', 'Reviewed read-only modules, dry runs, exact-scope approval, sequential bounded execution and cancellation.',
                'zorvyq.operations.engine.Engine', Status.EXPERIMENTAL, 'Exact one-time operation approval', 'System Operations',
                'Synthetic command/output tests; actual checks show session verification and NOT CHECKED results'),
        Feature('diagnosis', 'Full System Diagnosis', 'Read-only composition of resource, storage, service, network, process and log metadata collectors.',
                'zorvyq.operations.registry', Status.EXPERIMENTAL, 'Exact local metadata scope; no network scans', 'System Operations',
                'Mocked orchestration only; no stress tests, repairs or hardware-health certification'),
        Feature('investigation', 'Root-cause investigation foundation', 'Snapshot correlation and optional private AI hypotheses; no automatic fixes or confirmed root-cause claims.',
                'zorvyq.operations.reporting', Status.EXPERIMENTAL, 'Explicit operation and separate AI analysis', 'System Operations',
                'Numeric normalization/schema tests; no historical memory-growth evidence'),
        Feature('security_tools', 'Cybersecurity tool integration', 'Reviewed Nmap discovery adapter with exact scope, resource bounds and cancellation.',
                'zorvyq.security.Nmap', Status.EXPERIMENTAL, 'Target authorization and exact scope confirmation', 'Cybersecurity',
                'Mocked execution only; other security tools require individual review'),
        Feature('browser', 'Browser integrations', 'Reviewed browser handoffs; environment and owner-authentication limits apply.',
                'friday.desktop.browser.ManagedBrowser', Status.EXPERIMENTAL, 'Exact approval; owner-protected handoffs require the existing authenticator', 'Desktop Tools',
                'docs/FRIDAY_FULL_FEATURE_AUDIT.md; no current live browser acceptance'),
        Feature('reasoning', 'Local reasoning modes', 'Existing bounded standard/deep workload profiles; no specialist routing.',
                'friday.core.workload', Status.AVAILABLE, 'Session setting', 'Settings',
                'Workload tests; no new inference benchmark'),
        Feature('sync', 'Native model synchronization', 'C POSIX mutex with documented Python fallback; residency checked separately.',
                'friday.sync.create_synchronization', Status.AVAILABLE, 'Internal', 'Activity',
                'Native synchronization tests and runtime backend name'),
    )
    import importlib.util
    from dataclasses import replace
    runtime = runtime or {}
    from zorvyq.rag_runtime import runtime_status
    vector_runtime = runtime_status()['available']
    if type(runtime.get('knowledge')) is dict:
        vector_runtime = runtime['knowledge'].get('rag_runtime',{}).get('available',False)
    dependencies = {'vectors': vector_runtime, 'rag': vector_runtime}
    import shutil
    dependencies['projects'] = shutil.which('code') is not None
    dependencies['security_tools'] = bool(shutil.which('nmap') and shutil.which('prlimit'))
    if 'models' in runtime:
        models = runtime['models']
        names = {m['name'] for m in models['installed']} if models is not None else set()
        dependencies['chat'] = 'qwen3:4b' in names
        dependencies['specialist'] = any('foundation-sec' in name for name in names)
        dependencies['rag'] &= dependencies['chat']
    if 'knowledge' in runtime:
        dependencies['provenance'] = runtime['knowledge'] is not None
        dependencies['rag'] &= runtime['knowledge'] is not None
    if 'tools' in runtime:
        dependencies['desktop'] = bool(runtime['tools'])
    return tuple(replace(item, status=Status.UNAVAILABLE,
                         verification=item.verification+'; required runtime dependency unavailable')
                 if dependencies.get(item.feature_id) is False else item for item in registry)
