"""Index party evidence for case-insensitive keyword search."""

from alembic import op

revision = "0004_party_detail_search"
down_revision = "0003_incoming_cancellation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep the stable detail ID alongside the searchable copy of its text.
    op.execute(
        """
        CREATE VIRTUAL TABLE party_details_fts USING fts5(
            detail_id UNINDEXED,
            text,
            tokenize = 'unicode61 remove_diacritics 2'
        )
        """
    )
    op.execute(
        "INSERT INTO party_details_fts (detail_id, text) SELECT id, text FROM party_details"
    )

    # Maintain the index in the same transaction as the evidence it describes.
    op.execute(
        """
        CREATE TRIGGER party_details_search_insert
        AFTER INSERT ON party_details
        BEGIN
            INSERT INTO party_details_fts (detail_id, text) VALUES (NEW.id, NEW.text);
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER party_details_search_update
        AFTER UPDATE OF text ON party_details
        WHEN OLD.text IS NOT NEW.text
        BEGIN
            DELETE FROM party_details_fts WHERE detail_id = OLD.id;
            INSERT INTO party_details_fts (detail_id, text) VALUES (NEW.id, NEW.text);
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER party_details_search_delete
        AFTER DELETE ON party_details
        BEGIN
            DELETE FROM party_details_fts WHERE detail_id = OLD.id;
        END
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER party_details_search_delete")
    op.execute("DROP TRIGGER party_details_search_update")
    op.execute("DROP TRIGGER party_details_search_insert")
    op.execute("DROP TABLE party_details_fts")
