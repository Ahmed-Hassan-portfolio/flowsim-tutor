# flowsim-tutor

A domain-agnostic **hybrid-RAG MCP server** with workflow tracking and cross-session notes, plus a Chainlit chat UI that can compose it with any other MCP server. Ships with a small synthetic flow-simulation corpus ("FlowSim") so it runs end-to-end out of the box.

## What's technically interesting

- **Hybrid retrieval over dual indexes** — ChromaDB (HNSW + cosine, `all-MiniLM-L6-v2`) for semantic, `rank-bm25` for lexical, fused with **Reciprocal Rank Fusion (k=60)**. Both indexes share identical chunk IDs in identical order, with a SHA-256 manifest checked by the MCP server at startup — drift fails fast with a "run `index_docs.py`" hint.
- **Adaptive Markdown chunker** — splits on `---`, tracks full header hierarchy (`##`–`######`), merges adjacent `Model description` + `How to use` pairs into one chunk so the LLM never has to stitch them, and preserves numbered step sequences across paragraph boundaries.
- **stdio-safe FastMCP server** — Windows stdio pipe buffers are 4–8 KB, so every tool response is capped at 3500 bytes with a structured truncation summary. Heavy work runs through `asyncio.to_thread` and the embedding model is pre-loaded in the lifespan so the first `search_docs` call doesn't stall.
- **Multi-server orchestrator** with per-call timeouts, dead-server detection, and three-strike eviction — wires the FlowSim Tutor MCP server alongside any other MCP servers you point it at, and a Chainlit chat UI exposes the merged tool set to either Claude or OpenAI via a single unified `LLMConnector`.
- **Workflow + notes state** — `SessionManager` tracks multi-phase workflows with stale-session detection (24 h threshold); `NotesManager` keeps categorized cross-session memory. Both persist via atomic-write JSON (`os.replace`), no DB needed.

## Architecture

```
                ┌──────────────────────────────────────────┐
                │           Chainlit chat UI (chat_app)    │
                │  ┌────────────┐         ┌─────────────┐  │
                │  │LLMConnector│         │ MCPOrchestr │  │
                │  │ Claude /   │         │ (timeouts,  │  │
                │  │ OpenAI     │         │  dead-srv)  │  │
                │  └─────┬──────┘         └──────┬──────┘  │
                └────────┼────────────────────────┼────────┘
                         │                        │ stdio
                         │                ┌───────▼───────┐
                         │                │ other MCP     │
                         │                │ servers (opt) │
                         │                └───────────────┘
                ┌────────▼────────────────────────────────┐
                │       FastMCP server  (server.py)       │
                │   8 tools: search_docs · get_full_section
                │            get_session · start_workflow
                │            complete_step · end_session
                │            save_note · get_notes        │
                └────────┬────────────────────────────────┘
                         │
       ┌─────────────────┼──────────────────┐
       │                 │                  │
┌──────▼──────┐  ┌───────▼───────┐  ┌───────▼───────┐
│ RAG (rag/)  │  │ State (state/)│  │ Tools (tools/)│
│ chunker     │  │ session       │  │ search_tools  │
│ embedder    │  │ notes         │  │ session_tools │
│ indexer     │  │               │  │ notes_tools   │
│ retriever   │  │               │  │               │
└──────┬──────┘  └───────────────┘  └───────────────┘
       │
┌──────▼──────────────┐
│  ChromaDB           │   (vector, cosine, HNSW)
│  BM25 pickle        │   (keyword)
│  index_manifest.json│   (drift detection)
└─────────────────────┘
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for design decisions and the rationale behind each layer.

## Stack

Python 3.10+ · [FastMCP](https://github.com/modelcontextprotocol/python-sdk) · ChromaDB · sentence-transformers · rank-bm25 · Chainlit · Anthropic + OpenAI SDKs

## Try it

```bash
git clone <repo-url> flowsim-tutor && cd flowsim-tutor
pip install -e .[chat,dev]
python index_docs.py                          # ~30s on first run (downloads MiniLM)
pytest -q                                     # 34 tests; the indexer/retriever ones need chromadb+sentence-transformers
chainlit run chat_app.py                      # opens http://localhost:8000
```

The chunker, state, and truncation tests (23 of 34) run with no extra dependencies. The 11 retriever/indexer tests pull in `chromadb` and `sentence-transformers` and load the MiniLM model on first invocation (~10–20 s warm-up).

The synthetic corpus in `data/docs/` produces 48 chunks. Drop your own Markdown into that folder and re-run `index_docs.py` to point the tutor at a different domain.

## My contribution

I designed and implemented every layer of this repo: the adaptive Markdown chunker, the dual-index hybrid retriever with RRF fusion and confidence scoring, the FastMCP server with stdio-safe response capping and lifespan-managed embedding model, the provider-neutral `LLMConnector` for Anthropic and OpenAI tool calling, the multi-server `MCPOrchestrator` with timeouts and dead-server eviction, the Chainlit chat UI, the workflow + notes state managers with atomic-write JSON persistence, the example scripts, and the test harness. The FlowSim corpus is synthetic and exists only to make the project runnable without proprietary data.

## Safety and evaluation

- [`SECURITY_AND_GUARDRAILS.md`](SECURITY_AND_GUARDRAILS.md) — prompt-injection assumptions, tool-output bounding, low-confidence behavior, file-access policy, secret-handling rules.
- [`EVALS.md`](EVALS.md) — 15 retrieval probes against the shipped corpus with expected source files, pass criteria, and the current pass rate.

## Status

Portfolio / research project maintained for demonstration and reproducibility. The shipped corpus is synthetic and can be replaced with your own Markdown corpus.

## See also

A sibling project, `multiflash-mcp`, exposes 27 thermodynamic tools over the same MCP stdio interface and can be wired into this repo by adding a server entry to `mcp_servers.json` — Chainlit picks it up at startup. If both projects live under the same GitHub account, link them from your profile.
