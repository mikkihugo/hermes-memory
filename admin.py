"""HermesMemoryAdmin - Admin operations for the Hindsight memory backend."""

import json
from typing import Any


class HermesMemoryAdmin:
    """Wrap the Hindsight HTTP client for admin operations.

    All methods use synchronous urllib because we may be called from sync contexts.
    """

    BASE = "http://127.0.0.1:8888/v1/default"

    def __init__(self, hindsight_client) -> None:
        self._hindsight = hindsight_client

    def _request(self, url: str, method: str = "GET", data: dict | None = None) -> dict[str, Any]:
        import urllib.request

        body = json.dumps(data).encode() if data is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    # ── Banks ──────────────────────────────────────────────────────────

    def create_bank(self, name: str, mission: str = "") -> str:
        """Create a memory bank. Returns bank_id."""
        result = self._request(
            f"{self.BASE}/banks/{name}",
            method="PUT",
            data={"name": name, "background": mission},
        )
        return result.get("bank_id", name)

    def delete_bank(self, bank_id: str) -> dict[str, Any]:
        """Delete a bank and all its memories."""
        return self._request(f"{self.BASE}/banks/{bank_id}", method="DELETE")

    def list_banks(self) -> list[dict[str, Any]]:
        """List all banks."""
        result = self._request(f"{self.BASE}/banks")
        return result.get("banks", [])

    def get_bank_config(self, bank_id: str) -> dict[str, Any]:
        """Get bank configuration."""
        return self._request(f"{self.BASE}/banks/{bank_id}/config")

    def set_bank_config(self, bank_id: str, **kwargs) -> dict[str, Any]:
        """Set bank configuration (mission, disposition, etc.)."""
        # Support both Python field names and env-var names
        return self._request(
            f"{self.BASE}/banks/{bank_id}/config",
            method="PATCH",
            data=kwargs,
        )

    # ── Stats ──────────────────────────────────────────────────────────

    def get_stats(self, bank_id: str) -> dict[str, Any]:
        """Get bank statistics."""
        return self._request(f"{self.BASE}/banks/{bank_id}/stats")

    # ── Browse ─────────────────────────────────────────────────────────

    def browse_memories(
        self,
        bank_id: str,
        limit: int = 20,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Browse memories in a bank."""
        return self._request(
            f"{self.BASE}/banks/{bank_id}/memories/list?limit={limit}&offset={offset}"
        )

    # ── Search Debug ────────────────────────────────────────────────────

    def search_debug(self, bank_id: str, query: str, show_trace: bool = True) -> dict[str, Any]:
        """Search with full retrieval trace showing all methods."""
        return self._request(
            f"{self.BASE}/banks/{bank_id}/memories/recall",
            method="POST",
            data={"query": query, "trace": show_trace},
        )

    # ── Entities ────────────────────────────────────────────────────────

    def get_entities(self, bank_id: str, limit: int = 50) -> dict[str, Any]:
        """Get entity graph for a bank."""
        return self._request(f"{self.BASE}/banks/{bank_id}/entities?limit={limit}")

    # ── Audit ──────────────────────────────────────────────────────────

    def get_audit_log(self, bank_id: str, limit: int = 50) -> dict[str, Any]:
        """Get audit log for a bank."""
        return self._request(f"{self.BASE}/banks/{bank_id}/audit-logs?limit={limit}")
