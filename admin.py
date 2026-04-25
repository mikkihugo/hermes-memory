"""SingularityMemoryAdmin - Admin operations for the Singularity Memory backend."""

import json
from typing import Any


class SingularityMemoryAdmin:
    """Wrap the Singularity Memory HTTP client for admin operations.

    All methods use synchronous urllib because we may be called from sync contexts.
    Reads the base URL from the underlying client so it works whether the
    server is embedded in-process or running on a remote host.
    """

    def __init__(self, server_client) -> None:
        self._client = server_client
        self._base_url = getattr(server_client, "_base_url", "http://127.0.0.1:8888").rstrip("/")

    # ── Banks ──────────────────────────────────────────────────────────

    def create_bank(self, name: str, background: str = "") -> str:
        """Create a memory bank. Returns bank_id."""
        import urllib.request

        data = json.dumps({"name": name, "background": background}).encode()
        req = urllib.request.Request(
            f"{self._base_url}/v1/default/banks",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
        return result.get("bank_id", name)

    def delete_bank(self, bank_id: str) -> dict[str, Any]:
        """Delete a bank and all its memories."""
        import urllib.request

        req = urllib.request.Request(
            f"{self._base_url}/v1/default/banks/{bank_id}",
            method="DELETE",
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    def list_banks(self) -> list[dict[str, Any]]:
        """List all banks."""
        import urllib.request

        req = urllib.request.Request(f"{self._base_url}/v1/default/banks")
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
            return result.get("banks", [])

    def get_bank_config(self, bank_id: str) -> dict[str, Any]:
        """Get bank configuration."""
        import urllib.request

        req = urllib.request.Request(f"{self._base_url}/v1/default/banks/{bank_id}/config")
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    def set_bank_config(self, bank_id: str, **kwargs) -> dict[str, Any]:
        """Set bank configuration (mission, disposition, etc.)."""
        import urllib.request

        data = json.dumps(kwargs).encode()
        req = urllib.request.Request(
            f"{self._base_url}/v1/default/banks/{bank_id}/config",
            data=data,
            headers={"Content-Type": "application/json"},
            method="PATCH",
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    # ── Stats ──────────────────────────────────────────────────────────

    def get_stats(self, bank_id: str) -> dict[str, Any]:
        """Get bank statistics."""
        import urllib.request

        req = urllib.request.Request(f"{self._base_url}/v1/default/banks/{bank_id}/stats")
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    # ── Browse ─────────────────────────────────────────────────────────

    def browse_memories(
        self,
        bank_id: str,
        limit: int = 20,
        offset: int = 0,
        fact_type: str | None = None,
    ) -> dict[str, Any]:
        """Browse memories in a bank."""
        import urllib.request

        params = f"limit={limit}&offset={offset}"
        if fact_type:
            params += f"&type={fact_type}"
        req = urllib.request.Request(
            f"{self._base_url}/v1/default/banks/{bank_id}/memories/list?{params}"
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    # ── Search Debug ────────────────────────────────────────────────────

    def search_debug(self, bank_id: str, query: str, show_trace: bool = False) -> dict[str, Any]:
        """Search with full retrieval trace showing all methods."""
        import urllib.request

        req = urllib.request.Request(
            f"{self._base_url}/v1/default/banks/{bank_id}/memories/recall",
            data=json.dumps({"query": query, "trace": show_trace}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    # ── Entities ────────────────────────────────────────────────────────

    def get_entities(self, bank_id: str, limit: int = 50) -> dict[str, Any]:
        """Get entity graph for a bank."""
        import urllib.request

        req = urllib.request.Request(
            f"{self._base_url}/v1/default/banks/{bank_id}/entities?limit={limit}"
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    # ── Audit ──────────────────────────────────────────────────────────

    def get_audit_log(self, bank_id: str, limit: int = 50) -> dict[str, Any]:
        """Get audit log for a bank."""
        import urllib.request

        req = urllib.request.Request(
            f"{self._base_url}/v1/default/banks/{bank_id}/audit-logs?limit={limit}"
        )
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
