"""Keep the selected agent queryable on threads and runs."""

import sqlalchemy as sa
from alembic import context, op

revision = "0005_agent_attribution"
down_revision = "0004_party_detail_search"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("threads", "runs"):
        # Both values are absent when the original history has no agent selection.
        op.execute(f"ALTER TABLE {table} ADD COLUMN agent_id TEXT")
        op.execute(
            f"""
            ALTER TABLE {table} ADD COLUMN agent_version INTEGER
            CONSTRAINT ck_{table}_agent CHECK (
                (agent_id IS NULL AND agent_version IS NULL)
                OR (
                    agent_id IS NOT NULL AND agent_version IS NOT NULL
                    AND agent_version > 0
                    AND length(agent_id) BETWEEN 1 AND 64
                    AND agent_id NOT GLOB '*[^a-z0-9-]*'
                    AND substr(agent_id, 1, 1) GLOB '[a-z]'
                    AND substr(agent_id, -1) != '-'
                    AND instr(agent_id, '--') = 0
                )
            )
            """
        )

    # Recover the selection from the permanent creation record where it exists.
    op.execute(
        """
        UPDATE threads SET (agent_id, agent_version) = (
            SELECT json_extract(payload_json, '$.agent.id'),
                   json_extract(payload_json, '$.agent.version')
            FROM thread_records
            WHERE thread_id = threads.id AND sequence = 1
        )
        """
    )
    op.execute(
        """
        UPDATE runs SET (agent_id, agent_version) = (
            SELECT agent_id, agent_version FROM threads WHERE id = runs.thread_id
        )
        """
    )

    for table in ("threads", "runs"):
        op.execute(
            f"""
            CREATE TRIGGER {table}_keep_agent
            BEFORE UPDATE OF agent_id, agent_version ON {table}
            WHEN NEW.agent_id IS NOT OLD.agent_id
                OR NEW.agent_version IS NOT OLD.agent_version
            BEGIN
                -- Changing attribution would relabel work that already happened.
                SELECT RAISE(ABORT, 'Agent attribution cannot be changed');
            END
            """
        )

    op.execute(
        """
        CREATE TRIGGER runs_check_agent
        BEFORE INSERT ON runs
        BEGIN
            -- A run executes the definition selected by its thread.
            SELECT CASE WHEN NOT EXISTS (
                SELECT 1 FROM threads WHERE id = NEW.thread_id
                    AND agent_id IS NEW.agent_id
                    AND agent_version IS NEW.agent_version
            ) THEN RAISE(ABORT, 'Run agent must match its thread') END;
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER thread_records_check_agent
        BEFORE INSERT ON thread_records
        WHEN NEW.kind = 'THREAD_RECORD_KIND_THREAD_CREATED'
        BEGIN
            -- The queryable selection and its permanent history must agree.
            SELECT CASE WHEN NOT EXISTS (
                SELECT 1 FROM threads WHERE id = NEW.thread_id
                    AND agent_id IS json_extract(NEW.payload_json, '$.agent.id')
                    AND agent_version IS json_extract(NEW.payload_json, '$.agent.version')
            ) THEN RAISE(ABORT, 'Creation record agent must match its thread') END;
        END
        """
    )


def downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("This downgrade requires a live check for agent attribution")
    if op.get_bind().scalar(
        sa.text("SELECT EXISTS (SELECT 1 FROM threads WHERE agent_id IS NOT NULL)")
    ):
        raise RuntimeError("Cannot downgrade while threads carry agent attribution")
    op.execute("DROP TRIGGER thread_records_check_agent")
    op.execute("DROP TRIGGER runs_check_agent")
    for table in ("runs", "threads"):
        op.execute(f"DROP TRIGGER {table}_keep_agent")
        op.execute(f"ALTER TABLE {table} DROP COLUMN agent_version")
        op.execute(f"ALTER TABLE {table} DROP COLUMN agent_id")
