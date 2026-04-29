# Server engine: backlog ports

Six features were validated in the (now-retired) hand-written engine that
used to live at `extensions/hermes/` and that we want to land in this server
when there's a real Postgres + vchord test environment. The Hermes adapter
under `extensions/hermes/` is now a thin HTTP client — none of these ports
gate it from working — but they're the difference between "memory server"
and "memory server that matches what users actually wanted from the
integrated plugin."

Ordered by risk, lowest first.

---

## 1. `embeddings_pending` metric

**Why**: visibility into how much of the corpus is vectorized. Critical when
`vector_enabled` toggles on and a backfill is running — users need to see
progress without tailing logs.

**Implementation sketch**:
- Add an observable gauge to `metrics.py:MetricsCollector` (sibling to the
  DB-pool gauges around line 549). Name: `singularity_memory.embeddings.pending`.
- Wire the gauge callback to `SELECT COUNT(*) FROM <items_table> WHERE embedding IS NULL`.
  Needs a DB pool reference passed into the collector (the pool ref already
  threads through `engine/storage`).
- Expose the same count via a top-level admin endpoint
  (`GET /v1/{tenant}/banks/{bank}/stats/embeddings_pending`) for clients
  that don't scrape Prometheus.
- Fast — single COUNT, indexed `WHERE embedding IS NULL` should be cheap
  on partial index, but consider adding a partial index if not already present.

**Risk**: low. No state changes, just an additional read path.

---

## 2. `vector_enabled` opt-in toggle (config-level dense lane gate)

**Why**: today every retain call generates an embedding. For users without
an embedding endpoint, or who want to start lexical-only and add dense
later, that's a hard requirement. Toggle lets dense be opt-in; auto-backfill
(below) makes it safe to flip on later.

**Implementation sketch**:
- Add `vector_enabled: bool` to `SingularityConfig` (`singularity_config.py`,
  near the other lane toggles; default `True` to preserve current behavior,
  but document `False` as the intended starter setting). Env var:
  `SINGULARITY_VECTOR_ENABLED`.
- Cleanest mechanism — add a `"none"` value to `SINGULARITY_EMBEDDINGS_PROVIDER`
  (parallel to existing `NoneLLM` in `engine/providers/none_llm.py`).
  Implementation: a new `NoneEmbeddings(Embeddings)` class in
  `engine/embeddings.py` that returns empty/zero vectors and a flag the retain
  pipeline can check.
- In `engine/retain/orchestrator.py:_extract_and_embed` (around line 357):
  if `vector_enabled` is False (or provider is None), skip the
  `generate_embeddings_batch` call and produce facts with `embedding=None`.
- Schema is already nullable on the embedding column — verified.
- In `engine/retain/embedding_processing.py:store_embeddings_for_facts`:
  no-op when embeddings list contains None / is empty.
- In recall: every code path that does a vector ANN scan must filter
  `WHERE embedding IS NOT NULL` (so partially-embedded corpora return what's
  ready) and skip entirely if `vector_enabled` is False.

**Risk**: medium. Touches the central retain pipeline and recall paths.
Needs a test that retain-and-recall round-trips with `vector_enabled=False`
on a vchord-Postgres backend.

---

## 3. `backfill_embeddings` admin command + auto-backfill on flip

**Why**: paired with #2. When a user enables dense after running for a
while, there are NULL-embedding rows that will be invisible to the vector
lane until they're embedded. Manual reembedding via SQL is brittle.

**Implementation sketch**:
- Add `MemoryEngine.backfill_embeddings(bank_id: str | None = None,
  batch_size: int = 32, max_batches: int | None = None) -> int` in
  `engine/memory_engine.py`. Loop:
  ```python
  while True:
      rows = SELECT id, content FROM <items> WHERE embedding IS NULL
              AND bank_id = ? ORDER BY created_at LIMIT batch_size
      if not rows: break
      batch_embed = embeddings_model.embed_batch([r.content for r in rows])
      UPDATE <items> SET embedding = ? WHERE id = ?  -- per row
  ```
- Idempotent: each call processes only NULL-embedding rows; safe to interrupt.
- Expose via admin CLI: `singularity-memory-server admin backfill-embeddings
  --bank <id> [--batch-size 32]` (sibling of existing admin commands in
  `admin/cli.py`).
