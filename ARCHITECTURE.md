# Architecture

This document describes the components of `flowsim-tutor`, how data flows between them, and the rationale behind a few non-obvious design choices.

## Component diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                       chat_app.py (Chainlit)                    │
│  ┌──────────────────────────┐    ┌──────────────────────────┐   │
│  │      LLMConnector        │    │    MCPOrchestrator       │   │
│  │  (Anthropic | OpenAI,    │    │  (stdio sub-processes,   │   │
│  │   streaming, tool calls) │    │   timeouts, dead-server) │   │
│  └────────────┬─────────────┘    └────────────┬─────────────┘   │
│               │                                │                │
│      tools (local)               tools (remote via MCP)         │
└───────────────┼────────────────────────────────┼────────────────┘
                │                                │
                │              ┌─────────────────▼──────────┐
                │              │  External MCP servers      │
                │              │  (optional, configured in  │
                │              │   mcp_servers.json)        │
                │              └────────────────────────────┘
                │
                ▼
┌─────────────────────────────────────────────────────────────────┐
│                       server.py (FastMCP)                       │
│                                                                 │
│   ┌──────────────────┐  ┌──────────────────┐  ┌──────────────┐  │
│   │ tools/search_*   │  │ tools/session_*  │  │ tools/notes_*│  │
│   │  search_docs     │  │  get_session     │  │  save_note   │  │
│   │  get_full_section│  │  start_workflow  │  │  get_notes   │  │
│   │                  │  │  complete_step   │  │              │  │
│   │                  │  │  end_session     │  │              │  │
│   └────────┬─────────┘  └────────┬─────────┘  └──────┬───────┘  │
└────────────┼──────────────────────┼───────────────────┼─────────┘
             │                      │                   │
   ┌─────────▼─────────┐  ┌─────────▼─────────┐  ┌─────▼────────┐
   │ rag/retriever.py  │  │ state/session.py  │  │state/notes.py│
   │ (Flowsim          │  │ (SessionManager)  │  │(NotesManager)│
   │  Retriever)       │  │                   │  │              │
   └─────────┬─────────┘  └─────────┬─────────┘  └─────┬────────┘
             │                      │                   │
             ▼                      ▼                   ▼
   ┌─────────────────┐    ┌─────────────────────────────────┐
   │ ChromaDB        │    │   data/sessions/*.json          │
   │ BM25 pickle     │    │   data/notes/notes.json         │
   │ index_manifest  │    │   (atomic writes via os.replace)│
   └─────────────────┘    └─────────────────────────────────┘
             ▲
             │  built by
             │
   ┌─────────┴───────┐
   │  index_docs.py  │  reads data/docs/*.md, builds dual index
   └─────────────────┘
```

## Data flow

### Indexing (one-time)

1. `index_docs.py` reads every `.md` under `data/docs/`.
2. `rag.chunker.chunk_all` produces `Chunk` objects, splitting on `---`, tracking full heading hierarchy (`##`–`######`), merging `Model description` + `How to use` pairs, and preserving numbered step sequences.
3. `rag.embedder.encode_texts` produces (N, 384) embeddings via `all-MiniLM-L6-v2` (normalized for cosine).
4. `rag.indexer.build_chromadb_index` stores them in a persistent ChromaDB collection with HNSW (M=16, ef_construction=200, ef_search=100).
5. `rag.indexer.build_bm25_index` pickles a `BM25Okapi` over the same chunks in the same order, alongside a list of chunk IDs.
6. `rag.indexer.build_manifest` writes SHA-256 hashes of each source file and a hash of the sorted chunk-ID set, plus the two store counts. `counts_match` must be true.

### Query (runtime)

1. `chat_app.py` receives a user message and calls the LLM with the merged local + MCP tool list.
2. The LLM chooses `search_docs(query, source_filter?, top_k?)`.
3. `FlowsimRetriever.search_docs` embeds the query, retrieves top-20 from ChromaDB and top-20 from BM25, fuses with RRF (k=60), deduplicates by `section_path`, and returns the top `top_k` with a query-aware snippet.
4. If confidence is below threshold (`rrf_score < 0.025` or best chroma distance > 0.85), the result is flagged `low` so the LLM tells the user it didn't find what they asked for.
5. The LLM optionally calls `get_full_section(chunk_id)` to fetch the complete section text (all sub-chunks joined in chunk-index order).

## Key design decisions

### Why hybrid retrieval, not vector-only

Single-letter and acronym queries (`PIPELINE`, `MAXDT`, `INTEGRATION`) score poorly on dense embeddings because the model never saw them in pre-training, but BM25 finds them instantly. Conversely, paraphrased questions ("how do I make the time step adaptive") miss BM25 but match well in the embedding space. RRF gives both retrievers a vote without committing to a brittle linear weighting.

### Why merge `Model description` + `How to use` at chunk time

CHM-derived help splits these into adjacent siblings under the same parent. Returning only the `How to use` chunk without the `Model description` makes the LLM hallucinate the model description; returning two sibling chunks forces it to stitch them. Merging at chunk time keeps the answer self-contained and pushes one fewer round trip through the LLM.

### Why a manifest with counts_match

The two stores (ChromaDB + BM25) can drift if the indexing pipeline is interrupted mid-build. The manifest verifies on every server start that both stores have the same count as the chunk list. Drift is a hard refusal rather than a silent degradation.

### Why cap MCP responses at 3500 bytes

Windows stdio pipe buffers can be as small as 4 KB. A larger response causes a producer-consumer deadlock: the server writes, blocks on a full buffer, and the client blocks waiting for the server to finish so it can read. Truncation with a structured `{"truncated": true, "hint": ...}` reply gives the LLM a clean recovery path — narrow the query and retry.

### Why pre-load the embedding model in lifespan

`sentence-transformers.SentenceTransformer("all-MiniLM-L6-v2")` takes 3–5 s on first call. If that happens inside the first `search_docs` tool call, the MCP client times out. Loading it in `app_lifespan` moves the stall to server startup where it's expected.

### Why atomic-write JSON instead of SQLite

Sessions and notes are read-mostly, single-writer, and rarely more than a few hundred items. SQLite would be overkill and would introduce concurrency mode questions the project doesn't need to answer. `tmp_path.write_text(...); os.replace(tmp_path, final_path)` gives us crash-safe writes on both POSIX and Windows with no dependencies.

### Why two LLM providers in one connector

The MCP tool schema is provider-agnostic, but Claude's `tool_use` blocks and OpenAI's `tool_calls` streaming chunks have different shapes. The connector accepts whichever provider has an API key set, and a tool-call result coming out of the connector looks identical regardless of source. The Chainlit chat loop never knows which provider is in use.

### Why `FlowsimRetriever` and not `Retriever`

The class name is deliberately corpus-aware because the ChromaDB collection name (`flowsim_docs`) is hard-coded as the default. The retriever still accepts any collection name as a constructor argument, so it can be reused against a differently-named corpus without touching the class.
