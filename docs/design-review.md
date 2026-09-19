# Remaining design decisions

This is the review checklist for the current design. It consolidates the
[domain notes](data-modelling.md), [runtime notes](agent-runtime.md), and
[SQL draft and guide](../schema/README.md), reviewed against commit `365a435`.
The subsequent A/B review is captured in [Checkout lifecycle](checkout-lifecycle.md).
The final [runtime review](runtime-review.md) consolidates the subsequent
permissions, execution, recovery and scheduling walkthrough.
The [API contract](api-overview.md), [runtime contract](runtime-review.md), and
[permission/tool review](permissions-and-tools.md) are the current review surfaces.
This checklist adds no tables or indexes; answered parts are noted below.

Unchecked items are questions, not instructions to build more features. Answer
one section at a time; a deliberate simplification or deferral is a valid answer.
Record the answer against its ID, then update the relevant notes and SQL.

## What is already settled

Do not reopen these unless the author changes direction:

- Staff-facing application; hotel, booking, party, and guest are distinct concepts.
- A confirmed booking has a hotel. A party has a booking. A guest has a party.
  Return visits create new guest records; there is no permanent guest identity.
- No primary guest reference on bookings and no permanent guest-room assignment.
- Draft preparation is separate from confirmed bookings. A temporary hold is
  consumed on confirmation; its expiry is different from the stay dates.
- Booking cancellation is terminal. Rebooking creates a new booking.
- Checkout is editable without holding capacity; entering payment requires a
  live hold. Back out of a hold before editing. A booking requires confirmed
  payment; staff approval is also requested, with ordering still under review.
- Technical errors are operation failures, not booking states. Room changes do
  not replace the whole booking. Added travellers can have separate bookings.
- Parent booking cancellation makes activity reservations ineffective without
  rewriting all their historical records.
- Shared prices have stable IDs and versions. Previously agreed prices must
  survive later rate changes.
- Party details contain text and a list of referenced guests. Jev is selected
  for the guest-reference experiment; dietary requirements remain individual.
- A key follows its reservation dates, with no independent validity times. Access
  requires a confirmed booking, uncancelled reservation, and no key revocation.
  Explicit deactivation records a time and freeform reason; effective access is derived.
- Venues are multipurpose. Activities have minimum/maximum booking sizes and
  minimum age. Extra group-size steps are out. Null activity capacity means no
  activity-level limit.
- Python, Pydantic, a manually written agent loop, durable history, and UTC.
- Thread records hold history; threads project current state. One active run
  per thread, concurrency across threads, and execution independent of clients.
- Cued, added-to-history, and included-in-request are distinct milestones.
  Eligible input and due wake times are discovered from saved state by polling.
- No performance indexes in this pass. Lexical search is sufficient initially.

## Review map

| Section | Judgement to make | Needed before |
| --- | --- | --- |
| A. Creation | How a draft becomes a confirmed stay | Draft/hold DDL and confirmation operation |
| B. Changes and access | What survives a change or cancellation | Safe booking changes and key operations |
| C. Activities | What one reservation means and how events can change | Final activity rules |
| D. Prices and payment | What is agreed and what counts as payment evidence | Quoting and confirmation |
| E. People, contacts and audit | Who may act, who is notified, and what is recorded | Useful API/tool boundaries |
| F. Thread execution | How input becomes a durable run | Runtime DDL and turn loop |
| G. Work and recovery | How tools/jobs finish, wait, fail and resume | Async demonstration and restart behaviour |
| H. Scheduling | How future work becomes executable | Proactivity |

Recommended review order: A with D's confirmation rule, then B and C, then E;
review F, G and H together afterwards. No library selection is needed to answer
the behavioural questions.

## A. Creation: draft, hold, confirmation

**Progress:** the [checkout flow](checkout-lifecycle.md) now records the intended
journey. Checkout owns payer, guest and party information before confirmation.
The SQL still has no checkout/hold tables.

- [ ] **A1 — Storage and expiry details.** Answered: retain checkout information
  while checkout is live; delete abandoned/expired personal data. Still open:
  draft payload versus child rows, expiry duration, sweep delay, retention of
  payment-resolution references and copies in threads/logs/backups. Call this
  temporary storage with deletion, not a blanket zero-retention promise.
