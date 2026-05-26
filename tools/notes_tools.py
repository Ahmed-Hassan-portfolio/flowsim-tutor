"""Notes tools for cross-session memory persistence."""

import asyncio
import json
import logging
from typing import Annotated, Callable, Literal

from pydantic import Field
from mcp.server.fastmcp import Context

logger = logging.getLogger("flowsim-tutor.tools.notes")

NoteCategory = Literal["general", "preferences", "decisions", "issues"]

TOOL_TIMEOUT = 15
MAX_NOTES_RETURNED = 20


def register_notes_tools(mcp, truncate_response: Callable[[str], str]):
    """Register notes-related tools on the MCP server."""

    @mcp.tool()
    async def save_note(
        content: Annotated[str, Field(description="The note content to save")],
        category: Annotated[
            NoteCategory,
            Field(description="Category: 'general', 'preferences', 'decisions', or 'issues'")
        ] = "general",
        ctx: Context = None,
    ) -> str:
        """Save a note for cross-session memory.

        Use this to remember important information that should persist
        across conversations:
          - 'preferences': User's preferred ways of working (units, formats)
          - 'decisions': Key decisions made during workflows
          - 'issues': Problems encountered and solutions
          - 'general': Any other useful information

        Notes survive conversation resets and session ends.
        """
        try:
            app = ctx.request_context.lifespan_context
            note = await asyncio.wait_for(
                asyncio.to_thread(app.notes_mgr.save_note, content=content, category=category),
                timeout=TOOL_TIMEOUT,
            )
            logger.info(
                "save_note: id=%s, category=%s, content=%s...",
                note["id"][:8], category, content[:30]
            )
            return truncate_response(json.dumps(note, indent=2))
        except asyncio.TimeoutError:
            return json.dumps({"error": f"Timed out after {TOOL_TIMEOUT}s"})
        except ValueError as e:
            logger.warning("save_note: %s", e)
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.exception("save_note failed: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def get_notes(
        category: Annotated[
            NoteCategory | None,
            Field(description="Filter by category, or omit to get all notes")
        ] = None,
        ctx: Context = None,
    ) -> str:
        """Retrieve saved notes, optionally filtered by category.

        Returns notes sorted by creation time (newest first).
        Use this at conversation start to recall important user context.
        Returns at most 20 notes; use a category filter to narrow.
        """
        try:
            app = ctx.request_context.lifespan_context
            notes = await asyncio.wait_for(
                asyncio.to_thread(app.notes_mgr.get_notes, category=category),
                timeout=TOOL_TIMEOUT,
            )
            logger.info(
                "get_notes: category=%s, count=%d",
                category or "all", len(notes)
            )

            total_count = len(notes)
            truncated = total_count > MAX_NOTES_RETURNED
            if truncated:
                notes = notes[:MAX_NOTES_RETURNED]

            result = {
                "notes": notes,
                "count": len(notes),
                "total_count": total_count,
                "category_filter": category,
            }
            if truncated:
                result["truncated"] = True
                result["hint"] = "Use a category filter to narrow results"

            return truncate_response(json.dumps(result, indent=2, default=str))

        except asyncio.TimeoutError:
            return json.dumps({"error": f"Timed out after {TOOL_TIMEOUT}s"})
        except ValueError as e:
            logger.warning("get_notes: %s", e)
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.exception("get_notes failed: %s", e)
            return json.dumps({"error": str(e)})
