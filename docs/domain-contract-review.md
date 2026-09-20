# Next domain models

The reviewed foundation is committed as `82fa85e`. This batch extends the Pydantic
contract for review; its handlers still return 501 and make no database changes.
Field descriptions and enum docstrings appear in the generated OpenAPI.

## Reading order

| File | What to review |
| --- | --- |
| [addresses.py](../moseby/contracts/addresses.py) | Shared postal fields; nullable where absent; two-letter country code |
| [hotels.py](../moseby/contracts/hotels.py) | Name, address, identity and creation time |
| [staff_members.py](../moseby/contracts/staff_members.py) | Hotel, staff code, names, title and initial concierge role |
| [venues.py](../moseby/contracts/venues.py) | Shared location and administrative capacity, with no hotel owner |
| [bookings.py](../moseby/contracts/bookings.py) | Current booking state and embedded room allocations with agreed rate versions |
| [parties.py](../moseby/contracts/parties.py) | One party references one booking; no independent party creation |
| [guests.py](../moseby/contracts/guests.py) | Added search by IDs, party, booking and lexical name |
| [party_details.py](../moseby/contracts/party_details.py) | Evidence text, versioned guest references and proposed classification outcomes |
| [room_keys.py](../moseby/contracts/room_keys.py) | Reservation-bound validity, issuance and deactivation |
| [activities.py](../moseby/contracts/activities.py) | Dated event, venue, capacity, booking-size range, age and price |
| [activity_reservations.py](../moseby/contracts/activity_reservations.py) | One guest per reservation, cancellation and current itinerary information |

## Relationships retained

- Guest → party → booking → hotel. There is no primary guest, cross-visit identity
  or direct guest-to-booking field. Guest searches can still resolve by booking.
- A booking embeds its allocations. Each allocation has a stable ID and current
  accepted revision. Keys reference that stable allocation ID and have no guest owner.
- An activity reservation belongs to a guest and that guest's party. Its nested
  activity summary supplies current times for the itinerary; its agreed price
  retains the reservation's rate version. Neither is a payment ledger.
- Room and activity prices reuse the amount shape. Beds, prices, price versions
  and room reservations still have no public CRUD routes.

## Resolved in the latest consistency pass

- Domain enum wire values are SCREAMING_SNAKE_CASE. Field masks match the
  snake_case payload keys exactly; identifiers and permission codes retain their
  agreed spelling.
- Room `tier` uses standard/VIP/unknown values; search `tiers` matches any supplied
  tier. Bed types and staff roles also allow explicit unknown.
  Required fields remain required and arbitrary strings are rejected. Operational
  states, contact channels and pricing units do not gain an unknown fallback.
- One `DateRange` uses required `min_date`/`max_date` bounds. All scheduled intervals
  use `date_range`; keys inherit reservation dates; room search uses `availability_date_range` to
  describe its purpose. There are no separate window models or `period` fields.
  Missing, null, reversed and equal bounds are rejected. The upper bound is exclusive.
- Search identity filters accept lists, including guests, parties, bookings,
  activities, hotels and venues. They are OR within each list and AND across
  filters, with one flat paginated result. They select existing records rather
  than generating combinations. Lists are nonempty and capped at 100 entries.
- Both room and activity reservations record `cancelled` plus a reason when true.
  Passing the activity/end date needs no write. Activity reservation `effective`
  means not explicitly cancelled and permitted by the parent booking. It does not
  mean upcoming, ongoing or attended. Searches default to effective results;
  explicit false/null can inspect ineffective/all records. Filters still intersect:
  `cancelled: true` with `effective: true` matches nothing.
- At most one effective reservation per guest and scheduled activity is allowed.
  This is a service/database rule, not something an individual Pydantic object
  can enforce. Rebooking may leave multiple cancelled historical reservation IDs.
- Booking statuses are confirmed/cancelled/completed. The earlier notes left
  under-revision open; the current draft now follows the separate-change direction.
  Preparing an amendment keeps the booking confirmed and its existing allocations
  valid until the replacement succeeds. Amendment/checkout payloads still need review.

## Concrete proposals needing review

1. **Remaining lifecycle rules.** What marks a booking completed remains open.
   Confirmed and completed bookings preserve uncancelled activity reservations;
   cancelled bookings release them. New reservations and date changes must keep
   activities within the guest's stay. Historical queries must use
   historical eligibility. Terminal cancellation still requires transaction/history
   checks; these read models cannot enforce transitions by themselves.
