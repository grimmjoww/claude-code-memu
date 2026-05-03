"""Shared helpers for SessionStart, UserPromptSubmit, Stop hooks.

Soft-fail philosophy: hooks should NEVER crash Claude Code. Network errors,
malformed payloads, missing env vars all return safe defaults rather than
raising. The agent loses memory enrichment for that turn but keeps working.

Per rei_framing_separation.md: this module is SHARED across hooks but the
HOOK that calls it is responsible for choosing the correct scope (user_id +
agent_id) per the framing rule.
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

import httpx

DEFAULT_SERVER_URL = "http://localhost:8000"
RETRIEVE_TIMEOUT_SECONDS = 15.0
MEMORIZE_TIMEOUT_SECONDS = 10.0


def read_stdin_payload() -> dict[str, Any]:
    """Parse Claude Code hook payload from stdin. Returns {} on empty/malformed."""
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def get_scope() -> tuple[str, str, str]:
    """Return (server_url, user_id, agent_id) from env. Empty strings on missing."""
    server_url = os.environ.get("MEMU_SERVER_URL", DEFAULT_SERVER_URL).rstrip("/")
    user_id = os.environ.get("MEMU_USER_ID", "")
    agent_id = os.environ.get("MEMU_AGENT_ID", "")
    return server_url, user_id, agent_id


def retrieve_memories(
    server_url: str,
    user_id: str,
    agent_id: str,
    query: str,
    skip_routing: bool = False,
) -> list[dict[str, Any]]:
    """POST /api/v3/memory/retrieve with PR #25 + agent_id-extension body shape.

    Soft-fail: returns [] on any HTTP error, timeout, or malformed response.
    """
    body = {
        "query": query,
        "user_id": user_id,
        "agent_id": agent_id,
        "skip_routing": skip_routing,
    }
    try:
        resp = httpx.post(
            f"{server_url}/api/v3/memory/retrieve",
            json=body,
            timeout=RETRIEVE_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
    except (httpx.HTTPError, httpx.TimeoutException):
        return []
    try:
        payload = resp.json()
    except json.JSONDecodeError:
        return []
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        return []
    items = result.get("items")
    return items if isinstance(items, list) else []


def memorize_conversation(
    server_url: str,
    user_id: str,
    agent_id: str,
    conversation: list[dict[str, Any]],
) -> dict[str, Any]:
    """POST /api/v3/memory/memorize with the conversation. Soft-fail on errors."""
    body = {
        "conversation": conversation,
        "user_id": user_id,
        "agent_id": agent_id,
    }
    try:
        resp = httpx.post(
            f"{server_url}/api/v3/memory/memorize",
            json=body,
            timeout=MEMORIZE_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
    except (httpx.HTTPError, httpx.TimeoutException):
        return {}
    try:
        payload = resp.json()
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def format_recalled_context(items: list[dict[str, Any]], header_label: str = "Relevant memories from prior sessions (work-frame):") -> str:
    """Wrap recalled memories in <recalled-memories> block with anti-injection header."""
    if not items:
        return ""
    lines = ["<recalled-memories>", header_label]
    for i, item in enumerate(items, 1):
        category = item.get("category") or item.get("memory_type") or "memory"
        summary = item.get("summary") or item.get("text") or ""
        lines.append(f"{i}. [{category}] {summary}")
    lines.append("</recalled-memories>")
    return "\n".join(lines)


def emit_hook_output(
    hook_event_name: str,
    additional_context: str = "",
    flat: bool = False,
) -> None:
    """Print Claude Code hook output JSON to stdout.

    flat=False (default): nests additionalContext under hookSpecificOutput
        (correct for SessionStart, UserPromptSubmit per docs).
    flat=True: puts additionalContext at top level
        (correct for Stop hook per docs).
    """
    if flat:
        output: dict[str, Any] = {
            "additionalContext": additional_context,
            "continue": True,
            "suppressOutput": False,
        }
    else:
        output = {
            "hookSpecificOutput": {
                "hookEventName": hook_event_name,
                "additionalContext": additional_context,
            },
            "continue": True,
            "suppressOutput": False,
        }
    print(json.dumps(output))
