"""Read durable publications using the recipient's saved sequence position."""

from sqlalchemy import Connection, Select, select

from moseby.identifiers import HotelId, NotificationId, StaffMemberId

from ..models.published_events import EventPage, EventPosition, PublishedEventRow
from ..tables import notification_requests, published_events
from ._notification_queries import notification_scope


def _select(staff_member_id: StaffMemberId, hotel_id: HotelId) -> Select:
    """Apply notification visibility before returning an event or its payload."""
    return select(
        published_events.c.sequence,
        published_events.c.notification_id,
        published_events.c.created_at,
        published_events.c.format_version,
        published_events.c.payload_json.label("payload"),
    ).where(
        published_events.c.notification_id.in_(
            select(notification_requests.c.id).where(
                notification_scope(staff_member_id, hotel_id)
            )
        )
    )


def find_by_notification_id(
    connection: Connection,
    notification_id: NotificationId,
    *,
    staff_member_id: StaffMemberId,
    hotel_id: HotelId,
) -> PublishedEventRow | None:
    """Return the notification's publication, or None if unpublished or inaccessible."""
    row = (
        connection.execute(
            _select(staff_member_id, hotel_id).where(
                published_events.c.notification_id == notification_id
            )
        )
        .mappings()
        .one_or_none()
    )
    return PublishedEventRow.model_validate(dict(row)) if row is not None else None


def find_all_after_sequence(
    connection: Connection,
    position: EventPosition,
    *,
    staff_member_id: StaffMemberId,
    hotel_id: HotelId,
) -> EventPage:
    """Read visible events strictly after the supplied position, in sequence order.

    Hidden events and sequence gaps do not end the page. Resume after the last
    returned event; an empty page keeps the supplied position so polling can
    continue. Consumers keep a separate position per audience and acknowledge
    processing themselves. This read does not mark any message as handled.
    """
    rows = (
        connection.execute(
            _select(staff_member_id, hotel_id)
            .where(published_events.c.sequence > position.after_sequence)
            .order_by(published_events.c.sequence)
            .limit(position.limit)
        )
        .mappings()
        .all()
    )
    items = [PublishedEventRow.model_validate(dict(row)) for row in rows]
    return EventPage(
        items=items,
        next_sequence=items[-1].sequence if items else position.after_sequence,
    )
