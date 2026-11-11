"""Consumer adapters. Vanilla returns Reply. Each adapter renders it."""

from copilot.adapters.base import Adapter
from copilot.adapters.cli import CliAdapter
from copilot.adapters.replay import ReplayAdapter
from copilot.adapters.web import WebAdapter

__all__ = ["Adapter", "CliAdapter", "ReplayAdapter", "WebAdapter"]
