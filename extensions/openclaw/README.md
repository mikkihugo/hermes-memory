# Singularity Memory plugin for OpenClaw

Persistent memory for OpenClaw, backed by the standalone
[Singularity Memory](../../) server. BM25 + vector + RRF fusion retrieval
with optional reranking — same engine that other clients (Hermes, Claude
Code via MCP, etc.) connect to. This plugin is a thin proxy; all the
retrieval happens in the running server.

## Install

```bash
npm install @singularity-memory/openclaw-plugin
# or, in OpenClaw's plugin discovery flow:
openclaw plugins install @singularity-memory/openclaw-plugin
```

## Configure

Plugin config is set via OpenClaw's standard config flow (`openclaw config
set memory.singularity-memory.serverUrl http://localhost:8888`). Schema:

| Field         | Required | Default                | Notes                                               |
|---------------|----------|------------------------|-----------------------------------------------------|
| `serverUrl`   | yes      | `http://localhost:8888`| Running Singularity Memory server                  |
| `workspace`   | no       | `default`              | Memory bank scope                                   |
| `apiKey`      | no       |                        | Bearer token (only if server runs with auth)        |
| `autoRecall`  | no       | `true`                 | Inject memories into prompt before each agent run   |
| `autoCapture` | no       | `true`                 | Persist user messages at end of each agent run      |
| `recallLimit` | no       | `5`                    | Max memories per recall call                        |

## Run a server

```bash
# In the singularity-memory repo:
docker compose up singularity-postgres singularity-memory
# Or:
pip install -e .
singularity-memory serve --host 0.0.0.0 --port 8888
```

## What it does

- **Auto-recall** (`before_prompt_build`): on every agent run, calls
  `POST /v1/<workspace>/banks/default/memories/recall` and prepends the top
  results into prompt context (escaped, with explicit "untrusted historical
  data" framing so the model treats them as context not instructions).
- **Auto-capture** (`agent_end`): persists user-role messages from the run
  via `POST .../memories/retain`. Skips short messages, system-generated
  content, and obvious prompt-injection payloads.
- **Tools**: `memory_recall(query, limit?)` and `memory_store(text, context?)`
  for explicit invocation.
- **CLI**: `openclaw singularity-memory status` checks reachability.

## License

MIT. See ../../LICENSE.
