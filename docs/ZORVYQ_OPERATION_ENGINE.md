# Operation Engine

The shared engine is in `zorvyq/operations/`. It has immutable operation/stage/plan
contracts, a reviewed registry, exact one-time permissions, a sequential scheduler,
a bounded runner, metric collectors/parsers and session-only reporting. There is no
generic shell endpoint, model-created operation or unattended scheduler.

## Contracts and approval

Each implemented operation defines a stable ID, display purpose, derived required
tools, permission, input/target scope, fixed stages/command templates, timeout,
output/resource limits, cancellation policy, privacy, permitted side effects,
privilege needs, dry-run behavior, parsers, report schema and verification status.
Future entries have no executable stages and are rejected by planning.

A preview lists the exact target, purpose, permission, resource budget, each collector
and executable argv. Preview executes nothing. Run requires a default-No confirmation.
Network discovery additionally requires the owner's explicit authorization attestation.
An in-memory approval is bound to the complete plan hash, expires after 120 seconds,
and is single-use. Plans and selected project scope are revalidated before execution
and each stage. Unknown inputs, altered commands, traversal and escaping symlinks fail.

Permission classes are READ-ONLY LOCAL, NETWORK-ACTIVE, PRIVILEGED, STATE-CHANGING and
DESTRUCTIVE. Only the first two are implemented. The latter three are denied; there
is no sudo, password prompt, package install, firewall edit, service restart or repair
adapter. An installed tool or local-network connection is never scan authorization.

## Command rules and budgets

Only explicitly listed OS executable locations are considered. User PATH is not
searched for operation tools. Runner command validation checks exact reviewed flags
and schemas again. Commands use argv arrays, `shell=False`, no stdin, a fresh process
session and a minimal environment without inherited credentials. No model text can
become executable names, flags, targets or policy.

Every command is wrapped by the installed util-linux `prlimit`: 10 CPU seconds,
256 MiB address space and 1 MiB file-output limit. Missing prlimit means NOT CHECKED,
not unbounded execution. Normal command stages have an eight-second wall timeout
and 32 KiB combined captured stdout/stderr. Discovery has 30 seconds and 64 KiB.
Pipes are read incrementally; excess output stops the owned process group. EOF and
child-exit waits are bounded. SIGTERM is followed by SIGKILL only for the current
fresh operation process group, with child reaping. Diagnostic-discovered PIDs are
never kill targets. Cancellation before the worker starts is preserved.

Operations normally have 90 seconds total; Full System Diagnosis has 120. The engine
reduces remaining command budgets and stops scheduling stages when aggregate output
reaches 256 KiB. Collector inputs/dictionaries are independently bounded. Linux
resource sampling uses fixed public metadata paths, at most 512 processes, a short
sampling interval and at most 16 battery/thermal entries. Project summaries inspect
at most 256 direct visible entries; no recursion or source-file content reads.

The GUI remains responsive because one worker executes sequentially. The embedded
console shows fixed stage/proposed argv/status and sanitized bounded output; command
output appears at stage completion. It never launches GNOME Terminal. A separate
visible-terminal mode is not implemented and cannot be enabled by model output.

## Reports, privacy and AI

Reports contain operation ID/time/target/purpose, completed/skipped/failed checks,
metrics, bounded stage results, findings, severity, evidence references, limitations,
hypotheses and recommended further checks. Missing information is NOT CHECKED; no
absence-of-error test produces a hardware-health certification. Report data is
untrusted and cannot modify registry, approval or execution policy.

ANSI/control sequences, common credential assignments, email addresses and home user
identifiers are sanitized. Redaction is best effort; local network/process metadata
can still be sensitive. Journal requests exclude MESSAGE bodies, and raw journal
records are withheld from display/report output in favor of counts. No raw logs or
reports are persisted automatically.

Optional AI analysis receives a bounded allowlist of numeric observations (maximum
40 measurements, 4096 UTF-8 bytes), never stdout, log text, process names, usernames,
paths or unrestricted command dictionaries. It runs privately through the selected
generation model and native gate. Its JSON must contain an interpretation and valid
supplied measurement references. Successful analysis remains **AI hypotheses —
unverified**; deterministic measurements are retained on any analysis failure.

Export is a separate owner action choosing a new file. Files use mode 0600. Existing
files and symlinks are refused rather than overwritten. Review exported metadata
before sharing it. Export is local; no upload/telemetry integration exists.

## Extension procedure

Add an immutable registry definition and input validator, narrow command/collector,
parser and bounded report contract. Add synthetic positive/negative permission,
argument, timeout, cancellation, output-limit and privacy tests. Review dependencies,
privileges, side effects and owner acceptance separately. Future module entries do
not authorize execution merely by appearing in the registry.

Automated verification: engine, runner, parser, redaction and GUI tests use fixtures,
mock processes and synthetic pipes. No real diagnostic utility, scan or privileged
operation was run for acceptance. See the Phase 2B report for the final test total.
