# Singularity Memory

A standalone MCP+HTTP memory server for AI agents — and a Hermes plugin that
can either embed the server in-process or connect to a running standalone
instance. Postgres-first, with VectorChord for semantic search, BM25 for
lexical search, and reciprocal-rank fusion for ranking.

The same running server can be shared across **Hermes**, **Claude Code**,
**openclaw**, or any other MCP-aware client.

## Modes of operation

1. **Standalone server** — `singularity-memory serve` (or `docker compose up`)
   exposes HTTP at `/v1/...` and MCP at `/mcp/`. Multiple clients connect to
   one running instance.
2. **Hermes plugin** — drop this repo at
   `$HERMES_HOME/plugins/singularity_memory/`. Hermes loads it as a
   `MemoryProvider`. Set `server_url` in `singularity-memory.json` to use a
   running standalone server, or set `server_embedded: true` to spin up the
   server inside the Hermes process.

## Standalone server mode

### Install

```bash
pip install -e .          # from this repo
# or, when published:
# pip install singularity-memory
# uvx singularity-memory serve
```

### Run

```bash
# Embedded Postgres (no external DB), MCP enabled by default:
singularity-memory serve

# Use an existing Postgres:
SINGULARITY_DATABASE_URL=postgresql://user:pw@host:5432/db \
SINGULARITY_LLM_API_KEY=sk-... \
  singularity-memory serve --host 0.0.0.0 --port 8888

# Status check:
singularity-memory status
```

### Docker

```bash
# Default: external Postgres + server (port 8888)
docker compose up -d singularity-postgres singularity-memory

# Embedded variant (pg0, no external DB):
docker compose --profile embedded up singularity-memory-embedded
```

### Wire it up

```bash
# Claude Code:
claude mcp add --transport http singularity http://localhost:8888/mcp/

# openclaw or any MCP HTTP client: point it at the same URL.

# Hermes plugin: edit $HERMES_HOME/singularity-memory.json:
#   { "server_url": "http://localhost:8888" }
```

### Verify

```bash
curl -s http://localhost:8888/v1/banks | jq .
curl -s -X POST http://localhost:8888/mcp/ \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

## Hermes plugin mode

Hermes discovers memory providers from:

- `plugins/memory/<name>/` in the Hermes repo
- `$HERMES_HOME/plugins/<name>/` for user-installed providers

Place this directory at `$HERMES_HOME/plugins/singularity_memory/`. Hermes
will load `__init__.py:register()` and instantiate `SingularityMemoryProvider`.

Configure via `$HERMES_HOME/singularity-memory.json`:

```json
{
  "dsn": "postgresql://user:pw@host:5432/db",
  "server_url": "http://localhost:8888",
  "embedding_api_key": "...",
  "llm_api_key": "..."
}
```

If `server_url` is unset and `server_embedded` is true, the plugin starts an
embedded Singularity Memory server (with MCP enabled) inside the Hermes
process.

## Backend contract

- PostgreSQL is supported for durable storage (with `pgvector`, `vchord`, and
  optional `apache-age` extensions); `pg0://` embedded Postgres works for
  zero-setup local use.
- Local file storage is supported for development and tests.
- Dense embeddings come from `https://llm-gateway.centralcloud.com/v1/embeddings`
  by default (Qwen3 4B embedding model, 2560-dim vectors).
- Lexical retrieval uses BM25 (VectorChord-BM25).
- Fused ranking uses reciprocal-rank fusion.
- Optional reranking can use Qwen3 rerankers on
  `https://llm-embedding.centralcloud.com/v1`.

## Provider surface (Hermes plugin)

Implemented `MemoryProvider` methods:

- `name`, `is_available()`, `initialize()`, `system_prompt_block()`
- `prefetch()`, `queue_prefetch()`, `sync_turn()`
- `get_tool_schemas()`, `handle_tool_call()`
- `shutdown()`, `on_session_end()`, `on_memory_write()`
- `get_config_schema()`, `save_config()`

## Tools

- `singularity_memory_search`
- `singularity_memory_context`
- `singularity_memory_store`
- `singularity_memory_feedback`
- `singularity_memory_graph` (when AGE is enabled)
- `singularity_memory_metrics`
- Bank/admin tools when the embedded server is running:
  `memory_bank_create`, `memory_bank_delete`, `memory_bank_list`,
  `memory_bank_config_get`, `memory_bank_config_set`, `memory_stats`,
  `memory_browse`, `memory_search_debug`, `memory_entities`, `memory_audit`

## License & attribution

MIT. See `LICENSE`. The server and client packages were originally derived
from [vectorize-io/hindsight](https://github.com/vectorize-io/hindsight)
(also MIT) and have since been assimilated into this codebase. See `NOTICE`
for details.
