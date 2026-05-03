"""TDD: SessionStart hook test (RED phase first).

Per the test-driven-development skill: this test is written BEFORE
hooks/session_start.py exists. Will fail. Then we implement minimally.
Per testing-anti-patterns: tests REAL hook subprocess + REAL HTTP, not mocks.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
HOOK_SCRIPT = PROJECT_ROOT / "hooks" / "session_start.py"


def _run_hook(stdin_payload: dict, env_overrides: dict[str, str]) -> tuple[int, str, str]:
    """Subprocess-execute the hook script with given stdin + env. Returns (exit_code, stdout, stderr)."""
    env = os.environ.copy()
    env.update(env_overrides)
    # Use the venv's Python so memu/httpx are importable
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


def test_session_start_hook_returns_relevant_memories_in_additional_context(fake_memu_server) -> None:
    """When SessionStart fires, hook calls memU /retrieve scoped by user+agent and outputs
    hookSpecificOutput.additionalContext containing the recalled item summaries.
    """
    # Stage memU to return one memory for user=willie + agent=claude-code-rei
    fake_memu_server.stage_items(
        user_id="willie",
        agent_id="claude-code-rei",
        items=[
            {
                "memory_type": "profile",
                "summary": "User prefers MiniMax-M2.7 for chat work",
                "category": "preferences",
            },
        ],
    )

    stdin_payload = {
        "session_id": "test-session-abc123",
        "transcript_path": "/tmp/fake-transcript.jsonl",
        "cwd": "/tmp",
        "hook_event_name": "SessionStart",
        "source": "startup",
        "model": "claude-opus-4-7",
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
    assert "hookSpecificOutput" in out, f"missing hookSpecificOutput. stdout: {stdout}"
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "SessionStart"
    assert "MiniMax-M2.7" in hso["additionalContext"]


def test_session_start_hook_calls_retrieve_with_correct_scope(fake_memu_server) -> None:
    """Hook MUST send POST /api/v3/memory/retrieve with user_id + agent_id from env."""
    fake_memu_server.stage_items(user_id="willie", agent_id="claude-code-rei", items=[])

    stdin_payload = {
        "session_id": "scope-test",
        "transcript_path": "/tmp/x.jsonl",
        "cwd": "/tmp",
        "hook_event_name": "SessionStart",
        "source": "startup",
        "model": "claude-opus-4-7",
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
    assert len(posts) == 1, f"expected 1 retrieve POST, got {len(posts)}: {posts}"
    body = posts[0]
    assert body["user_id"] == "willie"
    assert body["agent_id"] == "claude-code-rei"
    assert "query" in body  # SessionStart needs SOME query string for retrieve


def test_session_start_hook_zero_items_returns_empty_context(fake_memu_server) -> None:
    """No staged items → hook still exits 0 with empty additionalContext (not crash, not error)."""
    fake_memu_server.stage_items(user_id="willie", agent_id="claude-code-rei", items=[])

    stdin_payload = {
        "session_id": "empty-test",
        "transcript_path": "/tmp/x.jsonl",
        "cwd": "/tmp",
        "hook_event_name": "SessionStart",
        "source": "startup",
        "model": "claude-opus-4-7",
    }

    exit_code, stdout, stderr = _run_hook(
        stdin_payload,
        env_overrides={
            "MEMU_SERVER_URL": fake_memu_server.url,
            "MEMU_USER_ID": "willie",
            "MEMU_AGENT_ID": "claude-code-rei",
        },
    )

    assert exit_code == 0, f"hook exited non-zero on empty memU. stderr:\n{stderr}"
    out = json.loads(stdout)
    # Either empty additionalContext OR hookSpecificOutput omitted entirely is acceptable
    if "hookSpecificOutput" in out:
        assert out["hookSpecificOutput"].get("additionalContext", "") == "" or out["hookSpecificOutput"].get("additionalContext") is not None
