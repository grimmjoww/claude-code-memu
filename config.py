"""Build memU MemoryService kwargs from environment variables.

Defaults: SQLite (single file under ~/.openclaw/memu/memu.db), MiniMax-M2.7 for chat,
Ollama qwen3-embedding for embeddings. Override any of it via env.

Switch to Postgres for vchord-backed scale by setting:
    MEMU_DB_PROVIDER=postgres
    MEMU_DB_DSN=postgresql://postgres@localhost:5433/memu
"""

import json
import os
from pathlib import Path
from typing import Any


def build_service_kwargs() -> dict[str, Any]:
    """Build the kwargs passed to memu.app.MemoryService(**kwargs)."""
    return {
        "llm_profiles": _build_llm_profiles(),
        "database_config": _build_database_config(),
        "memorize_config": _build_memorize_config(),
    }


def _build_llm_profiles() -> dict[str, dict[str, Any]]:
    chat = {
        "provider": os.getenv("MEMU_CHAT_PROVIDER", "openai"),
        "base_url": os.getenv("MEMU_CHAT_BASE_URL", "https://api.minimax.io/anthropic/"),
        "api_key": (
            os.getenv("MEMU_CHAT_API_KEY")
            or os.getenv("MINIMAX_API_KEY")
            or os.getenv("OPENAI_API_KEY", "")
        ),
        "chat_model": os.getenv("MEMU_CHAT_MODEL", "MiniMax-M2.7-highspeed"),
        "client_backend": os.getenv("MEMU_CHAT_CLIENT_BACKEND", "sdk"),
    }
    embed = {
        "provider": os.getenv("MEMU_EMBED_PROVIDER", "openai"),
        "base_url": os.getenv("MEMU_EMBED_BASE_URL", "http://localhost:11434/v1"),
        "api_key": os.getenv("MEMU_EMBED_API_KEY", "ollama"),
        "embed_model": os.getenv("MEMU_EMBED_MODEL", "qwen3-embedding:0.6b"),
    }
    return {"default": chat, "embedding": embed}


def _build_database_config() -> dict[str, Any]:
    provider = os.getenv("MEMU_DB_PROVIDER", "sqlite").lower()
    if provider == "postgres":
        dsn = os.getenv(
            "MEMU_DB_DSN", "postgresql://postgres@localhost:5433/memu"
        )
        return {"metadata_store": {"provider": "postgres", "dsn": dsn}}

    default_path = Path.home() / ".openclaw" / "memu" / "memu.db"
    sqlite_path = Path(os.getenv("MEMU_DB_PATH", str(default_path)))
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    posix = sqlite_path.as_posix()
    return {"metadata_store": {"provider": "sqlite", "dsn": f"sqlite:///{posix}"}}


def _build_memorize_config() -> dict[str, Any]:
    """Default memory categories tuned for an AI-companion runtime.

    Override the entire list by setting MEMU_CATEGORIES_JSON to a JSON array.
    """
    custom = os.getenv("MEMU_CATEGORIES_JSON")
    if custom:
        return {"memory_categories": json.loads(custom)}

    return {
        "memory_categories": [
            {
                "name": "preferences",
                "description": (
                    "Communication style, topic interests, working hours, tone "
                    "preferences, and other stable user attributes."
                ),
            },
            {
                "name": "relationships",
                "description": (
                    "Important people, contacts, ongoing interactions, family / "
                    "partner mentions, and the user's social context."
                ),
            },
            {
                "name": "knowledge",
                "description": (
                    "Domain expertise, learned facts, technical topics the user "
                    "works on, and reference material they care about."
                ),
            },
            {
                "name": "context",
                "description": (
                    "Recent conversations, pending tasks, current focus areas, "
                    "and short-horizon situational awareness."
                ),
            },
            {
                "name": "skills",
                "description": (
                    "Procedural how-to knowledge and workflows the user has "
                    "demonstrated or asked the assistant to learn."
                ),
            },
        ]
    }
