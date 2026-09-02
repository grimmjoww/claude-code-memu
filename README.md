# Claude Code + memU

**Persistent memory for Claude Code, plus a reusable memU MCP tool surface.**

This repository contains two related integrations:

1. A stdio MCP server that exposes memU memory operations to any MCP-compatible host.
2. Claude Code lifecycle hooks that recall useful memory before work and capture the latest exchange when a turn ends.

They solve slightly different problems and can be used independently. The MCP server gives an agent explicit memory tools. The hooks make recall and capture happen automatically around a Claude Code session.

## What is implemented

### memU MCP server

`server.py` wraps `memu.app.MemoryService` and exposes five tools:

| Tool | Purpose |
|---|---|
| `memorize` | Process a conversation into categorized memory |
| `retrieve` | Search memory with fast RAG retrieval or a deeper LLM method |
| `create_memory_item` | Add a known fact, event, skill, or preference directly |
| `list_categories` | Inspect the memory categories available for a scope |
| `clear_memory` | Delete scoped memory only when `confirmed=true` is supplied |

The service initializes lazily and can use local SQLite for a small setup or Postgres for a larger vchord-backed deployment.

### Claude Code lifecycle hooks

| Hook | Behavior |
|---|---|
| `SessionStart` | Retrieves broad context when a session starts or resumes |
| `UserPromptSubmit` | Retrieves memories related to the prompt that was just submitted |
| `Stop` | Reads Claude Code's JSONL transcript and sends the most recent user/assistant pair to memU |

The read hooks are deliberately soft-fail: a missing memory server should not crash Claude Code or block the user's prompt. The stop hook also exits cleanly when the transcript is missing, empty, or unreadable.

Claude Code's current hook lifecycle and configuration format are documented in the official [hooks reference](https://code.claude.com/docs/en/hooks).

## Architecture

```text
                         explicit memory tools
MCP-compatible host ───────── stdio ─────────▶ server.py ─▶ memU MemoryService
                                                        ├─ SQLite
                                                        └─ Postgres / vchord

                         automatic recall + capture
Claude Code ─▶ SessionStart / UserPromptSubmit / Stop hooks ─HTTP─▶ memU-server
```

The direct MCP server uses the memU Python library in-process. The Claude Code hooks currently expect a separate HTTP `memU-server` endpoint, configured with `MEMU_SERVER_URL`.

## Requirements

- Python 3.13 or newer
- `memu>=1.5.1`
- `mcp>=1.0.0`
- A compatible chat model and embedding endpoint for memU
- `memU-server` only when using the automatic Claude Code hooks

## Install the MCP server

```bash
git clone https://github.com/grimmjoww/claude-code-memu.git
cd claude-code-memu
python -m venv .venv
python -m pip install -e .
```

Run it directly:

```bash
grimmjoww-memu-mcp
```

Or register it with Claude Code as a local stdio server:

```bash
claude mcp add --transport stdio memu -- grimmjoww-memu-mcp
```

Then use `claude mcp list` or `/mcp` inside Claude Code to confirm that the server is connected.

## Configuration

### MCP server and memU library

| Variable | Default | Purpose |
|---|---|---|
| `MEMU_CHAT_PROVIDER` | `openai` | Chat-provider adapter used by memU |
| `MEMU_CHAT_BASE_URL` | MiniMax-compatible endpoint | Chat API base URL |
| `MEMU_CHAT_API_KEY` | provider environment fallback | Chat API key |
| `MEMU_CHAT_MODEL` | `MiniMax-M2.7-highspeed` | Chat model used for memory processing |
| `MEMU_EMBED_PROVIDER` | `openai` | Embedding-provider adapter |
| `MEMU_EMBED_BASE_URL` | `http://localhost:11434/v1` | Embedding API base URL |
| `MEMU_EMBED_MODEL` | `qwen3-embedding:0.6b` | Embedding model |
| `MEMU_DB_PROVIDER` | `sqlite` | `sqlite` or `postgres` |
| `MEMU_DB_PATH` | `~/.openclaw/memu/memu.db` | SQLite database path |
| `MEMU_DB_DSN` | local Postgres DSN | Postgres connection string |
| `MEMU_CATEGORIES_JSON` | built-in categories | Complete custom memory-category array |

Do not commit API keys or private database credentials to the repository.

### Claude Code hooks

| Variable | Default | Purpose |
|---|---|---|
| `MEMU_SERVER_URL` | `http://localhost:8000` | HTTP memU server used by the hook scripts |
| `MEMU_USER_ID` | empty | Optional user scope |
| `MEMU_AGENT_ID` | empty | Optional agent or runtime scope |

`run-hook.cmd` is a local Windows wrapper and currently contains machine-specific paths and scope values. Edit those values for your own installation before registering the commands in Claude Code's hook configuration. Use `/hooks` in Claude Code to inspect the active hook setup.

## Tests

The repository includes focused pytest coverage for the three lifecycle hooks:

```bash
python -m pip install pytest
python -m pytest -q
```

The tests cover memory injection, empty-input behavior, transcript parsing, scope handling, soft failures, and the stop hook's recent-turn capture behavior. The GitHub connector cannot execute this local suite, so this README does not claim a current passing count.

## Current status

**Experimental local integration, version 0.1.0.**

The MCP surface, configuration builder, hook scripts, and focused tests are present. This is not currently presented as a published PyPI package or a turnkey installer. The Windows hook wrapper also needs local path edits before use.

## Why this project matters

Most memory demos stop at “the agent can search a vector store.” This project works on the operational edges: when recall should happen, what should be captured, how memory is scoped between runtimes, how destructive actions are gated, and how the integration fails without taking the coding session down with it.

## License

MIT.
