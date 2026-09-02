# claude-code-memu

> Claude Code lifecycle hooks plus a stdio MCP server for persistent memU-backed memory.

This repository gives Claude Code two complementary memory paths:

1. **Automatic lifecycle memory** — hooks recall relevant context at session start and before a user prompt, then capture the latest completed exchange when the session stops.
2. **Explicit MCP memory tools** — an agent can store, retrieve, inspect, or clear scoped memory through a standard stdio MCP server.

## Status

**Development integration, version 0.1.0.** The repository contains working implementation code and hook tests, but it is not presented as a published or SLA-backed package.

## Architecture

```text
Claude Code
   │
   ├── SessionStart hook ────────▶ static relevance query
   ├── UserPromptSubmit hook ────▶ prompt-specific retrieval
   ├── Stop hook ────────────────▶ capture latest user/assistant pair
   └── MCP client ───────────────▶ explicit memory tools
                                      │
                                      ▼
                                  memU service
                              SQLite or Postgres
```

The hook path talks to `memU-server` over HTTP. The standalone MCP server instantiates `memu.app.MemoryService` directly and exposes memory operations over stdio.

## Lifecycle behavior

### `hooks/session_start.py`

Runs a broad “what is relevant right now” query and injects the recalled summaries as additional context. It is read-only and soft-fails when the memory server is unavailable.

### `hooks/user_prompt.py`

Uses the current user prompt as the retrieval query. Empty prompts skip the network call. Retrieval errors return empty context instead of interrupting Claude Code.

### `hooks/stop.py`

Reads Claude Code's JSONL transcript path, extracts user and assistant text, and sends only the latest pair to the memory service. Limiting capture to the newest pair avoids repeatedly sending a project-cumulative transcript after resume or compaction.

## MCP tools

The stdio server exposes:

| Tool | Purpose |
|---|---|
| `memorize` | Process a conversation through memU's extraction and categorization pipeline. |
| `retrieve` | Search memory with fast RAG retrieval or a deeper LLM-assisted method. |
| `create_memory_item` | Add a known memory item directly. |
| `list_categories` | Inspect available memory categories for a scope. |
| `clear_memory` | Delete scoped memory only when `confirmed=true` is supplied. |

## Configuration

The direct MCP service is configured with environment variables. Defaults currently include:

- SQLite under `~/.openclaw/memu/memu.db`
- an OpenAI-compatible chat endpoint
- an Ollama-compatible embedding endpoint at `http://localhost:11434/v1`
- `qwen3-embedding:0.6b` as the default embedding model

For Postgres:

```powershell
$env:MEMU_DB_PROVIDER = "postgres"
$env:MEMU_DB_DSN = "postgresql://postgres@localhost:5433/memu"
```

Hook scoping uses:

```powershell
$env:MEMU_SERVER_URL = "http://localhost:8000"
$env:MEMU_USER_ID = "example-user"
$env:MEMU_AGENT_ID = "work-agent"
```

Use separate identifiers when multiple users or agent roles must not share the same default memory pool.

## Install for development

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -e .
pip install pytest
```

Start the stdio MCP server through the installed command:

```bash
grimmjoww-memu-mcp
```

Register that command in the MCP configuration for the client you use. Configure Claude Code hooks to execute the scripts under `hooks/` through `run-hook.cmd` or the equivalent Python command for your environment.

## Tests

The hook tests use a real in-process HTTP server rather than replacing the network client with a mock. That verifies the request paths and payload boundary between the hooks and a memU-compatible server.

```bash
python -m pytest tests -q
```

The test suite covers session-start recall, prompt-specific recall, stop-hook transcript parsing and latest-pair capture, user/agent scoping, empty prompts, empty transcripts, and missing transcript files. The shared HTTP helper also implements soft-failure behavior for network, timeout, and malformed-response conditions; those particular error paths are not directly exercised by the current tests.

## Portfolio notes

This repository demonstrates:

- Claude Code lifecycle-hook integration;
- persistent memory retrieval and capture;
- scoped user/agent memory pools;
- soft-failure behavior that does not break the host agent;
- explicit destructive-operation confirmation;
- real HTTP-boundary tests;
- a standard MCP tool surface alongside automatic hooks.

The project was developed through an AI-assisted engineering workflow directed by **Willie Stewart / Phantom Horizon Studios**, including architecture decisions, implementation direction, test requirements, integration diagnosis, and revision against observed behavior.

## Known cleanup boundary

Some internal module comments and default filesystem paths still reflect the project's earlier OpenClaw-oriented prototype. The current repository adds Claude Code hooks on top of that memory server. Future cleanup should normalize naming and defaults without breaking existing local configurations.

## License

MIT.
