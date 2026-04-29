"""Add core_memory_blocks table

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-29

Adds a per-bank "core memory" table for short, named, always-in-context blocks
modeled on Letta / MemGPT (persona, human, system_directives, etc.) and on the
convergent pattern in Google's Always On Memory Agent. Distinct from
memory_units: core blocks are NOT searched, they're injected into every prompt
on prefetch, and they're updated by the agent itself via tool calls.

Each row: (bank_id, block_name) is the natural key. Content is bounded by
char_limit (default 2000) so a runaway agent can't blow context. The agent
edits content via core_memory_append / core_memory_replace MCP tools; the
character cap forces summarization when hit.

Reverse: drops the table.
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "c3d4e5f6a7b8"
down_revision: str | Sequence[str] | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _get_schema_prefix() -> str:
    """Get schema prefix for table names (required for multi-tenant support)."""
    schema = context.config.get_main_option("target_schema")
    return f'"{schema}".' if schema else ""


def upgrade() -> None:
    schema = _get_schema_prefix()
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {schema}core_memory_blocks (
            bank_id        TEXT        NOT NULL,
            block_name     TEXT        NOT NULL,
            content        TEXT        NOT NULL DEFAULT '',
            char_limit     INTEGER     NOT NULL DEFAULT 2000,
            description    TEXT        NOT NULL DEFAULT '',
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (bank_id, block_name)
        )
        """
    )
    op.execute(
        f"CREATE INDEX IF NOT EXISTS core_memory_blocks_bank_idx "
        f"ON {schema}core_memory_blocks (bank_id)"
    )


def downgrade() -> None:
    schema = _get_schema_prefix()
    op.execute(f"DROP INDEX IF EXISTS core_memory_blocks_bank_idx")
    op.execute(f"DROP TABLE IF EXISTS {schema}core_memory_blocks")
