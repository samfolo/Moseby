# Remaining design decisions

This is the review checklist for the current design. It consolidates the
[domain notes](data-modelling.md), [runtime notes](agent-runtime.md), and
[SQL draft and guide](../schema/README.md), reviewed against commit `365a435`.
The subsequent A/B review is captured in [Checkout lifecycle](checkout-lifecycle.md).
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
- A key opens one room, has independent validity times, and uses a freeform
  deactivation reason. No separate active/inactive key column is requested.
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
  status; cancellation stays terminal. Still open: whether `under_revision`
  remains or a separate change request leaves the booking confirmed; what marks
  completion and whether it is terminal; room reservation status meanings.
  The current SQL still allows `error` pending the next DDL pass.
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
- [ ] **B5 — What ends a key's access?** Decide whether keys are retained after
  deactivation, and approve or replace the draft's `deactivated_at` field. Explain
  shortening/extending stays, moving rooms, and cancelling a booking. The key
  only references a room today: there is no stay link to distinguish keys for
  different visits to that room. Decide how the application finds the keys to
  change without inventing a guest owner or a door-lock integration.

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
  capacity. SQL enforcement is still pending. Still open: parent states that
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
- [ ] **D2 — Who shares and manages a price?** Decide whether a price belongs to
  one hotel or can be shared across hotels, and who may change it. Review the
  current-version rule, supported currencies, amount representation and currency
  changes. The draft has no explicit pricing unit on the shared price object;
  agree how to prevent accidentally treating a nightly rate as an activity fee.
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
- [ ] **E2 — How do we attribute actions and restrict access?** Decide how the
  demo identifies the staff member, what concierge can read/write, and the hotel
  boundary. Link actions to their staff/system actor and, where applicable,
  agent run/tool call. Current domain histories lack actor fields. Threads and
  live subscriptions need access rules as well as the domain API. A role string
  and stored historical permissions do not themselves enforce current access.
- [ ] **E3 — What happens when Jev cannot resolve a reference?** Choose whether
  the detail is saved first, whether creation waits for classification, and the
  result for ambiguity or service failure. Decide how staff correct references
  and what changes when text or guest information is edited. Review `NULL`
  versus `[]` and whether more classification states/evidence are needed. Jev's
  typed-question capabilities were checked; the multi-guest mapping and thresholds
  still need an experiment. Ordinary code checks party membership.
- [ ] **E4 — What is the authority and history of a party detail?** Decide whether
  to store author, source and time; how to distinguish a request from an observed
  fact; and how edits are tracked. Define whether a dietary statement in a detail
  is only supporting evidence or can update a guest's dietary field through an
  explicit action. No automatic rewrite has been approved.

**Done when:** we can identify who changed something, who may see it, who should
hear about it, and whether model-derived information needs review.

## F. Durable thread execution and input

**Current gap:** behaviour is described, but no runtime schema exists.

- [ ] **F1 — What starts and ends a run?** Define the run states and links among
  thread, run, ordered records, model requests, tool calls/results and scheduled
  input. Decide which record kinds allow current state to be rebuilt, how the
  projection preserves thread identity, and where provider/model/format metadata
  belongs. Keep one active run per thread, including suspended runs.
- [ ] **F2 — How do cued messages move through the lifecycle?** Choose a separate
  inbox or pending thread records. Specify source, destination, order, target run,
  message identity, and the three milestones. Decide when request inclusion is
  recorded, how a failed send is represented, and how retries avoid adding a
  message twice. One component must own these changes.
- [ ] **F3 — What does steering do at each wait?** Decide default queue/steer
  behaviour, safe input checkpoints, which waits return early, and what happens
  if the intended run has ended. Retain pending external work when ending a wait.
  Decide whether a sleep tool is exposed; it has not been approved simply because
  the runtime has timed waits.
- [ ] **F4 — What context and output are durable?** Define handling of partial
  streams, complete tool-call arguments, provider errors and context limits.
  Decide how fresh time/world context is supplied when resuming. Stored times
  remain UTC, but “tomorrow” still needs interpretation. Compaction, if used,
  must not replace the durable source history. Automatic title generation is
  optional; if adopted, record its output and protect later manual title edits.

**Done when:** we can trace one message through model request, tool call, wait,
result, and final response, including a steer arriving during the wait.

## G. External work, workers and recovery

**Current gap:** desired async behaviour is agreed; execution ownership and
recovery are not designed. One simulated integration is enough to start.

- [ ] **G1 — What is a service job?** Specify identity, requested operation/input,
  relevant party/room, integration name, progress, result/failure, and links to
  its tool call and run. Separate work completed elsewhere from the act of
  dispatching it. Decide whether integration handlers can initially be registered
  in code; a general table of arbitrary endpoints is not required.
