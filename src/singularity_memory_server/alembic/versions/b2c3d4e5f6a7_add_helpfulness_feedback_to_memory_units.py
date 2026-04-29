"""Add helpful_count / unhelpful_count to memory_units

Revision ID: b2c3d4e5f6a7
Revises: z1u2v3w4x5y6
Create Date: 2026-04-29

Adds two integer columns to memory_units to track per-item helpfulness
feedback. Both default to 0 and have NOT NULL constraints so existing rows
get a sane neutral baseline. The retrieval scoring layer can use the
difference (helpful - unhelpful) to bias ranking toward items that have
demonstrated usefulness without retraining anything.

Reverse: drop both columns. Idempotent in both directions.
"""

from collections.abc import Sequence

from alembic import context, op

revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "z1u2v3w4x5y6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _get_schema_prefix() -> str:
    """Get schema prefix for table names (required for multi-tenant support)."""
    schema = context.config.get_main_option("target_schema")
    return f'"{schema}".' if schema else ""


def upgrade() -> None:
    schema = _get_schema_prefix()
    op.execute(
        f"ALTER TABLE {schema}memory_units "
        f"ADD COLUMN IF NOT EXISTS helpful_count INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        f"ALTER TABLE {schema}memory_units "
        f"ADD COLUMN IF NOT EXISTS unhelpful_count INTEGER NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    schema = _get_schema_prefix()
    op.execute(f"ALTER TABLE {schema}memory_units DROP COLUMN IF EXISTS unhelpful_count")
    op.execute(f"ALTER TABLE {schema}memory_units DROP COLUMN IF EXISTS helpful_count")
