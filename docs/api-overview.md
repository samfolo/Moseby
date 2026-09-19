# Current resource and API contract

This is the canonical API review after the author's iterations. **Selected**
conventions are distinguished from **proposed** paths or still-open behaviour.
It describes the intended model, not what the older SQL currently implements.
See [runtime contract](runtime-review.md), [permissions/tool review](permissions-and-tools.md)
and the [remaining decisions](design-review.md). The first
[Pydantic contract slice](python-contract.md) now makes room search and guest
updates reviewable. It now includes the author's enum, shared amount/range and
payload naming review; approved ULID prefixes and service-status naming are recorded there.
No working gateway or DDL is added.

## Selected conventions

- Plural resource names; multiword names use kebab case.
- `GET /resources` lists without business filters. Pagination and ordering are
  allowed; default order is creation time, with a stable tie-breaker to choose.
  Creation timestamps need adding where the current schema lacks them.
- `GET /resources/{id}` reads one resource; identity comes from the path.
- `QUERY /resources` searches with a structured body. No `/search` suffix.
- PATCH with `update_mask` is the selected partial-update convention across
  resources. No POST-for-update or PUT-for-partial-update convention remains.
- `request_id` identifies the logical command, with operation data in `payload`.
  Retries reuse the ID. Scope, retention and conflict responses remain to specify.
- Semantic lifecycle operations are selected instead of arbitrary status PATCH.
  The exact action separator is not final: colon examples below are proposals.
- Batch get uses `:batchGet`; QUERY with an ID array is the intended adaptation.
  Missing-ID behaviour, response order and limits remain open.
- Public resources and tables differ. Price, price version, bed, room reservation
  and payment-attempt storage do not imply agent-facing endpoints.

Selected update envelope (mask entries exactly match payload field names):

```json
{
  "request_id": "request-123",
  "update_mask": ["dietary_requirements"],
  "payload": {"dietary_requirements": "No peanuts"}
}
```

Domain enum values use SCREAMING_SNAKE_CASE; field masks use exact field names. One DateRange with min_date and
max_date is used throughout; both bounds are required and the end is exclusive.

A mask selects changes; it does not authorise immutable or forbidden fields.
Define omitted versus explicit-null values. Actor identity is resolved by the
application. Mask validation and permissions apply to UI and agent calls alike.
Search is read-only even if it uses inference. Public QUERY filters must not
become arbitrary SQL. Single-result search still uses the collection contract;
a get-by-ID operation remains distinct.

## Hotel, rooms and prices

| Resource | Selected shape | Public/API direction |
| --- | --- | --- |
| Hotel | ID, name, address | GET list/by-ID, PATCH by-ID; author proposed POST `/hotels/{id}` for client-chosen creation identity; collision semantics open |
| Staff member | ID, hotel ID, staff code, names, optional title, role | `/staff-members`; list/by-ID, no `/me`; seed one acting staff member, authentication later |
| Room | ID, hotel ID, label, description, bathrooms, tier, in-service flag, price reference, beds | GET list/by-ID, QUERY with filters, POST create, PATCH update; create-ID location still to settle |
| Bed | ID, room association, type | Internal mutable table; no bed endpoint; included in room views |
| Venue | ID, name, address, capacity; no hotel owner | `/venues` list/read/create; no search needed; back-office edits not part of this agent review |
| Price and versions | Shared stable ID; immutable revisions with minor-unit amount and currency | Repository methods only; room/activity responses include relevant price data |

Room QUERY uses availability_date_range, ID arrays, tiers, number ranges for beds
and bathrooms, bed types and a currency-qualified nightly amount range. ID arrays
use OR within each list and AND between filters; bed types require every listed
type. Current prices are joined into room views. Availability is computed from
in-service state, live holds and reservations, never stored as a room flag.
A successful search does not hold capacity. A room has one enum tier (standard,
VIP or explicit unknown); the `tiers` filter matches any supplied tier.

