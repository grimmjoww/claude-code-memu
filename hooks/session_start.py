#!/usr/bin/env python
"""SessionStart hook for Claude Code → memU integration.

Reads SessionStart payload from stdin, queries memU-server for relevant
memories scoped to (MEMU_USER_ID, MEMU_AGENT_ID), emits hookSpecificOutput
with additionalContext containing the recalled item summaries.

Soft-fail: never crashes Claude Code. Network/HTTP errors return empty context.

Env vars (all optional with safe defaults):
    MEMU_SERVER_URL  — base URL of memU-server (default http://localhost:8000)
    MEMU_USER_ID     — scope user_id (defaults to "" → unscoped retrieve)
    MEMU_AGENT_ID    — scope agent_id (Work-Rei vs Wife-Rei separation)

Per rei_framing_separation.md: hook only READS. Writes are forbidden here
(memorize happens in stop.py, with framing applied per agent_id).
"""
from __future__ import annotations

import sys

# Sibling import — when this script is run directly (as Claude Code hooks do),
# sys.path[0] is the hooks/ directory itself, so _common.py is importable as a
# top-level module. Avoids needing the project root on PYTHONPATH.
from _common import (  # type: ignore[import-not-found]
    emit_hook_output,
    format_recalled_context,
    get_scope,
    read_stdin_payload,
    retrieve_memories,
)

DEFAULT_QUERY = "what's relevant about the user right now"


def main() -> int:
    payload = read_stdin_payload()
    server_url, user_id, agent_id = get_scope()
    hook_event_name = payload.get("hook_event_name", "SessionStart")

    items = retrieve_memories(
        server_url=server_url,
        user_id=user_id,
        agent_id=agent_id,
        query=DEFAULT_QUERY,
    )
    context = format_recalled_context(items)
    emit_hook_output(hook_event_name=hook_event_name, additional_context=context, flat=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
