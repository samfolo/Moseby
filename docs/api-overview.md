# Resource and API overview for review

This is a first API sketch, not approved routes, an OpenAPI definition, or new
DDL. It consolidates current decisions, including changes not yet in the SQL.
Paths and operation boundaries below are proposals for the author's iteration.
Fields describe logical resources; one row here does not imply one new table.

## Shared request shape

Use `request_id` and a separate `payload` for commands. Example:

```json
{
  "request_id": "request-123",
  "payload": {
    "dietary_requirements": "No peanuts",
    "detail": "Guest reported a peanut allergy at reception."
  }
}
```

A successful response can echo `request_id` and put its result in `payload`.
An asynchronous response can return `job_id`; errors need a stable code and
message. These response details are proposals. Reads use path/query parameters,
not GET bodies; request-ID transport for reads remains open.

Recommended semantics: the request ID identifies one logical command and is
reused on retry, replacing a separate client idempotency-key field. The same
command ID with different input is rejected. Its scope, retention and storage
remain to be selected. Resource IDs, job IDs and tool-call IDs still identify
different objects. One command can cause several notifications: each delivery
needs a stable child identity rather than all recipients sharing one key.

The application supplies the acting staff member and enforces permissions.
Actor identity is not trusted simply because it appears in a client/model payload.
Exact scopes follow API review. There are no universal arbitrary-row mutation
or deletion endpoints. Compound operations preserve their own invariants.

## 1. Hotel, inventory and prices

| Resource | Current logical shape | Candidate API |
| --- | --- | --- |
| Hotel | ID, name, address | `GET /hotels`, `GET /hotels/{id}`, `PATCH /hotels/{id}`; creation/setup can remain seeded |
| Staff member | ID, hotel ID, staff code, names, optional title, role | `GET /staff/me`, `GET /staff`, `GET /staff/{id}`; account administration deferred |
| Room | ID, hotel ID, label, description, bathroom count, tier, in-service flag, price ID | `GET /rooms`, `GET /rooms/{id}`, `POST /rooms`, `PATCH /rooms/{id}` |
| Bed | ID, room ID, type | Return within room details; edit through `POST/PATCH /rooms/{id}/beds[/{bed_id}]`; no global bed listing for the agent |
| Venue | ID, name, address, capacity; no hotel-owner field | `GET /venues`, `GET /venues/{id}`, `POST /venues`, `PATCH /venues/{id}` |
| Price | Stable ID shared by rooms or activities; no hotel-owner field | `GET /prices`, `GET /prices/{id}`, `POST /prices` |
| Price version | Price ID, revision, integer amount in currency minor units, currency, creation time | `GET /prices/{id}/versions`, `POST /prices/{id}/versions`; versions are immutable |

Room category and bed-derived versus independent occupancy remain unresolved.
A bed-type capacity mapping may be code or a small table; no public resource is
required yet. Bed status was discussed but has no selected use or enum.
Venue capacity is descriptive/admin configuration; enforce activity capacity,
not a combined runtime venue cap. Shared venue use does not merge hotel bookings.

Availability is a query, not a mutable room field:
`GET /rooms/availability?hotel_id=...&from=...&to=...`, optionally filtering by
bed configuration, tier or party size once capacity rules are settled.
It uses in-service state, overlapping reservations and live holds. A search result
is not a reservation; the write operation must check again atomically.

## 2. Checkout and stays

| Resource | Current logical shape | Candidate API |
| --- | --- | --- |
| Checkout | ID, hotel ID, proposed payer/party/guest information, items with dates or slots, quoted rates/adjustments/total/currency, expiry, phase, resulting booking reference | `POST /checkouts`, `GET /checkouts/{id}`, `PATCH /checkouts/{id}` while editable; `POST /checkouts/{id}/cancel` |
| Checkout item / quote | Proposed room/activity, dates or slot, participants/quantity, pinned rate version and agreed amount | Part of checkout payload; no separate public CRUD resource |
| Hold | ID, checkout or proposed-change association, protected allocations, expiry, live/consumed/released outcome | `POST /checkouts/{id}/hold`, `POST /checkouts/{id}/release-hold`; return hold through checkout |
| Payment attempt | ID, checkout and quote reference, amount/currency, external job/reference, outcome, receipt reference | `POST /checkouts/{id}/pay`; inspect its job/status through checkout; simulated integration, no card/refund API |
| Booking | ID, hotel ID, name, creation time, current status and revision history, cancellation reason | `GET /bookings`, `GET /bookings/{id}`, descriptive `PATCH`, `POST /bookings/{id}/cancel`; completion operation subject to policy |
| Room reservation | Stable ID, revision, booking ID, room ID, its own check-in/out, status, pinned price version | `GET /bookings/{id}/room-reservations`, `GET /room-reservations/{id}`; explicit change-room/amendment operations below |
| Room key | ID, room ID, optional code, effective-from/to, deactivated-at, reason | `GET /rooms/{id}/keys`, `POST /rooms/{id}/keys`, `POST /room-keys/{id}/deactivate`; validity edits need review |

