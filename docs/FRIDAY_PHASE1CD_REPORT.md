# Phase 1C provisioning and Phase 1D collection — execution report

Completed on 2026-10-12 under explicit owner approval: Phase 1C passed before Phase 1D collection began. Existing uncommitted browser/voice/runtime work was preserved. No runtime routing, desktop or voice implementation was changed by this execution. No `.env`, personal memory or personal document was read. No cybersecurity tool or network scan, commit or push was performed.

## Phase 1C results

- Installation succeeded: all 84 reviewed wheels, exactly 105,993,182 bytes, downloaded from the pinned HTTPS `files.pythonhosted.org` URLs. Every size/SHA-256 matched, every wheel ZIP passed integrity checking, and installed versions matched the lock. No redirects were followed by the wheel helper. No `.pth` startup files were accepted. Bundled notice paths were inventoried; this is not a vulnerability certification.
- Installed only into `data/intelligence/rag-env`; `pip check` passed. ChromaDB is 1.5.9. No LangChain package or other model was installed.
- Provisioning correction: official PyPI uses `binary/octet-stream`; the helper now accepts that MIME type while retaining the original host, size and hash checks.
- Exact Nomic registry manifest verified before download; config, weights, license and parameters each hashed after installation. Ollama library `nomic-embed-text:v1.5`, 768 dimensions, F16 weights. Qwen3:4b retained its original digest, and no model remained resident after the experiments.

| Artifact | Verified SHA-256 |
| --- | --- |
| Nomic manifest | `0a109f422b47e3a30ba2b10eca18548e944e8a23073ee3f3e947efcf3c45e59f` |
| Qwen3:4b unchanged manifest | `359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7` |
| v1+json | `31df23ea7daa448f9ccdbbcecce6c14689c8552222b80defd3830707c0139d4f` |
| model | `970aa74c0a90ef7482477cf803618e776e173c007bf957f635f1015bfcfef0e6` |
| license | `c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4` |
| params | `ce4a164fc04605703b485251fe9f1a181688ba0eb6badb80cc6335c0de17ca0d` |

All 84 package identities, hashes and official URLs: [reviewed artifact manifest](FRIDAY_PHASE1C_ARTIFACTS.json), [lock](../requirements-rag-phase1c.lock), and verified installed inventory at `data/intelligence/provisioning/package-verification.json`. Final local model state is recorded at `data/intelligence/provisioning/final-model-state.json`.

| Measurement | Actual result |
| --- | --- |
| Synthetic corpus indexed | 5 original documents/chunks |
| Indexing time / throughput | 0.804 s / 6.22 chunks/s |
| Top-1 accuracy / citation integrity | 100% / 100%, 50 samples over five questions |
| Stale revision, revocation, unknown scope, persistent reopen | All passed |
| Ephemeral embedding + vector-search p50 / p95 | 305.7 / 311.6 ms |
| Embedding p50 / p95 | 303.8 / 309.6 ms |
| Vector search p50 / p95 | 1.95 / 2.22 ms |
| Cold model load + query/search, owned experiment | 538.9 ms |
| Resident warm p50 / p95, 20 repeats of one question | 24.4 / 26.6 ms |
| Peak simultaneous additional RSS | 445,808,640 bytes (425.2 MiB) |
| Sum of per-process-group additional RSS maxima | 449,982,464 bytes (429.1 MiB) |
| Sampled CPU / wall time | 53.45 CPU-seconds / 32.55 seconds |
| Mean CPU consumption | 1.64 CPU cores (164.2% of one core) |
| Resident experiment CPU / peak additional RSS | 4.13 CPU-seconds / 421.6 MiB |
| Safety gates | Additional RAM <=2 GiB; host available RAM >=2 GiB; both experiments passed |

The initial RSS/CPU sampler missed Ollama descendants. It was corrected and the complete 50-sample benchmark rerun; the numbers above use the corrected run only. Sampling every 50 ms can miss brief peaks and final CPU tails from exited runners; worker startup is outside the sampling interval. RSS sums include shared mappings and are not PSS. No OS cache was evicted, so cold means model nonresident, not cold disk cache. The resident experiment is isolated benchmark code that unloads only its owned Nomic model; runtime provider policy remains ephemeral. Retrieval timers measure embedding plus vector search, not answer generation. This five-document smoke test and repeated-question warm experiment do not establish real-corpus quality.

