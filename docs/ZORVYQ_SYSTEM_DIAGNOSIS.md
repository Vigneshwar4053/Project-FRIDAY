# System Operations and diagnosis

Open **System Operations**, inspect a card, review its dry-run plan and approve the
exact target. Commands run in the embedded console. Cancel stops only owned work;
partial results and NOT CHECKED stages remain visible. Reports are kept for the
current session only. Export and AI interpretation are separate explicit actions.

## Initial adapters and limits

| Operation | Implemented bounded observations | Important exclusions/limitations |
| --- | --- | --- |
| System Health | Sampled CPU utilization/model, RAM, swap occupancy, root filesystem usage, top sampled processes, available battery/thermal metadata | No GPU assumption, stress tests, RAM faults, temperature invention or hardware-health score; unavailable sensors NOT CHECKED |
| Network Overview | Existing interface/address/route/gateway JSON; NetworkManager device state and configured DNS | Local metadata only; no probes, password access or connecting to networks; absent tools NOT CHECKED |
| Authorized Network Discovery | Shared reviewed Nmap host-discovery flags, exact private IP/CIDR up to 256 addresses, unprivileged `-sn -n`, explicit purpose and authorization | No default target, hostname resolution, public target, port/service scan, exploitation or automatic discovery; missing dependencies disable Run |
| System Security Overview | UFW status without elevation, listening endpoints, failed services, SSH activity, cached update counts and audit-tool availability | Firewall access may fail without privilege; listening is not vulnerability; cached updates are not current security-update assurance; no configuration changes |
| Process Monitor | At most 512 processes, per-core sampled CPU, RSS, UID, name and accessible executable-path metadata; local connection endpoints | No cmdline/environ reads, automatic termination, malware verdict or memory-leak claim; short sample and access limits apply |
| Log Overview | At most 80 visible recent error and kernel-warning metadata entries per stage; priority counts | No full message bodies/private log collection; authentication failure counts NOT CHECKED; permissions/visibility limits do not imply no errors |
| Storage Overview | Root space/pressure and optional selected project's direct visible entry metadata; review-only cleanup guidance | No recursive directory totals, SMART, repair, arbitrary private paths or deletion; directory entry bytes are explicitly not content size |
| Developer Environment | Git/Python/Node/Docker CLI versions, optional selected project entry metadata, common development listener counts | No project scripts, dependency installation, Docker daemon health claim, Git content/status scan or database/API connections |

All modules are **experimental with mocked acceptance evidence**. Cards distinguish
installed tool availability from successful session execution. A missing subtool
permits remaining independent checks, with skipped/failed stages recorded. Operations
with no executable/collector available cannot Run. Future capabilities are listed as
unavailable and have no fake Run implementation.

Optional project scope comes only from direct visible folders under
`/home/vigneshwar/Projects`, revalidated after symlink resolution. No entire-home scan
or source-content inspection is used. No project is selected automatically.

## Full System Diagnosis

This is a read-only, 120-second maximum composition of the existing health, storage,
security/service, network metadata, process and log stages. It never adds Nmap,
network probing, stress tests, filesystem repair, package refresh, service restart
or configuration edits. It does not certify physical disk/RAM health.

Reports identify attempted/completed/skipped/failed checks, measured values, evidence
references, findings, severity, confidence limits and suggested next steps. Nested
unavailable metrics such as SMART, absent sensors or historical measurements are
also shown as NOT CHECKED. A complete command is not proof that every aspect of the
system is healthy.

## Root-cause investigator foundation

**Why is my laptop slow?** is a dedicated investigation card. It composes resource,
storage, process and log metadata, then correlates observed thresholds. For example,
high measured RAM utilization plus nonzero swap occupancy can support a *hypothesis*
of memory pressure, with references to those metrics. Swap occupancy does not measure
current swapping. No memory leak, malware or confirmed cause follows from one reading.

Historical trends and dynamic additional investigations are not implemented. Their
absence is reported. The owner may approve another registered operation or repeat a
sample; neither an LLM explanation nor a recommendation broadens permission. Optional
AI interpretation receives numeric observations only and remains labeled unverified.
There is no automatic repair button.

## Owner acceptance

1. Launch the checkout GUI; confirm no operation or inference runs on startup.
2. Open System Health → Dry-run, review scope, approve it once, inspect actual metrics
   and unavailable sensors. Confirm the console and other UI remain responsive.
3. Try Network Overview, Process Monitor, Security Overview and Log Overview. Confirm
   missing tools/inaccessible checks produce limitations, not invented success.
4. Choose a project explicitly for Storage/Developer; verify only that direct folder
   scope is displayed and no project scripts run.
5. Run Full System Diagnosis and inspect every skipped/failed check. Try cancellation;
   verify a partial report remains and unrelated applications are unaffected.
6. Run the slow-laptop investigation; compare measured facts with labeled hypotheses.
   Repeat if needed; do not infer trends from a single snapshot.
7. Optionally analyze normalized metrics using the selected model. Disconnecting
   Ollama must leave the deterministic report usable. Review/export a new local file.
8. Network discovery is a separate authorized lab test only: review exact private
   target and argv, attest authorization, approve Run and check Cancel. No live scan
   was performed by Codex. Public/oversized scopes must be refused.
9. Close during an operation, then verify cancellation/cleanup completes before exit.
   Closing during model generation waits for bounded completion and unload policy.