Room category and whether occupancy always equals bed sleeping capacity remain
open. Bed-type capacities may be a small code mapping or table. No bed status
system is selected. Joins within a domain service are acceptable; cross-service
access should use deliberate interfaces rather than arbitrary table access.

## Checkout, bookings and keys

| Resource | Selected shape | Public/API direction |
| --- | --- | --- |
| Checkout | Proposed payer/party/guests, items, dates, quoted rates/adjustments/total/currency, expiry, phase, resulting booking | `/checkouts` create/read/edit while editable; semantic hold/release/approve/pay/cancel actions, exact paths and phases open |
| Checkout items / quote / hold | Items and allocations, pinned amounts, hold deadline and consumed/released outcome | Embedded/internal; hold granularity remains open |
| Payment attempt | Checkout/quote, request/job/reference, amount/currency, outcome/receipt | Internal integration record; no standalone HTTP API |
| Booking | ID, hotel ID, name, timestamps, current status and revision history, room allocations | `/bookings` list/read and allowed mutations; booking operations own reservation creation and amendments |
| Room reservation | Stable ID, revision, booking ID, room ID, individual dates, cancellation flag and pinned rate | Internal; no standalone room-reservation API |
| Room key | ID, room-reservation association, derived effective access, optional code, deactivated-at/reason | Issuance/read/deactivate operations; top-level `/room-keys` versus room nesting remains open |

Booking creation must preserve checkout confirmation conditions: consume a live
hold and create booking/party/guests/reservations together after required payment
and approval. Removing a reservation endpoint does not bypass this rule. The
API entry point for final booking creation remains to be fixed with checkout.
Room changes and extensions are booking operations; the booking stays confirmed
while the change is prepared. There is no under-revision booking state in the
current contract. Keep original allocations valid until replacement/amendment succeeds. Extension pricing/payment is open.

Keys now reference the reservation, not only the room. They have individual IDs
but no guest owner or independent validity dates. Effective access requires no
explicit revocation, a confirmed booking, an uncancelled reservation, and now
within the reservation's current date range. Extensions carry through automatically.
Parent cancellation makes the key ineffective without setting `deactivated_at`;
that timestamp records explicit revocation. A new stay must not revive an old key.
Exactly how to reference a stable reservation identity with revision storage is
a DDL decision. Keys can expose derived room/booking IDs in responses.

Full billing, extra charges, refunds and physical door integration remain out.

## Parties, guests and activities

| Resource | Selected shape | Public/API direction |
| --- | --- | --- |
| Party | ID, one booking; one or more guests | `/parties` get/query; no independent party creation bypassing checkout |
| Guest | ID, one party, names, age, dietary text, phone/email/preference | `/guests` list/get/query/PATCH; query by party/booking and other agreed criteria |
| Party detail | ID, party ID, freeform text, versioned guest-reference array | `/party-details`; get-by-detail-ID and QUERY by party recommended; path-ID meaning needs final acceptance |
| Scheduled activity | ID, venue, title/type/description, date range, nullable capacity, booking sizes, minimum age, price | `/activities` list/get/create/query/controlled updates; dated instances, not templates |
| Activity reservation | ID/revision, guest, party, scheduled activity, cancellation flag, reason, agreed rate | `/activity-reservations` list/get/query/create and controlled cancellation; exact actions open |

One activity reservation represents one guest; at most one effective reservation
per guest/activity is allowed. Search uses multi-ID filters and defaults to effective
results; explicit false/null supports ineffective/all results. Party attributes
the booking for charges. Group
requests can create several records; all-or-nothing behaviour is still proposed.
Guest overlaps and shared venues are allowed. Activity capacity is enforced;
venue capacity remains admin configuration. Cancellation is terminal.

Itineraries are activity-reservation QUERY results by guest and time, enriched
with activity details. No dedicated itinerary route is needed. Activity views
may include computed capacity, effective reservation count and remaining places.
A count-only query variant is proposed; never count historical revisions as seats.
Live holds participate if activity holds are adopted. Availability check and
reservation acceptance remain one transaction.

