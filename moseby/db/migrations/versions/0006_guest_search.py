"""Index guest names for case-insensitive keyword search."""

from alembic import op

revision = "0006_guest_search"
down_revision = "0005_agent_attribution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Combine the names so keywords can match across first, last and preferred names.
    op.execute(
        """
        CREATE VIRTUAL TABLE guests_fts USING fts5(
            guest_id UNINDEXED,
            name,
            tokenize = 'unicode61 remove_diacritics 2'
        )
        """
    )
    op.execute(
        """
        INSERT INTO guests_fts (guest_id, name)
        SELECT id, first_name || ' ' || last_name || ' ' || COALESCE(preferred_name, '')
        FROM guests
        """
    )

    # Keep search results in step with inserts, name changes and deletions.
    op.execute(
        """
        CREATE TRIGGER guests_search_insert
        AFTER INSERT ON guests
        BEGIN
            INSERT INTO guests_fts (guest_id, name)
            VALUES (
                NEW.id,
                NEW.first_name || ' ' || NEW.last_name || ' ' || COALESCE(NEW.preferred_name, '')
            );
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER guests_search_update
        AFTER UPDATE OF first_name, last_name, preferred_name ON guests
        WHEN OLD.first_name IS NOT NEW.first_name
          OR OLD.last_name IS NOT NEW.last_name
          OR OLD.preferred_name IS NOT NEW.preferred_name
        BEGIN
            DELETE FROM guests_fts WHERE guest_id = OLD.id;
            INSERT INTO guests_fts (guest_id, name)
            VALUES (
                NEW.id,
                NEW.first_name || ' ' || NEW.last_name || ' ' || COALESCE(NEW.preferred_name, '')
            );
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER guests_search_delete
        AFTER DELETE ON guests
        BEGIN
            DELETE FROM guests_fts WHERE guest_id = OLD.id;
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER guests_search_delete")
    op.execute("DROP TRIGGER guests_search_update")
    op.execute("DROP TRIGGER guests_search_insert")
    op.execute("DROP TABLE guests_fts")
