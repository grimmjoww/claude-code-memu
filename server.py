"""OpenClaw memU memory MCP server.

Exposes the memU library's MemoryService over stdio MCP so OpenClaw plugins
and agents can use memU as their memory backend without any additional HTTP
service in between.

Register with OpenClaw:

    openclaw mcp set memu "{\"command\":\"python\",\"args\":[\"G:/projects/grimmjoww-memu-mcp/server.py\"]}"

Then restart the gateway visibly. The CLI's hot-reload sometimes leaves the
gateway session locked, so a kill-and-relaunch is the reliable path.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server import NotificationOptions, Server
from mcp.server.models import InitializationOptions

from memu.app import MemoryService

from config import build_service_kwargs

logger = logging.getLogger("grimmjoww-memu-mcp")

server = Server("grimmjoww-memu-mcp")
_service: MemoryService | None = None
_service_lock = asyncio.Lock()


async def get_service() -> MemoryService:
    """Lazy-init MemoryService. Single instance, guarded by lock."""
    global _service
    if _service is not None:
        return _service
    async with _service_lock:
        if _service is None:
            kwargs = build_service_kwargs()
            _service = MemoryService(**kwargs)
            logger.info("MemoryService initialized")
    return _service


@server.list_tools()
async def handle_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="memorize",
            description=(
                "Store a conversation as memory. memU's continuous-learning "
                "pipeline extracts facts/preferences/skills, auto-categorizes "
                "them, and cross-links related items."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "conversation": {
                        "type": "array",
                        "description": (
                            "List of message turns. Each turn must have "
                            "'role' and 'content' string fields."
                        ),
                        "items": {
                            "type": "object",
                            "required": ["role", "content"],
                            "properties": {
                                "role": {
                                    "type": "string",
                                    "enum": ["user", "assistant", "system"],
                                },
                                "content": {"type": "string"},
                            },
                        },
                    },
                    "user_id": {
                        "type": "string",
                        "description": "User the memory is scoped to.",
                    },
                    "agent_id": {
                        "type": "string",
                        "description": (
                            "Optional agent the memory is scoped to."
                        ),
                    },
                },
                "required": ["conversation", "user_id"],
            },
        ),
        types.Tool(
            name="retrieve",
            description=(
                "Search memory using a natural-language query. method='rag' "
                "is fast (embedding-based, milliseconds). method='llm' is "
                "deeper but slower."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Natural language query.",
                    },
                    "user_id": {"type": "string"},
                    "agent_id": {"type": "string"},
                    "method": {
                        "type": "string",
                        "enum": ["rag", "llm"],
                        "default": "rag",
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="create_memory_item",
            description=(
                "Inject a single memory item directly. Useful for "
                "bootstrapping known user facts without going through "
                "conversation processing."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "memory_content": {
                        "type": "string",
                        "description": "The fact or preference to remember.",
                    },
                    "memory_type": {
                        "type": "string",
                        "default": "profile",
                        "description": (
                            "Memory type: 'profile' (user attribute), "
                            "'episodic' (event), 'semantic' (fact), or "
                            "'procedural' (skill)."
                        ),
                    },
                    "memory_categories": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Categories to file under.",
                    },
                },
                "required": ["memory_content"],
            },
        ),
        types.Tool(
            name="list_categories",
            description="List all memory categories (auto-organized topics).",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "agent_id": {"type": "string"},
                },
            },
        ),
        types.Tool(
            name="clear_memory",
            description=(
                "DESTRUCTIVE: clear memories scoped to user/agent. Requires "
                "explicit 'confirmed': true to proceed."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "agent_id": {"type": "string"},
                    "confirmed": {
                        "type": "boolean",
                        "description": (
                            "Must be true to actually delete. Safety guard "
                            "against accidental wipes."
                        ),
                    },
                },
                "required": ["confirmed"],
            },
        ),
    ]


def _build_where(arguments: dict[str, Any]) -> dict[str, Any] | None:
    where: dict[str, Any] = {}
    if "user_id" in arguments and arguments["user_id"]:
        where["user_id"] = arguments["user_id"]
    if "agent_id" in arguments and arguments["agent_id"]:
        where["agent_id"] = arguments["agent_id"]
    return where or None


def _text_result(payload: Any) -> list[types.TextContent]:
    return [
        types.TextContent(
            type="text",
            text=json.dumps(payload, default=str, ensure_ascii=False),
        )
    ]


@server.call_tool()
async def handle_call_tool(
    name: str, arguments: dict[str, Any]
) -> list[types.TextContent]:
    service = await get_service()

    if name == "memorize":
        # memU.memorize() expects a file path; serialize the conversation to a
        # temp file, then clean up after the await returns.
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
            encoding="utf-8",
        ) as f:
            json.dump(arguments["conversation"], f, ensure_ascii=False)
            tmp_path = f.name
        try:
            user = {"user_id": arguments["user_id"]}
            agent_id = arguments.get("agent_id")
            if agent_id:
                user["agent_id"] = agent_id
            result = await service.memorize(
                resource_url=tmp_path,
                modality="conversation",
                user=user,
            )
            return _text_result(result)
        finally:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                logger.warning("Could not clean up temp file %s", tmp_path)

    if name == "retrieve":
        result = await service.retrieve(
            queries=[
                {"role": "user", "content": {"text": arguments["query"]}}
            ],
            where=_build_where(arguments),
            method=arguments.get("method", "rag"),
        )
        return _text_result(result)

    if name == "create_memory_item":
        result = await service.create_memory_item(
            memory_type=arguments.get("memory_type", "profile"),
            memory_content=arguments["memory_content"],
            memory_categories=arguments.get("memory_categories", []),
        )
        return _text_result(result)

    if name == "list_categories":
        result = await service.list_memory_categories(
            where=_build_where(arguments),
        )
        return _text_result(result)

    if name == "clear_memory":
        if not arguments.get("confirmed"):
            return _text_result(
                {
                    "error": (
                        "clear_memory requires confirmed=true. Refusing to "
                        "delete without explicit confirmation."
                    )
                }
            )
        result = await service.clear_memory(where=_build_where(arguments))
        return _text_result(result)

    raise ValueError(f"Unknown tool: {name}")


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="grimmjoww-memu-mcp",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


def run() -> None:
    """Console-script entry point."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
