"""Background workers running alongside the MemoryEngine.

Three coroutine tasks, all opt-in via SingularityConfig flags, all started
together by `BackgroundWorkers.start(engine)` and gracefully shut down by
`stop()`. They share one infrastructure to keep startup/shutdown ordering
predictable.

1. **Auto-backfill** — when `auto_backfill_enabled=True` and the engine has
   memory_units rows with NULL embedding, run `backfill_embeddings` in a
   loop (with `auto_backfill_interval_seconds` between passes). Lets users
   flip `vector_enabled` on with an existing corpus and have dense recall
   recover automatically without a manual CLI invocation.

2. **Auto-consolidation** — when `auto_consolidation_enabled=True`, call
   `run_consolidation_job` for each known bank periodically. Sleeptime
   reorganization without external scheduling. Defaults are conservative
   (every 60 minutes) — production schedules should set their own.

3. **Pending-count refresh** — periodically updates a cached count of
   `embedding IS NULL` rows on the engine. The OpenTelemetry observable
   gauge in `metrics.py` reads the cached value, avoiding the
   sync-callback-vs-async-DB problem. Cheap (one COUNT per refresh, every
   `embeddings_pending_refresh_seconds`).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .memory_engine import MemoryEngine

logger = logging.getLogger(__name__)


class BackgroundWorkers:
    """Owns the auto-backfill / auto-consolidation / pending-count tasks.

    Stateless except for the running task handles and the cached pending count.
    Safe to construct without starting; calls to `start()` are idempotent.
    """

    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []
        self._stopping = asyncio.Event()
        self._cached_unembedded_count: int = 0
        self._engine: "MemoryEngine | None" = None

    @property
    def cached_unembedded_count(self) -> int:
        """Last observed count of memory_units rows where embedding IS NULL.

        Refreshed periodically by `_pending_count_loop` when auto-backfill or
        the metrics gauge are enabled. Returns 0 if no refresh has run yet.
        """
        return self._cached_unembedded_count

    def start(self, engine: "MemoryEngine") -> None:
        """Spin up enabled workers. Idempotent — repeat calls do nothing."""
        if self._tasks:
            return
        self._engine = engine
        cfg = getattr(engine, "_config", None)

        backfill_enabled = bool(getattr(cfg, "auto_backfill_enabled", False))
        consolidation_enabled = bool(getattr(cfg, "auto_consolidation_enabled", False))
        pending_refresh_seconds = int(getattr(cfg, "embeddings_pending_refresh_seconds", 60))

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            logger.debug("background workers: no running event loop; deferring start")
            return

        # Pending-count refresh: useful both for the metrics gauge AND for
        # auto-backfill's "should we run another pass?" check. Always start
        # when either path needs it.
        if backfill_enabled or pending_refresh_seconds > 0:
            self._tasks.append(loop.create_task(
                self._pending_count_loop(refresh_seconds=pending_refresh_seconds),
                name="singularity_memory.pending_count",
            ))

        if backfill_enabled:
            self._tasks.append(loop.create_task(
                self._auto_backfill_loop(),
                name="singularity_memory.auto_backfill",
            ))

        if consolidation_enabled:
            self._tasks.append(loop.create_task(
                self._auto_consolidation_loop(),
                name="singularity_memory.auto_consolidation",
            ))

        if self._tasks:
            logger.info(
                "background workers started: backfill=%s consolidation=%s pending_refresh=%ss",
                backfill_enabled, consolidation_enabled, pending_refresh_seconds,
            )

    async def stop(self) -> None:
        """Cancel all running tasks and wait for them to settle."""
        if not self._tasks:
            return
        self._stopping.set()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        self._stopping.clear()

    # ── Workers ──────────────────────────────────────────────────────────

    async def _pending_count_loop(self, *, refresh_seconds: int) -> None:
        """Refresh the cached `embedding IS NULL` count every `refresh_seconds`.

        Read by `cached_unembedded_count` (used by the metrics gauge) and by
        `_auto_backfill_loop` to decide whether to run another pass.
        """
        engine = self._engine
        if engine is None:
            return
        # Run an initial refresh quickly so the cached value isn't 0 for the
        # first scrape interval.
        try:
            self._cached_unembedded_count = await engine.count_unembedded()
        except Exception:
            logger.exception("pending count loop: initial refresh failed")

        while not self._stopping.is_set():
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=max(5, refresh_seconds))
                return  # _stopping was set
            except asyncio.TimeoutError:
                pass
            try:
                self._cached_unembedded_count = await engine.count_unembedded()
            except Exception:
                logger.exception("pending count loop: refresh failed")

    async def _auto_backfill_loop(self) -> None:
        """Run `backfill_embeddings` whenever pending count > 0.

        Sleeps `auto_backfill_interval_seconds` between passes. Fully
        idempotent — backfill_embeddings only acts on NULL-embedding rows so
        there's no harm in running it on a stable corpus.
        """
        engine = self._engine
        if engine is None:
            return
        cfg = getattr(engine, "_config", None)
        interval = int(getattr(cfg, "auto_backfill_interval_seconds", 300))
        batch_size = int(getattr(cfg, "embedding_backfill_batch_size", 32))

        while not self._stopping.is_set():
            try:
                pending = self._cached_unembedded_count
                if pending > 0:
                    logger.info("auto_backfill: %d rows pending; running batch", pending)
                    try:
                        processed = await engine.backfill_embeddings(batch_size=batch_size)
                        logger.info("auto_backfill: processed %d rows", processed)
                    except Exception:
                        logger.exception("auto_backfill: backfill_embeddings failed")
            except Exception:
                logger.exception("auto_backfill: tick failed")

            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=max(5, interval))
                return  # _stopping was set
            except asyncio.TimeoutError:
                continue

    async def _auto_consolidation_loop(self) -> None:
        """Run `run_consolidation_job` for each known bank periodically.

        Banks are discovered via `engine.get_banks()` (or equivalent). Each
        run respects the bank's own consolidation enable flag — banks with
        `enable_observations=False` will short-circuit inside the consolidator.
        """
        engine = self._engine
        if engine is None:
            return
        cfg = getattr(engine, "_config", None)
        interval = int(getattr(cfg, "auto_consolidation_interval_seconds", 3600))

        while not self._stopping.is_set():
            try:
                bank_ids = await self._list_bank_ids(engine)
                for bank_id in bank_ids:
                    if self._stopping.is_set():
                        return
                    try:
                        from .consolidation.consolidator import run_consolidation_job
                        from ..models import RequestContext

                        result = await run_consolidation_job(
                            memory_engine=engine,
                            bank_id=bank_id,
                            request_context=RequestContext(),
                        )
                        logger.info("auto_consolidation(%s): %s", bank_id, result.get("status", "ok") if isinstance(result, dict) else "ran")
                    except Exception:
                        logger.exception("auto_consolidation(%s) failed", bank_id)
            except Exception:
                logger.exception("auto_consolidation: tick failed")

            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=max(60, interval))
                return  # _stopping was set
            except asyncio.TimeoutError:
                continue

    async def _list_bank_ids(self, engine: "MemoryEngine") -> list[str]:
        """Best-effort list of banks to consolidate. Falls back to ['default']
        when the engine doesn't surface a bank-list method."""
        for attr in ("list_banks", "get_banks", "list_bank_ids"):
            fn = getattr(engine, attr, None)
            if fn is None:
                continue
            try:
                result = await fn()
            except Exception:
                continue
            if isinstance(result, list):
                ids: list[str] = []
                for item in result:
                    if isinstance(item, str):
                        ids.append(item)
                    elif isinstance(item, dict) and "id" in item:
                        ids.append(str(item["id"]))
                    elif hasattr(item, "id"):
                        ids.append(str(getattr(item, "id")))
                if ids:
                    return ids
        return ["default"]
