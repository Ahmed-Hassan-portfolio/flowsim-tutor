"""Chainlit chat UI -- combines local FlowSim tools with dynamic MCP server connections.

Stability features:
  - Local tools use ``asyncio.to_thread()`` for blocking operations.
  - MCP tool calls have per-call timeouts (see mcp_client.py).
  - Dead MCP servers are detected and skipped.
"""
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import chainlit as cl
from dotenv import load_dotenv

from llm_connector import LLMConnector, ToolCall
from mcp_client import MCPOrchestrator
from web_system_prompt import get_system_prompt, get_available_tools_description

from rag.retriever import FlowsimRetriever
from state.session import SessionManager
from state.notes import NotesManager

load_dotenv(override=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("flowsim-tutor.chat")

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

BASE_DIR = Path(__file__).parent

LOCAL_TOOL_TIMEOUT = 30

_retriever: FlowsimRetriever | None = None
_session_mgr: SessionManager | None = None
_notes_mgr: NotesManager | None = None

_mcp: MCPOrchestrator | None = None
_mcp_lock = asyncio.Lock()
_mcp_tools_cache: list[dict] = []

LOCAL_TOOL_NAMES = {
    "search_docs", "get_full_section", "get_session",
    "start_workflow", "complete_step", "end_session",
    "save_note", "get_notes",
}


def get_retriever() -> FlowsimRetriever:
    global _retriever
    if _retriever is None:
        logger.info("Initializing FlowsimRetriever...")
        _retriever = FlowsimRetriever(
            chroma_dir=BASE_DIR / "data" / "chroma_db",
            bm25_path=BASE_DIR / "data" / "bm25_index.pkl",
        )
        logger.info("FlowsimRetriever initialized")
    return _retriever


def get_session_mgr() -> SessionManager:
    global _session_mgr
    if _session_mgr is None:
        _session_mgr = SessionManager(BASE_DIR / "data" / "sessions")
    return _session_mgr


def get_notes_mgr() -> NotesManager:
    global _notes_mgr
    if _notes_mgr is None:
        _notes_mgr = NotesManager(BASE_DIR / "data" / "notes")
    return _notes_mgr


async def ensure_mcp_connected() -> tuple[MCPOrchestrator, list[str]]:
    """Connect to MCP servers once (thread-safe). Returns (orchestrator, status_lines)."""
    global _mcp, _mcp_tools_cache

    async with _mcp_lock:
        if _mcp is not None and _mcp._connected:
            status = []
            for name, srv in _mcp.servers.items():
                status.append(f"  - **{name}**: {len(srv.tools)} tools")
            return _mcp, status

        _mcp = MCPOrchestrator()
        status_lines = []
        try:
            results = await _mcp.connect_all()
            for server_name, tool_names in results.items():
                if tool_names:
                    preview = ', '.join(tool_names[:5])
                    suffix = '...' if len(tool_names) > 5 else ''
                    status_lines.append(f"  - **{server_name}**: {len(tool_names)} tools ({preview}{suffix})")
                else:
                    status_lines.append(f"  - **{server_name}**: failed to connect")
            _mcp_tools_cache = _mcp.get_all_tools_schema()
        except Exception as e:
            logger.error(f"MCP connection error: {e}")
            status_lines.append(f"  - MCP init error: {e}")
            _mcp_tools_cache = []

        return _mcp, status_lines


LOCAL_TOOLS = [
    {
        "name": "search_docs",
        "description": "[flowsim-tutor] Search FlowSim documentation using hybrid retrieval (vector + keyword). Returns relevant snippets with metadata.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language search query"},
                "source_filter": {"type": "string", "description": "Optional: filter by source file (e.g., 'FlowSimHelp.md')"},
                "top_k": {"type": "integer", "description": "Number of results (default 5)", "default": 5}
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_full_section",
        "description": "[flowsim-tutor] Get the complete text of a documentation section by its chunk ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "chunk_id": {"type": "string", "description": "The chunk/section ID from search results"}
            },
            "required": ["chunk_id"]
        }
    },
    {
        "name": "get_session",
        "description": "[flowsim-tutor] Get current workflow session state, or {status: 'no_active_session'} if none.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "start_workflow",
        "description": "[flowsim-tutor] Start a new tracked workflow session with goal and phases.",
        "input_schema": {
            "type": "object",
            "properties": {
                "goal": {"type": "string", "description": "The goal of this workflow"},
                "phases": {
                    "type": "array",
                    "description": "List of phases, each with name and steps",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "steps": {"type": "array", "items": {"type": "string"}}
                        }
                    }
                }
            },
            "required": ["goal", "phases"]
        }
    },
    {
        "name": "complete_step",
        "description": "[flowsim-tutor] Mark a workflow step as completed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "step_id": {"type": "string", "description": "The step ID to mark complete"}
            },
            "required": ["step_id"]
        }
    },
    {
        "name": "end_session",
        "description": "[flowsim-tutor] End the current workflow session.",
        "input_schema": {
            "type": "object",
            "properties": {
                "completed": {"type": "boolean", "description": "True if completed, False if abandoned"}
            },
            "required": ["completed"]
        }
    },
    {
        "name": "save_note",
        "description": "[flowsim-tutor] Save a note for future reference.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The note content"},
                "category": {
                    "type": "string",
                    "enum": ["general", "preferences", "decisions", "issues"],
                    "description": "Note category"
                }
            },
            "required": ["content", "category"]
        }
    },
    {
        "name": "get_notes",
        "description": "[flowsim-tutor] Get saved notes, optionally filtered by category.",
        "input_schema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["general", "preferences", "decisions", "issues"],
                    "description": "Optional category filter"
                }
            }
        }
    }
]


