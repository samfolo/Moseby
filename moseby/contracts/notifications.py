"""Notification intent and durable publications, with recipient-owned processing."""

from typing import Self

from pydantic import AwareDatetime, Field, model_validator

from moseby.identifiers import GuestId, NotificationId, StaffMemberId

from .common import Contract, Request


class NotificationRecipient(Contract):
    guest_id: GuestId | None = None
    staff_member_id: StaffMemberId | None = None

    @model_validator(mode="after")
    def check_recipient(self) -> Self:
        if (self.guest_id is None) == (self.staff_member_id is None):
            raise ValueError("supply exactly one guest or staff recipient")
        return self


class NotificationContent(Contract):
    text: str = Field(min_length=1, description="Message to deliver to the recipient.")


class Notification(Contract):
    id: NotificationId
    actor_staff_member_id: StaffMemberId
    recipient: NotificationRecipient
    content: NotificationContent
    created_at: AwareDatetime
    updated_at: AwareDatetime
    published_at: AwareDatetime | None = Field(
        description="Time saved to the durable event stream; recipient processing is separate."
    )

    @model_validator(mode="after")
    def check_times(self) -> Self:
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must be at or after created_at")
        if (
            self.published_at is not None
            and not self.created_at <= self.published_at <= self.updated_at
        ):
            raise ValueError("published_at must be between created_at and updated_at")
        return self


class CreateNotificationRequestPayload(Contract):
    recipient: NotificationRecipient
    content: NotificationContent


class CreateNotificationRequest(Request[CreateNotificationRequestPayload]):
    pass


class PublishedEvent(Contract):
    sequence: int = Field(
        ge=1, strict=True, description="Stable publication cursor, with gaps allowed."
    )
    notification_id: NotificationId
    created_at: AwareDatetime
    content: NotificationContent


class ListPublishedEventsRequest(Contract):
    after_sequence: int = Field(
        default=0,
        ge=0,
        description="Read visible publications strictly after this position.",
    )
    limit: int = Field(default=50, ge=1, le=100)


class PublishedEventPage(Contract):
    items: list[PublishedEvent]
    next_sequence: int = Field(
        ge=0,
        strict=True,
        description="Resume after this scanned position, including when the page is empty.",
    )

    @model_validator(mode="after")
    def check_order(self) -> Self:
        sequences = [item.sequence for item in self.items]
        if sequences != sorted(set(sequences)):
            raise ValueError("events must have unique increasing sequences")
        if sequences and self.next_sequence < sequences[-1]:
            raise ValueError("next_sequence must cover every returned event")
        return self
