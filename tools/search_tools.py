"""Search tools for FlowSim documentation retrieval.

Stability: tools run sync operations via ``asyncio.to_thread`` and cap response
size so stdio pipe buffers don't deadlock.
"""

import asyncio
import json
import logging
from typing import Annotated, Callable

from mcp.server.fastmcp import Context
from pydantic import Field

logger = logging.getLogger("flowsim-tutor.tools.search")

TOOL_TIMEOUT = 30


def register_search_tools(mcp, truncate_response: Callable[[str], str]):
    """Register search-related tools on the MCP server."""

    @mcp.tool()
    async def search_docs(
        query: Annotated[
            str,
            Field(description="Natural language search query about FlowSim"),
        ],
        source_filter: Annotated[
            str | None,
            Field(
                description="Filter results by source file name (e.g., 'FlowSimHelp.md')"
            ),
        ] = None,
        top_k: Annotated[
            int,
            Field(description="Number of results to return (1-20)", ge=1, le=20),
        ] = 5,
        ctx: Context = None,
    ) -> str:
        """Search FlowSim documentation using hybrid retrieval (vector + keyword with RRF fusion).

        Returns ranked snippets with source citations and confidence scores.
        Use this as the primary way to find information in FlowSim docs.
        If confidence is "low", the search may not have found relevant results.
        """
        try:
            app = ctx.request_context.lifespan_context

            result = await asyncio.wait_for(
                asyncio.to_thread(
                    app.rag_engine.search_docs,
                    query=query,
                    source_filter=source_filter,
                    top_k=top_k,
                ),
                timeout=TOOL_TIMEOUT,
            )

            logger.info(
                "search_docs: query=%r, results=%d, confidence=%s",
                query[:50],
                len(result.get("results", [])),
                result.get("confidence"),
            )
            return truncate_response(json.dumps(result, indent=2))

        except asyncio.TimeoutError:
            logger.error("search_docs timed out after %ds", TOOL_TIMEOUT)
            return json.dumps({"error": f"Search timed out after {TOOL_TIMEOUT}s", "hint": "Try a simpler query"})
        except Exception as e:
            logger.exception("search_docs failed: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def get_full_section(
        section_id: Annotated[
            str,
            Field(description="Section ID or chunk ID from search results"),
        ],
        ctx: Context = None,
    ) -> str:
        """Retrieve the complete text of a documentation section.

        Use this after ``search_docs`` when you need the full content of a
        section, not just the snippet. Pass the chunk_id from search results.
        Large sections are truncated to prevent transport issues.
        """
        try:
            app = ctx.request_context.lifespan_context

            result = await asyncio.wait_for(
                asyncio.to_thread(app.rag_engine.get_full_section, section_id),
                timeout=TOOL_TIMEOUT,
            )

            logger.info("get_full_section: section_id=%r", section_id)
            return truncate_response(json.dumps(result, indent=2))

        except asyncio.TimeoutError:
            logger.error("get_full_section timed out after %ds", TOOL_TIMEOUT)
            return json.dumps({"error": f"Section retrieval timed out after {TOOL_TIMEOUT}s"})
        except Exception as e:
            logger.exception("get_full_section failed: %s", e)
            return json.dumps({"error": str(e)})
