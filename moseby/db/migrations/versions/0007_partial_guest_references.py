"""Retain clear guest references when other parts of a note remain ambiguous."""

import sqlalchemy as sa
from alembic import context, op

revision = "0007_partial_guest_references"
down_revision = "0006_guest_search"
branch_labels = None
depends_on = None


def _replace_reference_triggers(*, allow_ambiguous: bool) -> None:
    """Keep JSON, membership and uniqueness checks together for both write paths."""
    allowed_statuses = "'GUEST_REFERENCE_STATUS_RESOLVED'"
    if allow_ambiguous:
        allowed_statuses += ", 'GUEST_REFERENCE_STATUS_AMBIGUOUS'"
    for event in ("INSERT", "UPDATE"):
        name = f"party_references_{event.lower()}"
        op.execute(f"DROP TRIGGER {name}")
        op.execute(
            f"""
            CREATE TRIGGER {name}
            BEFORE {event} ON party_details
            BEGIN
            -- Validate JSON before inspecting its contents.
            SELECT CASE
                WHEN NOT json_valid(NEW.referenced_guest_ids_json)
                THEN RAISE(ABORT, 'Guest references must be valid JSON')
            END;

            -- Store references as an array of guest IDs.
            SELECT CASE
                WHEN json_type(NEW.referenced_guest_ids_json) != 'array'
                THEN RAISE(ABORT, 'Guest references must be an array')
            END;

            -- Each reference names a guest in this party.
            SELECT CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM json_each(NEW.referenced_guest_ids_json) AS ref
                    WHERE ref.type != 'text' OR NOT EXISTS (
                        SELECT 1
                        FROM guests
                        WHERE id = ref.value
                          AND party_id = NEW.party_id
                    )
                )
                THEN RAISE(ABORT, 'Referenced guests must belong to the party')
            END;

            -- Each guest appears once in the reference list.
            SELECT CASE
                WHEN (
                    SELECT COUNT(*)
                    FROM json_each(NEW.referenced_guest_ids_json)
                ) != (
                    SELECT COUNT(DISTINCT value)
                    FROM json_each(NEW.referenced_guest_ids_json)
                )
                THEN RAISE(ABORT, 'Guest references must be unique')
            END;

            -- Keep clear matches only for a settled classification.
            SELECT CASE
                WHEN NEW.reference_status NOT IN ({allowed_statuses})
                  AND json_array_length(NEW.referenced_guest_ids_json) != 0
                THEN RAISE(ABORT, 'This reference status cannot contain guest IDs')
            END;
            END
            """
        )


def upgrade() -> None:
    _replace_reference_triggers(allow_ambiguous=True)


def downgrade() -> None:
    # The earlier rule cannot retain guest IDs on an ambiguous note.
    if context.is_offline_mode():
        raise RuntimeError(
            "This downgrade requires a live check for partial references"
        )
    if op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM party_details "
            "WHERE reference_status = 'GUEST_REFERENCE_STATUS_AMBIGUOUS' "
            "AND json_array_length(referenced_guest_ids_json) > 0)"
        )
    ):
        raise RuntimeError(
            "Cannot downgrade while ambiguous notes contain clear guest references"
        )
    _replace_reference_triggers(allow_ambiguous=False)
