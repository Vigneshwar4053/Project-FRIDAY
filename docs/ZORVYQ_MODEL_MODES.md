# Manual models and response-depth controls

AI Chat has a Model dropdown containing the exact Ollama identities:

| Display | Identity | Current semantics |
| --- | --- | --- |
| Qwen3:4b | `qwen3:4b` | Default general model; approved RAG generation model |
| Foundation-Sec-8B-Instruct | `dr-ry/foundation-sec-8b-instruct-chat-GGUF:latest` | Experimental manual model chat; no production RAG |

No restart is required. Unavailable service/model entries are labeled unavailable;
a selected missing model is not substituted. Model, knowledge-mode and response-depth
controls are disabled while the serialized worker runs. The cybersecurity selector
chooses the explicit Approved Knowledge/Qwen or Specialist Chat/Foundation-Sec pair.

Immediately above the input, **Short**, **Medium** and **Deep Analysis** choose final
response depth. Short requests about 1–3 sentences for simple questions. Medium adds
supporting details/examples. Deep Analysis requests a fuller technical explanation,
assumptions, qualifications and conclusions. These are response-depth preferences,
not measured reasoning quality or a promise to expose private reasoning. Explicit
requests for more detail retain priority, complete code and verified citations.

Local `/api/show` inspection found Qwen's thinking capability and Foundation-Sec's
completion-only capability. Desktop prompts use standard chat roles so Ollama applies
its own installed template. Qwen uses `think=false`; Foundation-Sec omits that API
control. Neither displays message.thinking or marked internal deliberation. Legacy
adaptive classification remains available, but composer generation profiles take
precedence for ordinary model chat. No raw chain of thought is requested/displayed.

Ordinary chat budgets: context 8192; output tokens 768/1024/2048 for Short/Medium/Deep;
timeout 300/300/450 seconds; temperature 0.3; zero history messages; bounded input and
transport; explicit normal completion required. A direct request for detail raises
the output budget to Deep while retaining the saved preference. Exceeding a budget
fails safely rather than presenting truncated output. RAG retains its existing JSON
profile/evidence/claims budget and verification; see the cybersecurity guide.

Settings persist atomically in `~/.config/zorvyq/desktop.json` (absolute XDG override
supported), mode 0600 for new files. `selected_model` and `response_mode` are added
without discarding voice/history settings. Existing Balanced/Detailed preferences
migrate to Medium/Deep Analysis when the new field is absent. Theme remains session-only.

## Residency and exit

Generation loads only on an explicit request. The existing native POSIX mutex remains
the inference gate. Model residency is checked separately. Normal desktop generation
uses `keep_alive=0`; the embedding adapter already does so. Foreign or unconfirmed
resident models block requests; AI Models offers warned explicit unload. This also
applies to an externally preloaded copy of the same generation model, preventing
silent reuse followed by automatic unload of that workload.

If a model absent before an app request remains resident afterward, the controller
records a conservative digest/expiry/size lease. Only unchanged app-created leases
are eligible for release before a new generation or on exit. Changed/unknown leases
are left alone. Ollama does not expose client ownership; external races remain a
limitation. This is not a global Ollama scheduler.

**Closing ZORVYQ now waits for bounded generation, denies unfinished authorization,
cancels owned operation work, and performs model cleanup on a worker before closing.**
It does not stop the Ollama daemon, delete models, kill unrelated clients or evict
unconfirmed shared workloads. Crashes/power loss cannot guarantee GUI cleanup;
per-request zero keep-alive still applies. Unload connection/gate failure is reported
as unconfirmed rather than claimed successful.

Owner acceptance: switch both models, try all depths, confirm controls freeze during
generation and selections restore after restart. Inspect AI Models before/after
requests, then close/reopen and verify no app-owned generation models remain. If a
shared model blocks the request, inspect it and use explicit warned unload only if
appropriate. No live inference was used by automated tests.
