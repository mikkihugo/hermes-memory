# MCP wire-up recipes

Singularity Memory exposes MCP-over-HTTP at `/mcp/` on the same port as its
HTTP API (default `:8888`). Any MCP-aware client speaks to it directly — no
plugin to install, just a one-line config on the client side. This folder
collects ready-to-paste snippets for the common ones.

Start the server first:

```bash
docker compose up singularity-postgres singularity-memory
# or:
singularity-memory serve --host 0.0.0.0 --port 8888
```

Verify MCP is listening:

```bash
curl -s -X POST http://localhost:8888/mcp/ \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

## Claude Code

```bash
claude mcp add --transport http singularity http://localhost:8888/mcp/
```

Or in `.mcp.json` (project-scoped or `~/.claude/mcp.json`):

See [`claude-code.mcp.json`](./claude-code.mcp.json).

## Cursor

`~/.cursor/mcp.json` — see [`cursor.mcp.json`](./cursor.mcp.json).

## Windsurf

`~/.codeium/windsurf/mcp_config.json` — see
[`windsurf.mcp.json`](./windsurf.mcp.json).

## OpenCode / OpenCode-extras

`~/.config/opencode/config.json` mcp section — see
[`opencode.mcp.json`](./opencode.mcp.json).

## Generic MCP-over-HTTP clients

If your client follows the MCP HTTP transport spec, point it at:

```
http://<host>:8888/mcp/
```

Add `Authorization: Bearer <token>` if you started the server with auth.
Pin to a specific bank with `X-Bank-Id: <bank>` (the server's
multi-tenant header).

## Troubleshooting

- `connection refused` — server isn't running. `singularity-memory status`
  pings the HTTP API.
- `404 /mcp/` — MCP transport isn't enabled. Default in `serve` is
  `SINGULARITY_MCP_ENABLED=true`; verify with `curl http://host:8888/v1/banks`
  to confirm the HTTP side is up.
- Empty results — confirm a bank exists. The "default" bank is auto-created
  on first retain; explicit creation: `POST /v1/default/banks` with
  `{"name": "default"}`.
