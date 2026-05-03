"""TDD: Stop hook test (RED phase first).

Stop hook is the most complex of the three:
  - stdin gives session_id + transcript_path (NOT the conversation itself)
  - Hook MUST open transcript_path (a JSONL file Claude Code writes per session)
  - Parse messages out of it
  - POST a /memorize call to memU-server with the conversation

Per testing-anti-patterns: real subprocess + real fake HTTP + real temp file
on disk (no mocked filesystem).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
HOOK_SCRIPT = PROJECT_ROOT / "hooks" / "stop.py"


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


def _write_transcript(messages: list[dict]) -> str:
    """Write a Claude Code-style JSONL transcript to a temp file. Returns the path."""
    fd, path = tempfile.mkstemp(suffix=".jsonl", prefix="test-transcript-", text=True)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")
    return path


def test_stop_hook_reads_transcript_and_posts_to_memorize(fake_memu_server) -> None:
    """The hook MUST open transcript_path, parse user/assistant messages,
    and POST them as a conversation to /api/v3/memory/memorize.
    """
    transcript = _write_transcript([
        {"type": "user", "message": {"role": "user", "content": "Remember I prefer MiniMax for chat work."}},
        {"type": "assistant", "message": {"role": "assistant", "content": "Got it — MiniMax for chat preference noted."}},
    ])

    try:
        stdin_payload = {
            "session_id": "stop-test-1",
            "transcript_path": transcript,
            "cwd": "/tmp",
            "hook_event_name": "Stop",
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

        posts = fake_memu_server.posts_to("/api/v3/memory/memorize")
        assert len(posts) == 1, f"expected 1 memorize POST, got {len(posts)}"

        body = posts[0]
        assert body["user_id"] == "willie"
        assert body["agent_id"] == "claude-code-rei"
        assert isinstance(body["conversation"], list)
        assert len(body["conversation"]) == 2
        # Each entry must have role + content (memU's expected shape)
        roles = [t.get("role") for t in body["conversation"]]
        assert roles == ["user", "assistant"]
        # First message text should match what we wrote
        first_text = body["conversation"][0].get("content", {}).get("text") or body["conversation"][0].get("content")
        assert "MiniMax" in str(first_text)
    finally:
        Path(transcript).unlink(missing_ok=True)


def test_stop_hook_handles_missing_transcript_file_gracefully(fake_memu_server) -> None:
    """If transcript_path doesn't exist, hook exits 0 without crashing.
    No memorize POST sent (nothing to memorize)."""
    stdin_payload = {
        "session_id": "stop-test-missing",
        "transcript_path": "/tmp/this-file-does-not-exist-12345.jsonl",
        "cwd": "/tmp",
        "hook_event_name": "Stop",
    }

    exit_code, stdout, stderr = _run_hook(
        stdin_payload,
        env_overrides={
            "MEMU_SERVER_URL": fake_memu_server.url,
            "MEMU_USER_ID": "willie",
            "MEMU_AGENT_ID": "claude-code-rei",
        },
    )

    assert exit_code == 0, f"hook exited non-zero on missing transcript. stderr:\n{stderr}"
    posts = fake_memu_server.posts_to("/api/v3/memory/memorize")
    assert len(posts) == 0, f"expected 0 memorize POSTs for missing transcript, got {len(posts)}"


def test_stop_hook_skips_memorize_for_empty_transcript(fake_memu_server) -> None:
    """Transcript exists but has no user/assistant messages (e.g. just system events).
    Hook exits 0 without posting (nothing meaningful to memorize)."""
    transcript = _write_transcript([
        {"type": "system", "subtype": "session_start"},
        {"type": "system", "subtype": "session_end"},
    ])

    try:
        stdin_payload = {
            "session_id": "stop-test-empty",
            "transcript_path": transcript,
            "cwd": "/tmp",
            "hook_event_name": "Stop",
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
        posts = fake_memu_server.posts_to("/api/v3/memory/memorize")
        assert len(posts) == 0, f"expected 0 memorize POSTs for empty transcript, got {len(posts)}"
    finally:
        Path(transcript).unlink(missing_ok=True)
