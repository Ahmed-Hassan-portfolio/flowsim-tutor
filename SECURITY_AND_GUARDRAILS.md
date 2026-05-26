# Security and guardrails

This document describes the threat model, agent guardrails, and operational
safety properties of `flowsim-tutor`. It is intentionally specific about what
the system **does** enforce and what it **does not**, so a reviewer can decide
where additional controls are needed for a particular deployment.

The project is a portfolio / demonstration codebase. Treat it as a
reference implementation, not a hardened production agent.

## Threat model

The agent runs locally on a developer machine and connects out to:

- the Anthropic or OpenAI inference API (chosen via env vars);
- a small set of MCP servers reachable over stdio (the in-process FlowSim
  server, plus anything declared in `mcp_servers.json`).

There is **no** network listener on the FlowSim server itself — MCP traffic
goes through anonymous stdio pipes spawned by the orchestrator. The Chainlit
UI listens on `localhost:8000` by default.

We assume:

- The LLM provider's transport is TLS-encrypted and authenticated by API key.
- The user's `.env` is readable only by the user account that runs the chat.
- The shipped corpus in `data/docs/` is trusted, synthetic content the user
  controls. If you replace it with externally-sourced Markdown, see the
  prompt-injection notes below.

We do not assume:

- That every chunk returned by retrieval is benign instructions.
- That an MCP server configured in `mcp_servers.json` is well-behaved or
  even alive — see "MCP server isolation" below.
- That the LLM will obey the system prompt under every adversarial input.

## Secret handling

- API keys come from environment variables (`ANTHROPIC_API_KEY`,
  `OPENAI_API_KEY`). They are read once in `LLMConnector.__init__` and
  passed to the official SDK, which scopes them to the HTTP client.
- `.env` is gitignored (`.gitignore` line 25). Only `.env.example` is
  committed, and its values are obvious placeholders.
- No keys are written to logs. The logger in `server.py:35` and
  `chat_app.py:35` does not interpolate environment variables, and
  the truncation logic in `server.py:109` only echoes structured tool
  payloads, never request headers.
- The `LLMConnector` error handler in `llm_connector.py:320` deliberately
  reduces provider exceptions to a category string before they reach the
  user. Raw exception text — which can carry partial keys on some
  provider misconfigurations — is logged at `ERROR` level to stderr only,
  never returned to the chat.

## Tool surface and bounding

Eight tools are registered on the local FastMCP server:

- `search_docs`, `get_full_section` — read-only retrieval.
- `get_session`, `start_workflow`, `complete_step`, `end_session` —
  workflow state writes, scoped to `data/sessions/`.
- `save_note`, `get_notes` — categorized notes, scoped to `data/notes/`.

What the agent **cannot** do via these tools:

- Read arbitrary files. All file access is mediated through the retriever
  (which reads only the pre-built ChromaDB collection and BM25 pickle)
  and the state managers (which only read/write inside
  `data/sessions/` and `data/notes/`).
- Execute arbitrary commands. There is no `exec` or `shell` tool.
- Reach the network from a tool. The local tools are pure I/O on the
  data directory.
- Mutate the indexed corpus. `index_docs.py` is offline and run by the
  user; the server never rebuilds the index.

What it **can** do:

- Persist notes and workflow state to disk in JSON. The category set is
  fixed (`general`, `preferences`, `decisions`, `issues`) and content
  is stored verbatim — treat the notes file as user-content storage,
  not a trust boundary.

### Response bounding

Every tool response goes through `truncate_response` (`server.py:109`)
which caps responses at 3500 bytes. This serves two purposes:

1. Prevents Windows stdio pipe deadlocks (4–8 KB buffers).
2. Limits how much retrieval content the LLM ingests per call, which
   shrinks the surface for prompt injection by retrieval poisoning.

When truncation occurs, the LLM receives a structured
`{"truncated": true, "hint": "..."}` reply with no document text,
forcing a narrower query rather than letting it consume a partial
response.

`get_notes` separately caps returned notes at 20 entries
(`tools/notes_tools.py:16`).

