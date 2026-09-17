# Domain schema draft

[draft.sql](draft.sql) is the current executable SQLite structure for the
hotel-side concepts reviewed so far. It is a review artifact, not a production
migration or a complete booking engine. It can be loaded into an empty database.
The [design notes](../docs/data-modelling.md) preserve decisions and open questions.

No performance indexes are included. Primary keys and the one-to-one party link
are structural constraints; SQLite may create internal indexes for them. Staff
code uniqueness, hotel-scoped room labels, and other business uniqueness rules
are left for the next constraint pass.

## Objects and relationships

| Table | Purpose and relationships |
| --- | --- |
| `hotels` | Name and address of the hotel |
| `hotel_staff_members` | Hotel, staff code, names, title, role |
| `prices` | Stable identity for a rate shared by rooms or activities |
| `price_versions` | Ordered, immutable amounts and currencies for a price |
| `rooms` | Hotel, label, description, beds, bathrooms, occupancy, category, tier, operational status, shared price |
| `bookings` | Confirmed booking identity, hotel, name, immutable creation time |
| `booking_revisions` | Ordered status history and cancellation reason |
| `parties` | A party associated with one confirmed booking |
| `guests` | Party membership, names, age, dietary requirements |
| `party_details` | Freeform party information and the list of referenced guests |
| `room_reservations` | Ordered room allocations, stay dates, status, agreed price version |
| `room_keys` | Issued room access with its own validity period and deactivation information |
| `venues` | Multipurpose venue, address and capacity |
| `scheduled_activities` | A dated activity, venue, description, capacity, booking sizes, minimum age, shared price |
| `activity_reservations` | Ordered activity reservations associated with a party and, provisionally, an individual guest |

A booking has no primary guest field. Guests reach the booking through their
party. Rooms have no permanent guest assignments. A room key opens one room.

`parties.booking_id` is unique: a booking has at most one party. A transaction
creating the stay still needs to create its party and at least one guest.
The database does not currently enforce those minimum child counts.

## Current state and history

The four ordinary views select the latest revision for each identity:

- `current_booking_revisions`
- `current_price_versions`
- `current_room_reservations`
- `current_activity_reservations`

They are named queries, not materialised caches. History rows contain the full
state represented by that revision. This does not mean every property of every
object is event-sourced: hotel descriptions and guest names, for example, do not
have revision tables in this draft.

Revision triggers prevent overwriting/deleting history, replacement of existing
revision numbers, and gaps in the sequence. Room and activity reservation
revisions keep the same associated resources. Choosing revisions and retrying
conflicting writes remain application responsibilities.

### Booking cancellation is terminal

The first booking revision must be `confirmed`. A `cancelled` revision needs a
reason. No further booking revision may be appended after cancellation.
Booking again creates a new booking rather than reinstating the old one.
The full transition graph for other statuses, especially `error`, is still open.

`uncancelled_activity_reservations` implements only the agreed cancellation
predicate: latest activity status is active and parent booking is not cancelled.
It retains historical activity rows without inserting child cancellations.
This view is not a complete capacity calculation. The meaning of other parent
statuses, historical reporting, and concurrent reservation changes still need
policy. No physical delete cascade represents a business cancellation.

Individual activity reactivation has not been made terminal by the booking
rule. If supported, it requires a fresh capacity check.

## Provisional representation choices

These make the draft concrete without claiming the author has settled them:

- Text IDs, with the ID format still unselected.
- Integer Unix timestamps in UTC, preserving the earlier draft convention.
- Integer currency minor units for amounts. This does not assume every currency
  has two decimal places. Supported currencies and validation remain open.
- A price version is identified by `(price_id, revision)`. Highest revision is
  current for new quotes. Reservations pin their agreed version.
- Price-per-night and activity charging units are interpreted by their use.
  The activity charging unit remains open; no pricing calculation is implemented.
- `max_occupants` on rooms; no minimum occupancy. Category, tier, and operational
  status remain text while their meanings and allowed values are reviewed.
- A staff member belongs to one hotel in this draft; multi-hotel staff membership
  is not modelled. Code uniqueness scope remains open.
- Address columns include an optional country code. No claim of a complete
  international address standard is made.
- Party detail references are a JSON array. SQL checks only that it is an array;
  Python must validate element types, duplicates, and membership in the party.
  `NULL` means no accepted classification yet; `[]` means no referenced guests.
  Failure versus ambiguity versus waiting still needs API design.