- [ ] **A2 — Hold scope.** Answered: editing/shopping reserves no capacity; the
  first successful acquisition reserves it before payment, and conflicting
  requests cannot both proceed. Still open: one hold per item or whole basket,
  whether all requested rooms/activities are acquired together, and duration.
- [ ] **A3 — Confirmation ordering.** Answered: no booking before confirmed
  payment, no consumption of an expired hold. Staff approval is also wanted.
  Proposed ordering: acquire hold/freeze quote, staff approval, payment, then
  check and consume the hold while creating the stay. Approve that ordering
  and define late/duplicate payment results. Approval alone is not payment.
- [ ] **A4 — Backing out and payment uncertainty.** Answered: no editing while
  held; release the hold and compete again. Still open: retry/cancellation once
  payment is underway or its outcome is unknown. A late successful payment
  needs resolution even though the expired hold cannot create a booking.

**Done when:** we can explain one successful checkout and one abandoned checkout,
including where data and capacity live at each step.

## B. Confirmed changes, parties, rooms and keys

**Current gap:** the SQL has revision history, but the change workflow and most
state transitions are not agreed.

- [ ] **B1 — Room change procedure.** Answered: changing rooms does not replace
  the whole booking or void its party/activities/details. Proposed flow: retain
  the original allocation, secure the replacement and agreed adjustment, then
  confirm the replacement and cancel the old room allocation together. Approve
  the sequence, including complimentary upgrades and failed payment outcomes.
- [ ] **B2 — Remaining statuses.** Answered: technical `error` must leave booking
  status; cancellation stays terminal. The current contract removes under-revision:
  a separate change leaves the accepted booking confirmed. Reservations now use a
  cancellation boolean, independent of time passing. Still open: what marks
  completion and whether it is terminal. SQL still contains the old status fields
  and enum values pending the next DDL pass.
- [ ] **B3 — Membership corrections and departures.** Answered: additional
  travellers can use a separate booking/party even if socially part of the same
  group. Still open: corrections and early departures, their effects on future
  activities/capacity, and whether attendance dates need representing. Do not
  automatically turn a correction into a new stay or erase prior records.
