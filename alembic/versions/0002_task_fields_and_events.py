"""task recovery fields and persistent events

Revision ID: 0002_task_fields_and_events
Revises: 0001_initial_schema
Create Date: 2026-06-23
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_task_fields_and_events"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("attempt", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("idempotency_key", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("cancel_requested", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("heartbeat_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("locked_by", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("lease_until", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("retry_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("error_code", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("failed_reason", sa.Text(), nullable=True))
        batch.add_column(sa.Column("parent_task_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("trace_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))
        batch.create_unique_constraint("uq_tasks_user_type_idempotency", ["user_id", "task_type", "idempotency_key"])
        batch.create_index("idx_tasks_user_status_created", ["user_id", "status", "created_at"])
        batch.create_index("idx_tasks_retry", ["status", "retry_at"])
    op.create_table(
        "task_events",
        sa.Column("event_id", sa.String(length=64), primary_key=True),
        sa.Column("task_id", sa.String(length=64), sa.ForeignKey("tasks.task_id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.String(length=64), nullable=True),
        sa.Column("message_id", sa.String(length=64), nullable=True),
        sa.Column("trace_id", sa.String(length=64), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("public_payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("task_id", "sequence", name="uq_task_events_task_sequence"),
    )
    op.create_index("idx_task_events_task_sequence", "task_events", ["task_id", "sequence"])


def downgrade() -> None:
    op.drop_index("idx_task_events_task_sequence", table_name="task_events")
    op.drop_table("task_events")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_index("idx_tasks_retry")
        batch.drop_index("idx_tasks_user_status_created")
        batch.drop_constraint("uq_tasks_user_type_idempotency", type_="unique")
        for column in (
            "deleted_at",
            "version",
            "trace_id",
            "parent_task_id",
            "failed_reason",
            "error_code",
            "retry_at",
            "lease_until",
            "locked_by",
            "heartbeat_at",
            "cancel_requested",
            "idempotency_key",
            "max_attempts",
            "attempt",
        ):
            batch.drop_column(column)
