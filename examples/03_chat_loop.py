"""Example 3 -- minimal programmatic chat loop using the LLM connector.

Skips the Chainlit UI; calls the LLM directly with tool descriptions for the
local FlowSim tools. Useful as a starting point for embedding the FlowSim
Tutor in another application.

Prerequisites:
    1. ``python index_docs.py`` to build the index.
    2. Either ANTHROPIC_API_KEY or OPENAI_API_KEY in ``.env`` or your shell env.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from llm_connector import LLMConnector  # noqa: E402
from rag.retriever import FlowsimRetriever  # noqa: E402
from state.notes import NotesManager  # noqa: E402
from state.session import SessionManager  # noqa: E402
from web_system_prompt import get_system_prompt  # noqa: E402


LOCAL_TOOLS = [
    {
        "name": "search_docs",
        "description": "[flowsim-tutor] Search FlowSim documentation (hybrid vector + keyword).",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer", "default": 3},
            },
            "required": ["query"],
        },
    },
]


def execute_tool(name: str, args: dict, retriever: FlowsimRetriever) -> str:
    if name == "search_docs":
        result = retriever.search_docs(query=args["query"], top_k=args.get("top_k", 3))
        return json.dumps(result, indent=2)
    return json.dumps({"error": f"Unknown tool: {name}"})


async def main() -> None:
    if not (os.getenv("ANTHROPIC_API_KEY") or os.getenv("OPENAI_API_KEY")):
        print("ERROR: set ANTHROPIC_API_KEY or OPENAI_API_KEY first.")
        sys.exit(1)

    llm = LLMConnector()
    retriever = FlowsimRetriever(
        chroma_dir=PROJECT_ROOT / "data" / "chroma_db",
        bm25_path=PROJECT_ROOT / "data" / "bm25_index.pkl",
    )
    print(f"Using {llm.provider.value} / {llm.model}\n")

    history: list[dict] = []
    user_question = " ".join(sys.argv[1:]) or "How do I set up the time step in FlowSim?"
    history.append({"role": "user", "content": user_question})

    for iteration in range(5):
        response = await llm.chat(
            messages=history,
            tools=LOCAL_TOOLS,
            system_prompt=get_system_prompt(),
        )

        if response.tool_calls:
            history.append({
                "role": "assistant",
                "content": response.content or "",
                "tool_calls": [
                    {"id": tc.id, "name": tc.name, "input": tc.input}
                    for tc in response.tool_calls
                ],
            })
            for tc in response.tool_calls:
                print(f"  [tool] {tc.name}({tc.input})")
                result = execute_tool(tc.name, tc.input, retriever)
                history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": tc.name,
                    "content": result,
                })
        else:
            print("\nAssistant:")
            print(response.content)
            break

    else:
        print("\n(max iterations reached)")


if __name__ == "__main__":
    asyncio.run(main())
