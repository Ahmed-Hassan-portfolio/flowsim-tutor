# FlowSim Tutor

A documentation-grounded chat assistant for the (fictional) FlowSim flow-simulation tool. The corpus in `data/docs/` is invented and intended to demonstrate the underlying RAG pipeline; drop your own Markdown in there to retarget the tutor at a different domain.

## What's behind the chat

- **Hybrid retrieval** — ChromaDB vectors + BM25 keyword, fused with RRF.
- **Workflow tracking** — start a multi-step task and check off steps as you go.
- **Cross-session notes** — anything categorized as a preference, decision, or known issue persists across chat sessions.
- **Multi-MCP** — additional MCP servers configured in `mcp_servers.json` show up as extra tools automatically.

To suppress this welcome screen, empty out `chainlit.md`.
