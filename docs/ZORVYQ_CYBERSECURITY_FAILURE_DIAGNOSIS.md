# Cybersecurity failure diagnosis — Phase 2B

Inspection date: 2026-10-31. Branch: `feature/voice-foundation`. No inference,
network scan, audio capture or private document read was used for diagnosis.

## Confirmed observations and causes

1. Read-only approved metadata inventory verified **20 active approved sources and
   312 indexed chunk records**. Counts are derived at runtime, not inserted into UI
   constants. SQLite counts do not prove Chroma vector integrity.
2. `importlib.util.find_spec('chromadb')` returned unavailable in the current Python
   3.14 environment. Live approved retrieval cannot be accepted here without a
   separately approved dependency compatibility review/installation. No index was
   deleted, rebuilt, reindexed or copied.
3. The Phase 2A cybersecurity page defaulted to Use Approved Knowledge but offered
   Foundation-Sec in the same independent selector. The controller correctly refused
   that incompatible combination, producing a seemingly unresponsive specialist
   experience. It now has separate Approved Knowledge and Specialist Chat modes.
4. The worker recognized only a small subset of provider errors. Returned RAG status
   was displayed alongside generic backend text, and schema/citation/permission
   failures were difficult to distinguish. Fixed safe categories and expandable,
   scalar-only technical status now expose the actual failure class.
5. Inspection confirmed the input's Enter signal, Send callback and worker result /
   finished connections existed. No missing connection or prematurely terminating
   worker was established. Per-request model/mode values are captured on the GUI
   thread; they are never read from Qt controls by the inference worker.
6. Local Ollama `/api/show` metadata was inspected without loading models. Qwen
   advertises completion/tools/thinking, family qwen3. Foundation-Sec advertises
   completion only, family llama. Both templates contain role markers and references
   to thinking, but a template string alone is not evidence that the same API control
   is supported. Desktop Foundation-Sec requests now omit the thinking control.
7. Existing residency refusal remains necessary: the POSIX gate serializes this
   application's inference; it does not establish memory ownership of the shared
   Ollama service. Unconfirmed resident workloads are not automatically evicted.

## Request lifecycle after repair

User submission → freeze model/depth/scope → serialized Qt worker → select explicit
mode → existing backend → one-time exact knowledge authorization when retrieval is
available → Nomic/Chroma retrieval → native-gated Qwen generation → original strict
claims schema/source-revision/citation validation → safe result/status → GUI display.
Specialist Chat takes a separate private generation path with Foundation-Sec and
states that model answers are experimental and not automatically source-verified.
There is no automatic cybersecurity router or general-model fallback for failed RAG.

The RAG orchestrator emits fixed stage names (backend, retrieval, generation,
validation). Its authorization bridge remains a queued GUI-thread dialog; Deny is
the default. Failure categories distinguish evidence absence, denial, unavailable
model/dependency, connection failure, timeout, truncation/incomplete generation,
invalid schema, rejected citations, source changes, residency/synchronization and
worker failure. No private question, answer, evidence passage, raw exception or
credential is added to diagnostic logging. Chat and technical status remain ephemeral.

## Qt/Wayland finding — unconfirmed correlation

The reported `qt.qpa.wayland.textinput` focus warning concerns the input-method
protocol. The warning alone does not establish failed submission. There is no
captured owner reproduction tying it to missing keystrokes or a lost request.
Offscreen Qt tests exercise focus, typing, Shift+Enter, Enter, Send, model/depth
changes, worker responsiveness and result delivery; they pass. They do **not** test
physical Wayland input-method integration and cannot certify the warning harmless
on the owner's compositor.

No global Wayland change, warning filter or permanent display-backend override was
added. The existing app-local generic theme/Fusion choice remains unchanged.
Offscreen mode is used only by automated tests. Owner acceptance should reproduce
with a harmless synthetic question, try Enter and Send separately, and inspect the
technical category. Record whether characters were lost, Send was disabled, a
permission dialog was awaiting a decision, or the worker actually returned a backend
failure. A focus-specific workaround requires that evidence first.

## Hypotheses and remaining acceptance

A shared resident model, local provider outage, source/index mismatch, unsupported
live specialist behavior, generation truncation or Wayland IME issue may affect a
particular owner session. None was established by live inference in this checkpoint.
Synthetic tests verify their safe handling, not their occurrence. Chroma dependency
repair and physical Wayland/live model acceptance remain owner checkpoints.