Proposed approval route: `POST /checkouts/{id}/approve`. The exact relationship
between approval, hold acquisition and entering payment remains to be reviewed.
Booking creation is the validated completion of checkout, not a general
`POST /bookings` that bypasses a live hold and payment evidence. The local
conversion creates booking/party/guests/reservations and consumes the hold together.
Terminal cancellation has no restore endpoint. Expired holds cannot be consumed.

Proposed room operation: `POST /room-reservations/{id}/change-room` takes the
replacement and proposed adjustment. Keep the old room until the replacement
is secured; commit the swap together under the same booking. Whether this
returns a pending amendment/job or completes immediately depends on payment.
An extension is a proposed operation against a room reservation; its workflow,
extra-rate calculation and relationship to payment are still open. Do not expose
unrestricted date/status PATCH that bypasses capacity checks.

Every room reservation already has its own stay dates. Room subtotal is the sum
of each agreed nightly rate times its nights. Night boundaries remain a query/
calculation decision. Full billing, extra charges and refunds are deferred.

The key-to-stay association is still a gap: current keys reference rooms only.
Bookings permissions cover key actions, but permissions do not establish which
stay an issued key belongs to. Do not pretend a booking-scoped key query is
already supported by that relationship.

## 3. People and activity participation

| Resource | Current logical shape | Candidate API |
| --- | --- | --- |
| Party | ID, one booking ID; one or more guests | `GET /parties/{id}`, `GET /bookings/{id}/party`; created through checkout |
| Guest | ID, one party ID, names, age, dietary text, optional phone/email/contact preference | `GET /guests`, `GET /guests/{id}`, `PATCH /guests/{id}`; creation through checkout, no permanent human identity |
| Party detail | ID, party ID, freeform evidence, versioned JSON guest-reference list | `GET /parties/{id}/details`, `POST /parties/{id}/details`; text editing/reference correction remain for review |
| Scheduled activity | ID, venue ID, title/type/description, start/end, nullable capacity, min/max booking size, minimum age, price ID | `GET /activities`, `GET /activities/{id}`, `POST /activities`, controlled `PATCH /activities/{id}` |
| Activity reservation | Stable ID/revision, guest ID, party ID, activity ID, active/cancelled, cancellation reason, pinned price version | `GET /activity-reservations`, `GET /activity-reservations/{id}`, `POST /activities/{id}/reservations`, `POST /activity-reservations/{id}/cancel` |

`/activities` means dated scheduled activities, not a second template resource.
Activity creation/configuration and participant reservations are distinct actions.
Whole-activity cancellation and capacity-reducing edits still need policy; a
reschedule can affect existing reservations and must arrange notifications.

Reservation creation can accept a list of participants while storing one logical
reservation per guest. Mixed parties need individual attribution and guest-party
validation. Proposed group behaviour is all-or-nothing, still to approve. Guests
may reserve overlapping activities; capacity checks still apply. Cancellation is
terminal. Rebooking creates a new reservation ID. Walk-ins without stay bookings
are not yet represented.

Derived queries:

- `GET /guests/{id}/itinerary?from=...&to=...`
- `GET /activities/{id}/availability`
- `GET /activities/{id}/participants`

An itinerary has no independent writable resource. Effective reservations and
activity times determine it; notes use party details with guest references.

Proposed compound operation: `POST /guests/{id}/dietary-updates` receives the
new dietary information and supporting detail; save both in one transaction.
The desired combined action is selected; this endpoint/transaction design is a
recommendation. Any necessary inference happens outside the write transaction.
Guest reference classification checks membership; unresolved classification needs
its own outcome. Raw classifier-produced IDs are not freely client-editable.

Contact preference null uses all supplied channels. A specific preference
requires the matching contact value. Missing both contacts needs a staff-facing
outcome; it must not look like successful notification.

## 4. Agent conversation

| Resource | Current logical shape | Candidate API |
| --- | --- | --- |
| Thread | Stable ID, title, current-state projection including active run/wake/cancellation information; operational fields derive from records | `POST /threads`, `GET /threads`, `GET /threads/{id}`; title editing can be separate |
| Input/message | ID, thread ID, source, text/payload, queued/steer intent, optional target run, received/order/handling state | `POST /threads/{id}/messages`; inspect queued inputs through the thread |
| Run | ID, thread ID, initiating input(s), lifecycle state, wait reason, timestamps, cancellation intent/outcome | `GET /runs/{id}`, `POST /runs/{id}/cancel`; creation/resumption normally internal |
| Thread record | ID, thread ID, sequence, record kind, payload format version, typed payload and related run/call/job IDs | `GET /threads/{id}/records?after=...`; only runtime-controlled appends |

