"""Tests for the hermes-memory provider."""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from config import CONFIG_FILENAME  # noqa: E402
from provider import HermesMemoryProvider  # noqa: E402


def _write_provider_config(hermes_home: Path) -> None:
    """Write a provider config for tests."""
    storage_path = hermes_home / "memory-store.json"
    config_path = hermes_home / CONFIG_FILENAME
    config_path.write_text(
        json.dumps(
            {
                "context_tokens": 12,
                "dsn": f"file://{storage_path}",
                "workspace": "test-workspace",
            }
        ),
        encoding="utf-8",
    )


def _create_initialized_provider(hermes_home: Path) -> HermesMemoryProvider:
    """Return one initialized provider."""
    _write_provider_config(hermes_home)
    provider = HermesMemoryProvider()
    provider.initialize(session_id="session-1", hermes_home=str(hermes_home))
    return provider


def test_store_tool_returns_memory_item_id_when_content_is_persisted(tmp_path: Path) -> None:
    """The store tool should persist one explicit memory item."""
    provider = _create_initialized_provider(tmp_path)
    response = json.loads(
        provider.handle_tool_call(
            "hermes_memory_store",
            {
                "content": "The deployment rollback used the canary lane.",
                "source_uri": "note://deploy",
            },
        )
    )
    assert response["stored"] is True


def test_search_tool_returns_stored_memory_when_query_matches(tmp_path: Path) -> None:
    """The search tool should return previously stored memory."""
    provider = _create_initialized_provider(tmp_path)
    provider.handle_tool_call(
        "hermes_memory_store",
        {
            "content": "The database password rotates every 30 days.",
            "source_uri": "secret://rotation",
        },
    )
    response = json.loads(provider.handle_tool_call("hermes_memory_search", {"query": "password rotates"}))
    assert response["results"][0]["content"] == "The database password rotates every 30 days."


def test_context_tool_honors_token_budget_when_results_are_formatted(tmp_path: Path) -> None:
    """The context tool should trim output when the token budget is small."""
    provider = _create_initialized_provider(tmp_path)
    provider.handle_tool_call(
        "hermes_memory_store",
        {
            "content": "Alpha memory about deployment strategy and verification evidence.",
            "source_uri": "note://alpha",
        },
    )
    provider.handle_tool_call(
        "hermes_memory_store",
        {
            "content": "Beta memory about database incidents and recovery notes.",
            "source_uri": "note://beta",
        },
    )
    response = json.loads(provider.handle_tool_call("hermes_memory_context", {"query": "deployment database", "token_budget": 8}))
    assert response["context"].count("\n") == 0


def test_sync_turn_persists_completed_turn_into_searchable_memory(tmp_path: Path) -> None:
    """Completed turns should be searchable through the provider."""
    provider = _create_initialized_provider(tmp_path)
    provider.sync_turn(
        user_content="How did we fix the cron crash?",
        assistant_content="We increased the timeout and added retry logging.",
    )
    response = json.loads(provider.handle_tool_call("hermes_memory_search", {"query": "retry logging"}))
    assert "retry logging" in response["results"][0]["content"]


def test_session_end_stores_summary_as_searchable_memory(tmp_path: Path) -> None:
    """Session-end summaries should become searchable memory items."""
    provider = _create_initialized_provider(tmp_path)
    provider.on_session_end(
        [
            {"role": "user", "content": "The tunnel route points at the wrong service."},
            {"role": "assistant", "content": "We should swap the route to the webui service."},
        ]
    )
    response = json.loads(provider.handle_tool_call("hermes_memory_search", {"query": "wrong service"}))
    assert "Session summary:" in response["results"][0]["content"]


def test_queue_prefetch_makes_next_prefetch_return_cached_result(tmp_path: Path) -> None:
    """Background prefetch should cache the next context block."""
    provider = _create_initialized_provider(tmp_path)
    provider.handle_tool_call(
        "hermes_memory_store",
        {
            "content": "Portal traffic should route to the Hermes web UI service.",
            "source_uri": "note://portal",
        },
    )
    provider.queue_prefetch("portal traffic")
    if provider._prefetch_thread is not None:  # noqa: SLF001
        provider._prefetch_thread.join(timeout=5.0)  # noqa: SLF001
    context_block = provider.prefetch("portal traffic")
    assert "Portal traffic should route to the Hermes web UI service." in context_block
