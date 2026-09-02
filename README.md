# Claude Code + memU

**Status: Prototype / active development.** This repository is not presented as a published, production-ready package.

Claude Code sessions are useful while they are running, but the context that matters can disappear between sessions or become difficult to retrieve when a project grows. This project connects Claude Code to a memU memory backend through two surfaces:

1. a standard stdio MCP server for direct memory tools; and
2. lifecycle hooks that recall relevant context before work and capture the latest exchange when a session stops.

## What It Does

The MCP server exposes five memory operations:

- `memorize` — process a conversation into memories
- `retrieve` — search memory using RAG or deeper LLM retrieval
- `create_memory_item` — add a known memory directly
- `list_categories` — inspect the available memory categories
- `clear_memory` — remove scoped memory only when `confirmed=true`

The server lazily initializes one memU `MemoryService` instance and guards initialization with an async lock. Conversation memorization uses a temporary JSON file because the memU API expects a resource path; the file is removed after processing.

## Claude Code Lifecycle Hooks

### `SessionStart`

`hooks/session_start.py` asks memU for context that is broadly relevant at the beginning of a session and returns it to Claude Code as additional context. It is read-only and soft-fails when the memory service is unavailable.

### `UserPromptSubmit`

`hooks/user_prompt.py` searches memory using the user’s current prompt instead of a static query. Empty prompts skip retrieval, and network failures return empty context rather than interrupting Claude Code.

### `Stop`

`hooks/stop.py` reads Claude Code’s JSONL transcript, extracts user and assistant text, and sends only the most recent exchange to memU. Limiting capture to the latest pair prevents cumulative transcripts from growing into an unbounded memorization payload. Missing files, empty transcripts, malformed lines, and service failures are handled as soft failures so Claude Code can stop normally.

## Architecture

```text
Claude Code
   │
   ├── SessionStart ───────┐
   ├── UserPromptSubmit ───┼──▶ memU server / retrieval
   └── Stop ───────────────┘          │
                                      ▼
                               persistent memory

Any MCP-compatible client
   │
   └── stdio MCP ─────────────▶ server.py ──▶ memU MemoryService
```

Memory can be scoped by `user_id` and `agent_id` so separate agents or working contexts do not need to share one undifferentiated pool.

## Storage and Model Configuration

Configuration is built from environment variables in `config.py`.

Default behavior:

- SQLite metadata store under the user profile
- Ollama-compatible embedding endpoint
- `qwen3-embedding:0.6b` as the default embedding model
- configurable OpenAI-compatible chat endpoint
- memory categories for preferences, relationships, knowledge, context, and skills

PostgreSQL can be selected with `MEMU_DB_PROVIDER=postgres` and `MEMU_DB_DSN`. Chat, embedding, storage, user, agent, and category settings are all environment-configurable.

Never commit API keys or database credentials. Supply them through environment variables in the runtime that launches the MCP server and hooks.

## Development Install

Requires Python 3.13 or newer.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e .
```

The installed console entry point is:

```text
grimmjoww-memu-mcp
```

## Testing

The repository includes focused tests for:

- session-start recall and context emission
- prompt-specific recall
- stop-hook transcript parsing and capture
- empty input and malformed transcript handling
- soft-failure behavior when services or files are unavailable

The test files are under `tests/` and mirror the three lifecycle hooks.

## Current Limitations

- The package and setup flow are still being refined.
- The MCP module retains some older OpenClaw-oriented comments that should be treated as implementation history, not the current product positioning.
- Stop-hook capture intentionally stores text only; tool-use blocks are skipped in the current version.
- This repository documents a prototype integration, not a hosted memory service or guaranteed deployment.

## My Role and Workflow

I directed the integration from requirements through implementation and verification: defining the memory behavior, separating read and write responsibilities across lifecycle hooks, scoping memory by user and agent, limiting cumulative transcript capture, reviewing repository changes, testing failure paths, and correcting the workflow when observed behavior did not match the intended design.

The project was built through an AI-assisted engineering workflow with human review of architecture, diffs, tests, and runtime behavior.

## Provenance and License

This project integrates the external `memU` and `mcp` Python packages. Their code and licenses remain with their respective maintainers.

The integration code in this repository is licensed under MIT as declared in `pyproject.toml`.
