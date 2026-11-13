"""Addresses and keys the running copilot uses. Loaded from .env when present."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _path(name: str, default: Path) -> Path:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    path = Path(raw).expanduser()
    return path if path.is_absolute() else ROOT / path


def chat_api_key() -> str:
    return os.environ.get("CHAT_API_KEY", "").strip()


def chat_base_url() -> str:
    return os.environ.get("CHAT_BASE_URL", "https://103.42.50.41:1032/v1").strip()


def chat_ca_cert() -> Path:
    return _path("CHAT_CA_CERT", ROOT / "vm06-ca.crt")


def chat_model() -> str:
    return os.environ.get("CHAT_MODEL", "Qwen/Qwen3-8B").strip()


def mcp_url() -> str:
    return os.environ.get("ONB_MCP_URL", "https://onb-k8ud.onrender.com/mcp").strip()


def corpus_search_url() -> str:
    return os.environ.get("CORPUS_SEARCH_URL", "http://127.0.0.1:8081").strip()


def corpus_api_key() -> str:
    return os.environ.get("CORPUS_API_KEY", "").strip()


# Back-compat for imports that expect module-level names.
CHAT_BASE_URL = chat_base_url()
CHAT_CA_CERT = chat_ca_cert()