## Disk usage

| Owned storage | Logical bytes | Allocated bytes |
| --- | ---: | ---: |
| isolated_environment | 497,267,966 | 523,657,216 |
| wheel_cache | 105,993,182 | 106,164,224 |
| all_synthetic_benchmarks | 1,447,736 | 1,474,560 |
| cybersecurity_dataset | 5,393,471 | 5,529,600 |

Verified model layers add 274,302,450 bytes to the Ollama store, plus the small manifest. All synthetic benchmark directories, including incomplete sandbox/first-measurement attempts, are retained and counted separately from the real corpus.

## Phase 1D dataset

- Storage: `knowledge/cybersecurity/`, with `manifest.json`, `sources/`, `processed/`, and `reports/`. `.gitignore` excludes the entire dataset; `git ls-files knowledge/cybersecurity` is empty.
- 24 documentation originals downloaded: 22 substantive corpus entries plus two deprecated/moved-page stubs retained as excluded archives. Corpus distribution: 10 WSTG, 11 Cheat Sheet Series, one ATT&CK ICS bundle.
- Active original documents: 4,424,228 bytes. All collector transfers including stubs, original license texts and commit/tree metadata: 4,825,743 bytes (4.83 MB decimal). Below 100 MB total, 100 documents/responses, 20 MB per document; largest original is 4,057,891 bytes.
- MITRE original bundle is archival only. Prepared subset includes 12 active techniques, eight mitigations, matching relationships and original identity/marking objects; object versions and creation/modification dates remain in the STIX JSON. The derived text retains the MITRE license and copyright. This is ICS coverage, not Enterprise ATT&CK.
- Estimated inventory: 355 chunks using the existing deterministic 1,536-byte paragraph chunker with 192-byte overlap. Only the intended processed text was counted; no repository ingestion, SQLite corpus, Chroma indexing or cybersecurity embedding occurred.
- Publication dates remain null when unknown; repository commit dates are recorded separately and are not represented as publication dates. Commit SHA is the document version. WSTG comes from the development branch at the pinned commit and is not labeled stable v4.2. Cheat Sheet Markdown is a pinned working-source snapshot; canonical published pages should be used for future external citations.

| Topic | Documents tagged |
| --- | ---: |
| networking | 4 |
| network_scanning | 4 |
| nmap | 0 |
| web_security | 17 |
| linux_security | 3 |
| vulnerability_management | 6 |
| threat_intelligence | 1 |
| defensive_security | 18 |

Tags overlap. Networking coverage emphasizes TLS, network configuration and segmentation; Linux coverage emphasizes permissions, containers and command injection. No complete networking/Linux curriculum is claimed. Nmap documentation was reviewed but deferred.

## Provenance, licenses and additional-source decisions

