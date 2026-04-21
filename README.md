# hermes-memory

Real Hermes external memory-provider plugin.

## Purpose

Provide a user-installed Hermes memory provider that plugs into the real
`MemoryProvider` lifecycle without patching Hermes core and without depending
on Honcho.

## Install shape

Hermes discovers memory providers from:

- `plugins/memory/<name>/` in the Hermes repo
- `$HERMES_HOME/plugins/<name>/` for user-installed providers

This directory is shaped for the second path. To use it, place it at:

```text
$HERMES_HOME/plugins/hermes_memory/
```

The git repo can be named `hermes-memory`, but the installed plugin directory
should use `hermes_memory`. Hermes derives the active provider name from the
directory, and underscore names are safer for module and CLI handler loading.

## Backend contract

- Postgres is supported for durable storage
- local file storage is supported for development and tests
- dense embeddings come from `https://llm-gateway.centralcloud.com/v1/embeddings`
- default embedding lane assumes a Qwen3 4B embedding model
- vector retrieval uses `2560d` vectors
- lexical retrieval uses BM25
- fused ranking uses reciprocal-rank fusion
- optional reranking can use the Qwen3 rerankers on `https://llm-embedding.centralcloud.com/v1`
- graph expansion with AGE is a later phase

## Provider surface

Implemented for Hermes:

- `name`
- `is_available()`
- `initialize()`
- `system_prompt_block()`
- `prefetch()`
- `queue_prefetch()`
- `sync_turn()`
- `get_tool_schemas()`
- `handle_tool_call()`
- `shutdown()`
- `on_session_end()`
- `on_memory_write()`
- `get_config_schema()`
- `save_config()`

## Tools

- `hermes_memory_search`
- `hermes_memory_context`
- `hermes_memory_store`
- `hermes_memory_feedback`

## Status

This is now a Hermes plugin scaffold rather than a generic library scaffold.
Implemented first slice:

- durable `store_memory_item`
- durable `store_turn`
- helpfulness feedback persistence
- lexical search
- semantic-ish overlap search
- fused ranking with reciprocal-rank fusion

Still later:

- real embedding calls
- AGE graph expansion
