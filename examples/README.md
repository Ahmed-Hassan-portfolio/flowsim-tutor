# Examples

Three minimal entry points for FlowSim Tutor. All examples assume the
synthetic corpus in `data/docs/` has been indexed first:

```bash
cd ..
pip install -e .[chat]
python index_docs.py
```

`index_docs.py` reads every `.md` file in `data/docs/`, chunks it, builds
the ChromaDB and BM25 indexes, and writes `data/index_manifest.json`.

## 01_search_docs.py — direct retriever

A one-shot hybrid search against the local index, no LLM involved.

```bash
python examples/01_search_docs.py "how do I set the time step"
```

Prints the top three results with section path, RRF score, and a snippet.

## 02_workflow.py — tracked workflow lifecycle

Creates a session, advances through two steps (which auto-advances the
phase), then ends the session. Session JSON is written under
`data/sessions/`.

```bash
python examples/02_workflow.py
```

## 03_chat_loop.py — programmatic chat

Minimal chat loop that wires `LLMConnector` to the `search_docs` tool —
think of it as the Chainlit UI minus the UI. Requires either
`ANTHROPIC_API_KEY` or `OPENAI_API_KEY` in `.env`.

```bash
python examples/03_chat_loop.py "How do I configure the steady-state preprocessor?"
```

## Corpus

The corpus in `data/docs/` is **invented**. It mimics the structural
conventions of CHM-derived flow-simulator help (`---` separators,
hierarchical headers, paired `Model description` + `How to use`
sections, numbered step sequences) so the chunker has something
representative to exercise. None of the content describes a real
product. Replace the six `.md` files with your own corpus to point the
tutor at a different domain — no code changes required.
