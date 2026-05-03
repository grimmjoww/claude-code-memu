#!/usr/bin/env python
"""UserPromptSubmit hook for Claude Code → memU integration.

Reads the user's prompt from stdin, queries memU-server for memories
relevant to THAT prompt (not a static query like SessionStart uses), emits
hookSpecificOutput with additionalContext for the model.

Soft-fail philosophy: never crash Claude Code. Network errors return empty
context. Empty prompts skip the retrieve entirely (no point querying memU
for nothing).

Per rei_framing_separation.md: this hook only READS. Per agent_id env var,
scoped to one pool. Cross-pool reads are allowed; this hook reads from the
work-Rei pool by default.
"""
from __future__ import annotations

import sys

# Sibling import — hooks/ is sys.path[0] when Claude Code subprocess runs us.
from _common import (  # type: ignore[import-not-found]
    emit_hook_output,
    format_recalled_context,
    get_scope,
    read_stdin_payload,
    retrieve_memories,
)


def main() -> int:
    payload = read_stdin_payload()
    server_url, user_id, agent_id = get_scope()
    hook_event_name = payload.get("hook_event_name", "UserPromptSubmit")
    prompt = (payload.get("prompt") or "").strip()

    if not prompt:
        # Empty prompt → skip retrieve entirely. Emit minimal output.
        emit_hook_output(
            hook_event_name=hook_event_name,
            additional_context="",
            flat=False,
        )
        return 0

    items = retrieve_memories(
        server_url=server_url,
        user_id=user_id,
        agent_id=agent_id,
        query=prompt,
    )
    context = format_recalled_context(items)
    emit_hook_output(hook_event_name=hook_event_name, additional_context=context, flat=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
