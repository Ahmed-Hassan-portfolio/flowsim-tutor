"""Session management tools for FlowSim workflow tracking."""

import asyncio
import json
import logging
from typing import Annotated, Callable

from pydantic import Field
from mcp.server.fastmcp import Context

logger = logging.getLogger("flowsim-tutor.tools.session")

TOOL_TIMEOUT = 15


def register_session_tools(mcp, truncate_response: Callable[[str], str]):
    """Register session-related tools on the MCP server."""

    @mcp.tool()
    async def get_session(ctx: Context = None) -> str:
        """Get the current workflow session state.

        IMPORTANT: Call this at the START of every conversation to check
        if the user has an active workflow in progress.

        Returns the current session with goal, phase, step, and progress,
        or ``{status: "no_active_session"}`` if no workflow is active.
        """
        try:
            app = ctx.request_context.lifespan_context
            session = await asyncio.wait_for(
                asyncio.to_thread(app.session_mgr.get_current),
                timeout=TOOL_TIMEOUT,
            )
            if session is None:
                logger.info("get_session: no active session")
                return json.dumps({"status": "no_active_session"})
            logger.info(
                "get_session: id=%s, status=%s, progress=%s",
                session["id"][:8], session["status"], session["progress"]
            )
            return truncate_response(json.dumps(session, indent=2))
        except asyncio.TimeoutError:
            return json.dumps({"error": f"Timed out after {TOOL_TIMEOUT}s"})
        except Exception as e:
            logger.exception("get_session failed: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def start_workflow(
        goal: Annotated[str, Field(description="High-level goal the user wants to accomplish")],
        phases: Annotated[
            list[dict],
            Field(description="List of phase objects, each with 'name', 'description', and 'steps' (list with 'id', 'description', 'completed')")
        ],
        ctx: Context = None,
    ) -> str:
        """Create a new tracked workflow session.

        Use this when the user starts a new multi-step task. Break down
        the task into phases, each with discrete steps.
        """
        try:
            app = ctx.request_context.lifespan_context
            session = await asyncio.wait_for(
                asyncio.to_thread(app.session_mgr.create_session, goal=goal, phases=phases),
                timeout=TOOL_TIMEOUT,
            )
            logger.info(
                "start_workflow: created session %s with %d phases",
                session["id"][:8], len(phases)
            )
            summary = await asyncio.to_thread(app.session_mgr.get_current)
            return truncate_response(json.dumps(summary, indent=2))
        except asyncio.TimeoutError:
            return json.dumps({"error": f"Timed out after {TOOL_TIMEOUT}s"})
        except Exception as e:
            logger.exception("start_workflow failed: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def complete_step(
        step_id: Annotated[str, Field(description="The step ID to mark as completed")],
        ctx: Context = None,
    ) -> str:
        """Mark a workflow step as completed and advance to the next step.

        Returns the updated session progress. If all steps in a phase are
        done, automatically advances to the next phase.
        """
        try:
            app = ctx.request_context.lifespan_context
            summary = await asyncio.wait_for(
                asyncio.to_thread(app.session_mgr.advance_step, step_id),
                timeout=TOOL_TIMEOUT,
            )
            logger.info(
                "complete_step: step=%s, progress=%s",
                step_id, summary["progress"]
            )
            return truncate_response(json.dumps(summary, indent=2))
        except asyncio.TimeoutError:
            return json.dumps({"error": f"Timed out after {TOOL_TIMEOUT}s"})
        except ValueError as e:
            logger.warning("complete_step: %s", e)
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.exception("complete_step failed: %s", e)
            return json.dumps({"error": str(e)})

    @mcp.tool()
    async def end_session(
        completed: Annotated[bool, Field(description="True if workflow completed, False if abandoned")],
        ctx: Context = None,
    ) -> str:
        """Explicitly end the current workflow session.

        Use when the user has finished all steps (completed=True), wants to
        abandon the workflow (completed=False), or wants to start a different task.
        """
        try:
            app = ctx.request_context.lifespan_context
            summary = await asyncio.wait_for(
                asyncio.to_thread(app.session_mgr.end_session, completed),
                timeout=TOOL_TIMEOUT,
            )
            logger.info(
                "end_session: id=%s, completed=%s, final_status=%s",
                summary["id"][:8], completed, summary["status"]
            )
            return truncate_response(json.dumps(summary, indent=2))
        except asyncio.TimeoutError:
            return json.dumps({"error": f"Timed out after {TOOL_TIMEOUT}s"})
        except ValueError as e:
            logger.warning("end_session: %s", e)
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.exception("end_session failed: %s", e)
            return json.dumps({"error": str(e)})