2. **Group reservation creation.** The activity price and booking-size models
   were accepted. This demo currently exposes per-guest pricing. Adding a court/group
   pricing unit and defining atomic group reservation creation remain future details;
   no reservation-creation endpoint is invented here.
3. **Guest references.** Pending, resolved, ambiguous and failed are proposed
   outcomes. Only resolved references carry guest IDs; resolved with an empty list
   means no guests were identified. The proposed create flow saves evidence as
   pending, then classifies outside the transaction. Save timing, retries and staff
   handling of ambiguous/failed results still need review. A client cannot submit
   inferred IDs through the creation payload.
4. **Key operations.** Top-level `/room-keys` is proposed for list/read/issue.
   `:deactivate` and activity-reservation `:cancel` use proposed action paths.
   Review notes stay here, outside operation metadata. Deactivation requires a
   reason and server-recorded time. Access follows the rule below; its enforcement
   requires service checks.
   The optional key code is a demo label; physical credential handling is deferred.
5. **Postal/staff fields.** Address fields can be absent; code validation checks
   shape, not a country registry. Staff role is concierge or explicit unknown (no grants); exact
   grant assignments and staff-code uniqueness remain outside these models.

## Room-key access

Keys have no independent date range. The service derives `effective` at read/use
time from all of these conditions:

- The key has not been explicitly deactivated.
- Its booking is confirmed and its room reservation is not cancelled.
- The current reservation has `min_date <= now < max_date`.

An extension of the same reservation automatically extends access for its
nonrevoked keys. Explicit revocation is permanent. Cancelling the booking or
reservation removes access immediately; it does not fabricate a `deactivated_at`
for each key. That timestamp records explicit key revocation only. An ineffective
key can therefore have no deactivation timestamp.

A reservation's room association stays fixed. Moving rooms replaces the allocation;
keys linked to the old allocation never gain access to the replacement room.
The `effective` response is a snapshot; actual use must check current state again.
Physical lock synchronization is outside this demo.

## Filter and response conventions

- `DateRange` consistently uses `min_date`/`max_date`, with offset-aware instants
  and an exclusive end. The caller omits the whole filter when no date restriction
  is wanted. A service normalizes instants to UTC.
- List routes accept pagination only. QUERY routes combine structured filters;
  IDs/names/relationships do not become GET query filters.
- Activity date searches match overlap, not containment. `places_required` checks
  remaining capacity; it does not by itself prove group size or guest eligibility.
  Null capacity means unlimited. `reserved_places` is a derived effective count,
  never a stored booking flag or a count of history rows. Activity holds remain open.
- Activity-reservation searches default to `effective: true`. A non-cancelled
  reservation can be ineffective after parent cancellation. Date filtering separately
  selects the upcoming or past activity interval.
- Created timestamps are proposed for the new read models, supporting the agreed
  list ordering. Adding missing timestamps to older storage remains migration work.

## Permission placement

[domain_api.py](../moseby/contracts/domain_api.py) places proposed permissions next
to each operation. Bookings cover keys; guests cover parties/details; activities
cover reservations and itineraries. Hotels, staff members and venues have their
own proposed read capabilities. Catalogue reads for shared venues/activities do
not invent hotel ownership. Guest-associated records still require hotel scope.
Names use `moseby.resource:read/write`, with `moseby:read/write` as alternative
broad grants. All ownership checks still apply. These annotations do not implement
authorization or finalize the role matrix.

## What this validation proves

Checks cover enum/ID shapes, interval and booking-size ordering, cancellation and
deactivation snapshots, unique resolved guest references, QUERY request bodies,
pagination-only list routes and all local OpenAPI references. All 30 operations
have unique IDs and permission metadata; valid requests reach the draft 501
handlers, and invalid examples receive 422.

Membership, room overlap, capacity races, authorization, idempotency and terminal
transitions require saved state and transactions. Pydantic alone cannot prove them.

## Following batches

- Checkout, quote, holds and payment evidence: preserve the accepted boundaries
  while reviewing phase names, hold scope and late-result handling.
- Threads, inbox, runs and typed records: keep provider payloads separate and
  preserve classifier-only decisions without duplicating the original user text.
- Jobs, tasks, claims, schedules, occurrences and publication: specify the runtime
  states and links, then review their read/command APIs and tool permissions.

Remaining setup/create/PATCH operations, room batch-get and group reservation
creation will follow the corresponding payload and lifecycle review. This batch
does not claim to complete the entire API or introduce new workers or integrations.