async def execute_local_tool(name: str, args: dict) -> str:
    """Execute a local tool in a thread pool with timeout protection."""
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_execute_local_tool_sync, name, args),
            timeout=LOCAL_TOOL_TIMEOUT,
        )
        return result
    except asyncio.TimeoutError:
        logger.error(f"Local tool {name} timed out after {LOCAL_TOOL_TIMEOUT}s")
        return json.dumps({"error": f"Tool '{name}' timed out after {LOCAL_TOOL_TIMEOUT}s"})
    except Exception as e:
        logger.error(f"Local tool {name} error: {e}")
        return json.dumps({"error": str(e)})


def _execute_local_tool_sync(name: str, args: dict) -> str:
    """Synchronous local tool execution (runs in thread pool)."""
    if name == "search_docs":
        retriever = get_retriever()
        results = retriever.search_docs(
            query=args["query"],
            source_filter=args.get("source_filter"),
            top_k=args.get("top_k", 5)
        )
        return json.dumps(results, indent=2)

    elif name == "get_full_section":
        retriever = get_retriever()
        result = retriever.get_full_section(args["chunk_id"])
        return json.dumps(result, indent=2)

    elif name == "get_session":
        session_mgr = get_session_mgr()
        result = session_mgr.get_current()
        if result is None:
            return json.dumps({"status": "no_active_session"})
        return json.dumps(result, indent=2, default=str)

    elif name == "start_workflow":
        session_mgr = get_session_mgr()
        result = session_mgr.create_session(
            goal=args["goal"], phases=args["phases"]
        )
        return json.dumps(result, indent=2, default=str)

    elif name == "complete_step":
        session_mgr = get_session_mgr()
        result = session_mgr.advance_step(args["step_id"])
        return json.dumps(result, indent=2, default=str)

    elif name == "end_session":
        session_mgr = get_session_mgr()
        result = session_mgr.end_session(completed=args["completed"])
        return json.dumps(result, indent=2, default=str)

    elif name == "save_note":
        notes_mgr = get_notes_mgr()
        result = notes_mgr.save_note(
            content=args["content"], category=args["category"]
        )
        return json.dumps(result, indent=2, default=str)

    elif name == "get_notes":
        notes_mgr = get_notes_mgr()
        result = notes_mgr.get_notes(category=args.get("category"))
        return json.dumps({"notes": result}, indent=2, default=str)

    else:
        return json.dumps({"error": f"Unknown local tool: {name}"})


async def execute_tool(name: str, args: dict) -> str:
    """Route tool call to local handler or MCP server."""
    if name in LOCAL_TOOL_NAMES:
        return await execute_local_tool(name, args)

    if _mcp and _mcp.is_mcp_tool(name):
        return await _mcp.call_tool(name, args)

    return json.dumps({"error": f"Unknown tool: {name}"})


@cl.on_chat_start
async def on_chat_start():
    """Initialize chat session with local tools + any configured MCP servers."""
    logger.info("Chat session started")

    try:
        llm = LLMConnector()
        cl.user_session.set("llm", llm)
        logger.info(f"LLM initialized: {llm.provider.value} / {llm.model}")
    except ValueError as e:
        await cl.Message(
            content=f"**Setup Error:** {e}\n\nPlease set ANTHROPIC_API_KEY or OPENAI_API_KEY in your .env file.",
        ).send()
        return

    await cl.Message(content="Initializing knowledge base & connecting MCP servers...").send()
    try:
        get_retriever()
        from rag.embedder import _get_model
        await asyncio.to_thread(_get_model)
        logger.info("Retriever + embedding model ready")
    except Exception as e:
        await cl.Message(content=f"**Error loading knowledge base:** {e}").send()
        return

    mcp, mcp_status_lines = await ensure_mcp_connected()

    all_tools = LOCAL_TOOLS + _mcp_tools_cache
    cl.user_session.set("all_tools", all_tools)
    cl.user_session.set("history", [])

    available = llm.get_available_providers()
    providers_str = ", ".join(p.value for p in available)

    mcp_section = ""
    if mcp_status_lines:
        mcp_section = "\n\n**MCP Servers:**\n" + "\n".join(mcp_status_lines)

    tools_desc = get_available_tools_description(all_tools)

    await cl.Message(
        content=(
            f"**FlowSim Tutor** ready!\n\n"
            f"Using: **{llm.provider.value}** / {llm.model}\n"
            f"Available providers: {providers_str}"
            f"{mcp_section}\n\n"
            f"{tools_desc}"
        )
    ).send()


