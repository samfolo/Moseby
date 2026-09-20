"""Retain pending messages and record staff cancellation before delivery."""

import sqlalchemy as sa
from alembic import context, op

revision = "0003_incoming_cancellation"
down_revision = "0002_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Inline constraints let SQLite add these columns while retaining its triggers.
    # cancelled_at records a completed withdrawal, not a request to cancel later.
    op.execute("ALTER TABLE incoming_thread_records ADD COLUMN cancelled_at INTEGER")
    op.execute(
        """
        ALTER TABLE incoming_thread_records
        ADD COLUMN cancelled_by_staff_member_id TEXT
            CONSTRAINT fk_incoming_cancel_actor REFERENCES staff_members(id)
            CONSTRAINT ck_incoming_cancellation CHECK (
                -- Pending and appended messages have no cancellation details.
                (cancelled_at IS NULL AND cancelled_by_staff_member_id IS NULL)
                OR (
                    cancelled_at IS NOT NULL
                    AND cancelled_by_staff_member_id IS NOT NULL
                    -- Only user input still outside the conversation can be withdrawn.
                    AND kind = 'INCOMING_THREAD_RECORD_KIND_USER_MESSAGE'
                    AND record_id IS NULL
                    -- updated_at includes the write that saved cancellation.
                    AND cancelled_at BETWEEN created_at AND updated_at
                )
            )
        """
    )
    op.execute(
        """
        CREATE TRIGGER incoming_keep_cancelled
        BEFORE UPDATE ON incoming_thread_records
        WHEN OLD.cancelled_at IS NOT NULL
        BEGIN
            -- Retain the withdrawal and prevent later delivery or retargeting.
            SELECT RAISE(ABORT, 'Cancelled input cannot be changed');
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER incoming_thread_records_no_delete
        BEFORE DELETE ON incoming_thread_records
        BEGIN
            -- Keep the saved message and its delivery or cancellation receipt.
            SELECT RAISE(ABORT, 'Saved input cannot be deleted');
        END
        """
    )


def downgrade() -> None:
    # Without these columns, cancelled messages would look pending and be delivered.
    if context.is_offline_mode():
        raise RuntimeError("This downgrade requires a live check for cancelled input")
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM incoming_thread_records WHERE cancelled_at IS NOT NULL)"
        )
    ):
        raise RuntimeError(
            "Cannot downgrade: removing cancellation fields would make cancelled messages pending again"
        )
    op.execute("DROP TRIGGER incoming_thread_records_no_delete")
    op.execute("DROP TRIGGER incoming_keep_cancelled")
    op.execute(
        "ALTER TABLE incoming_thread_records DROP COLUMN cancelled_by_staff_member_id"
    )
    op.execute("ALTER TABLE incoming_thread_records DROP COLUMN cancelled_at")
