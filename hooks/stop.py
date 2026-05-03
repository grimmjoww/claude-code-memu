#!/usr/bin/env python
"""Stop hook for Claude Code → memU integration.

Fires when Claude Code stops a session (clear / quit / compact). Reads the
session's transcript_path JSONL file from stdin payload, parses user +
assistant messages, posts them as a conversation to memU /memorize.

Why open the file ourselves: per Claude Code hook docs (verified 2026-05-02),
Stop hook receives ONLY {session_id, transcript_path, cwd, hook_event_name}
in stdin. The conversation transcript is NOT inlined — we must read it from
the file at transcript_path.

Soft-fail philosophy:
  - Missing transcript file → exit 0, no POST (nothing to memorize)
  - Empty / system-only transcript → exit 0, no POST
  - memU-server unreachable → exit 0 (already handled in _common.memorize_conversation)
  - Never crash Claude Code's stop sequence

Per rei_framing_separation.md: Stop hook WRITES to memU (memorize). The
content is automatically work-frame because the agent_id env var scopes us
to the work-Rei pool. The conversation text itself is what Claude Code
generated, in work-Rei voice (this is the work runtime). No re-framing
needed for same-pool writes.
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path
from typing import Any

# Sibling import — Claude Code subprocess sets sys.path[0] = hooks/ dir
from _common import (  # type: ignore[import-not-found]
    emit_hook_output,
    get_scope,
    memorize_conversation,
    read_stdin_payload,
)


def _extract_text(content: Any) -> str:
    """Pull text out of Claude Code's polymorphic message.content shapes.

    Possible shapes per Claude Code transcript format:
      - plain string: "hello"
      - list of content blocks: [{"type": "text", "text": "..."}, {"type": "tool_use", ...}]
      - dict with text field: {"text": "..."}
    """
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, dict):
        text = content.get("text")
        if isinstance(text, str):
            return text.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text")
                if isinstance(t, str):
                    parts.append(t)
        return "\n".join(parts).strip()
    return ""


def _parse_transcript(transcript_path: str) -> list[dict[str, Any]]:
    """Parse Claude Code JSONL transcript into a memU-shape conversation list.

    Returns: [{"role": "user"|"assistant", "content": {"text": "..."}, "created_at": "..."}]
    Skips system events, tool_use blocks (text-only memorization for v1).
    """
    p = Path(transcript_path)
    if not p.exists() or not p.is_file():
        return []

    conversation: list[dict[str, Any]] = []
    now_iso = _dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    try:
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(entry, dict):
                    continue

                entry_type = entry.get("type")
                if entry_type not in ("user", "assistant"):
                    # Skip system events, errors, etc.
                    continue

                msg = entry.get("message")
                if not isinstance(msg, dict):
                    continue

                role = msg.get("role")
                if role not in ("user", "assistant"):
                    continue

                text = _extract_text(msg.get("content"))
                if not text:
                    continue

                conversation.append(
                    {
                        "role": role,
                        "content": {"text": text},
                        "created_at": entry.get("timestamp") or now_iso,
                    }
                )
    except OSError:
        # File became unreadable mid-read — soft fail
        return []

    return conversation


def main() -> int:
    payload = read_stdin_payload()
    server_url, user_id, agent_id = get_scope()
    transcript_path = payload.get("transcript_path", "")

    conversation = _parse_transcript(transcript_path) if transcript_path else []

    if conversation:
        memorize_conversation(
            server_url=server_url,
            user_id=user_id,
            agent_id=agent_id,
            conversation=conversation,
        )
    # Stop hook output is OPTIONAL. We exit 0 silently to allow Claude to stop.
    # No additionalContext needed — memorize is fire-and-forget on this side.
    return 0


if __name__ == "__main__":
    sys.exit(main())
