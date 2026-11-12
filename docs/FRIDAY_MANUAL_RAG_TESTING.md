# Manual FRIDAY RAG testing

Live acceptance is owner-operated through the Ubuntu terminal. The coding agent
may implement changes and run synthetic, mocked and regression tests; it must
not run real Qwen/Nomic end-to-end acceptance or automatically submit live RAG
questions.

## Launch

Open an interactive Ubuntu terminal and run:

```bash
cd ~/Projects/FRIDAY
./data/intelligence/rag-env/bin/python -B -m friday.main
```

This uses the existing isolated environment with Chroma installed. No virtual
environment activation or configuration change is needed. Use a normal terminal
with interactive input and output; do not pipe input or redirect output, because
knowledge approval requires both streams to be terminals. The existing local
Ollama service and installed models must be available for an approved live query.

## Enter a question inside FRIDAY

At the `You:` prompt, type:

```text
answer using approved knowledge: <question>
```

Replace `<question>` with a nonempty question; do not type the angle brackets.
This is a FRIDAY input command, not a Bash command. Recognition is case-insensitive
and accepts whitespace around the colon/question.

An optional question with qualifying evidence in the repair diagnostics is:

```text
answer using approved knowledge: When should the server check access permissions for a specific object or function?
```

## Authorization

After successful corpus/index verification and before the query embedding, the
existing `CLIKnowledgeApproval` displays:

```text
Allow once: local approved-knowledge retrieval for this question only.
Scope fingerprint: ...
<approved source IDs, titles, URLs and revisions>
[1] Allow once
[2] Deny
Knowledge permission choice:
```

Review the scope, then enter `1` only if you approve that request, or `2` to deny.
Permission is per request; a later question requires its own approval. This is
the knowledge-retrieval prompt, separate from desktop owner authentication.
If preflight fails, FRIDAY may return a safe failure before displaying the prompt.

The CLI wiring, command parser and exact approval contract were inspected. Two
synthetic tests passed for command recognition and interactive allow-once/deny
behavior. No live application session or model inference was run to verify this
document; actual terminal appearance remains part of the owner's manual check.

## Short checklist

1. Launch with the isolated Python command above and confirm the `You:` prompt.
2. Enter an explicit approved-knowledge question and review the displayed scope.
3. Choose `2` to check denial, or `1` to run the question you intend to approve.
4. Expect either a complete answer with verified source labels and source metadata,
   or a clear safe failure/insufficient-evidence response. Partial or uncited output
   must not be presented as a verified answer.
5. Confirm the RAG response is not automatically spoken. Its private path excludes
   the turn from personal-memory/history writes and tool routing; terminal output
   alone does not audit database contents.
6. Record success/failure and displayed error/source metadata for review. The
   original BOLA wording currently returns insufficient evidence in diagnostics;
   that is not successful generated-answer acceptance.
7. Type `exit`, `quit` or `/bye`, or press Ctrl+C, to close FRIDAY.

No model configurations, `.env`, owner permissions or corpus contents were changed
while preparing these instructions. No commit or push was made.
