# Server engine: backlog ports

Status of the six features that landed in the (now-retired) hand-written
engine and want a real Postgres + vchord test environment to land here
safely. Each section flags what's in code today vs still pending.

---

## 1. `embeddings_pending` metric

**Core method**: ✅ in code — `MemoryEngine.count_unembedded(bank_id=None) -> int`
in `engine/memory_engine.py`. Single SQL count. Safe to call.

**Pending**: prometheus observable gauge in `metrics.py`. Wiring it requires
threading the `MemoryEngine` (or its DB pool) into the metrics collector,
which is a non-trivial refactor of how `MetricsCollector` is constructed.
Verify the simplest path is to register the gauge in
`MemoryEngine.__init__` rather than in the standalone metrics module.

---

## 2. `vector_enabled` opt-in toggle

**Core code**: ✅ in code.
- `vector_enabled: bool` field added to `SingularityConfig` (default `True`
  to preserve current behavior).
- `NoneEmbeddings(Embeddings)` class added in `engine/embeddings.py`.
- `create_embeddings_from_env()` returns `NoneEmbeddings` when provider is
  `none` or when `vector_enabled=False`.
- `engine/retain/orchestrator.py:_extract_and_embed` skips
  `generate_embeddings_batch` and produces `embedding=None` when the
  configured provider's `provider_name == "none"`. Downstream paths must
  tolerate `None`; the embedding column is already nullable.

**Pending**: real-world validation against vchord-backed Postgres that:
- INSERTing a row with `embedding=None` doesn't error (column is nullable
  per schema, but the storage code path needs verification).
- Vector recall with NULL rows in the table returns sensible top-K
  (relies on pgvector's `<=>` returning NULL, which sorts last; this is
  the documented behavior but worth a smoke test).

---

## 3. `backfill_embeddings` admin command

**Core code**: ✅ in code.
- `MemoryEngine.backfill_embeddings(bank_id, batch_size, max_batches)` in
  `engine/memory_engine.py`. Idempotent loop over `embedding IS NULL`
  rows. Skips bad rows rather than aborting.
- Admin CLI subcommand: `singularity-memory-server admin
  backfill-embeddings [--bank ...] [--batch-size 32] [--max-batches N]`
  in `admin/cli.py`.

**Pending**: optional auto-trigger at server startup (when
`vector_enabled=True` and `count_unembedded > 0`, kick off backfill in a
background task with throttling). Defer until real-world usage tells us
whether auto-backfill is wanted.

---

## 4. RRF lane weighting

**Core code**: ✅ fully in code.
- `reciprocal_rank_fusion(result_lists, k, weights=None)` in
  `engine/search/fusion.py` accepts an optional per-lane weight list.
  Negative weights are clamped to 0; `None` preserves the equal-weight
  baseline behavior.
- `SingularityConfig` exposes `rrf_vector_weight`,
  `rrf_lexical_weight`, `rrf_graph_weight`, `rrf_temporal_weight` (all
  default `1.0`).
- Caller in `engine/memory_engine.py` reads the four weights from config
  and passes `weights=[w_vec, w_lex, w_grf, w_tmp]` to RRF.

**Pending**: nothing, this port is complete. Sample env tuning:
`SINGULARITY_RRF_LEXICAL_WEIGHT=1.5` for code-heavy workloads.

---

## 5. Two-tier reranking (fast → deep)

**Core code**: ✅ orchestrator in code.
- `rerank_two_tier(query, candidates, fast, deep, fast_top_n,
  deep_top_n)` in `engine/search/reranking.py`. Runs fast over all,
  keeps top fast_top_n, runs deep over deep_top_n, returns
  `[deep_scored_head, fast_scored_tail]`. Falls back to single-tier
  output if either tier raises.
- Config fields: `rerank_fast_model`, `rerank_deep_model`, `rerank_top_n`
  (default 20), `rerank_deep_top_n` (default 4). Empty model strings
  disable that tier.

**Pending**: wire the orchestrator into the recall pipeline. The current
`CrossEncoderReranker` invocation site needs a config-driven branch:
when both `rerank_fast_model` and `rerank_deep_model` are non-empty,
call `rerank_two_tier`; otherwise fall back to single-tier
`CrossEncoderReranker.rerank`. Trivial branching, kept out of this batch
to avoid blind edits to the recall hot path.

---

## 6. Helpfulness feedback

**Core code**: ✅ migration + method in code.
- Alembic revision
  `b2c3d4e5f6a7_add_helpfulness_feedback_to_memory_units` adds
  `helpful_count INTEGER NOT NULL DEFAULT 0` and `unhelpful_count` to
  `memory_units`. Idempotent up/down.
- `MemoryEngine.record_feedback(memory_item_id, helpful: bool) -> dict`
  in `engine/memory_engine.py`. Atomic increment via UPDATE…RETURNING.

**Pending**:
1. HTTP endpoint:
   `POST /v1/{tenant}/banks/{bank}/memories/{id}/feedback {"helpful": true}`
   wired in `api/http.py`. Trivial route definition.
2. MCP tool: `memory_feedback(memory_item_id, helpful)` exposed in
   `mcp_tools.py`.
3. Retrieval ranking that uses `helpful_count - unhelpful_count` to
   bias scores. Suggested: add a small additive boost to the RRF score
   (`rrf_score *= 1 + 0.05 * (helpful - unhelpful)`, clamped to a
   reasonable range like `[0.5, 1.5]`). Requires touching the recall
   path; deferred to its own commit alongside benchmarks of how big the
   bias should be.

---

## What's done in code today (this commit)

| # | Feature | Migration / data | Method | Wiring | Endpoint |
|---|---|:---:|:---:|:---:|:---:|
| 1 | embeddings_pending metric | n/a | ✅ | ❌ gauge | ❌ |
| 2 | vector_enabled toggle | n/a | ✅ | ✅ retain | n/a |
| 3 | backfill_embeddings | n/a | ✅ | ✅ CLI | ❌ HTTP |
| 4 | RRF lane weighting | n/a | ✅ | ✅ recall | n/a |
| 5 | two-tier rerank | n/a | ✅ | ❌ recall | n/a |
| 6 | helpfulness feedback | ✅ alembic | ✅ | ❌ ranking | ❌ |

Remaining wiring is small and isolated; landing it requires a real
Postgres + vchord environment to verify the integration path doesn't
regress existing recall behavior.
