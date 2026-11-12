# Cybersecurity workspace repair

Open **Cybersecurity**. Choose one explicit mode:

- **Approved Knowledge**: visible Qwen3:4b selection, original exact-scope one-time
  authorization, Nomic retrieval, approved Chroma/SQLite provenance, revocation and
  strict claims/citation validation. The model selector is fixed within this mode.
- **Specialist Chat**: explicit Foundation-Sec selection, experimental model knowledge;
  no automatic source verification. No specialist RAG is enabled.

Short, Medium and Deep Analysis are available above the composer. RAG retains its
original compact evidence/claims limits (at most four claims, 200 claim words), JSON
completion checks and citations; response-depth prompting cannot expand those limits
or the source scope. Validated output is never sliced to meet a length setting.

**Technical status** expands a bounded allowlisted status view. Failure text now
states whether the problem is denial, no evidence, dependency/index availability,
provider connection, unavailable/incompatible model, timeout, truncated/incomplete
output, schema/citation rejection, synchronization/residency or worker failure.
Unknown exceptions become a safe worker failure, not a claim of insufficient evidence.
Provider/evidence text is not copied into error details. Loading-on-demand and fixed
RAG stage updates are visible while the worker runs.

**Cybersecurity Operations** is a separate workspace containing local network
metadata, security posture, bounded log metadata and separately authorized discovery.
It shares the Operation Engine with System Operations. Scan configuration is not a
model tool call. It requires a private IP/CIDR, purpose, target authorization, exact
argv preview and Run confirmation. Other security tools remain unavailable until
review; no exploitation, privilege escalation or Metasploit is integrated.

The confirmed causes, lifecycle and unconfirmed Wayland hypothesis are recorded in
[the failure diagnosis](ZORVYQ_CYBERSECURITY_FAILURE_DIAGNOSIS.md). The live Chroma
Python dependency is still absent; this implementation repairs UI/mode/error handling
but does not certify live retrieval. No packages were installed or knowledge reindexed.

Owner acceptance: submit a harmless question in Specialist Chat and verify the
model name; compare Short/Medium/Deep final answers. Select Approved Knowledge, review
and deny an exact request when dependencies are ready, then allow one and inspect
verified citations. Invalid or incomplete model output must not produce a sourced
answer. If a dependency fails first, use the displayed category instead of assuming
that authorization or retrieval succeeded. Repeat Enter/Send on the actual Wayland
session and note focus/typing behavior. No automatic routing should occur.