Dietary changes use the general guest PATCH. A supporting party detail can be
included in the operation and saved atomically; the command shape for that detail
is open. No separate dietary-updates endpoint. Classification happens outside
write transactions; ambiguous/failed classification needs an explicit outcome.
Guest and activity fields are mutable without change history. Party-detail edit
history is not yet settled. Walk-ins without stay bookings remain unmodelled.

## Conversation resources

| Resource | Selected shape | Gateway direction |
| --- | --- | --- |
| Thread | Stable ID, creator, immutable permission snapshot, title, current-state projection | `/threads` list/get/POST create; no cross-thread search initially |
| Thread mailbox / inbox | Durable input, thread, source, queue/steer mode, target run if any, order/handling state | Accept input through a controlled operation; route/table names open |
| Run | Thread, initiating inputs, state/wait, cancellation intent/outcome, times | Read and semantic cancellation; no arbitrary status PATCH |
| Thread record | Thread, sequence, kind, persisted format version, typed payload, run/call/job links | Top-level `/thread-records`; access always checks its thread; QUERY by thread/cursor proposed |

Creator-only thread access is selected. Frozen thread capabilities do not preserve
revoked grants: reads and executions also need current authority. New privileges
require a new thread. Exact permission codes and data-scope representation remain
for the permission pass. Related jobs, records and published events must not bypass
thread access. See [permissions and tools](permissions-and-tools.md).

The agent may invoke authorised application operations, not forge internal
records or arbitrary worker claims. Model context is a projection of durable
history. Classifier records are excluded from the main-model message projection.

## Work, scheduling and publication

| Resource | Selected shape | Gateway direction |
| --- | --- | --- |
| Job | Overall operation, actor/request/call/run links, workflow type/state, result/error, times | `/jobs` list/get/create; creation limited to registered operations; no search |
| Task | One independently claimable/retryable unit, job link, handler/input, status/result, attempt counter/timing | Separate internal resource/table for learning fan-out; public task API not yet selected |
| Worker claim | Task ID, owner, unique token, heartbeat, expiry | Separate internal table; no public CRUD |
| Schedule | Timing expression, action/input, destination, author, enabled/version information | `/schedules` create/list/get/PATCH; semantic actions where warranted |
| Schedule occurrence | Particular due firing, schedule/revision, intended time, accepted time, job/outcome | Separate table and gateway-readable resource selected; proposed `/schedule-occurrences` list/get with parent scoping |
| Notification/publication | Stable event/request identity, audience, payload, stream position, published time | `/notifications` list/get/create with cursor-based reading; no search; SQLite-backed |

Job/task separation is now selected for learning. Workers claim tasks, not both
job and task concurrently. Initial jobs may have one task; bounded registered job
handlers can demonstrate fan-out. See runtime contract for orchestration and
atomic task completion. Attempts are task counters/timing initially, not a required
public attempts resource. A job can expose aggregate retry information.

Occurrences record a due firing being accepted, not every hypothetical future
cron match and not only successful completions. Save occurrence and initial work
together. A schedule edit does not retract accepted work. SQLite publication
appends an event and marks it published atomically; consumers own their cursors.
No Kafka or mandatory future queue migration is selected.

## Internal boundaries

Tool calls remain in assistant messages; tool results link to their call IDs.
Classifier decisions and inference-request metadata are typed internal records.
The completion outbox holds pending delivery, not request deduplication.
`request_id` is the idempotency key, but stored operation/input/outcome information
must make it effective. No public request-receipts resource is needed; physical
storage is an implementation choice. Booking/reservation revisions stay internal.

All route examples remain design documentation. The SQL is older and has not
been migrated to this contract. The [checklist](design-review.md) records remaining
behavioural decisions; no schema or framework is silently selected by this file.