- Optional auto-trigger: at server startup, if `vector_enabled` is True and
  pending count > 0, kick off backfill in a background task. Throttle so
  large corpora don't hammer the embedding endpoint.

**Risk**: medium. Long-running operation; needs careful handling of
embedding endpoint failures (skip-and-continue, not abort), API budget
awareness, and graceful interruption.

---

## 4. RRF lane weighting

**Why**: today the RRF fusion code in B treats every lane equally
(`1 / (k + rank)`). The retired engine had `lexical_weight`,
`vector_weight`, `graph_weight` knobs that let users bias the fusion when
their domain has a known preference (e.g. for code search, BM25 should
weight higher than vector).

**Implementation sketch**:
- Find B's RRF site — likely under `engine/search/` or wherever the
  multi-lane recall results are merged.
- Change the formula from `score += 1/(k+rank)` to
  `score += weight[lane] * 1/(k+rank)`.
- Add `lexical_weight`, `vector_weight`, `graph_weight` (default `1.0`) to
  `SingularityConfig`. Bank-level override via `bank_config` if the
  existing per-bank override path supports it.

**Risk**: low to medium — depends on how clean B's fusion code is. Test:
synthetic corpus where lexical and vector return disjoint top-Ks; verify
weighted fusion shifts the order as expected.

---

## 5. Two-tier reranking (fast → deep)

**Why**: B has cross-encoder support (`engine/cross_encoder.py:
LocalSTCrossEncoder`, `RemoteTEICrossEncoder`) but no orchestration that
runs a fast-rerank over many candidates and a deep-rerank over the
top-N. The retired engine ran Qwen3-0.6B over ~20 candidates and Qwen3-4B
over the top 4 — meaningful precision lift with bounded API cost.

**Implementation sketch**:
- Add config fields: `rerank_fast_model`, `rerank_deep_model`,
  `rerank_deep_top_n` (default 4). Env vars
  `SINGULARITY_RERANK_FAST_MODEL` etc.
- After retrieval, before returning results, run the fast reranker over the
  full candidate list, keep top `rerank_top_n` (e.g. 20), then run the deep
  reranker over the top `rerank_deep_top_n` (e.g. 4) and use deep scores
  for the final order; preserve fast-reranker order for the rest.
- Skip both stages cleanly when models aren't configured.

**Risk**: medium. New dependency on running two model endpoints. Failure of
either stage should fall back to the prior stage's order, not error.

---

## 6. Helpfulness feedback (alembic migration)

**Why**: per-memory-item up/down signals biasing future retrieval scores.
Lets the system learn from "this memory was useful for this query" without
retraining anything.

**Implementation sketch**:
- New alembic revision under `alembic/versions/`. Add `helpful_count: int
  NOT NULL DEFAULT 0` and `unhelpful_count: int NOT NULL DEFAULT 0` to the
  primary memory table (and `memory_units` if applicable).
- Add `record_feedback(memory_item_id, helpful: bool)` method on
  `MemoryEngine`.
- Expose endpoint:
  `POST /v1/{tenant}/banks/{bank}/memories/{id}/feedback {"helpful": true}`.
- Adjust retrieval scoring to incorporate the signal. Simple form:
  `score *= (1 + 0.1 * (helpful - unhelpful))` (clamped). More principled
  form: a separate weighted lane in RRF.
- Surface via MCP tool: `memory_feedback(memory_item_id, helpful)`.

**Risk**: highest of the six. Schema change in inherited code, multi-table
migration, retrieval ranking change, new endpoint. Needs:
- Migration tested against both fresh and pre-existing DBs.
- Default `0` counts so existing rows don't accidentally tank in ranking.
- Monotonicity tests for the scoring adjustment.

---

## Order of implementation

If picking these up in batches, recommended order: 1 → 4 → 2 → 3 → 5 → 6.
- Start with #1 (lowest risk, immediate observability win).
- #4 (lane weighting) is independent of the others and lets users tune
  retrieval before any pipeline changes.
- #2 + #3 (vector_enabled + backfill) ship together since one is half-useful
  without the other.
- #5 (two-tier rerank) is independent.
- #6 (feedback) last because it needs a migration plan and the other
  features may inform what feedback should bias.

Each is its own commit. Each requires a real Postgres + vchord environment
to validate. Don't try to land all six in one PR.
