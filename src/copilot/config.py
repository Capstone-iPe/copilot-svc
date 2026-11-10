"""Addresses the running copilot uses. The API key stays in the environment."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHAT_BASE_URL = "https://103.42.50.41:1032/v1"
CHAT_CA_CERT = ROOT / "vm06-ca.crt"
DEFAULT_MODEL = "Qwen/Qwen3-8B"
DEFAULT_MCP = "https://onb-k8ud.onrender.com/mcp"
DEFAULT_INDEX = ROOT / "index"


def chat_api_key() -> str:
    return os.environ.get("CHAT_API_KEY", "").strip()


def chat_model() -> str:
    return os.environ.get("CHAT_MODEL", DEFAULT_MODEL)


def mcp_url() -> str:
    return os.environ.get("ONB_MCP_URL", DEFAULT_MCP)
