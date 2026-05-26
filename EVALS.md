# Evaluation

This is a small retrieval-evaluation suite over the synthetic FlowSim corpus
shipped in `data/docs/`. It is **not** an end-to-end LLM evaluation — the
agent's tool-using behavior depends on the LLM provider and would be
non-reproducible to bake into CI. Instead, it locks down the
retriever-level signal that the LLM relies on.

## What the suite checks

15 retrieval probes and 2 low-confidence probes, each a natural-language
question paired with the source file (and optionally a section keyword)
that **must appear in the top-5 results**.

Two metrics are reported:

- **Source recall** — does the correct `.md` file appear in top-5?
  This is the metric that actually matters for honest LLM citations:
  if the retriever returns the right document, the LLM can quote and
  attribute it correctly.
- **Section recall (strict)** — does a result whose `section_path`
  contains the expected keyword appear in top-5? This is a tighter
  bar: the retriever has to surface the leaf subsection, not just a
  sibling chunk under the same document.

The probes are defined in
[`tests/evals/retrieval_eval.yaml`](tests/evals/retrieval_eval.yaml)
and executed by
[`tests/evals/run_evals.py`](tests/evals/run_evals.py).

## How to run

```bash
python index_docs.py                # builds the index in data/
python -m tests.evals.run_evals
```

The eval script loads the same `FlowsimRetriever` the MCP server uses,
so a passing score reflects the runtime configuration.

## Current results

Last run against the shipped synthetic corpus (48 chunks):

| Metric                                    | Score  |
| ----------------------------------------- | ------ |
| Source recall (top-5)                     | 15/15  |
| Section recall, strict (top-5)            |  9/15  |
| Low-confidence detection on off-topic     |  2/2   |

The retriever finds the correct source document on every probe. On six
probes it returns a parent-section chunk (e.g.,
`WellEditorHelp > Equipment` instead of `WellEditorHelp > Equipment > Valve`)
rather than the exact leaf subsection. This is consistent with how the
chunker promotes parent-level material when child sections are short —
the LLM still gets useful content and the right source file, but a
follow-up `get_full_section` call may be needed to surface the leaf.

## Known weaknesses

1. **Leaf-subsection recall is weaker than source recall.** Queries
   that target a specific equipment item or sub-workflow often
   surface the parent section instead. For chunked CHM-style
   documentation this is acceptable (the chunks under that parent
   contain the answer) but a chunker tuned to preserve more
   leaf-level boundaries would push the strict score up.

2. **No multi-document fusion test.** Every probe expects one
   source file. A real user question that legitimately spans
   multiple `.md` files is not exercised.

3. **No LLM-in-the-loop scoring.** The suite measures retrieval
   quality, not answer correctness or grounding. An LLM that calls
   `search_docs` correctly is still free to hallucinate during the
   compose step — the system prompt's citation rule
   (`web_system_prompt.py:14`) is the only guard against that and it
   relies on the model's compliance.

4. **Off-topic confidence detection has only 2 probes.** Sufficient
   for a smoke test, not for tuning the confidence thresholds in
   `rag/retriever.py:20`.

## Adding probes

Extend `retrieval_eval.yaml`:

```yaml
probes:
  - id: my_new_probe
    query: "the user's natural-language question"
    expected_source: SomeFile.md
    expected_section_contains: "a substring of the expected section_path"
```

Each new probe should target a section actually present in the corpus.
Probes against sections the chunker merges (`Model description` +
`How to use` pairs) should use the merged section path,
e.g., `... > Model description + How to use`.