## Prompt-injection assumptions

Retrieved document chunks are treated as **data**, not instructions, by the
system prompt (`web_system_prompt.py`):

- The "Citation Rule" requires every documentation-derived instruction to
  carry a `(Source: file > section)` tag. An attacker who manages to
  inject instructions into the corpus must either get the LLM to ignore
  the citation rule or expose the source path, which is visible to the
  user in the collapsible tool-result panel.
- The "No Hallucination Rule" tells the LLM to refuse rather than guess
  when confidence is low.

The retriever returns a `confidence: low` flag (`rag/retriever.py:135`)
when both the best RRF score is below 0.025 and the best ChromaDB
distance is above 0.85. The system prompt instructs the LLM to surface
this flag to the user rather than answer from low-confidence retrieval.

### Known limitations

- The shipped corpus is synthetic and trusted. We do **not** sanitize
  retrieved Markdown for injection patterns ("ignore previous
  instructions", embedded tool-call JSON, etc.). If you point this at
  a corpus that includes user-submitted content, add a sanitizer pass
  in `rag/chunker.py` before publishing.
- We do not separate the retrieved-text token budget from the
  user-message token budget. A very long injected payload can still
  crowd the system prompt — the 3500-byte response cap limits this but
  does not eliminate it.
- The Chainlit "screenshot handling" branch in the system prompt asks
  the LLM to identify UI elements in uploaded images. The repo does
  not actually process image content; the LLM sees only a textual
  note that an image was uploaded (`chat_app.py:374`). This is a
  deliberate scope decision, not an oversight, but is worth flagging.

## MCP server isolation

When external MCP servers are declared in `mcp_servers.json`, the
orchestrator (`mcp_client.py:88`) treats them as untrusted by default:

- Each server runs as a subprocess over stdio — no shared address
  space, no shared file descriptors beyond the pipe.
- Connection attempts time out after 30 s (`MCP_CONNECT_TIMEOUT`).
- Each tool call times out after 60 s (`MCP_TOOL_CALL_TIMEOUT`).
- Three consecutive failures from the same server mark it dead
  (`MAX_CONSECUTIVE_FAILURES = 3`); subsequent calls receive an error
  without reaching the dead server, so a stuck server cannot poison
  the chat loop.

The orchestrator does **not** authenticate the spawned server. The
implicit trust boundary is "if it's in your `mcp_servers.json`, you
trust it". Reviewers running this should audit that file before
running the chat.

## Operational safety

- **Human escalation.** The system prompt's "Pacing Rule" caps the
  agent at two action steps per message and instructs it to wait for
  user confirmation between steps. This is convention, not a hard
  enforcement; an adversarial LLM could ignore it.
- **Determinism.** The retriever is deterministic for a fixed index
  (RRF over fixed top-20 lists). The LLM is not — model output is
  stochastic, and tool-calling behavior varies by provider and
  version.
- **Idempotency.** `complete_step` is idempotent on a step ID that has
  already been advanced past (the inner loop short-circuits on the
  first incomplete step). `save_note` always creates a new note;
  there is no upsert.
- **Crash safety.** Sessions and notes use temp-file + `os.replace`
  atomic writes (`state/session.py:138`, `state/notes.py:81`) so a
  crash during a write leaves either the old file or the new file,
  never a partial file.

## What this project does not do

- Does not enforce per-user authentication on the Chainlit UI. If you
  deploy beyond `localhost`, add Chainlit's auth integration.
- Does not encrypt session or notes JSON at rest.
- Does not rate-limit tool calls beyond the per-call timeouts.
- Does not redact PII from retrieved snippets.
- Does not validate that the LLM's tool-call arguments are
  benign — Pydantic validation catches type errors but not semantic
  abuse (e.g., a `query` containing an attempted injection).

If you need any of the above, the relevant injection point is small
and local: validation goes in `tools/*.py`, rate limiting goes in
`mcp_client.py:MCPServerConnection.call_tool`, and corpus sanitization
goes in `rag/chunker.py`.
