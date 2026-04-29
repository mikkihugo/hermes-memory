"""Hermes adapter for Singularity Memory.

This is the THIN adapter that lets a Hermes session use a running Singularity
Memory server as its memory backend. It implements Hermes' MemoryProvider
lifecycle (initialize / prefetch / sync_turn / handle_tool_call / shutdown) by
forwarding everything over HTTP+MCP to the standalone server.

There is no in-process retrieval engine here. The full memory engine lives at
src/singularity_memory_server/ in this repo (and runs as singularity-memory
serve, on port 8888 by default). The adapter either points at a running
server (config field `server_url`) or starts one in-process when
`server_embedded=True` is set.

Configuration is read from `$HERMES_HOME/singularity-memory.json`. The minimum
viable config is:

    {
      "server_url": "http://localhost:8888",
      "workspace": "default"
    }
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

try:
    from agent.memory_provider import MemoryProvider
except ImportError:
    class MemoryProvider:
        """Fallback when Hermes is not on sys.path (development / test)."""


CONFIG_FILENAME = "singularity-memory.json"
DEFAULT_SERVER_URL = "http://127.0.0.1:8888"
DEFAULT_WORKSPACE = "default"
DEFAULT_PREFETCH_LIMIT = 8
DEFAULT_CONTEXT_TOKENS = 1800

PROVIDER_NAME = "singularity_memory"
SYSTEM_PROMPT_BLOCK = (
    f"{PROVIDER_NAME} is active. Use it for durable cross-session recall about "
    "repos, infrastructure, decisions, incidents, and proven fixes. Retrieved "
    "memory is background context, not new user input. IMPORTANT: If the user "
    "says 'Magic Words' like 'Remember when...', 'We did this before...', or "
    "'Check our history...', you MUST call singularity_memory_search or "
    "singularity_memory_context to recall specific episodes."
)


def _load_config(hermes_home: str) -> dict[str, Any]:
    path = Path(hermes_home) / CONFIG_FILENAME
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load %s: %s", path, exc)
        return {}


def _http_request(url: str, *, method: str = "GET", body: dict | None = None,
                  api_key: str | None = None, timeout: float = 30.0) -> Any:
    """Synchronous JSON HTTP call. Returns parsed JSON or raises on HTTP error."""
    headers = {"Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


class SingularityMemoryProvider(MemoryProvider):
    """Hermes MemoryProvider that delegates to a Singularity Memory server."""

    def __init__(self) -> None:
        self._config: dict[str, Any] = {}
        self._server_url: str = DEFAULT_SERVER_URL
        self._workspace: str = DEFAULT_WORKSPACE
        self._api_key: str | None = None
        self._session_id: str = ""
        self._embedded_thread: threading.Thread | None = None

    @property
    def name(self) -> str:
        return PROVIDER_NAME

    def is_available(self) -> bool:
        try:
            from hermes_constants import get_hermes_home
            cfg = _load_config(str(get_hermes_home()))
        except Exception:
            return False
        return bool(cfg.get("server_url") or cfg.get("server_embedded"))

    def initialize(self, session_id: str, **kwargs) -> None:
        self._session_id = session_id
        hermes_home = kwargs.get("hermes_home", "")
        self._config = _load_config(hermes_home)
        self._server_url = (self._config.get("server_url") or DEFAULT_SERVER_URL).rstrip("/")
        self._workspace = self._config.get("workspace") or DEFAULT_WORKSPACE
        self._api_key = self._config.get("api_key") or self._config.get("server_api_key")

        if self._config.get("server_embedded"):
            self._start_embedded_server()

    def _start_embedded_server(self) -> None:
        """Spin up the standalone server in this process for users who don't run
        it as a separate daemon. Reads the same env vars as `singularity-memory
        serve`. No-op if a server already responds at the configured URL."""
        try:
            self.status()
            return
        except Exception:
            pass

        host = self._config.get("server_host", "127.0.0.1")
        port = int(self._config.get("server_port", 8888))
        os.environ.setdefault("SINGULARITY_HOST", host)
        os.environ.setdefault("SINGULARITY_PORT", str(port))
        os.environ.setdefault("SINGULARITY_MCP_ENABLED", "true")
        if "embedding_api_key" in self._config:
            os.environ.setdefault("SINGULARITY_EMBEDDINGS_OPENAI_API_KEY", self._config["embedding_api_key"])
        if "llm_api_key" in self._config:
            os.environ.setdefault("SINGULARITY_LLM_API_KEY", self._config["llm_api_key"])

        def _run() -> None:
            from singularity_memory_server.main import main as api_main
            api_main()

        self._embedded_thread = threading.Thread(target=_run, daemon=True, name="singularity-memory-embedded")
        self._embedded_thread.start()

        deadline = time.time() + 10.0
        while time.time() < deadline:
            try:
                self.status()
                return
            except Exception:
                time.sleep(0.2)
        logger.warning("Embedded singularity-memory server did not respond within 10s; tools may fail until it does.")

    # ── Hermes lifecycle hooks ────────────────────────────────────────

    def system_prompt_block(self) -> str:
        return SYSTEM_PROMPT_BLOCK

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        if not query.strip():
            return ""
        try:
            results = self._recall(query, limit=DEFAULT_PREFETCH_LIMIT)
        except Exception:
            logger.exception("prefetch failed")
            return ""
        return self._format_context(results, max_chars=DEFAULT_CONTEXT_TOKENS * 4)

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        return

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "") -> None:
        try:
            self._retain(
                content=f"User: {user_content}\nAssistant: {assistant_content}",
                context="Conversation turn",
            )
        except Exception:
            logger.exception("sync_turn failed")

    def shutdown(self) -> None:
        return

    def on_session_end(self, messages: list[dict[str, Any]]) -> None:
        return

    def on_pre_compress(self, messages: list[dict[str, Any]]) -> str:
        return ""

    def on_memory_write(self, action: str, target: str, content: str) -> None:
        return

    # ── Tool surface ──────────────────────────────────────────────────

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "singularity_memory_search",
                "description": "Search Singularity Memory for items relevant to the query.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 8},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "singularity_memory_context",
                "description": "Return formatted memory context under a token budget.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "token_budget": {"type": "integer", "minimum": 100, "maximum": 8000, "default": 1800},
                    },
                    "required": ["query"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "singularity_memory_store",
                "description": "Persist a durable fact in Singularity Memory.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "source_uri": {"type": "string"},
                    },
                    "required": ["content"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "singularity_memory_status",
                "description": "Report whether the Singularity Memory server is reachable.",
                "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        ]

    def handle_tool_call(self, tool_name: str, args: dict[str, Any], **kwargs) -> str:
        try:
            if tool_name == "singularity_memory_search":
                results = self._recall(args["query"], limit=int(args.get("limit", 8)))
                return json.dumps({"results": results})
            if tool_name == "singularity_memory_context":
                results = self._recall(args["query"], limit=8)
                budget = int(args.get("token_budget", DEFAULT_CONTEXT_TOKENS))
                return json.dumps({"context": self._format_context(results, max_chars=budget * 4)})
            if tool_name == "singularity_memory_store":
                memory_id = self._retain(content=args["content"], context=args.get("source_uri", ""))
                return json.dumps({"memory_item_id": memory_id, "stored": True})
            if tool_name == "singularity_memory_status":
                return json.dumps(self.status())
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
        except Exception as exc:
            logger.exception("Tool %s failed", tool_name)
            return json.dumps({"error": str(exc)})

    # ── Server-talking primitives ─────────────────────────────────────

    def _recall(self, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
        url = f"{self._server_url}/v1/{self._workspace}/banks/default/memories/recall"
        body = {"query": query, "limit": limit}
        payload = _http_request(url, method="POST", body=body, api_key=self._api_key)
        results = payload.get("results") or []
        return [
            {
                "memory_item_id": r.get("id"),
                "content": r.get("text", ""),
                "context": r.get("context"),
                "score": r.get("score"),
            }
            for r in results
        ]

    def _retain(self, *, content: str, context: str = "") -> str:
        url = f"{self._server_url}/v1/{self._workspace}/banks/default/memories/retain"
        body: dict[str, Any] = {"content": content}
        if context:
            body["context"] = context
        payload = _http_request(url, method="POST", body=body, api_key=self._api_key)
        return str(payload.get("memory_item_id") or payload.get("id") or "")

    def status(self) -> dict[str, Any]:
        url = f"{self._server_url}/v1/banks"
        _http_request(url, method="GET", api_key=self._api_key, timeout=2.0)
        return {"ok": True, "server_url": self._server_url, "workspace": self._workspace}

    def _format_context(self, results: list[dict[str, Any]], *, max_chars: int) -> str:
        if not results:
            return ""
        lines: list[str] = []
        used = 0
        for i, r in enumerate(results, start=1):
            line = f"[{i}] {r['content']}"
            if used + len(line) > max_chars:
                break
            lines.append(line)
            used += len(line) + 1
        return "\n".join(lines)

    # ── Hermes setup wizard ───────────────────────────────────────────

    def get_config_schema(self) -> list[dict[str, Any]]:
        return [
            {
                "key": "server_url",
                "description": "Singularity Memory server URL (e.g. http://localhost:8888). Required unless server_embedded is true.",
                "default": DEFAULT_SERVER_URL,
            },
            {
                "key": "workspace",
                "description": "Workspace identifier (memory bank scope).",
                "default": DEFAULT_WORKSPACE,
            },
            {
                "key": "server_api_key",
                "description": "Optional bearer token for the server (only needed when running with auth).",
                "default": "",
                "sensitive": True,
            },
            {
                "key": "server_embedded",
                "description": "Start an embedded server inside the Hermes process instead of connecting to a remote one.",
                "default": False,
            },
            {
                "key": "server_host",
                "description": "Bind host for the embedded server.",
                "default": "127.0.0.1",
            },
            {
                "key": "server_port",
                "description": "Bind port for the embedded server.",
                "default": 8888,
            },
            {
                "key": "embedding_api_key",
                "description": "Forwarded to the embedded server as SINGULARITY_EMBEDDINGS_OPENAI_API_KEY.",
                "default": "",
                "sensitive": True,
            },
            {
                "key": "llm_api_key",
                "description": "Forwarded to the embedded server as SINGULARITY_LLM_API_KEY.",
                "default": "",
                "sensitive": True,
            },
        ]

    def save_config(self, values: dict[str, Any], hermes_home: str) -> None:
        path = Path(hermes_home) / CONFIG_FILENAME
        current = _load_config(hermes_home)
        current.update(values)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(current, indent=2, sort_keys=True), encoding="utf-8")
