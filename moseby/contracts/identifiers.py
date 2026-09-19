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