One active run per thread, including sleeping. Process the current eligible
message batch in order. A run may make many inference requests and calls.
Input can also be handled by a classifier without a main-model request.

Sleeping/cancellation rules are accepted: a waiting run can resume; a cancelled
run never does. Late results are recorded without reviving it. New user input
or independent scheduled work can initiate a new run when eligible. A due wake
for the cancelled run is consumed/ignored. Previously queued input disposition
and exact cancellation scope remain to be specified.

The durable history contains more than the model receives. Context construction
selects appropriate records; public clients cannot inject arbitrary tool results,
job completions or control records by posting a user message.

## 5. External work, scheduling and published events

| Resource | Current logical shape | Candidate API |
| --- | --- | --- |
| Job | ID, operation and input, request/call/run links, status, timestamps, attempt/retry information, result/error and current claim | `GET /jobs/{id}`, optional filtered `GET /jobs`; domain tools create jobs rather than an unrestricted arbitrary-job API |
| Schedule | ID, action/input, thread or handler destination, one-off/recurring timing, enabled state, actor | `GET /schedules`, `GET /schedules/{id}`, `POST /schedules`, `PATCH /schedules/{id}`; disable via controlled edit |
| Schedule occurrence | ID, schedule/revision reference, intended due time, accepted input and job reference/outcome | `GET /schedules/{id}/occurrences`; generated internally |
| Notification/publication | ID, stable request/delivery identity, event type, recipient/channel or audience, payload, stream position, published time | `POST /notifications` as a constrained domain notification request; `GET /notifications?after=...` as a scoped durable feed; exact feed naming/filtering open |

A notification request and its published event are distinct stages, not necessarily
separate public resources. The latest definition of publication is a durable
append, not proof that a client received it. Append the event and record published
state atomically. Consumers read retained events after their own cursor and own
handling/cursor advancement. Publication is not undone or re-emitted because a
consumer has not advanced. Replay yields the same event ID. No subscriptions or
consumer-cursor management API is required in this pass. Stable ordering/cursor
scope and retention still need defining; request IDs are not stream positions.

Actual email/phone delivery remains simulated. A real delivery adapter can later
consume published events; its external side-effect guarantees remain separate.

Schedule edits do not retract jobs already accepted. Independent scheduled work
can initiate a new run or call a handler. Every occurrence needs deduplication;
reminders check current facts before acting. The scheduler does not do the
business work while scanning schedules.

## 6. Internal resources, with no general client CRUD

| Concept | Information it must retain |
| --- | --- |
| Worker claim (separate table) | Job ID, worker identity, unique token, heartbeat and expiry; at most one current owner |
| Job attempt | Job, attempt identity/number, timing and outcome; separate table versus fields/history remains open |
| Tool call and result | Internal call identity, provider call identity when relevant, name/arguments, originating request/run, job link, result/error; may live as thread-record kinds |
| Inference request | Identity, run, provider/model, submitted context or links identifying it, outcome; full snapshot storage and dedicated-table need remain open |
| Classifier decision | Input, chosen operation or unresolved outcome, validation/execution links; may be a record kind, not a new table |
| Completion outbox | Durable result-delivery intent, destination, stable identity and consumed state |
| Request receipt | Request ID, scoped operation/input identity, accepted job/result; enough to return the same outcome on retry; physical storage open |
| Booking/reservation revision | Stable entity identity, ordered revision, state and recorded time; written through domain operations |
| Record/payload format | Version identifying how to parse data; not a new public API resource |

Accepting a tool call and creating its job is one transaction. Completing work
and recording outbox intent is one transaction. Appending the thread record and
consuming that intent is one transaction. Claim validation participates in the
protected write, not an earlier separate check. No database transaction stays
open during model/network waits.

Permission definitions/role groupings and the integration-handler registry can
start as application configuration; no management tables/endpoints are selected.
Services coordinate repository methods in a shared transaction. The HTTP API and
tool dispatcher should use those same operations. Whether tools call HTTP or
invoke the in-process service directly is still an implementation choice.

## Review boundaries

These are the resources needed by the current scope, not a list of independent
services to build. Checkout totals, availability, itineraries and current-state
views can be derived or embedded. No separate billing engine, physical lock
integration, guest identity service, floor-plan service, notification broker or
arbitrary workflow engine is proposed.

Open details are local to their resources: room occupancy/category, key-to-stay
link, hold/payment phases, extension policy, group booking behaviour, classification
failure, exact runtime states, claims/retention and permission mapping. They remain
visible rather than being silently decided by these example paths.