| Official repository | Immutable commit | License |
| --- | --- | --- |
| [ OWASP/wstg ](https://github.com/OWASP/wstg) | `74a854b2635316b63b53f1e4e2e8d482a59d2f71` | [CC-BY-SA-4.0](https://raw.githubusercontent.com/OWASP/wstg/74a854b2635316b63b53f1e4e2e8d482a59d2f71/LICENSE) |
| [ OWASP/CheatSheetSeries ](https://github.com/OWASP/CheatSheetSeries) | `cb9fe01e5ddf17b42513d2c53c4b86196c665c45` | [CC-BY-SA-4.0](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/cb9fe01e5ddf17b42513d2c53c4b86196c665c45/LICENSE.md) |
| [ mitre-attack/attack-stix-data ](https://github.com/mitre-attack/attack-stix-data) | `6cda5ad8462c79e14fbb872f4e09059b18e0cfc4` | [LicenseRef-MITRE-ATTACK](https://raw.githubusercontent.com/mitre-attack/attack-stix-data/6cda5ad8462c79e14fbb872f4e09059b18e0cfc4/LICENSE.txt) |

OWASP originals remain byte-for-byte copies, and normalized text records source URLs, attribution, licenses and changes. CC BY-SA notices must accompany future redistribution; adaptations retain applicable ShareAlike conditions. MITRE has its own ATT&CK permission license, not the MIT open-source license. Its copyright designation and license accompany all copies/derived selections. No publisher endorsement is implied.

| Additional official source | Decision / finding |
| --- | --- |
| [Nmap](https://nmap.org/book/) | deferred: Reference Guide permission verified; book-wide permission not inferred. Initial collection prioritizes Markdown/JSON. No Nmap book copied. |
| [NIST SP 800-115](https://csrc.nist.gov/pubs/sp/800/115/final) | deferred: Official final publication identified; government and third-party authors listed. Document-specific permission and PDF processing deferred; no substantial content copied. |
| [CISA KEV](https://www.cisa.gov/known-exploited-vulnerabilities-catalog) | skipped: Official catalog/policy requests unavailable during review; catalog-specific license could not be verified. No catalog downloaded. |
| [Wireshark](https://www.wireshark.org/docs/) | deferred: User Guide explicitly includes a GPL v2 document license. Initial Markdown/JSON scope retained; HTML/source redistribution treatment deferred. |
| [Zeek](https://docs.zeek.org/) | skipped: Official documentation identified; documentation-specific license not verified. Software/Spicy BSD licensing was not treated as a grant for the Book of Zeek. |

Exact source URLs, raw SHA-256, processed hashes, license hashes, retrieval timestamps, versions, sizes and tags are preserved in [local manifest](../knowledge/cybersecurity/manifest.json). Per-document hashes are also in `knowledge/cybersecurity/reports/SHA256SUMS.txt`; license review evidence is at `reports/source-review.json`. No linked third-party reference was crawled. No rejected source was copied substantially.

## Original-document SHA-256 inventory

| Document | Raw SHA-256 | Exact immutable source |
| --- | --- | --- |
| 2. Introduction | `fb9527bf77829831cd4c0ad5de062362d6c458928f5f9b1fa01b06c052f83212` | [source](https://raw.githubusercontent.com/OWASP/wstg/74a854b2635316b63b53f1e4e2e8d482a59d2f71/document/2-Introduction/README.md) |
| The Web Security Testing Framework | `8a027d3c686807c0906a4c277d7ea38a17c59cf961f712a6cead7ec8115d0bc1` | [source](https://raw.githubusercontent.com/OWASP/wstg/74a854b2635316b63b53f1e4e2e8d482a59d2f71/document/3-The_OWASP_Testing_Framework/0-The_Web_Security_Testing_Framework.md) |
| Conduct Search Engine Reconnaissance for Information Leakage | `df053f7f6c267fad013c147fcc01db9bdf792985af30dc06706066b75b3f7ae6` | [source](https://raw.githubusercontent.com/OWASP/wstg/74a854b2635316b63b53f1e4e2e8d482a59d2f71/document/4-Web_Application_Security_Testing/01-Information_Gathering/01-Conduct_Search_Engine_Reconnaissance_for_Information_Leakage.md) |
| Fingerprint Web Server | `5f1677ef5c39ff16ffc5df1595a02bf36c73ba4b0378c5c632691bee71fd873d` | [source](https://raw.githubusercontent.com/OWASP/wstg/74a854b2635316b63b53f1e4e2e8d482a59d2f71/document/4-Web_Application_Security_Testing/01-Information_Gathering/02-Fingerprint_Web_Server.md) |
| Network Infrastructure Configuration | `f492acfd3f7d60c0db5f3c0e38c69aafec5dc523498356846b1565bd6f1e75df` | [source](https://raw.githubusercontent.com/OWASP/wstg/74a854b2635316b63b53f1e4e2e8d482a59d2f71/document/4-Web_Application_Security_Testing/02-Configuration_and_Deployment_Management/01-Network_Infrastructure_Configuration.md) |
| Application Platform Configuration | `ccbf608faeb758cf11a37b99c651ec6a1068f84539c42e352058c09122877be8` | [source](https://raw.githubusercontent.com/OWASP/wstg/74a854b2635316b63b53f1e4e2e8d482a59d2f71/document/4-Web_Application_Security_Testing/02-Configuration_and_Deployment_Management/02-Application_Platform_Configuration.md) |
| File Permissions | `0a67db8f808ffcfcdf5ead2252ff6178477a761a2a572ce437743db48be03bb6` | [source](https://raw.githubusercontent.com/OWASP/wstg/74a854b2635316b63b53f1e4e2e8d482a59d2f71/document/4-Web_Application_Security_Testing/02-Configuration_and_Deployment_Management/09-File_Permissions.md) |
| Sensitive Information Sent via Unencrypted Channels | `345317d8a05797f6b3ccc77d553914a0f7e7a484df6daa98f3c8d99116904f46` | [source](https://raw.githubusercontent.com/OWASP/wstg/74a854b2635316b63b53f1e4e2e8d482a59d2f71/document/4-Web_Application_Security_Testing/09-Weak_Cryptography/03-Sensitive_Information_Sent_via_Unencrypted_Channels.md) |
| Bypassing Authorization Schema | `5166e2806116493983c5ab20f1c1ae189bd7312cb2750f25f92da52729f2c0d7` | [source](https://raw.githubusercontent.com/OWASP/wstg/74a854b2635316b63b53f1e4e2e8d482a59d2f71/document/4-Web_Application_Security_Testing/05-Authorization/02-Bypassing_Authorization_Schema.md) |
| Penetration Testing Methodologies | `58a9c5b2c685a8727b90a33cf6945c95971b83dd92a436521f14c395257fda70` | [source](https://raw.githubusercontent.com/OWASP/wstg/74a854b2635316b63b53f1e4e2e8d482a59d2f71/document/3-The_OWASP_Testing_Framework/1-Penetration_Testing_Methodologies.md) |
| Authentication Cheat Sheet | `92f7483b28548679917a329c7b9be1824f33e934d9eed670aaf3e9a1e7b37e83` | [source](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/cb9fe01e5ddf17b42513d2c53c4b86196c665c45/cheatsheets/Authentication_Cheat_Sheet.md) |
| Authorization Cheat Sheet | `fb8b6e5c60ed783025beefb5049142fd9da02d01f5c95de18a19d26479737975` | [source](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/cb9fe01e5ddf17b42513d2c53c4b86196c665c45/cheatsheets/Authorization_Cheat_Sheet.md) |
| Input Validation Cheat Sheet | `163390e3dcf5cc965aeac5e633692682403c08067a7f2ae54bdb49372e886810` | [source](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/cb9fe01e5ddf17b42513d2c53c4b86196c665c45/cheatsheets/Input_Validation_Cheat_Sheet.md) |
| SQL Injection Prevention Cheat Sheet | `0c00c87970eceb404ec4061a30b0fbe3390d870244f3d0802465e20c39178bbb` | [source](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/cb9fe01e5ddf17b42513d2c53c4b86196c665c45/cheatsheets/SQL_Injection_Prevention_Cheat_Sheet.md) |
| Logging Cheat Sheet | `ab43825f2095a964542a3ea3392e50c79fe4d51794ae1bdfc3bc246b243c5f39` | [source](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/cb9fe01e5ddf17b42513d2c53c4b86196c665c45/cheatsheets/Logging_Cheat_Sheet.md) |
| Transport Layer Security Cheat Sheet | `f9c79d45e84f972d7578644d16b4629e75d2b0cf03cb359182d5a47358cf391e` | [source](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/cb9fe01e5ddf17b42513d2c53c4b86196c665c45/cheatsheets/Transport_Layer_Security_Cheat_Sheet.md) |
| Docker Security Cheat Sheet | `9dbfa41b1c29828045c984bcfa2f5fe410ca2c6c7237ed8bc4ea8bc935601eaf` | [source](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/cb9fe01e5ddf17b42513d2c53c4b86196c665c45/cheatsheets/Docker_Security_Cheat_Sheet.md) |
| Network segmentation Cheat Sheet | `843f0de69d31b794dff05496610b0a07b6584e99d1b1e9023eb0ccc5fcec0156` | [source](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/cb9fe01e5ddf17b42513d2c53c4b86196c665c45/cheatsheets/Network_Segmentation_Cheat_Sheet.md) |
| OS Command Injection Defense Cheat Sheet | `83997daf32c011234875a8342dc9a1f50079b6925b20d7175213008f3cba1431` | [source](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/cb9fe01e5ddf17b42513d2c53c4b86196c665c45/cheatsheets/OS_Command_Injection_Defense_Cheat_Sheet.md) |
| Vulnerable Dependency Management Cheat Sheet | `77e7a460c4072442d524394109125391317d61961db78c3cdc2dd771c006872a` | [source](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/cb9fe01e5ddf17b42513d2c53c4b86196c665c45/cheatsheets/Vulnerable_Dependency_Management_Cheat_Sheet.md) |
| Vulnerability Disclosure Cheat Sheet | `11c58e683e1cbeae8447dcbcadf6ae7a23ac3d9f24fced746552266f9ab71a4f` | [source](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/cb9fe01e5ddf17b42513d2c53c4b86196c665c45/cheatsheets/Vulnerability_Disclosure_Cheat_Sheet.md) |
| MITRE ATT&CK ICS — bounded defensive subset | `08b83d2cea6b6d6752468ef0e62e2ab2a53c9443ef72c439ecccb07ab9e89da9` | [source](https://raw.githubusercontent.com/mitre-attack/attack-stix-data/6cda5ad8462c79e14fbb872f4e09059b18e0cfc4/ics-attack/ics-attack.json) |
| Credentials Transported over an Encrypted Channel (excluded stub) | `7a1e7d6157efc92b59dc675e6582dc0e59251b6450fd0b6f168b131c68bd65c3` | [source](https://raw.githubusercontent.com/OWASP/wstg/74a854b2635316b63b53f1e4e2e8d482a59d2f71/document/4-Web_Application_Security_Testing/04-Authentication/01-Credentials_Transported_over_an_Encrypted_Channel.md) |
| DEPRECATED: Transport Layer Protection Cheat Sheet (excluded stub) | `86ddfbe1de52c3573d687a8fb0e5d3f72d034038c7650d46984e77d7bbff571d` | [source](https://raw.githubusercontent.com/OWASP/CheatSheetSeries/cb9fe01e5ddf17b42513d2c53c4b86196c665c45/cheatsheets/Transport_Layer_Protection_Cheat_Sheet.md) |

## Validation and remaining indexing work

- Offline dataset validation passed: official publisher/source/license binding, UTF-8 and content types, original/processed/subset SHA-256, per-document Git blob identity, license notices, duplicate detection, size/transfer accounting, paths, links, filesystem identity and nonexecutability. All metadata and excluded archives are checked as inert UTF-8 data. Download contents/embedded instructions were never executed. Known secret-pattern checks found no matches; they are not an exhaustive detector.
- Eighteen dataset tests passed, including malformed/binary/login content, unsupported files, credential markers, redirect refusal, partial-transfer accounting, oversize responses, symlink/hardlink/path escapes, tampering, duplicates and bounded MITRE selection. Combined dataset/foundation/adapter suite: 73 passed.
- Full final regression suite: **1,633 passed in 13.453 seconds** outside the sandbox. Initial sandbox full tests hit the existing four headless IPC errors and four cleanup failures. Final output is in `data/intelligence/provisioning/final-regression.log`. `git diff --check` passed.
- A non-retaining compatibility check found 20/22 processed documents satisfy the Phase 1B text privacy policy. Two require review of public credential/example material or other policy exclusions; originals were preserved and policy was not bypassed. Details: `knowledge/cybersecurity/reports/rag-readiness.json`.
- Before real indexing: approve the exact selected corpus/revisions; review the two excluded-by-policy documents and any proposed sanitization; use the bounded processed MITRE subset rather than its 4 MB archival bundle; preserve license/attribution and transformation hashes; protect corpus storage through the reviewed sensitive-path boundary; create a separate knowledge repository and pinned index manifest; validate retrieval on real cybersecurity questions and enforce budgets/current revisions/citations. Runtime evidence assembly, private history handling and speech policy remain separate future work.
- Nmap, fuller networking/Linux coverage, NIST, CISA, Wireshark and Zeek need their documented follow-up source/format/permission work. No additional package/model installation is needed merely to inventory this dataset.

Machine-readable measured results: `data/intelligence/provisioning/final-measurements.json`; authoritative corrected benchmark: `data/intelligence/phase1c-benchmarks/e960304826124e15a3e75104fe87c659/report.json`; resident experiment: `data/intelligence/phase1c-benchmarks/e960304826124e15a3e75104fe87c659/resident-report.json`.
