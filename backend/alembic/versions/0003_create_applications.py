"""create applications table

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-15

LangGraph's checkpoint tables are created by AsyncPostgresSaver.setup(), not Alembic.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "applications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("cv_id", sa.Uuid(), nullable=False),
        sa.Column("job_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["cv_id"], ["cvs.id"], name=op.f("fk_applications_cv_id_cvs"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_applications")),
    )
    op.create_index(op.f("ix_applications_cv_id"), "applications", ["cv_id"])
    op.create_index(op.f("ix_applications_status"), "applications", ["status"])


def downgrade() -> None:
    op.drop_index(op.f("ix_applications_status"), table_name="applications")
    op.drop_index(op.f("ix_applications_cv_id"), table_name="applications")
    op.drop_table("applications")
