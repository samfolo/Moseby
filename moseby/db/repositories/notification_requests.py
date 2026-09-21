"""Read notification intent visible to its author or staff recipient."""

from collections.abc import Sequence

from sqlalchemy import Connection, Select, select

from moseby.identifiers import HotelId, NotificationId, StaffMemberId

from ..models.notification_requests import NotificationFilters, NotificationRequestRow
from ..pagination import Page, PageRequest, read_page
from ..tables import notification_requests
from ._notification_queries import notification_scope
from ._queries import unique_ids


def _select(staff_member_id: StaffMemberId, hotel_id: HotelId) -> Select:
    """Read the saved message and receipt within the caller's audience and hotel."""
    return select(
        notification_requests.c.id,
        notification_requests.c.created_at,
        notification_requests.c.updated_at,
        notification_requests.c.actor_staff_member_id,
        notification_requests.c.request_id,
        notification_requests.c.recipient_staff_member_id,
        notification_requests.c.recipient_guest_id,
        notification_requests.c.format_version,
        notification_requests.c.payload_json.label("payload"),
        notification_requests.c.published_at,
    ).where(notification_scope(staff_member_id, hotel_id))


def find_by_id(
    connection: Connection,
    id: NotificationId,
    *,
    staff_member_id: StaffMemberId,
    hotel_id: HotelId,
) -> NotificationRequestRow | None:
    """Return the saved row if it exists and the caller can read it; otherwise None."""
    row = (
        connection.execute(
            _select(staff_member_id, hotel_id).where(notification_requests.c.id == id)
        )
        .mappings()
        .one_or_none()
    )
    return NotificationRequestRow.model_validate(dict(row)) if row is not None else None


def find_by_ids(
    connection: Connection,
    ids: Sequence[NotificationId],
    *,
    staff_member_id: StaffMemberId,
    hotel_id: HotelId,
) -> dict[NotificationId, NotificationRequestRow]:
    """Read at most 100 supplied IDs, counting repeats towards the limit.

    Missing or inaccessible IDs are omitted. Repeated IDs appear once, and an
    empty input returns an empty dictionary.
    """
    ids = unique_ids(ids)
    if not ids:
        return {}
    rows = connection.execute(
        _select(staff_member_id, hotel_id).where(notification_requests.c.id.in_(ids))
    ).mappings()
    return {row["id"]: NotificationRequestRow.model_validate(dict(row)) for row in rows}


def find_by_request_id(
    connection: Connection,
    request_id: str,
    *,
    actor_staff_member_id: StaffMemberId,
    hotel_id: HotelId,
) -> NotificationRequestRow | None:
    """Find the notification authored under this request ID, including after publication.

    Another author's matching request ID belongs to a separate notification,
    even when the caller is its recipient.
    """
    row = (
        connection.execute(
            _select(actor_staff_member_id, hotel_id).where(
                notification_requests.c.actor_staff_member_id == actor_staff_member_id,
                notification_requests.c.request_id == request_id,
            )
        )
        .mappings()
        .one_or_none()
    )
    return NotificationRequestRow.model_validate(dict(row)) if row is not None else None


def find_all(
    connection: Connection,
    *,
    staff_member_id: StaffMemberId,
    hotel_id: HotelId,
    page: PageRequest | None = None,
) -> Page[NotificationRequestRow]:
    """List visible notifications in creation order, including those already published."""
    return search(
        connection,
        NotificationFilters(),
        staff_member_id=staff_member_id,
        hotel_id=hotel_id,
        page=page,
    )


def search(
    connection: Connection,
    filters: NotificationFilters,
    *,
    staff_member_id: StaffMemberId,
    hotel_id: HotelId,
    page: PageRequest | None = None,
) -> Page[NotificationRequestRow]:
    """Apply recipient and publication filters before paging visible notifications.

    Published means saved to the event stream; it does not mean that an email
    arrived or that the recipient handled the message.
    """
    statement = _select(staff_member_id, hotel_id)
    for column, values in (
        (notification_requests.c.id, filters.ids),
        (notification_requests.c.recipient_guest_id, filters.recipient_guest_ids),
        (
            notification_requests.c.recipient_staff_member_id,
            filters.recipient_staff_member_ids,
        ),
    ):
        if values is not None:
            statement = statement.where(column.in_(values))
    if filters.pending_only:
        statement = statement.where(notification_requests.c.published_at.is_(None))
    return read_page(
        connection,
        statement,
        table=notification_requests,
        row_type=NotificationRequestRow,
        page=page or PageRequest(),
        query="notification_requests.search",
        criteria={
            "staff_member_id": staff_member_id,
            "hotel_id": hotel_id,
            "filters": filters.model_dump_json(),
        },
    )
