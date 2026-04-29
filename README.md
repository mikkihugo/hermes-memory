# Singularity Memory

A standalone memory server for AI agents — Postgres-backed, MCP+HTTP
native, with BM25 + vector + RRF fusion retrieval and optional reranking.
The same running server can be shared across **Hermes**, **OpenClaw**,
**Claude Code** (and any other MCP-aware client) so memories persist and
move with the user, not the tool.

```
src/
  singularity_memory/             # CLI shim (singularity-memory serve|mcp|status)
  singularity_memory_server/      # the engine — HTTP + MCP server, retrieval pipeline
  singularity_memory_client/      # Python HTTP client (used by extensions)
  singularity_memory_client_api/  # OpenAPI-generated Python client
extensions/
  hermes/                          # Python plugin — Hermes adapter (HTTP client)
  openclaw/                        # TypeScript plugin — OpenClaw adapter (HTTP client)
  mcp/                             # Wire-up recipes for Claude Code, Cursor, Windsurf, OpenCode
```

The server in `src/` is the product. The directories under `extensions/`
are thin adapters — none of them duplicate retrieval logic; they all
forward to the running server.

## Quick start

```bash
# Bring up the server (Postgres + Singularity Memory):
docker compose up singularity-postgres singularity-memory

# Or, against your own Postgres with vchord installed:
SINGULARITY_DATABASE_URL=postgresql://user:pw@host:5432/db \
SINGULARITY_LLM_API_KEY=sk-... \
  pip install -e . && singularity-memory serve --host 0.0.0.0
```

Verify both APIs are up:

```bash
curl -s http://localhost:8888/v1/banks | jq .
curl -s -X POST http://localhost:8888/mcp/ \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

## Wire it up

| Client       | How                                                                          |
|--------------|------------------------------------------------------------------------------|
| **Hermes**   | Symlink `extensions/hermes/` into `$HERMES_HOME/plugins/singularity_memory/`. Edit `$HERMES_HOME/singularity-memory.json` to set `server_url`. |
| **OpenClaw** | `npm install @singularity-memory/openclaw-plugin`, set `serverUrl` in plugin config. See `extensions/openclaw/README.md`. |
| **Claude Code** | `claude mcp add --transport http singularity http://localhost:8888/mcp/`. See `extensions/mcp/`. |
| **Cursor / Windsurf / OpenCode** | Drop the appropriate `.mcp.json` snippet from `extensions/mcp/`. |

## What lives where

### `src/singularity_memory_server/` — the engine

Originally derived from [vectorize-io/hindsight](https://github.com/vectorize-io/hindsight)
(MIT) and assimilated into this codebase under our namespace; see `NOTICE`.
Provides retain / recall / reflect operations, Banks, entities, mental
models, audit logs, async workers, alembic migrations, and the FastAPI
HTTP + MCP server.

A ports backlog from the retired in-tree engine lives at
[`src/singularity_memory_server/BACKLOG.md`](./src/singularity_memory_server/BACKLOG.md):
six features (`embeddings_pending` metric, `vector_enabled` opt-in,
auto-backfill, lane weighting, two-tier reranking, helpfulness feedback)
that landed in the hand-written engine and want a real Postgres+vchord
test environment to land in B safely.

### `extensions/hermes/` — Python plugin

Thin Hermes `MemoryProvider` that forwards every call to the running
server over HTTP. ~330 lines, no in-process retrieval. Implements
`initialize` / `prefetch` / `sync_turn` / `handle_tool_call` / setup
wizard config schema.

Two operating modes:
- **External server** (recommended): set `server_url` in
  `$HERMES_HOME/singularity-memory.json`. Multiple Hermes sessions share
  one server.
- **Embedded**: set `server_embedded: true`. Plugin starts the server
  inside the Hermes process. Useful for laptops / single-user setups.

### `extensions/openclaw/` — TypeScript plugin

OpenClaw plugin (`@singularity-memory/openclaw-plugin`) that hooks
`before_prompt_build` (auto-recall) and `agent_end` (auto-capture) to
forward to the same HTTP server. Modeled after OpenClaw's in-tree
`memory-lancedb` plugin, swapping LanceDB for our server.

### `extensions/mcp/` — recipes

`.mcp.json` snippets for Claude Code, Cursor, Windsurf, OpenCode. No
plugin to install on the client side — the server's `/mcp/` endpoint
speaks JSON-RPC over HTTP and any MCP-aware client connects in one
config line.

## Retrieval stack

- **Vector**: `pgvector` by default (works everywhere). Optional upgrade
  to `vchord` (Rust-built, better at scale + multilingual). Configure via
  `SINGULARITY_VECTOR_EXTENSION`.
- **Lexical**: Postgres native FTS by default (works everywhere).
  Optional upgrades: `pg_textsearch` (Tantivy-based BM25) or
  `vchord_bm25` (real BM25 with Block-Max-WAND). Configure via
  `SINGULARITY_TEXT_SEARCH_EXTENSION`.
- **Fusion**: Reciprocal Rank Fusion across lanes.
- **Reranking**: optional cross-encoder via OpenAI-compatible HTTP
  endpoint (e.g. Qwen3 reranker on a local LLM gateway).
- **Graph**: Apache AGE (optional).

For typical workloads (tens of thousands of memories per workspace,
mostly English / code), pgvector + native FTS is genuinely fine.
vchord-stack matters at scale (>1M items) or for multilingual content.

## Configuration

All server config flows through `SINGULARITY_*` environment variables;
`singularity_memory_server/singularity_config.py` is the canonical list.
Common ones:

| Var                                       | Purpose                              |
|-------------------------------------------|--------------------------------------|
| `SINGULARITY_DATABASE_URL`                | Postgres DSN                         |
| `SINGULARITY_HOST` / `SINGULARITY_PORT`   | Bind host / port (default 127.0.0.1:8888) |
| `SINGULARITY_MCP_ENABLED`                 | Enable `/mcp/` (default true)        |
| `SINGULARITY_LLM_PROVIDER`                | `openai` / `anthropic` / `none` etc. |
| `SINGULARITY_LLM_API_KEY`                 | Forwarded to the LLM provider        |
| `SINGULARITY_EMBEDDINGS_PROVIDER`         | `local` / `openai` / `cohere` etc.   |
| `SINGULARITY_EMBEDDINGS_OPENAI_API_KEY`   | Embedding endpoint key               |
| `SINGULARITY_VECTOR_EXTENSION`            | `pgvector` / `vchord`                |
| `SINGULARITY_TEXT_SEARCH_EXTENSION`       | `native` / `pg_textsearch` / `vchord` |

## License & attribution

MIT. See `LICENSE`. Engine code derived from
[`vectorize-io/hindsight`](https://github.com/vectorize-io/hindsight) (also
MIT) and assimilated here; see `NOTICE` for details.
