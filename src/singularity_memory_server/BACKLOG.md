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

### #13 Team-memory secret scanner + write-time guard

Borrowed from Claude Code's `src/services/teamMemorySync/secretScanner.ts`
+ `teamMemSecretGuard.ts`. We're a SHARED memory backend across many
agents; without this, an agent can persist an API key into a bank that
gets surfaced to other agents/users on recall. Real security gap.

**Implementation sketch**:
- New `engine/secret_scanner.py` module with a curated gitleaks-style
  regex set. Patterns to cover: AWS (`AKIA...`), GCP (`AIza...`), Azure
  AD, Anthropic (`sk-ant-api-03-...`), OpenAI (`sk-...`), HuggingFace,
  GitHub PATs (`ghp_`, `github_pat_`), DigitalOcean (`dop_v1_`,
  `doo_v1_`), generic high-entropy tokens.
- Hook point: `MemoryEngine.retain` and `MemoryEngine.core_memory_set
  / core_memory_append`. Two modes via config:
  - `secret_scan_mode = "block"` (default): reject the write with the
    matched label list.
  - `secret_scan_mode = "redact"`: replace the matched span with
    `[REDACTED:<label>]` and continue.
- Surface the matched label in the API response so the client can
  surface a clear error to the user.
- Make the regex set extensible via env or config so operators can add
  org-specific patterns.

**Risk**: low. No schema change. Hook is in retain — adding it doesn't
disturb recall.

### #14 Tool-context-aware retrieval filter

Borrowed from Claude Code's `findRelevantMemories.ts` system prompt
("if a list of recently-used tools is provided, do not select memories
that are usage reference or API documentation for those tools"). When
the agent is actively using tool X, surfacing how-to-use-X memories is
noise — gotchas for X are still valuable.

**Implementation sketch**:
- Add an optional `tool_context: list[str]` parameter to recall.
- Memory items can carry an optional `tool_refs: list[str]` and
  `memory_kind: "usage_doc" | "gotcha" | "fact" | ...` (extends
  existing fact_type taxonomy).
- Recall path filters out items where
  `memory_kind == "usage_doc" AND tool_refs ∩ tool_context != ∅`.
  Items with `memory_kind == "gotcha"` referencing the same tools get
  a small ranking boost (they matter EXACTLY when the tool is in use).
- Pure metadata filter — no LLM call.

**Risk**: low-medium. Schema change (alembic migration adding two
nullable columns to `memory_units`) but no behavioral changes for
existing rows (which leave both fields NULL → filter never fires).

### #15 End-of-turn extraction with dedup-by-inspection (opt-in)

Borrowed from Claude Code's `services/extractMemories/`. Replaces blind
`retain(every_turn_text)` with an LLM-driven extraction that looks at
recent messages, checks against existing memories in this bank, and
writes only fresh facts. Higher memory quality, bounded cost.

**Implementation sketch**:
- New `MemoryEngine.extract_and_retain(bank_id, messages,
  recent_memory_count=20)` method. Two-step LLM call:
  1. List recent memory headers from the bank (cheap SQL, no embedding).
  2. Send the agent a prompt: "Here are the recent messages and the
     existing memory headers. Return a JSON list of new facts to save,
     or an empty list. Update an existing fact in place if a duplicate
     would be created."
  3. Apply the writes.
- Off by default (config: `extract_memories_enabled: bool = False`).
  Operators who want it pay the per-turn LLM cost.
- HTTP/MCP surface: the existing `sync_turn`/`retain` paths can opt
  into extraction mode via a request flag, or operators can change the
  default at config level.

**Risk**: medium. Adds a new LLM call path; failures should silently
fall back to the existing `retain` behavior. Doesn't touch retrieval.

### Why we DON'T port

For posterity, the patterns we examined and rejected as poor fits for
a multi-client memory backend:

- **`MEMORY.md` always-loaded entrypoint with caps** — their
  human-readable index of topic files. Our `core_memory_blocks` does
  the same job in a structured shape. Different surface, equivalent
  function; double-implementing would create two truths.
- **DreamTask forked-agent runtime** — only works when one agent owns
  the memory directory and can fork a sub-agent against the same
  toolset. Doesn't generalize to a server with many concurrent clients,
  none of which "own" the corpus. Our consolidation is server-driven
  via `run_consolidation_job` + the autoDream-borrowed scheduling
  discipline; that's the right shape for our use case.
- **`agentMemorySnapshot`** — single-agent warm-start. We track per-bank
  state in DB.
- **LLM-as-retrieval (Sonnet picks ≤5 from headers)** — expensive per
  query, doesn't beat our BM25+vector+RRF at scale. Acceptable when
  query volume is low and the corpus is small (Claude Code's case);
  not when many agents share one backend.
- **Boundary-marker compaction semantics** — caller-driven version is
  already supported by `summarize_and_offload`. Explicit boundary
  semantics are a UX layer the client should add, not the engine.

### Earlier follow-ups (still open)

- **Feedback signal tuning** — the `tanh / 5` saturation and `±5%`
  bound in `apply_combined_scoring` are conservative defaults. Once
  real-world feedback data is available, sweep these against held-out
  recall benchmarks.
- **Validate against real Postgres + vchord** — none of the engine
  ports have been run against a live database in this session. Code
  compiles, signatures align, but the alembic migrations + retain/recall
  integration paths need a smoke test before we make confident
  retrieval-quality claims.
