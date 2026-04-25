"""Command-line entry point for the Singularity Memory server.

Subcommands:
- serve  : Start the full HTTP + MCP server (default port 8888).
- mcp    : Convenience wrapper for local MCP-only use (Claude Code, etc.).
- status : Probe whether a running server is reachable.

The serve command is a thin wrapper over `singularity_memory_server.main:main`
that pre-applies sensible defaults: MCP enabled, embedded `pg0://` Postgres
unless a DSN is supplied or `SINGULARITY_DATABASE_URL` is already set.
"""

from __future__ import annotations

import argparse
import os
import sys


def cmd_serve(args: argparse.Namespace) -> int:
    os.environ.setdefault("SINGULARITY_MCP_ENABLED", "true")
    os.environ.setdefault(
        "SINGULARITY_DATABASE_URL",
        args.dsn or "pg0://singularity-memory",
    )
    if args.host:
        os.environ["SINGULARITY_HOST"] = args.host
    if args.port:
        os.environ["SINGULARITY_PORT"] = str(args.port)

    from singularity_memory_server.main import main as api_main

    sys.argv = ["singularity-memory-server"]
    api_main()
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    os.environ.setdefault(
        "SINGULARITY_DATABASE_URL",
        args.dsn or "pg0://singularity-memory",
    )
    os.environ["SINGULARITY_MCP_ENABLED"] = "true"
    if args.host:
        os.environ["SINGULARITY_HOST"] = args.host
    if args.port:
        os.environ["SINGULARITY_PORT"] = str(args.port)

    from singularity_memory_server.main import main as api_main

    sys.argv = ["singularity-memory-mcp"]
    api_main()
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    import urllib.request

    url = f"http://{args.host}:{args.port}/v1/banks"
    try:
        urllib.request.urlopen(url, timeout=2)
    except Exception as exc:
        print(f"DOWN: {url} ({exc})")
        return 1
    print(f"OK: {url}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="singularity-memory",
        description="Singularity Memory - standalone MCP+HTTP memory server.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="Start the HTTP + MCP server.")
    serve.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1).")
    serve.add_argument("--port", type=int, default=8888, help="Bind port (default: 8888).")
    serve.add_argument("--dsn", default=None, help="Database DSN (postgresql://... or pg0://...).")
    serve.set_defaults(func=cmd_serve)

    mcp = sub.add_parser("mcp", help="Start in MCP-focused local mode (embedded pg0 by default).")
    mcp.add_argument("--host", default="127.0.0.1")
    mcp.add_argument("--port", type=int, default=8888)
    mcp.add_argument("--dsn", default=None)
    mcp.set_defaults(func=cmd_mcp)

    status = sub.add_parser("status", help="Check if a running server is reachable.")
    status.add_argument("--host", default="127.0.0.1")
    status.add_argument("--port", type=int, default=8888)
    status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    sys.exit(args.func(args) or 0)


if __name__ == "__main__":
    main()
