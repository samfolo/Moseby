from typing import Literal

from moseby.identifiers import GuestId, NotificationId, StaffMemberId
from moseby.runtime.models.common import JsonObject

from .common import Row
from .filters import Filters, IdFilter


class NotificationRequestRow(Row):
    """A saved message and its publication receipt, separate from recipient handling."""

    id: NotificationId
    created_at: int
    updated_at: int
    actor_staff_member_id: StaffMemberId
    request_id: str
    recipient_staff_member_id: StaffMemberId | None
    recipient_guest_id: GuestId | None
    format_version: Literal[1]
    payload: JsonObject
    published_at: int | None


class NotificationFilters(Filters):
    ids: IdFilter[NotificationId] | None = None
    recipient_guest_ids: IdFilter[GuestId] | None = None
    recipient_staff_member_ids: IdFilter[StaffMemberId] | None = None
    pending_only: bool = False
