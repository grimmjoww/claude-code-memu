"""TDD: UserPromptSubmit hook test (RED phase first).

Hook reads stdin payload, extracts the user's `prompt` field, queries memU
for memories relevant to THAT prompt (not a static query), emits
hookSpecificOutput.additionalContext.

Per testing-anti-patterns: real subprocess + real fake HTTP, no mocks.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
HOOK_SCRIPT = PROJECT_ROOT / "hooks" / "user_prompt.py"


def _run_hook(stdin_payload: dict, env_overrides: dict[str, str]) -> tuple[int, str, str]:
    env = os.environ.copy()
    env.update(env_overrides)
    proc = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input=json.dumps(stdin_payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_user_prompt_hook_uses_prompt_field_as_retrieve_query(fake_memu_server) -> None:
    """The hook MUST send the user's `prompt` text as the retrieve query
    (not a static placeholder like SessionStart's default).
    """
    fake_memu_server.stage_items(user_id="willie", agent_id="claude-code-rei", items=[])

    stdin_payload = {
        "session_id": "prompt-test-1",
        "transcript_path": "/tmp/x.jsonl",
        "cwd": "/tmp",
        "permission_mode": "default",
        "hook_event_name": "UserPromptSubmit",
        "prompt": "What is the vchord port status?",
    }

    _run_hook(
        stdin_payload,
        env_overrides={
            "MEMU_SERVER_URL": fake_memu_server.url,
            "MEMU_USER_ID": "willie",
            "MEMU_AGENT_ID": "claude-code-rei",
        },
    )

    posts = fake_memu_server.posts_to("/api/v3/memory/retrieve")
    assert len(posts) == 1, f"expected 1 retrieve POST, got {len(posts)}"
    assert posts[0]["query"] == "What is the vchord port status?"
    assert posts[0]["user_id"] == "willie"
    assert posts[0]["agent_id"] == "claude-code-rei"


def test_user_prompt_hook_returns_recalled_memories_in_additional_context(fake_memu_server) -> None:
    fake_memu_server.stage_items(
        user_id="willie",
        agent_id="claude-code-rei",
        items=[
            {
                "memory_type": "episodic",
                "summary": "vchord port shipped 2026-04-26 by Willie",
                "category": "knowledge",
            },
        ],
    )

    stdin_payload = {
        "session_id": "prompt-test-2",
        "transcript_path": "/tmp/x.jsonl",
        "cwd": "/tmp",
        "permission_mode": "default",
        "hook_event_name": "UserPromptSubmit",
        "prompt": "When did vchord ship?",
    }

    exit_code, stdout, stderr = _run_hook(
        stdin_payload,
        env_overrides={
            "MEMU_SERVER_URL": fake_memu_server.url,
            "MEMU_USER_ID": "willie",
            "MEMU_AGENT_ID": "claude-code-rei",
        },
    )

    assert exit_code == 0, f"hook exited non-zero. stderr:\n{stderr}"
    out = json.loads(stdout)
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "UserPromptSubmit"
    assert "2026-04-26" in hso["additionalContext"]


def test_user_prompt_hook_handles_empty_prompt_gracefully(fake_memu_server) -> None:
    """Empty prompt → hook still exits 0, doesn't crash, no retrieve POST sent
    (no point in querying memU for empty string).
    """
    fake_memu_server.stage_items(user_id="willie", agent_id="claude-code-rei", items=[])

    stdin_payload = {
        "session_id": "prompt-test-empty",
        "transcript_path": "/tmp/x.jsonl",
        "cwd": "/tmp",
        "permission_mode": "default",
        "hook_event_name": "UserPromptSubmit",
        "prompt": "",
    }

    exit_code, stdout, stderr = _run_hook(
        stdin_payload,
        env_overrides={
            "MEMU_SERVER_URL": fake_memu_server.url,
            "MEMU_USER_ID": "willie",
            "MEMU_AGENT_ID": "claude-code-rei",
        },
    )

    assert exit_code == 0, f"hook exited non-zero on empty prompt. stderr:\n{stderr}"
    posts = fake_memu_server.posts_to("/api/v3/memory/retrieve")
    assert len(posts) == 0, f"hook should not call retrieve for empty prompt; got {len(posts)} POSTs"
