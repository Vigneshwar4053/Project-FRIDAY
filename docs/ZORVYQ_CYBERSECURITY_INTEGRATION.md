# Cybersecurity integration

The Cybersecurity workspace uses the existing backend. Qwen3:4b remains the
unconditional general-chat default. **Use Approved Knowledge** is selected on the
cybersecurity page and delegates to the original exact-scope authorized RAG,
revision/source checks, structured claims JSON and verified citation renderer.
The Knowledge page lists approved metadata; it does not reindex or ingest documents.
No model can use that inventory to bypass retrieval permission.

## Manual specialist

The compatible general model is `qwen3:4b`. The candidate is
`dr-ry/foundation-sec-8b-instruct-chat-GGUF:latest`. Ollama tags/ps detect installation
and residency without inference. The selector labels unavailable candidates;
selecting an unavailable model fails without generating a Qwen fallback.

To try the specialist, explicitly select Foundation-Sec and turn **Use Approved
Knowledge** OFF. This is experimental ordinary cybersecurity chat, with uncertainty
instructions and no claim of verified sources. Specialist requests for approved
knowledge fail closed and direct the owner to select Qwen explicitly. There is
no automatic cybersecurity classifier/routing switch; owner acceptance must precede
any future rollout.

`tests/test_phase1g_specialist_contract.py` already checks the candidate HTTP adapter's
structured-output protocol with synthetic evidence, rejected missing/unknown or
malformed citations, revoked evidence, permission denial and output exhaustion.
Those are compatibility infrastructure, not a live specialist-RAG certification.
The production orchestrator retains its Qwen model guard. Previous manual
benchmarks found mistakes in both models; neither model is treated as authoritative.

Desktop generation serializes requests, checks residency under the existing native
POSIX inference gate, requests `keep_alive=0` after generation, and refuses conflicting
models without eviction. Explicit unload requires the existing shared-client warning.
External Ollama clients can race snapshots; their activity cannot be inferred from
residency alone. No large model is preloaded on startup. Private job bodies/results
are cleared, and desktop conversations are not persisted.

## Answer length

Settings → **Answer Length** provides Short (default), Balanced and Detailed.
The local preference file is `~/.config/zorvyq/desktop.json` (absolute XDG override
supported). Each model receives standard Ollama chat roles, letting Ollama apply
its own installed model template rather than hard-coding incompatible token markers.
Simple Short answers request about 1–3 sentences; Balanced adds a few useful details;
Detailed asks for a full explanation. Every prompt honors explicit requests for
more detail and preserves complete code, warnings, uncertainty, permission explanations
and verified citations. Validated responses are never truncated. These guidelines
are prompt-based; actual style and technical correctness require owner assessment.

## Tools and Nmap

Review of the current typed tool registry found desktop/file/system tools and no
previous Nmap or exploitation adapter. Other security tools have not been approved
for execution. Nothing adds Metasploit, exploitation or privilege escalation.

This host provides `/usr/bin/nmap` and `prlimit` from util-linux. The cybersecurity
panel shows Nmap's purpose, installed status, exact permission, supported discovery
action and last operation verification. If dependencies disappear, preparation
reports the installation requirements; packages are never installed silently.

**Request an authorized discovery scan…** asks for one IP, a strict CIDR with at
most 256 addresses, or a syntactically valid hostname, plus a purpose. The owner
must confirm authorization for that exact target and the complete displayed argument
array. This attestation is not independent proof of network ownership. An approval
is single-use and expires after two minutes. Educational command explanations in
chat never execute a scan.

The reviewed adapter constructs:

```text
prlimit --cpu=15 --as=536870912 --fsize=1048576 --
  nmap -sn -n --unprivileged --max-retries 1 --host-timeout 5s TARGET
```

IPv6 adds `-6`. Discovery is bounded to 30 seconds wall time, 15 CPU seconds,
512 MiB address space and 1 MiB output-file size; at most 64 KiB is presented.
No arbitrary shell string, port scan, script or model-proposed flags are accepted.
Execution uses `shell=False`, no stdin, a separate session, termination/kill on
cancel/timeout, and child reaping. **Cancel discovery** remains usable during the
operation. Hostnames can resolve differently between preparation and execution;
for exact address scope, enter an IP/CIDR. Nmap's hostname choice and unprivileged
probe behavior require owner review. Discovery itself still sends network traffic.

This is an experimental, explicitly requested adapter. No network execution ran
during development. Owner acceptance should first review the arguments and Cancel,
then, only with authorization, use an isolated lab target. Never treat a mock test
as evidence that a real network assessment succeeded.

## Verification and pending acceptance

Automated tests mock both model templates, all three length modes, detail overrides,
private job cleanup, specialist availability, explicit selection, unchanged citation
text, no auto-routing, resident-model refusal and exact unload. Synthetic RAG contract
tests cover authorization and rejected citations. Adapter tests validate targets,
denial, scope identity, command arrays, limits, expiry and cancellation without
launching Nmap. See the additional Phase 2A report for full-suite results.

Owner steps: try a simple general question in each length mode; request detail;
review a code answer for completeness. Try both models manually and check factual
claims. For RAG, select Qwen and approve an exact knowledge request; verify sources,
then deny one request. ChromaDB was previously unavailable in this venv; if still
absent, installation/compatibility review needs separate approval before live RAG
acceptance. Try specialist+RAG and verify the refusal. Do not enable automatic
specialist routing based on this implementation or mocked evidence alone.
