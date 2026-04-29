"""
Local MCP server entry point for use with Claude Code (HTTP transport).

This is a thin wrapper around the main singularity-memory server that pre-configures
sensible defaults for local use (embedded PostgreSQL via pg0, warning log level).

The full API runs on localhost:8888. Configure Claude Code's MCP settings:
    claude mcp add --transport http singularity http://localhost:8888/mcp/

Or pinned to a specific bank (single-bank mode):
    claude mcp add --transport http singularity http://localhost:8888/mcp/default/

Run with:
    singularity-memory mcp

Or with uvx:
    uvx singularity-memory@latest singularity-memory mcp

Environment variables:
    SINGULARITY_LLM_API_KEY: Required. API key for LLM provider.
    SINGULARITY_LLM_PROVIDER: Optional. LLM provider (default: "openai").
    SINGULARITY_LLM_MODEL: Optional. LLM model (default: "gpt-4o-mini").
    SINGULARITY_DATABASE_URL: Optional. Override database URL (default: pg0://singularity-memory).
"""

import os


def main() -> None:
    """Start the Singularity Memory server with local defaults."""
    # Set local defaults (only if not already configured by the user)
    os.environ.setdefault("SINGULARITY_DATABASE_URL", "pg0://singularity-memory")

    from singularity_memory_server.main import main as api_main

    api_main()


if __name__ == "__main__":
    main()
