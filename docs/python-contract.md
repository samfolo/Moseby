# Python contract draft

Pydantic models are the authored source for data shapes. FastAPI route declarations
supply paths, methods, operation IDs and proposed permission metadata. Generate
[OpenAPI](../openapi.yaml) from those sources; do not edit its schemas separately.
No Python client is needed. TypeScript generation is a later consumer of OpenAPI.

The first contract sample and its conventions were approved before extending the models.
The [next domain review](domain-contract-review.md) lists the added models and their
proposed lifecycle details. This document records the approved foundation.

## First review slice

| Operation | Proposed permission | Purpose |
| --- | --- | --- |
| `QUERY /rooms` | `Moseby.rooms:read` | Search configuration, nightly prices and dated availability |
| `GET /rooms/{id}` | `Moseby.rooms:read` | Read configuration with its current nightly price |
| `GET /guests/{id}` | `Moseby.guests:read` | Read one guest for one stay |
| `PATCH /guests/{id}` | `Moseby.guests:write` | Change only the explicitly masked guest fields |

This is a naming and generation sample, not the full API catalogue. The other
resources remain in [the API review](api-overview.md). Every draft handler raises
501. There is no database access, permission enforcement or running server here.

`x-permissions.anyOf` accepts either the named resource capability or its broad
`Moseby:read` / `Moseby:write` grant. Broad grants preserve all data scopes. The proposed
`x-hotel-scoped: true` additionally limits records through their hotel
association. False removes that ownership filter for shared venues/activities;
it does not remove the permission requirement. These are our extensions, not
built-in FastAPI authorization. The [permission list](permissions-and-tools.md#current-domain-permissions)
covers every capability declared by the current routes. A
filter cannot broaden access. Thread creator/snapshot checks still follow the
existing permission contract when those routes are added.

## Naming and field intent

- Python classes use PascalCase; fields use snake_case. Paths are plural and
  kebab-case. Stable operation IDs use camelCase for eventual client methods.
- Resource IDs now use readable prefixes and canonical uppercase ULIDs, such as
  `room_01ARZ3NDEKTSV4RRFFQ69G5FAV`. Each resource has its own validated type,
  including path parameters. These prefix spellings and the ULID choice are accepted for this draft.
  Request IDs remain caller-supplied retry keys; they are not resource identities.
- `request_id` and `payload` use the agreed envelope. Mask placement is top-level.
- `Field(description=...)` carries short explanations into OpenAPI. Model docstrings
  describe the resource; ordinary comments explain only code-specific choices.
- Rooms include beds and current versioned prices. There are no bed/price routes.
- Guest IDs identify visits, not permanent people. Membership is absent from the
  update payload. The service must validate a patched guest after merging it with
  saved data; checking the partial payload alone cannot enforce contact preferences.
- `UpdateGuestRequestPayload` is a Pydantic-validated `TypedDict` with optional keys. This keeps
  omission distinct from null in both runtime validation and generated types:
  omitting age is allowed, clearing age is rejected, clearing preferred name is allowed.
- The mask must exactly match the supplied keys and cannot contain duplicates.
  Unknown payload fields are rejected. Cross-field validators remain server checks;
  OpenAPI descriptions explain rules that ordinary generated types cannot enforce.

## Shared values and filters

- Named `StrEnum` classes constrain bed types and contact preferences. Wire values
  carry prefixes, such as `BED_TYPE_KING` and `CONTACT_PREFERENCE_EMAIL`. Python
  already scopes members as `BedType.KING`; the wire prefixes help when reading JSON.
- Domain enum wire values use SCREAMING_SNAKE_CASE. Field masks instead name
  payload fields exactly: `dietary_requirements`. `UpdateGuestFieldMask` is a
  constrained string type, with no case conversion or domain enum.
- Descriptive enums support an explicit `UNKNOWN`: bed type, room tier, activity
  type and staff role. Missing required fields and unrecognised strings still
  fail validation; there is no automatic fallback. Unknown staff roles grant
  no permissions, and unknown bed types do not establish sleeping capacity.
  Booking/service/classification states, pricing units and contact channels keep
  their defined choices; uncertainty must not silently select behaviour.
- A room has one required `tier`: `ROOM_TIER_STANDARD`, `ROOM_TIER_VIP` or
  `ROOM_TIER_UNKNOWN`. Search uses optional `tiers`, matching any listed value.
  Omission means no tier filter; an empty list is invalid.
- `SearchRoomsRequestPayload` and `UpdateGuestRequestPayload` follow the selected
  operation naming convention. Resource models remain distinct from requests.
- `Amount` contains `value` in integer minor units and `currency`. Currency is an
  ISO 4217 code, not a country code; the current validator checks three uppercase
  letters, not membership in the currency registry. `NonNegativeAmount` restricts
  prices to zero or above without asserting that all monetary values must be positive.
- `NumberRange` uses inclusive `min_value` / `max_value` integer bounds. Either may
  be omitted; at least one must be supplied. Equal bounds mean an exact match.
  `AmountRange` adds a mandatory currency and expresses bounds in minor units.
  Filters may have negative bounds; stored nightly prices cannot be negative.
- `DateRange` uses `min_date` / `max_date` for offset-aware timestamps. The lower
  bound is inclusive and upper bound exclusive; a bounded interval must have
  positive duration. Both bounds are required in this draft; one-sided date
  searches are not currently exposed. There is one DateRange model, including for
  reservations. Keys inherit reservation dates rather than storing their own.
  UTC normalization belongs in the service; this
  does not decide hotel-local billing nights or timestamp storage.
- A supplied `availability_date_range` means return only rooms available throughout it:
  in service, with no overlapping reservation or live hold. Without it, no dated
  availability filter applies. The old `available` boolean and `RoomMatch` wrapper
  are removed; search returns rooms. Searching never holds capacity.

## Reviewed choices and remaining details

The sample is approved; the explicit remaining details below are still open:

- The initial bed vocabulary is single, twin, double, queen and king. It is a demo
  catalogue, not an international sizing standard. Dimensions, single/twin meaning
  and capacity mapping still need agreement; no sleeping-capacity formula is added.
- Search ID fields use arrays: OR within each ID list, AND across filters. Each
  list accepts 1–100 IDs; omitted filters add no restriction, and duplicates must
  not multiply results. Pagination is one flat list with one cursor. `bed_types`
  retains its distinct requirement to contain every listed bed type; it is not
  an identity filter. ID search is not the ordered batch-get contract.
- `number_of_beds` and `number_of_bathrooms` take number ranges. `nightly_amount`
  takes an amount range for current nightly prices, not a total-stay quote.
- `service_status` replaces the public `in_service` boolean with a named
  enum: `ROOM_SERVICE_STATUS_IN_SERVICE` or `ROOM_SERVICE_STATUS_OUT_OF_SERVICE`.
  `service_statuses` matches any listed value. This preserves the two conditions
  already agreed; it does not make held/booked/available permanent room states.
  Combining an availability date range with only out-of-service rooms matches nothing.
  This contract choice is accepted; database representation remains unchanged.
- Pagination proposes a default of 50, maximum 100 and opaque cursors tied to the
  same query. Ordering and cursor implementation remain unimplemented.
- First/last/preferred names remain freeform strings. No middle-name field is added;
  names are not assumed unique. Dietary requirements and contact fields can be
  cleared with null. Contact syntax and deliverability validation remain open.
- Permission names and hotel scoping above await the permissions pass. Supporting
  party details in a guest update remain a separate unresolved payload choice.
- Pydantic's generated `Id` titles are left untouched; they are schema labels, not UI text.

## Identifier choice

[ULIDs](https://github.com/ulid/spec) and [UUIDs](https://www.rfc-editor.org/rfc/rfc9562.html)
are both 128-bit identifiers. ULID uses a 48-bit millisecond timestamp and an
80-bit random part; its canonical text is 26 characters. UUIDv7 also orders by
millisecond time and fits existing UUID tooling; Python 3.14 provides
[`uuid.uuid7()`](https://docs.python.org/3/library/uuid.html#uuid.uuid7).
ULID is drafted here for the author's readability preference, not because this
system needs a larger ID space. A generation library is not selected yet.

Prefixes help reject cross-resource mix-ups but cannot prove existence, membership
or authorization. Canonical uppercase avoids two spellings of the same ULID;
the validator also rejects values above 128 bits. Prefixed strings require text
storage or an adapter for native UUID columns. Their sort order groups by resource
prefix first; within a prefix it follows the ULID. Neither format supplies a
reliable global event order or replaces explicit thread sequences and timestamps.

## QUERY compatibility

[OpenAPI 3.2.1](https://spec.openapis.org/oas/v3.2.1.html#path-item-object)
defines `query` as a Path Item operation. Pydantic's
[field descriptions](https://docs.pydantic.dev/latest/concepts/json_schema/)
are included in its generated schemas.

Verified locally with Python 3.14.6, Pydantic 2.13.5 and FastAPI 0.141.1:
FastAPI routes and validates QUERY bodies, but emits OpenAPI 3.1.0 and omits the
QUERY request body from that document. The draft explicitly references the
already-generated Pydantic request schema in `openapi_extra.requestBody` and
exports version 3.2.1. Merely changing the version would not fix the missing body.
This small compatibility annotation now lives in `route_metadata.query_body` so
all QUERY declarations retain their required request body consistently.

FastAPI is used for this contract draft. This check does not establish broad 3.2
feature support, browser/proxy compatibility, documentation-UI support or TypeScript
generator support. Verify the chosen frontend generator against QUERY before adopting it.

The draft passed package installation, generation, local schema-reference checks,
QUERY body validation, enum and resource-prefix checks (including paths), ULID
bounds, amount/date/number ranges, and guest mask/null/contact checks.
Valid requests reach the 501 stubs; invalid inputs receive 422. This verifies the
contract boundary, not availability, authorization or persistence.

## Generate

From the repository root, using Python 3.14:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[contract]'
.venv/bin/python -m moseby.contracts.export
```

The direct dependency versions record the combination checked for this draft.
They are not a complete transitive dependency lock; choose that workflow with the
remaining tooling. No worker, scheduler, inference or database library is added.
