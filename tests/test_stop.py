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


def test_stop_hook_windows_transcript_to_last_exchange(fake_memu_server) -> None:
    """Block 2.7 — Stop fires per-turn, but Claude Code's transcript_path is
    project-cumulative (grows across --resume cycles). The hook MUST submit
    only the most recent user+assistant pair, not the entire history.

    Empirical bug 2026-05-02: real Stop fires sent ~2MB JSON files (the whole
    project transcript dating back to 2026-04-28) → MiniMax 400 context-overflow
    on every memorize task. memU library has no chunking; caller owns windowing.

    Asserts:
      - len(conversation) == 2 (last user+assistant pair only)
      - First entry is the MOST RECENT user message, not an old one
      - Second entry is the MOST RECENT assistant reply, not an old one
    """
    # Many old turn-pairs followed by the most recent exchange
    history: list[dict] = []
    for i in range(50):
        history.append({"type": "user", "message": {"role": "user", "content": f"old user msg {i}"}})
        history.append({"type": "assistant", "message": {"role": "assistant", "content": f"old assistant reply {i}"}})

    transcript = _write_transcript(history + [
        {"type": "user", "message": {"role": "user", "content": "MOST_RECENT_USER_MARKER"}},
        {"type": "assistant", "message": {"role": "assistant", "content": "MOST_RECENT_ASSISTANT_MARKER"}},
    ])

    try:
        stdin_payload = {
            "session_id": "stop-window-test",
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
        assert len(body["conversation"]) == 2, (
            f"expected only 2 messages (last user+assistant pair); "
            f"got {len(body['conversation'])} — likely sending full transcript "
            f"(this is the Block 2.7 bug)"
        )
        roles = [t.get("role") for t in body["conversation"]]
        assert roles == ["user", "assistant"], f"expected ['user','assistant'], got {roles}"
        last_user_text = body["conversation"][0].get("content", {}).get("text", "")
        last_assistant_text = body["conversation"][1].get("content", {}).get("text", "")
        assert "MOST_RECENT_USER_MARKER" in last_user_text, f"got: {last_user_text!r}"
        assert "MOST_RECENT_ASSISTANT_MARKER" in last_assistant_text, f"got: {last_assistant_text!r}"
    finally:
        Path(transcript).unlink(missing_ok=True)


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