- Keep the earlier one-guest-per-activity-reservation structure while changing
  its parent reference to party. A party quantity-only reservation remains an
  alternative. Individual guest/party consistency needs validation.
- `deactivated_at` records key revocation without an active/inactive column.
  Retention of disabled keys is not decided. No door-lock integration exists.
- A null activity capacity means no activity-level limit. How this interacts
  with finite venue capacity remains open. Maximum booking size may also be null.
- Zero is a possible price. Choosing a confirmed booking does not imply payment
  has been received; confirmation and payment remain distinct concepts.

## Boundaries still to model

These are not hidden assumptions or placeholder runtime tables. They remain
explicit work to do before the model supports a complete booking journey.

### Drafts and holds

Known: a draft describes the desired stay; a hold secures capacity temporarily;
confirmation consumes the hold and creates a confirmed booking. Hold expiry and
room checkout are separate times.

Still open: draft contents and guest-data retention, one hold per room versus a
set of rooms, which records link drafts to parties, expiry/consumption fields,
quote locking, and the transaction that confirms the stay. An expired hold must
stop blocking capacity without waiting for cleanup. No draft/hold DDL has been
invented to force these unresolved choices.

### External service requests and jobs — next design pass

Preserve the desired asynchronous behaviour:

1. A tool submits work and obtains a stable job reference.
2. The run can stop waiting without losing the job.
3. Later updates report progress, completion, failure, or a need for more input.
4. Those updates can let the appropriate run continue.

A simulated integration can exercise that contract. We do not need a set of
real vendors, a general integration registry, or stored arbitrary endpoint URLs
for the first experiment. These are proposed boundaries, not an implementation.
Job properties, update history, correlation with tool calls/runs, and restart
behaviour still need modelling after the runtime walkthrough.

### Payment evidence — proposed minimum, no provider integration

We need to distinguish an agreed price from evidence that money was paid.
A possible small record would include identity, the draft/booking it relates
to, amount, currency, source, an external transaction/reference when present,
reported outcome and time. These fields are a proposal, not a selected payment
schema. The pre-confirmation association is unresolved with the draft model.

A source must distinguish simulation from a staff-recorded external payment or
an eventual provider confirmation. A simulation cannot establish that real money
moved. A staff-recorded payment is an assertion, not provider verification.
No card numbers, payment-provider credentials, charge execution, refunds, or
payment-provider state machine are being implemented. Stripe integration is
not required for this modelling pass. See the
[Stripe payment object description](https://docs.stripe.com/payments/payment-intents)
for the distinction between amount/currency and a payment's lifecycle.

### Notifications

Changed activities need notifications to affected parties/guests. Recipient
contact details, delivery attempts, and an email operation remain to be designed.
No emails have been sent and no provider is configured.

### Agent runtime

Threads, thread records, runs, cued inputs, model requests, pending tool work,
schedules, and claims remain in [runtime notes](../docs/agent-runtime.md).
The author is still reviewing that list; this pass does not invent their DDL.

## Deferred scope

- Grouped trip workflows, pre-packaged stays, and reserved VIP/standard activity
  quotas. Grouping a trip does not require separate capacity tiers.
- Arrival/departure logbook: there is no reliable complete tap-out signal.
- Discounts, room-credit accounting, and a full payment integration.
- Semantic retrieval, code execution, and subagents.

## Rules still to verify

This is deliberately not a finished concurrency or constraint design. Remaining
rules include room/hold overlap, aggregate room occupancy over time, activity
capacity, age and booking-size checks, cross-hotel references, guest/party
consistency, duplicate active activity reservations, quote timing, operational
room restrictions, and the complete status transitions. A hold, reservation,
and payment must not be assumed to commit atomically across an external vendor.

## Inspect the draft

Requires SQLite 3.38+ for the JSON functions and `unixepoch()` used here.

```sh
sqlite3 :memory: '.read schema/draft.sql' 'PRAGMA foreign_key_check;'
```

Every database connection must enable `PRAGMA foreign_keys = ON` before starting
a transaction. This script's setting applies only to the connection loading it.
SQLite has one simultaneous write transaction per database, not one permanent
writer or one row change at a time. A transaction can change many rows. Read and
write transactions are described in [SQLite's documentation](https://www.sqlite.org/lang_transaction.html).
