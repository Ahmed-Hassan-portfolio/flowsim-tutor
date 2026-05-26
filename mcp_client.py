"""MCP Client Orchestrator -- connects to multiple MCP servers and routes tool calls.

Stability features:
  - Connection timeout: servers that don't respond within ``MCP_CONNECT_TIMEOUT``
    are skipped.
  - Tool call timeout: individual tool calls timeout after ``MCP_TOOL_CALL_TIMEOUT``.
  - Dead server detection: servers that fail repeatedly are marked dead and skipped.
"""
import asyncio
import json
import logging
import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

logger = logging.getLogger("flowsim-tutor.mcp-client")

MCP_CONNECT_TIMEOUT = 30
MCP_TOOL_CALL_TIMEOUT = 60
MAX_CONSECUTIVE_FAILURES = 3


class MCPServerConnection:
    """A single MCP server connection with its tools."""

    def __init__(self, name: str, session: ClientSession, tools: list[types.Tool]):
        self.name = name
        self.session = session
        self.tools = tools
        self.tool_names = {t.name for t in tools}
        self._consecutive_failures = 0
        self.alive = True

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Call a tool on this server with timeout protection."""
        if not self.alive:
            return json.dumps({"error": f"Server '{self.name}' is not responding. Restart the chat to reconnect."})

        try:
            result = await asyncio.wait_for(
                self.session.call_tool(name, arguments=arguments),
                timeout=MCP_TOOL_CALL_TIMEOUT,
            )
            self._consecutive_failures = 0

            parts = []
            for block in result.content:
                if isinstance(block, types.TextContent):
                    parts.append(block.text)
                elif isinstance(block, types.EmbeddedResource):
                    parts.append(str(block.resource))
                else:
                    parts.append(str(block))
            return "\n".join(parts) if parts else "{}"

        except asyncio.TimeoutError:
            self._consecutive_failures += 1
            logger.error(
                "Tool '%s' on '%s' timed out after %ds (failure %d/%d)",
                name, self.name, MCP_TOOL_CALL_TIMEOUT,
                self._consecutive_failures, MAX_CONSECUTIVE_FAILURES,
            )
            if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                self.alive = False
                logger.error("Server '%s' marked as dead after %d consecutive failures", self.name, MAX_CONSECUTIVE_FAILURES)
            return json.dumps({
                "error": f"Tool '{name}' timed out after {MCP_TOOL_CALL_TIMEOUT}s",
                "hint": "The MCP server may be stalled. Try a simpler query or restart the chat.",
            })

        except Exception as e:
            self._consecutive_failures += 1
            logger.error(
                "Tool '%s' on '%s' failed: %s (failure %d/%d)",
                name, self.name, e,
                self._consecutive_failures, MAX_CONSECUTIVE_FAILURES,
            )
            if self._consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                self.alive = False
                logger.error("Server '%s' marked as dead after %d consecutive failures", self.name, MAX_CONSECUTIVE_FAILURES)
            return json.dumps({"error": f"Tool call failed: {e}"})


class MCPOrchestrator:
    """Manages connections to multiple MCP servers and routes tool calls."""

    def __init__(self, config_path: str | Path | None = None):
        self.config_path = Path(config_path) if config_path else Path(__file__).parent / "mcp_servers.json"
        self.servers: dict[str, MCPServerConnection] = {}
        self.tool_to_server: dict[str, str] = {}
        self._exit_stack = AsyncExitStack()
        self._connected = False

    async def connect_all(self) -> dict[str, list[str]]:
        """Connect to all configured MCP servers."""
        if self._connected:
            return {name: list(srv.tool_names) for name, srv in self.servers.items()}

        config = self._load_config()
        results = {}

        for server_name, server_config in config.items():
            try:
                tools = await self._connect_server(server_name, server_config)
                results[server_name] = [t.name for t in tools]
                logger.info(f"Connected to '{server_name}': {len(tools)} tools")
            except asyncio.TimeoutError:
                logger.error(f"Timeout connecting to '{server_name}' after {MCP_CONNECT_TIMEOUT}s")
                results[server_name] = []
            except Exception as e:
                logger.error(f"Failed to connect to '{server_name}': {e}")
                results[server_name] = []

        self._connected = True
        return results

    async def disconnect_all(self) -> None:
        """Disconnect from all MCP servers."""
        if self._connected:
            try:
                await self._exit_stack.aclose()
            except Exception as e:
                logger.warning(f"Error during MCP disconnect: {e}")
            self.servers.clear()
            self.tool_to_server.clear()
            self._exit_stack = AsyncExitStack()
            self._connected = False
            logger.info("All MCP servers disconnected")

    def get_all_tools_schema(self) -> list[dict]:
        """Get combined tool schemas from all connected servers."""
        all_tools = []
        for server in self.servers.values():
            if not server.alive:
                continue
            for tool in server.tools:
                schema = {
                    "name": tool.name,
                    "description": f"[{server.name}] {tool.description or ''}",
                    "input_schema": tool.inputSchema if tool.inputSchema else {"type": "object", "properties": {}},
                }
                all_tools.append(schema)
        return all_tools

    def get_server_for_tool(self, tool_name: str) -> str | None:
        return self.tool_to_server.get(tool_name)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Route a tool call to the appropriate MCP server."""
        server_name = self.tool_to_server.get(name)
        if not server_name or server_name not in self.servers:
            return json.dumps({"error": f"Unknown MCP tool: {name}"})

        server = self.servers[server_name]
        return await server.call_tool(name, arguments)

    def is_mcp_tool(self, name: str) -> bool:
        return name in self.tool_to_server

    @property
    def connected_servers(self) -> list[str]:
        return list(self.servers.keys())

    def get_server_health(self) -> dict[str, dict]:
        return {
            name: {
                "alive": srv.alive,
                "tools": len(srv.tools),
                "consecutive_failures": srv._consecutive_failures,
            }
            for name, srv in self.servers.items()
        }

    def _load_config(self) -> dict[str, dict]:
        if not self.config_path.exists():
            logger.warning(f"MCP config not found: {self.config_path}")
            return {}

        with open(self.config_path, "r") as f:
            data = json.load(f)

        return data.get("mcpServers", {})

    async def _connect_server(self, name: str, config: dict) -> list[types.Tool]:
        command = config["command"]
        args = config.get("args", [])

        env = dict(os.environ)
        if config.get("env"):
            env.update(config["env"])

        server_params = StdioServerParameters(
            command=command,
            args=args,
            env=env,
        )

        async with asyncio.timeout(MCP_CONNECT_TIMEOUT):
            read, write = await self._exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            session = await self._exit_stack.enter_async_context(
                ClientSession(read, write)
            )
            await session.initialize()
            tools_result = await session.list_tools()

        tools = tools_result.tools

        self.servers[name] = MCPServerConnection(name, session, tools)
        for tool in tools:
            if tool.name in self.tool_to_server:
                logger.warning(
                    f"Tool name conflict: '{tool.name}' exists in '{self.tool_to_server[tool.name]}', "
                    f"overriding with '{name}'"
                )
            self.tool_to_server[tool.name] = name

        return tools
