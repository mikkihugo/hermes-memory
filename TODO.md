# Singularity Memory — TODOs

Production-readiness work derived from a code review of the post-rebrand
codebase (commit `0ee7b2f`). Items grouped by priority.

`BACKLOG.md` (in `src/singularity_memory_server/`) tracks ports from the
retired in-tree engine. **This file is forward-looking** — gaps that are real
but didn't exist in the upstream Hindsight codebase either.

---

## P0 — required before downstream tools depend on this in production

### 1. Test suite

- **Status:** zero automated tests in the repo.
- **Why it matters:** any downstream tool (singularity-crush, Hermes,
  OpenClaw, Claude Code MCP wire-up) takes on all of this codebase's risk
  with no regression backstop.
- **Concrete first cut:**
  - `tests/integration/test_retain_recall.py` — happy path: retain N entries,
    recall a query, assert top-k matches.
  - `tests/integration/test_anti_patterns.py` — retain anti-pattern, recall
    excludes from default, surfaces in `<anti_patterns>` block.
  - `tests/integration/test_two_bank.py` — retain into `project/foo` and
    `global/coding`, recall from each independently.
  - `tests/integration/test_outage.py` — `pending_retain` queue catches
    failed retains, retries succeed when service recovers.
  - `tests/contract/test_openapi.py` — assert the FastAPI-generated
    `/openapi.json` is non-empty and includes the expected paths.
- Use `pytest` + Postgres in Docker (compose recipe already exists) or
  testcontainers-python.
- Target: 5–10 happy-path tests for v0.3 milestone. Coverage % is not the
  goal; "does retain/recall work end-to-end" is.

### 2. CI

- **Status:** no `.github/workflows/`.
- **Concrete first cut:** `.github/workflows/ci.yml` running on every PR:
  - lint (`ruff check`)
  - type-check (`mypy`)
  - integration tests (`pytest tests/integration/`)
- Postgres + vchord brought up via `services:` in the workflow.
- Add a status badge to README.

### 3. Checked-in OpenAPI spec

- **Status:** OpenAPI is generated at runtime by FastAPI; nothing committed.
- **Why:** downstream Go/Rust/etc. clients regenerate from the running
  service. If the service has a bug or a config divergence, the client is
  generated against drift. Pinning the spec to a commit is the only way
  for downstream language clients to have a stable contract.
- **Concrete:**
  - Script: `scripts/dump-openapi.py` — start the app in test mode, write
    `openapi.json` to repo root.
  - CI: regenerate on PR, fail if the committed spec drifts from the live
    one (or auto-bump in a follow-up commit).
  - Tag releases include the matching `openapi.json` for that version.

---

## P1 — meaningful improvements; not blocking but high-value

### 4. Decompose `memory_engine.py` (9,335 lines)

- One file holds retrieval, reflection, retain orchestration, embeddings
  glue, query analysis routing, and admin operations.
- **Concrete:**
  - Extract retain orchestration → already partly in `engine/retain/`.
    Move remaining retain code there.
  - Extract recall pipeline → `engine/recall/` (search fusion + decay
    weighting + maturity filter).
  - Extract reflect → `engine/reflect/` (already exists, move more in).
  - Extract admin ops → `engine/admin/`.
- Goal: no single engine file > 1,500 LOC.

### 5. Decompose `api/http.py` (6,390 lines) and `mcp_tools.py` (3,424 lines)

- **HTTP routes** should be split per resource: `api/banks.py`,
  `api/entries.py`, `api/admin.py`, etc.
- **MCP tools** are largely a hand-written second copy of HTTP route
  shapes. Either:
  - **(a)** generate MCP tool definitions from the FastAPI routes
    automatically (preferred — single source of truth), or
  - **(b)** at minimum, run a contract test that asserts every HTTP
    endpoint has an equivalent MCP tool with the same input schema.

### 6. Decompose `singularity_config.py` (1,936 lines)

- One Pydantic model per domain: `DBConfig`, `EmbeddingsConfig`,
  `RetrievalConfig`, `RerankerConfig`, `WorkerConfig`, etc.
- Compose into a top-level `SingularityConfig`.
- Easier to test individual sections; easier to PR changes that touch
  one domain.

### 7. Upstream sync strategy with `vectorize-io/hindsight`

- **Status:** code preserves `vectorize-io/hindsight#XXX` issue refs but
  there is no documented process for pulling future fixes.
- **Concrete:** `UPSTREAM.md` documenting:
  - What "assimilated" means in practice (no upstream runtime dep).
  - A periodic sync cadence (e.g. quarterly review of upstream commits).
  - A ruleset for what to take (correctness fixes, security patches) vs
    leave (features that conflict with our roadmap).
  - The map of upstream paths → our paths so a maintainer can `diff`
    upstream's `hindsight/api/` against our `singularity_memory_server/api/`
    selectively.

### 8. Auto-start sidecar mode for non-Python consumers

- The current "embedded" mode is Python-in-process only. Go/Rust/Node
  consumers can't actually embed.
- **Concrete:** ship a `singularity-memory sidecar` mode that launches
  the server bound to `127.0.0.1:0`, prints the chosen port to stdout,
  and exits cleanly on SIGTERM. Downstream binaries (e.g. sf) can spawn
  this and point their config at the printed port. This is what the
  current SPEC.md v0.8 actually means by "embedded for sf".

---

## P2 — operational polish

### 9. Health check transitivity

- `/healthz` currently checks the server is up. It should report:
  - DB connectivity (Postgres + vchord)
  - Embeddings provider reachability (last successful call timestamp)
  - Reranker reachability (same)
  - Pending retain queue depth
- Format: structured JSON, surfaceable in `/sf doctor` output.

### 10. Observability

- Prometheus `/metrics` endpoint with: retain count, recall count,
  recall latency histogram, retain failure count, queue depth.
- Structured request logs with `request_id` propagation.
- Tracing (OpenTelemetry) on the recall path — useful for debugging
  cross-tool integration latency.

### 11. Rate limiting / authentication

- HTTP API has no auth visible at a glance. For shared tailnet
  deployment this is fine for trusted nets; less fine for any wider
  exposure.
- **Concrete:** API token via `Authorization: Bearer` header,
  per-token rate limits, audit log on all retain/feedback/validate calls.

### 12. Dependency hygiene

- `pyproject.toml` pins to ranges (`pydantic>=2,<3`). Add a `requirements.lock`
  or `uv.lock` for reproducible builds in CI.
- Document supported Postgres + vchord versions.

---

## What this list explicitly excludes

- **Go client port.** Lives in `singularity-ng/singularity-memory-client-go`,
  not here.
- **MCP wire-up recipes.** Already shipped in `extensions/mcp/`.
- **Hermes / OpenClaw adapters.** Already minimal HTTP forwarders, no
  meaningful work to do until upstream APIs change.
- **PostgreSQL replacement.** Postgres + vchord is the right backend.
  Don't rewrite to SQLite or anything else.
