# Server engine: ports from the retired hand-written engine

All six features from the retired in-tree engine are now landed in
`src/singularity_memory_server/`. This file is the historical record of
what was ported and where.

| # | Feature | Schema | Method | Wiring | Endpoint / surface |
|---|---|:---:|:---:|:---:|:---:|
| 1 | embeddings_pending | n/a | ✅ `count_unembedded` | n/a (see note) | ✅ `GET /v1/default/banks/{id}/admin/embeddings-pending` |
| 2 | vector_enabled | n/a | ✅ `NoneEmbeddings` | ✅ retain gate | n/a |
| 3 | backfill_embeddings | n/a | ✅ method | ✅ admin CLI | ✅ `POST /admin/backfill-embeddings` |
| 4 | RRF lane weighting | n/a | ✅ `weights=` param | ✅ recall caller | ✅ env vars |
| 5 | two-tier rerank | n/a | ✅ `rerank_two_tier` | ✅ recall branch | ✅ env vars |
| 6 | helpfulness feedback | ✅ alembic | ✅ `record_feedback` | ✅ ranking boost | ✅ HTTP + MCP tool |

---

## Where each port lives

### #1 `embeddings_pending` count

- **Method**: `MemoryEngine.count_unembedded(bank_id=None)` →
  `engine/memory_engine.py`. Single SQL `COUNT(*) WHERE embedding IS NULL`.
- **HTTP**: `GET /v1/default/banks/{bank_id}/admin/embeddings-pending` in
  `api/http.py`. Returns `{bank_id, embeddings_pending}`.
- **CLI**: surfaced indirectly via the backfill command's logs (it logs
  the pending count before each batch).
- **Prometheus**: deliberately not wired as an OTel observable gauge.
  Bridging an async-DB-query into a sync OTel callback would require a
  fragile background loop; operators can scrape the HTTP endpoint with
  blackbox_exporter instead. See note in `metrics.py`.

### #2 `vector_enabled` opt-in

- **Config**: `vector_enabled: bool` in `SingularityConfig` (default `True`,
  env: `SINGULARITY_VECTOR_ENABLED`).
- **Provider class**: `NoneEmbeddings` in `engine/embeddings.py` —
  `provider_name="none"`, `encode()` returns empty vectors.
- **Factory**: `create_embeddings_from_env()` returns `NoneEmbeddings`
  when `embeddings_provider="none"` or when `vector_enabled=False`.
- **Retain gate**: `engine/retain/orchestrator.py:_extract_and_embed`
  skips `generate_embeddings_batch` and produces facts with
  `embedding=None` when `provider_name=="none"`. Embedding column is
  already nullable.

### #3 `backfill_embeddings`

- **Method**: `MemoryEngine.backfill_embeddings(bank_id, batch_size,
  max_batches)` in `engine/memory_engine.py`. Idempotent loop over
  `embedding IS NULL` rows. Per-row failures logged-and-skipped.
- **HTTP**: `POST /v1/default/banks/{bank_id}/admin/backfill-embeddings`
  in `api/http.py`. Body: `{batch_size?, max_batches?}`. Returns
  `{bank_id, processed}`.
- **CLI**: `singularity-memory-server admin backfill-embeddings
  [--bank ...] [--batch-size 32] [--max-batches N]` in `admin/cli.py`.
- **Auto-trigger**: not implemented. Operators run this manually after
  flipping `vector_enabled` on. Adding auto-on-startup would need
  throttling and idle detection — defer until real-world usage shows it
  matters.

### #4 RRF lane weighting

- **Function**: `reciprocal_rank_fusion(result_lists, k, weights=None)`
  in `engine/search/fusion.py`. Negative weights clamped to 0; `None`
  is the equal-weight baseline.
- **Config**: `rrf_vector_weight`, `rrf_lexical_weight`,
  `rrf_graph_weight`, `rrf_temporal_weight` in `SingularityConfig`
  (default `1.0`, env: `SINGULARITY_RRF_*_WEIGHT`).
- **Caller**: `engine/memory_engine.py` recall path reads the four
  weights from config and passes `weights=[w_vec, w_lex, w_grf, w_tmp]`
  to RRF.
- Sample: code search with `SINGULARITY_RRF_LEXICAL_WEIGHT=1.5`.

### #5 Two-tier reranking

- **Function**: `rerank_two_tier(query, candidates, fast, deep,
  fast_top_n, deep_top_n)` in `engine/search/reranking.py`. Falls
  back gracefully when either tier raises.
- **Config**: `rerank_fast_model`, `rerank_deep_model`, `rerank_top_n`
  (default 20), `rerank_deep_top_n` (default 4) in `SingularityConfig`.
  Empty model = tier disabled.
- **Recall branch**: `engine/memory_engine.py` constructs the deep
  cross-encoder when both `rerank_fast_model` and `rerank_deep_model`
  are non-empty (and not equal), then routes through `rerank_two_tier`.
  Falls back to single-tier `CrossEncoderReranker.rerank` otherwise or
  on construction failure.

### #6 Helpfulness feedback

- **Migration**: alembic revision
  `b2c3d4e5f6a7_add_helpfulness_feedback_to_memory_units` adds
  `helpful_count` and `unhelpful_count` (`INTEGER NOT NULL DEFAULT 0`)
  to `memory_units`. Idempotent up/down.
- **Method**: `MemoryEngine.record_feedback(memory_item_id, helpful)`
  in `engine/memory_engine.py`. Atomic `UPDATE ... RETURNING`.
- **HTTP**: `POST /v1/default/banks/{bank_id}/memories/{memory_id}/feedback`
  with `{helpful: bool}`. Returns post-increment counts.
