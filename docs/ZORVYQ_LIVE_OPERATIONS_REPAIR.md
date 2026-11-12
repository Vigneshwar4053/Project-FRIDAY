# Live operations investigation and repairs

## Findings

Inspection and mocked Qt clicks confirmed cards → details → registry plan → explicit permission → worker → engine dispatch. The prior implementation already used a reviewed allowlist, argument arrays, prlimit, output bounds, timeouts, cancellation, subprocess stdout/stderr capture and structured reports. There was no evidence justifying a replacement command runner.

Confirmed presentation gaps: command output was only emitted at stage completion; stdout/stderr lacked labels; the console omitted exit codes and elapsed times, offered no copy action, and reports exported only JSON. System Health used a bounded Python collector rather than visibly executing the suggested summary commands. The repairs retain the runner and add complete-line streaming, labeled output, terminal status/exit/time, approved plan display, copy, readable report sections and explicit Markdown export. Complete-line streaming preserves secret redaction across subprocess read boundaries. Journal raw records remain withheld by the existing metadata privacy policy.

The owner-reported live button failure has NOT been reproduced under actual execution. Mocked dispatch success is not live success. No claim is made that unavailable packages caused that report. Fresh owner-authorized execution is needed to distinguish a device/session/prerequisite error from another live failure; the repaired console and deterministic report expose that evidence.

## Execution lifecycle

GUI action → registry → validated inputs → exact preview → default-deny approval → single execution worker → reviewed sequential stages → bounded sanitized output → deterministic report → optional separately requested model analysis.

System Health now includes the existing bounded CPU/memory/process/sensor collector plus `free -h`, `df -h`, and `uptime`. Network Overview retains reviewed address, route and NetworkManager queries and adds `ss -tuln`. Security uses existing firewall status, listening sockets, failed services, SSH status and cached tool inventory. Developer Environment uses Git/Python/Node/Docker versions and optional approved project metadata. The GUI preview shows the exact argv including prlimit. Timeouts can be reduced by the remaining operation budget without changing executed flags.

Read-only executable-path checks and dry-run previews found the reviewed tools available for health, network and security. Node and Docker were unavailable in the existing reviewed paths; this is not an assertion about every installation method or PATH entry. Those checks report NOT CHECKED. Firewall status may require access: no sudo prompt or elevation is attempted.

The runner never executes LLM-generated commands, uses no shell, restricts executable resolution to reviewed OS paths, passes a minimal environment, and reaps only its owned process group. One-use scope tickets, plan validation, operation locking and GUI busy controls prevent duplicate concurrent runs. Console/report output is sanitized and bounded; exported reports still require owner privacy review.

Reports show operation, Completed/Partial/Failed/Cancelled status, observations, deterministic findings, optional AI interpretation, recommendations, limitations and command results. Missing checks never establish health. Ports do not establish vulnerabilities; unfamiliar processes do not establish malware. AI input remains normalized numeric observations. AI failure leaves the deterministic report available. Markdown/JSON exports create a new owner-selected file with mode 0600 and refuse overwrite or symlink targets. Reports otherwise remain in session memory.

## Owner-operated live acceptance

No diagnostics or network discovery were executed during development.

1. Open System Operations → System Health → Dry-run preview. Review each command, limits and collector. Deny execution once and confirm no output starts.
2. Reopen and explicitly approve the exact plan. Confirm current operation and plan appear, each executed argv matches the preview, stdout/stderr are labeled, exit codes and elapsed times appear, then inspect the report. A collector has no subprocess exit code; it reports `None`.
3. Copy command output. Export a new Markdown file and a new JSON file, review their contents and permissions. Confirm export refuses an existing file.
4. Review and approve Network Overview, Security Overview and Developer Environment individually. Missing commands or denied firewall/journal access must appear as unavailable, failed or NOT CHECKED; there is no automatic installation/elevation.
5. Cancel a running check and verify bounded termination plus a partial/cancelled report. Repeated clicks must not start duplicate work.
6. Optionally analyze normalized metrics with the selected model. If the model is unavailable, verify the deterministic report remains available. This step was mocked during development.
7. Report any actual failure with the displayed safe category, stage status, exit code and sanitized output. Live reproduction remains necessary before attributing the original failure to a specific runtime cause.

Nmap remains separate: the owner must supply an exact approved private/lab target, purpose, target authorization and one-use approval. Never automatically scan the current subnet. No Nmap command ran during automated tests or development.
