"""LLM Connector -- unified interface for Anthropic and OpenAI APIs with tool calling."""
import os
import json
import logging
from dataclasses import dataclass
from enum import Enum
from typing import AsyncIterator, Any

logger = logging.getLogger("flowsim-tutor.llm")


class LLMProvider(Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMResponse:
    """Unified response shape from any provider."""
    content: str
    tool_calls: list[ToolCall]
    stop_reason: str | None  # end_turn, tool_use, stop, tool_calls, error
    is_complete: bool


class LLMConnector:
    """Unified LLM interface supporting Claude and OpenAI with tool calling."""

    DEFAULT_MODELS = {
        LLMProvider.ANTHROPIC: "claude-sonnet-4-20250514",
        LLMProvider.OPENAI: "gpt-4o",
    }

    AVAILABLE_MODELS = {
        LLMProvider.ANTHROPIC: [
            "claude-sonnet-4-20250514",
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
        ],
        LLMProvider.OPENAI: [
            "gpt-4o",
            "gpt-4-turbo",
            "gpt-4",
        ],
    }

    def __init__(
        self,
        provider: LLMProvider | str | None = None,
        model: str | None = None,
    ):
        if isinstance(provider, str):
            provider = LLMProvider(provider)

        if provider is None:
            provider = self._detect_provider()

        self.provider = provider
        self.model = model or self._get_default_model(provider)
        self.client = None

        if self.provider == LLMProvider.ANTHROPIC:
            self._init_anthropic_client()
        else:
            self._init_openai_client()

        logger.info(f"LLMConnector initialized: provider={self.provider.value}, model={self.model}")

    def _detect_provider(self) -> LLMProvider:
        if os.getenv("ANTHROPIC_API_KEY"):
            return LLMProvider.ANTHROPIC
        elif os.getenv("OPENAI_API_KEY"):
            return LLMProvider.OPENAI
        else:
            raise ValueError(
                "No API key found. Set ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable."
            )

    def _get_default_model(self, provider: LLMProvider) -> str:
        if provider == LLMProvider.ANTHROPIC:
            return os.getenv("ANTHROPIC_MODEL", self.DEFAULT_MODELS[provider])
        else:
            return os.getenv("OPENAI_MODEL", self.DEFAULT_MODELS[provider])

    def _init_anthropic_client(self) -> None:
        try:
            import anthropic
            self.client = anthropic.AsyncAnthropic()
            logger.debug("Anthropic client initialized")
        except ImportError:
            raise ImportError("anthropic package required. Install with: pip install anthropic")

    def _init_openai_client(self) -> None:
        try:
            import openai
            self.client = openai.AsyncOpenAI()
            logger.debug("OpenAI client initialized")
        except ImportError:
            raise ImportError("openai package required. Install with: pip install openai")

    def _format_tools_anthropic(self, mcp_tools: list[dict]) -> list[dict]:
        if not mcp_tools:
            return []
        return [
            {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "input_schema": tool.get("inputSchema", tool.get("input_schema", {"type": "object", "properties": {}})),
            }
            for tool in mcp_tools
        ]

    def _format_tools_openai(self, mcp_tools: list[dict]) -> list[dict]:
        if not mcp_tools:
            return []
        return [
            {
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool.get("description", ""),
                    "parameters": tool.get("inputSchema", tool.get("input_schema", {"type": "object", "properties": {}})),
                },
            }
            for tool in mcp_tools
        ]

    async def _anthropic_stream(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> AsyncIterator[LLMResponse]:
        """Stream responses from Claude.

        Yields partial responses during streaming, with the final response
        containing any tool_use blocks parsed into ToolCall objects.
        """
        formatted_tools = self._format_tools_anthropic(tools)

        kwargs = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt
        if formatted_tools:
            kwargs["tools"] = formatted_tools

        async with self.client.messages.stream(**kwargs) as stream:
            content = ""

            async for event in stream:
                if event.type == "content_block_delta":
                    if hasattr(event.delta, "text"):
                        content += event.delta.text
                        yield LLMResponse(
                            content=content,
                            tool_calls=[],
                            stop_reason=None,
                            is_complete=False,
                        )

            final_message = await stream.get_final_message()
            tool_calls = []

            for block in final_message.content:
                if block.type == "tool_use":
                    tool_calls.append(ToolCall(
                        id=block.id,
                        name=block.name,
                        input=block.input,
                    ))
                elif block.type == "text":
                    content = block.text

            yield LLMResponse(
                content=content,
                tool_calls=tool_calls,
                stop_reason=final_message.stop_reason,
                is_complete=True,
            )

    async def _openai_stream(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str,
    ) -> AsyncIterator[LLMResponse]:
        """Stream responses from OpenAI.

        Tool calls are streamed incrementally (arguments chunked) and assembled
        into complete ToolCall objects in the final response.
        """
        formatted_tools = self._format_tools_openai(tools)

        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})

        for msg in messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                formatted_tcs = []
                for tc in msg["tool_calls"]:
                    formatted_tcs.append({
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc.get("input", {})),
                        },
                    })
                full_messages.append({
                    "role": "assistant",
                    "content": msg.get("content") or None,
                    "tool_calls": formatted_tcs,
                })
            elif msg.get("role") == "tool":
                full_messages.append({
                    "role": "tool",
                    "tool_call_id": msg["tool_call_id"],
                    "content": msg.get("content", ""),
                })
            else:
                full_messages.append(msg)

        kwargs = {
            "model": self.model,
            "messages": full_messages,
            "stream": True,
        }
        if formatted_tools:
            kwargs["tools"] = formatted_tools

        stream = await self.client.chat.completions.create(**kwargs)

        content = ""
        tool_calls_data: dict[int, dict] = {}
        finish_reason = None

        async for chunk in stream:
            if not chunk.choices:
                continue

            choice = chunk.choices[0]
            delta = choice.delta
            finish_reason = choice.finish_reason or finish_reason

            if delta.content:
                content += delta.content
                yield LLMResponse(
                    content=content,
                    tool_calls=[],
                    stop_reason=None,
                    is_complete=False,
                )

            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    if idx not in tool_calls_data:
                        tool_calls_data[idx] = {
                            "id": tc.id or "",
                            "name": tc.function.name if tc.function and tc.function.name else "",
                            "arguments": "",
                        }
                    else:
                        if tc.id:
                            tool_calls_data[idx]["id"] = tc.id
                        if tc.function and tc.function.name:
                            tool_calls_data[idx]["name"] = tc.function.name

                    if tc.function and tc.function.arguments:
                        tool_calls_data[idx]["arguments"] += tc.function.arguments

        tool_calls = []
        for idx in sorted(tool_calls_data.keys()):
            data = tool_calls_data[idx]
            try:
                args = json.loads(data["arguments"]) if data["arguments"] else {}
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse tool call arguments: {data['arguments']}")
                args = {}
            tool_calls.append(ToolCall(
                id=data["id"],
                name=data["name"],
                input=args,
            ))

        yield LLMResponse(
            content=content,
            tool_calls=tool_calls,
            stop_reason=finish_reason,
            is_complete=True,
        )

    async def chat_stream(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system_prompt: str = "",
    ) -> AsyncIterator[LLMResponse]:
        """Stream LLM response with tool calling support."""
        try:
            if self.provider == LLMProvider.ANTHROPIC:
                async for response in self._anthropic_stream(messages, tools or [], system_prompt):
                    yield response
            else:
                async for response in self._openai_stream(messages, tools or [], system_prompt):
                    yield response

        except Exception as e:
            logger.error(f"LLM API error: {type(e).__name__}: {e}")

            error_msg = f"LLM API Error: {type(e).__name__}"
            error_str = str(e).lower()

            if "rate_limit" in error_str or "rate limit" in error_str:
                error_msg = "Rate limit exceeded. Please wait a moment and try again."
            elif "authentication" in error_str or "api_key" in error_str or "invalid_api_key" in error_str:
                error_msg = f"Authentication error. Check your {self.provider.value.upper()}_API_KEY."
            elif "timeout" in error_str:
                error_msg = "Request timed out. Please try again."
            elif "connection" in error_str:
                error_msg = "Connection error. Check your network and try again."

            yield LLMResponse(
                content=error_msg,
                tool_calls=[],
                stop_reason="error",
                is_complete=True,
            )

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system_prompt: str = "",
    ) -> LLMResponse:
        """Non-streaming LLM call (convenience wrapper)."""
        final_response = None
        async for response in self.chat_stream(messages, tools, system_prompt):
            final_response = response

        return final_response or LLMResponse(
            content="",
            tool_calls=[],
            stop_reason="error",
            is_complete=True,
        )

    def switch_provider(self, provider: LLMProvider | str, model: str | None = None) -> None:
        """Switch to a different LLM provider at runtime."""
        if isinstance(provider, str):
            provider = LLMProvider(provider)

        self.provider = provider
        self.model = model or self._get_default_model(provider)

        if provider == LLMProvider.ANTHROPIC:
            self._init_anthropic_client()
        else:
            self._init_openai_client()

        logger.info(f"Switched to {provider.value} with model {self.model}")

    def get_available_providers(self) -> list[LLMProvider]:
        """Return list of providers with valid API keys configured."""
        available = []
        if os.getenv("ANTHROPIC_API_KEY"):
            available.append(LLMProvider.ANTHROPIC)
        if os.getenv("OPENAI_API_KEY"):
            available.append(LLMProvider.OPENAI)
        return available

    def get_models_for_provider(self, provider: LLMProvider | None = None) -> list[str]:
        provider = provider or self.provider
        return self.AVAILABLE_MODELS.get(provider, [])

    @property
    def current_config(self) -> dict[str, str]:
        return {
            "provider": self.provider.value,
            "model": self.model,
        }

    async def check_connection(self) -> dict[str, Any]:
        """Test the API connection with a minimal request."""
        try:
            response = await self.chat(
                messages=[{"role": "user", "content": "Say 'ok'"}],
                tools=None,
                system_prompt="Respond with just 'ok'.",
            )

            if response.stop_reason == "error":
                return {"success": False, "error": response.content}

            return {"success": True, "provider": self.provider.value, "model": self.model}

        except Exception as e:
            return {"success": False, "error": str(e)}
