"""Pytest fixtures for hook script tests.

Per testing-anti-patterns skill: use a REAL in-process HTTP server (not mocks)
so tests verify actual hook → memU-server wire behavior. Mocking httpx would
test mock behavior, not real behavior.
"""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest


class _FakeMemUHandler(BaseHTTPRequestHandler):
    """Records every request the hook makes, returns canned responses."""

    # Class-level state because BaseHTTPRequestHandler instances are per-request.
    server: "FakeMemUServer"  # type: ignore[assignment]

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Silence default request logging during tests.
        pass

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 — http.server protocol
        self.server.requests.append({"method": "GET", "path": self.path, "body": None})
        if self.path in ("/api/health", "/api/v3/health"):
            self._send_json({"status": "ok"})
            return
        self._send_json({"detail": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802 — http.server protocol
        length = int(self.headers.get("Content-Length", "0"))
        body_raw = self.rfile.read(length) if length else b""
        body = json.loads(body_raw.decode("utf-8")) if body_raw else None
        self.server.requests.append({"method": "POST", "path": self.path, "body": body})

        # /api/v3/memory/retrieve — return canned items keyed by user_id+agent_id
        if self.path == "/api/v3/memory/retrieve":
            scoped_key = f"{(body or {}).get('user_id', '')}|{(body or {}).get('agent_id', '')}"
            items = self.server.canned_items.get(scoped_key, [])
            self._send_json(
                {
                    "status": "success",
                    "result": {
                        "needs_retrieval": True,
                        "original_query": (body or {}).get("query", ""),
                        "rewritten_query": (body or {}).get("query", ""),
                        "next_step_query": "",
                        "categories": [],
                        "items": items,
                        "resources": [],
                    },
                }
            )
            return

        # /api/v3/memory/memorize — accept and return PENDING (Stop hook fires this)
        if self.path == "/api/v3/memory/memorize":
            self._send_json(
                {
                    "status": "success",
                    "result": {"task_id": "memorize-test-fake", "status": "PENDING"},
                }
            )
            return

        self._send_json({"detail": f"unhandled path {self.path}"}, status=404)


class FakeMemUServer:
    """In-process HTTP fake of memU-server for hook tests."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.canned_items: dict[str, list[dict[str, Any]]] = {}
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.url: str = ""

    def start(self) -> None:
        # Bind to ephemeral port on loopback
        handler = _FakeMemUHandler
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        # Bind class-level attr so handler can reach back to us
        _FakeMemUHandler.server = self  # type: ignore[assignment]
        self._server.requests = self.requests  # type: ignore[attr-defined]
        self._server.canned_items = self.canned_items  # type: ignore[attr-defined]
        port = self._server.server_address[1]
        self.url = f"http://127.0.0.1:{port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def stage_items(self, *, user_id: str, agent_id: str, items: list[dict[str, Any]]) -> None:
        """Pre-stage canned items the fake server returns for a given scope."""
        self.canned_items[f"{user_id}|{agent_id}"] = items

    def posts_to(self, path: str) -> list[dict[str, Any]]:
        """Return all POST request bodies that hit a given path."""
        return [r["body"] for r in self.requests if r["method"] == "POST" and r["path"] == path]


@pytest.fixture()
def fake_memu_server() -> "FakeMemUServer":  # noqa: D401 — fixture
    """Spin up a fresh fake memU-server for each test, tear down after."""
    server = FakeMemUServer()
    server.start()
    try:
        yield server
    finally:
        server.stop()
