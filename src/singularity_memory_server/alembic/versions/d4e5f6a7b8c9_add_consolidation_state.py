"""Add consolidation_state table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-29

Tracks per-bank consolidation scheduling state so the
`_auto_consolidation_loop` background worker can gate runs on actual
activity instead of a flat interval timer. Borrows the discipline from
Claude Code's autoDream:

  - last_run_at: when consolidation last completed for this bank
  - memories_at_last_run: count of memory_units at that point, so the
    next gate check can compute "how many memories arrived since."

Combined with a Postgres advisory lock keyed on bank_id (no schema
needed), this gives us cross-instance-safe consolidation scheduling
that won't fire when nothing has happened.

Reverse: drops the table.
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "d4e5f6a7b8c9"
down_revision: str | Sequence[str] | None = "c3d4e5f6a7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _get_schema_prefix() -> str:
    schema = context.config.get_main_option("target_schema")
    return f'"{schema}".' if schema else ""


def upgrade() -> None:
    schema = _get_schema_prefix()
    op.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {schema}consolidation_state (
            bank_id              TEXT        PRIMARY KEY,
            last_run_at          TIMESTAMPTZ,
            memories_at_last_run BIGINT      NOT NULL DEFAULT 0,
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    schema = _get_schema_prefix()
    op.execute(f"DROP TABLE IF EXISTS {schema}consolidation_state")