- [ ] **B4 — Room configuration and availability.** Answered: separate mutable
  bed rows belong to rooms; retain versioned pricing; use an `in_service` boolean
  and derive dated availability from reservations and live holds. Housekeeping
  is outside this version. Still open: category/tier meaning, bed-type capacity
  mapping and whether the demo equates room capacity with total sleeping places;
  treatment of existing reservations when a room goes out of service. See
  [the bed relationship review](data-modelling.md#bed-relationship-latest-review).
  Check-in records and the arrival/departure logbook remain deferred.
- [ ] **B5 — Key validity.** Answered: `deactivated_at` and a room-reservation
  link are selected; keys have identity but no guest owner. Current SQL remains
  room-only. Specify retained/deleted history, identity linkage through reservation
  revisions, and enforcement of the agreed effective-access rule. A later stay
  must never revive an earlier key. Physical lock integration stays deferred.

**Done when:** we can walk through a room change, guest departure, and booking
cancellation without losing the original agreement or leaving unintended access.

## C. Activities and changes to the schedule

**Progress:** one activity reservation per guest is now selected. Itineraries are
queries, guest overlaps are allowed, shared venues are allowed, and individual
activity cancellation is terminal.

- [ ] **C1 — Group requests and guests without stays.** Answered: each reservation
  has a guest and party; party leads to booking for charge attribution. Derive
  itineraries from reservations; store notes in party details. Still open: how
  one group request satisfies booking-size limits and is committed together;
  whether walk-ins without stay bookings are supported. Different parties can
  participate in the same activity without merging their bookings.
- [ ] **C2 — Eligibility.** Answered: guest activity overlaps and simultaneous
  activities at a venue are allowed. Venue capacity is admin configuration;
  the system enforces activity capacity only, with null meaning unlimited.
  No combined venue-capacity check or segmentation is required. Still open:
  whether age eligibility uses booking time or attendance time.
- [ ] **C3 — Changes after reservations exist.** Answered: activity time changes
  are allowed; notify affected guests and derive itinerary conflicts as needed.
  Still open: whole-activity cancellation, venue/age changes, reduced capacity,
  and retaining old/new values for notification. Delivery is initially simulated;
  see E1. Guest conflicts remain advisory.
- [ ] **C4 — Terminal cancellation and parent eligibility.** Answered: individual
  activity cancellation is terminal; rebooking needs a new ID and available
  capacity. At most one effective reservation per guest/activity is selected.
  Cancellation is represented by a boolean in the current contract; effective
  searches default to true and date filtering is separate. SQL enforcement is
  still pending. Still open: parent states that
  qualify for activity access, especially completed bookings. Historical reports
  must use historical parent state, not apply today's state retrospectively.

**Done when:** we can book several attendees, cancel one, and reschedule their
activity with a clear result for capacity and communication.

## D. Prices, quotes and payment evidence

**Current gap:** rate versions are modelled, but a rate is not a full quote or
proof of payment.

- [ ] **D1 — Quote and room subtotal.** Answered: freeze the quote on Confirm /
  proceeding to checkout, before payment, preserving agreed rate versions and
  adjustments. Sum each room's nightly rate times its own stay length. Room
  reservations already have individual arrival/departure times. Still open:
  exact night-count convention, quote validity, stay-extension procedure, and
  activity pricing unit. Hotel-local date differences are recommended for nights.
- [ ] **D2 — Shared rates.** Answered: prices have no hotel-owner field and
  amounts use integer currency minor units. Still open: who may publish rates,
  current-version rule, supported currencies and currency changes. The draft
  has no explicit pricing unit; prevent confusing nightly rates with activity fees.
- [ ] **D3 — What is the minimum payment story?** Choose staff-recorded external
  payment, explicit simulation, or both. A booking now requires confirmed
  payment (A3). Decide how a payer/contact is identified without
  restoring `primary_guest_id`, and whether the evidence references a draft or
  booking. Specify amount, currency, source, reference, reported outcome and time
  if those are needed. No payment provider, live collection, refund engine or
  card storage is required for this pass. Cancelling a booking is not itself
  evidence of a refund.

**Done when:** the demo can explain what was agreed, why confirmation was allowed,
and what evidence of payment it actually has.

## E. Contacts, provenance, permissions and party details

**Progress:** contact information belongs to each guest. Revision timestamps
still do not identify who took an action.

- [ ] **E1 — Contact validation and delivery.** Answered: optional phone and email
  on each guest; preference phone/email/null, with null using all supplied
  channels. A specific preference requires that channel to exist. Notify each
  affected participant; initial dispatch is simulated and logged as external
  work. Still open: staff fallback when no contacts exist, phone channel meaning,
  delivery states, duplicate prevention and retries. UI edits must trigger the
  same notification behaviour as agent edits. Urgency/escalation is deferred.
- [ ] **E2 — Permissions and attribution.** Answered: seed a single acting staff
  member; carry its identity through the service layer. The agent inherits user
  permissions. Bookings include allocations/keys; guests include parties; rooms
  include beds. Final permission mapping follows API design. Staff belong to one
  hotel; venues/prices have no hotel-owner field. Threads now have creator-only
  access and fixed permission snapshots, bounded by current authority. Still open:
  exact operation grants and data scopes; complete audit is deferred.
- [ ] **E3 — Classification outcomes.** Answered: guest references use a known,
  versioned JSON-array shape. Programmatic correction is deferred. Still open:
  where the format version lives, save-before/after-classification, ambiguity,
  service failure and validation. Classifier output is not proof of identity.
- [ ] **E4 — Party detail authority.** Answered: the agent may explicitly record
  a reported dietary change and update the guest's requirements as one action.
  A combined transactional operation is recommended, not yet selected. Guest
  information and activity definitions are mutable without change history.
  Party-detail authorship/source/time and edit history remain open.

**Done when:** we can identify who changed something, who may see it, who should
hear about it, and whether model-derived information needs review.

## F. Durable thread execution and input

**Progress:** one active run; external work normally suspends it. Thread records
hold more than the model sees. Ordinary input is batched when eligible; steering
can interrupt a wait. See [runtime review](runtime-review.md).

- [ ] **F1 — Run and record schema.** Define exact states, record kinds and links
  among input, run, model request, tool call, job and result. Source history must
  support rebuilding the projection without changing thread identity.
- [ ] **F2 — Pending input.** Durable thread mailbox/inbox is selected. Define
  storage, ordered batch consumption and request-inclusion tracking. Direct classifier
  handling must not require a main-model request to count as handled.
- [ ] **F3 — Steering checkpoints.** Ended-target steering becomes ready input;
  it must respect a newer active run. Define safe checkpoints, ownership and
  wake consumption. Ending a wait does not cancel external work. A generic sleep
  tool remains unselected.
- [ ] **F4 — Context and output.** Our versioned, typed storage is independent
  of provider schema. Classifier decisions are excluded from main-model messages.
  Define persisted format markers, inference snapshot storage, partial-stream
  handling and complete tool-call persistence. Compaction,
  broad context-query tools and classifier tool discovery are deferred. Fresh
  time/world context and helper-title behaviour remain to be specified if used.

**Done when:** we can trace a message through request, call, wait, result and
response, including steering and classifier-only handling.

## G. External work, workers and recovery

**Progress:** separate jobs and tasks are selected for learning fan-out. Workers
claim tasks, superseding the earlier job-level claim. Claims remain a separate
table. One registered job type with one task is a valid initial implementation.

- [ ] **G1 — Job/task state machines.** Define handler types, task readiness,
  inputs/results and job aggregation. Retry counters live on independent tasks;
  an attempts table is not required. Decide parallel-branch failure/cancellation
  and which component creates successor tasks. No general workflow DSL is needed.
- [ ] **G2 — Atomic handover.** Accepted: persist queued calls/jobs/initial tasks
  together; persist task outcome plus parent transition/next tasks together;
  persist terminal job outcome plus outbox together. Append thread result and
  consume outbox together. Define uniqueness so retries and competing branch
  completions do not duplicate tasks/results. One job result answers its call.
- [ ] **G3 — Claims.** Claim table now references tasks. Define atomic claim,
  heartbeat/expiry and stale-token checks in protected writes. Only expired
  ownership is reclaimed. Task work runs while the agent is suspended.
- [ ] **G4 — Retry and cancellation.** Request IDs are command idempotency keys;
  backing deduplication state is required, but no public receipts resource.
  Define scope/retention, attempt budgets, external unknown outcomes and task
  cancellation. Use accepted wake rules. Publication means a SQLite event append;
  actual external sends have separate delivery guarantees.

**Done when:** independent tasks can run/retry without replaying completed branches,
losing dispatch, duplicating job results or allowing stale-owner writes.

## H. Scheduling and proactivity

**Progress:** schedules trigger independent accepted jobs; schedule edits do not
cancel those jobs. Reminders recheck their relevant facts before acting. Initial
notifications are simulated/logged; no separate pubsub system is required.

- [ ] **H1 — Schedule schema.** Define schedule identity, recurrence/one-off time,
  action, destination, enabled state and author. A tick discovers due work;
  workers execute it. Cron library and process topology remain unselected.
- [ ] **H2 — Occurrence handover.** A separate, gateway-readable occurrence table
  is selected. It records an accepted due firing before completion, not hypothetical
  future matches. Define unique identity and atomic occurrence/job/task creation.
  Preserve accepted inputs across schedule edits; decide overlapping firings.
- [ ] **H3 — Recovery and relevance.** Earlier scope allows skipping occurrences
  missed during downtime; accepted jobs still recover. Define wake consumption
  and expected-state checks, logging irrelevant reminders as skipped. Classifier
  relevance checks are optional additions to deterministic validity checks.

**Done when:** a due occurrence reliably becomes work, stays independent of later
schedule edits, and skips reminders whose underlying facts no longer hold.

## SQL status and remaining representation review

These choices already exist in the draft. Accepted changes not yet implemented
are identified explicitly; the SQL is not the current decision source.

| Draft choice | Review with |
| --- | --- |
| Booking revisions store status/reason only; booking name remains mutable | B2, E2 — this is not a snapshot of the whole stay |
| `error` remains in SQL but has now been rejected; completed is not terminal in SQL | B2 — remove `error` in the next DDL pass |
| One party per booking is enforced as “at most one”; first revision and guests must be created by an operation | A3, B3 |
| Guest information mutable without history — accepted; party-detail history still open | B3, E4 |
| One staff member belongs to one hotel — accepted | E2 |
| Venues and prices have no hotel-owner field — accepted | Cross-hotel venue/activity use allowed; permission rules still apply |
| Room `number_of_beds`, `max_occupants`, category, tier and operational status remain in SQL | B4 — beds table and `in_service` selected; derived occupancy still needs its scope assumption |
| SQL still has room-only key; reservation reference and `deactivated_at` now selected | B5 — DDL pending; retention open |
| One activity reservation per guest; maximum booking size can be null | C1 |
| Activity definitions mutable without history — accepted; cancellation representation still open | C3 |
| Highest price revision is current; reservations pin `(price_id, revision)` | D1, D2 |
| Integer currency minor units accepted; zero-total policy and charging units still open | D1–D3 |
| Party references as a versioned JSON-array shape accepted; version placement and `NULL` semantics open | E3 |
| Text IDs, whole-second UTC timestamps, optional country code | Representation pass after domain rules |
| Sequential revision and immutability triggers, ordinary current-state views | Constraint/history pass below; broader than the original room-only draft |

## Constraint and transaction pass: after the behaviour decisions

These enforce chosen rules. They are not additional product features, and this
list does not authorise adding indexes now.

- [ ] **Uniqueness:** staff-code scope, room label per hotel, repeated active
  guest/activity reservations, and duplicate submissions. Name, amount and
  timestamp equality are not substitutes for identity.
- [ ] **Membership and ownership:** activity guest belongs to the stated party;
  room belongs to the booking's hotel; venue/price use has no hotel-owner filter
  but must satisfy operation permissions. Party-detail array validation checks known IDs from that party.
  Independent foreign keys currently do not prove these paired relationships.
- [ ] **Minimum structure:** confirming creates the initial booking revision,
  one party, required guests and room allocations together. A foreign key only
  checks a referenced parent; it does not force child rows to exist.
- [ ] **Intervals and occupancy:** define boundary equality (checkout and next
  check-in at the same time), and overlapping live holds and reservations.
  Cleaning remains outside scope. Check party accommodation across every part of its stay, not
  by adding capacities of rooms booked on different dates.
- [ ] **Activity limits:** capacity shared with holds if adopted, venue rules,
  party booking size, ages, and concurrent requests for the last place. Check
  availability and commit together; appending history alone is insufficient.
- [ ] **State changes:** allowed transitions, cancellation reasons, what fields
  are immutable, and whether non-cancelled revisions may carry old cancellation
  reasons. The complete booking and room transition graphs are not enforced.
- [ ] **Competing edits and retries:** detect an edit based on an outdated
  revision, not just assign the next revision number. Define transaction scope,
  busy/conflict responses and repeat-request handling. Do not hold database
  write transactions open during inference or external calls.
- [ ] **History and current views:** apply one eligibility rule consistently in
  capacity, itineraries and UI. Parent-cancellation filtering currently exists
  only for activity reservations; room availability, keys and jobs require
  their own agreed consequences. Historical queries use historical state.
- [ ] **Retention:** deletion/correction rules must agree with append-only
  triggers, foreign keys, draft cleanup and any retained copies in threads.
  Decide required behaviour before implementing a purge.

## Implementation decisions that can wait

Once the behaviour above is settled, choose Python/package/server structure,
repository and service operations, API and inference gateways, tool handlers,
Pydantic boundary models, worker/process arrangement, streaming transport,
provider SDK/model, cron/calendar libraries and basic telemetry/evaluations.

The proposed module for inspecting thread records (last user/assistant message,
end-of-turn predicates) belongs here. Its semantics follow F, and focused tests
can be designed when implementation is requested. No framework decision is
needed to decide the hotel model. No extra Python scaffold or test suite is
part of this review.

## Explicitly outside the current review

These are deferred scope, not gaps to solve now:

- Packaged holidays, grouped-trip workflows, VIP/standard capacity buckets.
- Arrival/departure logbook and physical door-lock integration.
- Full payment provider, refunds, room credit, discounts, seasonal rate calendars.
- Permanent guest identities, identity documents, cross-visit memory.
- Complex group-size steps, attendance tracking, maximum-age policies.
- Floor-plan ingestion, OCR, geometry and spatial queries.
- Embeddings/vector-search experiments, automatic personalisation, broader Jev uses.
- Subagents, side-question mode, code execution, generative UI and agent-filled forms.
- Hotel-local timezone support; keep UTC for the initial version.
- Production-scale database tuning and performance indexes.

## Next review

Use the [permission/tool operation map](permissions-and-tools.md) for a short
capability pass, then select dependencies and implement a small vertical path.
The walkthrough is complete; unchecked local decisions remain visible above.
Do not restart the whole domain review or silently treat every checkbox as a
new feature requirement.