- [ ] **G2 — How do updates resume work?** Choose polling or simulated callback,
  identify which job each update belongs to, and handle duplicate/late updates.
  Decide whether the same run waits throughout or a job reference completes the
  turn and a later input starts another run. Specify the path for an external
  request for more information and for a result arriving after a steer changed
  the goal or a booking was cancelled.
- [ ] **G3 — How does one worker own a piece of work?** Decide what workers claim,
  how that claim expires or is released after a crash, and how stale workers are
  prevented from writing an obsolete result. Define which work is eligible while
  its thread is suspended. Tool work must continue while the agent waits for it.
- [ ] **G4 — What can be retried or cancelled?** Scope cancellation intent and
  recovery counters to the appropriate run/job/attempt. Record actual outcomes
  separately from requests. Decide timeout/retry limits and what to do when an
  external action may have succeeded but its reply was lost. Repeating a request
  must not silently duplicate bookings, messages or jobs. Cancelling an agent
  run does not automatically undo a vendor action or a confirmed hotel booking.

**Done when:** simulated work survives a restart and reports back without a second
worker duplicating it or a late result reviving cancelled work.

## H. Scheduling and proactivity

**Current gap:** recurring schedules, individual occurrences and thread wake times
are distinct, but their records and handover are not designed.

- [ ] **H1 — What does a schedule store?** Specify one-time versus recurring time,
  action/input, target thread or application handler, enabled state, and author.
  Choose cron syntax/validation later. A thread's `wake_at` is not a substitute
  for several independent future actions or a recurring schedule.
- [ ] **H2 — How does a due occurrence become work?** Define occurrence identity,
  intended time, actual start/outcome, and a handover that cannot create duplicate
  work when polled twice. Specify how editing/cancelling a schedule affects work
  already queued or executing, and how overlapping occurrences are handled.
- [ ] **H3 — What happens after downtime or an early wake?** Missing scheduled
  occurrences during downtime may be skipped; that does not permit losing work
  already accepted. Define recovery and when wake times are cleared/replaced so
  a steer or result does not cause a second wake. Staff or a changed booking may
  invalidate a reminder; decide when relevance is checked before action.

**Done when:** a saved future action runs once as intended, remains attributable,
and has defined behaviour when the process restarts or the schedule is edited.

## SQL choices requiring review, not silent approval

These are already present to make the draft executable. Keep/change/defer each
when reviewing the relevant section; do not treat their existence as agreement.

| Draft choice | Review with |
| --- | --- |
| Booking revisions store status/reason only; booking name remains mutable | B2, E2 — this is not a snapshot of the whole stay |
| `error` remains in SQL but has now been rejected; completed is not terminal in SQL | B2 — remove `error` in the next DDL pass |
| One party per booking is enforced as “at most one”; first revision and guests must be created by an operation | A3, B3 |
| Guest names, ages, dietary requirements and party details are mutable without history | B3, E4 |
| One staff member belongs to one hotel | E2 |
| Venues and prices have no hotel-owner field | C2, D2, E2 |
| Room `number_of_beds`, `max_occupants`, category, tier and operational status remain in SQL | B4 — beds table and `in_service` selected; derived occupancy still needs its scope assumption |
| Room-only key reference, nullable deactivation time, retained record | B5 |
| One activity reservation per guest; maximum booking size can be null | C1 |
| Activity fields are mutable; no change record or cancellation field | C3 |
| Highest price revision is current; reservations pin `(price_id, revision)` | D1, D2 |
| Integer currency minor units, zero prices allowed; charging unit implicit | D1–D3 |
| Party references stored as a JSON array; `NULL` differs from `[]` | E3 |
| Text IDs, whole-second UTC timestamps, optional country code | Representation pass after domain rules |
| Sequential revision and immutability triggers, ordinary current-state views | Constraint/history pass below; broader than the original room-only draft |

## Constraint and transaction pass: after the behaviour decisions

These enforce chosen rules. They are not additional product features, and this
list does not authorise adding indexes now.

- [ ] **Uniqueness:** staff-code scope, room label per hotel, repeated active
  guest/activity reservations, and duplicate submissions. Name, amount and
  timestamp equality are not substitutes for identity.
- [ ] **Membership and ownership:** activity guest belongs to the stated party;
  room belongs to the booking's hotel; price/venue references obey chosen hotel
  boundaries. Party-detail array validation checks known IDs from that party.
  Independent foreign keys currently do not prove these paired relationships.
- [ ] **Minimum structure:** confirming creates the initial booking revision,
  one party, required guests and room allocations together. A foreign key only
  checks a referenced parent; it does not force child rows to exist.
- [ ] **Intervals and occupancy:** define boundary equality (checkout and next
  check-in at the same time), cleaning buffers, and overlapping live holds and
  reservations. Check party accommodation across every part of its stay, not
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

## Start with one concrete example

The [checkout and room-change diagrams](checkout-lifecycle.md) now cover that
example. Review the remaining A/B decisions there before continuing with C.
The retention terminology and the late-payment edge are recorded in the same
place; no full payment integration is required to discuss them.