@cl.on_chat_end
async def on_chat_end():
    logger.info("Chat session ended")


@cl.on_message
async def on_message(message: cl.Message):
    """Handle incoming user messages with LLM + tool calling."""
    llm: LLMConnector = cl.user_session.get("llm")
    if not llm:
        await cl.Message(content="LLM not initialized. Please refresh the page.").send()
        return

    all_tools: list[dict] = cl.user_session.get("all_tools", LOCAL_TOOLS)
    history: list[dict] = cl.user_session.get("history", [])

    user_msg = {"role": "user", "content": message.content}

    if message.elements:
        image_note = f"\n[User uploaded {len(message.elements)} image(s)]"
        user_msg["content"] += image_note

    history.append(user_msg)

    response_msg = cl.Message(content="")
    await response_msg.send()

    max_iterations = 10
    iteration = 0

    while iteration < max_iterations:
        iteration += 1

        full_response = None
        async for partial in llm.chat_stream(
            messages=history,
            tools=all_tools,
            system_prompt=get_system_prompt(),
        ):
            if not partial.is_complete:
                response_msg.content = partial.content
                await response_msg.update()
            else:
                full_response = partial

        if not full_response:
            break

        if full_response.tool_calls:
            tool_results = []

            for tool_call in full_response.tool_calls:
                result = await execute_tool_with_step(tool_call)
                tool_results.append({
                    "tool_call_id": tool_call.id,
                    "name": tool_call.name,
                    "result": result,
                })

            history.append({
                "role": "assistant",
                "content": full_response.content or "",
                "tool_calls": [
                    {"id": tc.id, "name": tc.name, "input": tc.input}
                    for tc in full_response.tool_calls
                ],
            })

            for tr in tool_results:
                history.append({
                    "role": "tool",
                    "tool_call_id": tr["tool_call_id"],
                    "name": tr["name"],
                    "content": tr["result"],
                })

            response_msg = cl.Message(content="")
            await response_msg.send()

        else:
            history.append({
                "role": "assistant",
                "content": full_response.content or "",
            })
            break

    cl.user_session.set("history", history)


@cl.step(type="tool", show_input="json")
async def execute_tool_with_step(tool_call: ToolCall) -> str:
    """Execute a tool call and display as collapsible step."""
    current_step = cl.context.current_step

    server_name = _mcp.get_server_for_tool(tool_call.name) if _mcp else None
    if server_name:
        current_step.name = f"{tool_call.name} [{server_name}]"
    else:
        current_step.name = tool_call.name

    current_step.input = json.dumps(tool_call.input, indent=2)

    logger.info(f"Calling tool: {tool_call.name} (server={server_name or 'local'}) with {tool_call.input}")
    result = await execute_tool(tool_call.name, tool_call.input)

    summary = _summarize_tool_result(tool_call.name, result)
    current_step.output = summary

    logger.info(f"Tool result: {summary[:100]}...")
    return result


def _summarize_tool_result(tool_name: str, result: str) -> str:
    """Create a brief summary of tool result for UI display."""
    try:
        data = json.loads(result)

        if tool_name == "search_docs":
            if "results" in data:
                count = len(data["results"])
                sources = set()
                for r in data["results"]:
                    if "source_file" in r:
                        sources.add(r["source_file"].replace(".md", ""))
                sources_str = ", ".join(sorted(sources)[:3])
                return f"{count} results from {sources_str}"

        elif tool_name == "get_full_section":
            if "content" in data:
                lines = data["content"].count("\n") + 1
                return f"Section retrieved ({lines} lines)"

        elif tool_name == "get_session":
            if "status" in data:
                if data["status"] == "no_active_session":
                    return "No active session"
                return f"Session: {data.get('goal', 'Active')[:50]}"

        elif tool_name in ("start_workflow", "complete_step", "end_session"):
            if "status" in data:
                return f"Status: {data['status']}"

        elif tool_name in ("save_note", "get_notes"):
            if "notes" in data:
                return f"{len(data['notes'])} notes"
            elif "id" in data:
                return "Note saved"

        if isinstance(data, dict):
            if "error" in data:
                return f"Error: {str(data['error'])[:80]}"
            if "result" in data:
                return f"Result: {str(data['result'])[:80]}"

        return result[:200] + ("..." if len(result) > 200 else "")

    except json.JSONDecodeError:
        return result[:200] + ("..." if len(result) > 200 else "")