- **MCP tool**: `memory_feedback(memory_item_id, helpful)` in
  `mcp_tools.py`. Registered by default.
- **Ranking**: `apply_combined_scoring` in `engine/search/reranking.py`
  applies a `feedback_boost = 1 + 0.05 * tanh((helpful - unhelpful) / 5)`
  multiplier alongside the existing recency/temporal/proof_count
  boosts. Bounded to roughly [0.95, 1.05] so a few thumbs don't
  dominate the cross-encoder score.

---

## Letta / MemGPT-style features (also landed)

Three additional features ported from the convergent design across Letta,
MemGPT, and Google's Always On Memory Agent.

### #7 Core memory blocks

Letta-style "always-in-context" facts (persona, user_profile, system_directives).
Distinct from archival memory: not searched, injected into every prompt by
the client adapter; edited by the agent via tool calls.

- **Migration**: `c3d4e5f6a7b8_add_core_memory_blocks` adds a
  `core_memory_blocks` table (bank_id, block_name, content, char_limit,
  description, created_at, updated_at).
- **Engine**: `MemoryEngine.{get_core_memory, core_memory_set,
  core_memory_append, core_memory_replace, core_memory_delete}`.
  All bounded by `char_limit` (default 2000) with a `truncated=True`
  signal so the agent knows to summarize.
- **HTTP**: `GET /v1/.../core-memory`, `PUT/PATCH/DELETE
  /v1/.../core-memory/{block_name}` (and `.../append`, `.../replace`).
- **MCP**: `core_memory_get / set / append / replace / delete` tools,
  registered by default.
- **Hermes adapter**: `prefetch()` now fetches core blocks before recall
  and prepends them in a `<core-memory>` envelope (with explicit
  "untrusted historical context" framing). Tool surface added:
  `singularity_core_memory_*` and `singularity_memory_summarize_offload`.

### #8 Pressure pager (`summarize_and_offload`)

MemGPT's working-memory loop: agent voluntarily compresses old turns to
free context space.

- **Engine**: `MemoryEngine.summarize_and_offload(bank_id, messages,
  target_chars)` — concatenates messages, truncates to roughly
  `target_chars` (head + tail with ellipsis), retains via the standard
  retain pipeline so the summary becomes searchable, returns
  `{memory_item_id, preview, compressed_chars, original_message_count}`.
- **HTTP**: `POST /v1/.../memories/summarize-and-offload`.
- **MCP**: `memory_summarize_and_offload` tool, registered by default.
- **Note**: current implementation uses structural compression
  (head+tail), not LLM summarization. LLM-driven version is a follow-up
  — drop in `llm_config.summarize(...)` call when ready.

### #9 Idle consolidation worker

Wraps the existing `run_consolidation_job` so it can be triggered
manually or on a schedule outside the retain pipeline (which only runs
consolidation reactively).

- **CLI**: `singularity-memory-server admin consolidate --bank <id>
  [--interval 60]`. Without `--interval`, runs once. With `--interval N`,
  loops with N-minute gaps until Ctrl-C — minimal viable cron-in-process.
  For real production scheduling use systemd timers / k8s CronJob calling
  the bare command repeatedly.

---

## Background workers (also landed)

A single `engine/background_workers.py` module owns three opt-in
coroutine tasks, started by `MemoryEngine.initialize()` and stopped
cleanly by `MemoryEngine.close()`.

### #10 Auto-backfill loop

- `BackgroundWorkers._auto_backfill_loop`: when `auto_backfill_enabled=True`,
  checks the cached unembedded-row count every
  `auto_backfill_interval_seconds` (default 300) and calls
  `backfill_embeddings` whenever pending > 0. Idempotent.
- Eliminates the manual `admin backfill-embeddings` step after flipping
  `vector_enabled=True` on an existing corpus.

### #11 Auto-consolidation loop

- `BackgroundWorkers._auto_consolidation_loop`: when
  `auto_consolidation_enabled=True`, iterates known banks every
  `auto_consolidation_interval_seconds` (default 3600) and runs
  `run_consolidation_job` on each. Banks with `enable_observations=False`
  short-circuit inside the consolidator, so this is safe to leave on.
- Replaces the need for external cron / k8s CronJob calling the
  `admin consolidate` command.

### #12 Cached unembedded count + OTel gauge

- `BackgroundWorkers._pending_count_loop`: refreshes
  `cached_unembedded_count` every `embeddings_pending_refresh_seconds`
  (default 60) via a single `count_unembedded` call.
- `MetricsCollector.set_memory_engine(engine)` registers an observable
  gauge `singularity_memory.embeddings.pending` whose callback yields
  the cached value (no async-from-sync hack required).
- Wired automatically at engine startup; replaces the
  "scrape the HTTP endpoint with blackbox_exporter" workaround.

### LLM-driven summarization for pressure pager

- `summarize_and_offload` now calls the configured LLM
  (`_consolidation_llm_config` → `_llm_config` fallback) with a
  pressure-pager system prompt. Falls back to structural head+tail
  truncation when the LLM provider is `none` or the call fails.
- No new config — reuses existing LLM credentials.

---

## Remaining follow-ups

- **Feedback signal tuning** — the `tanh / 5` saturation and `±5%`
  bound in apply_combined_scoring are conservative defaults. Once
  real-world feedback data is available, sweep these against held-out
  recall benchmarks.
- **Validate against real Postgres + vchord** — none of the engine
  ports have been run against a live database in development. Code
  compiles, signatures align, but the alembic migrations + retain/recall
  integration paths need a smoke test before we make confident
  retrieval-quality claims.
