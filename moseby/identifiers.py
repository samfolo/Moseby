"""Resource prefixes with canonical uppercase ULIDs; validation does not prove existence."""

from typing import Annotated

from pydantic import Field

ULID_PATTERN = r"[0-7][0-9A-HJKMNP-TV-Z]{25}"

type HotelId = Annotated[str, Field(pattern=rf"^hotel_{ULID_PATTERN}$")]
type RoomId = Annotated[str, Field(pattern=rf"^room_{ULID_PATTERN}$")]
type BedId = Annotated[str, Field(pattern=rf"^bed_{ULID_PATTERN}$")]
type PriceId = Annotated[str, Field(pattern=rf"^price_{ULID_PATTERN}$")]
type GuestId = Annotated[str, Field(pattern=rf"^guest_{ULID_PATTERN}$")]
type PartyId = Annotated[str, Field(pattern=rf"^party_{ULID_PATTERN}$")]
type StaffMemberId = Annotated[str, Field(pattern=rf"^staff_member_{ULID_PATTERN}$")]
type VenueId = Annotated[str, Field(pattern=rf"^venue_{ULID_PATTERN}$")]
type BookingId = Annotated[str, Field(pattern=rf"^booking_{ULID_PATTERN}$")]
type RoomReservationId = Annotated[
    str, Field(pattern=rf"^room_reservation_{ULID_PATTERN}$")
]
type RoomKeyId = Annotated[str, Field(pattern=rf"^room_key_{ULID_PATTERN}$")]
type PartyDetailId = Annotated[str, Field(pattern=rf"^party_detail_{ULID_PATTERN}$")]
type ActivityId = Annotated[str, Field(pattern=rf"^activity_{ULID_PATTERN}$")]
type ActivityReservationId = Annotated[
    str, Field(pattern=rf"^activity_reservation_{ULID_PATTERN}$")
]

type ThreadId = Annotated[str, Field(pattern=rf"^thread_{ULID_PATTERN}$")]
type ThreadRecordId = Annotated[str, Field(pattern=rf"^thread_record_{ULID_PATTERN}$")]
type IncomingThreadRecordId = Annotated[
    str, Field(pattern=rf"^incoming_thread_record_{ULID_PATTERN}$")
]
type RunId = Annotated[str, Field(pattern=rf"^run_{ULID_PATTERN}$")]
type JobId = Annotated[str, Field(pattern=rf"^job_{ULID_PATTERN}$")]
type ScheduleId = Annotated[str, Field(pattern=rf"^schedule_{ULID_PATTERN}$")]
type NotificationId = Annotated[str, Field(pattern=rf"^notification_{ULID_PATTERN}$")]
type InferenceRequestId = Annotated[
    str, Field(pattern=rf"^inference_request_{ULID_PATTERN}$")
]
type ScheduleOccurrenceId = Annotated[
    str, Field(pattern=rf"^occurrence_{ULID_PATTERN}$")
]

type TaskId = Annotated[str, Field(pattern=rf"^task_{ULID_PATTERN}$")]
type CompletionId = Annotated[str, Field(pattern=rf"^completion_{ULID_PATTERN}$")]
