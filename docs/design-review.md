# Remaining design decisions

This is the review checklist for the current design. It consolidates the
[domain notes](data-modelling.md), [runtime notes](agent-runtime.md), and
[SQL draft and guide](../schema/README.md), reviewed against commit `365a435`.
It adds no tables, features, indexes, or implementation decisions.

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

**Current gap:** the SQL starts at confirmed bookings. There is no representation
of the preceding checkout and no agreed storage for its party information.

- [ ] **A1 — What survives an unfinished checkout?** Decide what a draft stores
  (room choices, dates, proposed guest details, quote), whether staff can resume
  it, and for how long. Choose draft-local data or temporary domain records.
  The earlier discussions considered both; neither was selected. Hold expiry
  need not automatically mean deleting the draft. Retention also needs to account
  for copies in threads or job payloads; deleting guest rows alone is not a
  complete deletion policy. No legal-compliance decision has been made.
- [ ] **A2 — What does one hold cover?** One room or a set of allocations? Are
  activities also held before confirmation, or added only after the stay is
  confirmed? Decide duration, renewal/release, and all-or-nothing versus partial
  acquisition. A partially available request needs a defined outcome.
- [ ] **A3 — What authorises confirmation?** Is staff approval enough, is payment
  evidence required, or are both supported? Earlier discussion allowed a sponsored
  stay; later wording referred to creating the booking only after payment.
  Reconcile these explicitly with D3. Confirmation must consume the live hold
  once and create the agreed stay without releasing capacity in between.
- [ ] **A4 — What if the draft changes or expires?** Decide whether editing rooms,
  dates, guests, or price replaces a hold; whether confirmation uses a particular
  saved draft revision; and what happens if a response arrives after expiry.
  Confirming twice must not create two stays. Resume may require new availability
  and price checks rather than reviving the old hold.

**Done when:** we can explain one successful checkout and one abandoned checkout,
including where data and capacity live at each step.

## B. Confirmed changes, parties, rooms and keys

**Current gap:** the SQL has revision history, but the change workflow and most
state transitions are not agreed.

- [ ] **B1 — What is replaced when someone changes rooms?** Choose a new room
  reservation under the same booking, a proposed revision, or a replacement
  booking. The last option also affects the one-to-one party link and activities
  hanging from it. Specify what stays intact while the replacement is pending
  and what happens if it fails. Do not silently move the party to bypass the
  original booking's terminal cancellation.
- [ ] **B2 — What do the remaining statuses mean?** Define allowed booking
  transitions, including `under_revision`, `completed`, and whether `error`
  belongs on the booking or only on an attempted operation. Define room
  reservation statuses and which states retain capacity. Decide what marks a
  stay completed and whether completion is terminal. The SQL enforces only
  confirmed-first and cancellation-terminal, not the full lifecycle.
- [ ] **B3 — How can party membership change?** The earlier immutable-party idea
  conflicts with adding/removing guests and correcting mistakes. Decide what
  can change, whether identity links can move, and how a departed guest's future
  activities are treated. Define when to recheck accommodation capacity. If
  guests have different attendance dates, either model that or explicitly leave
  it outside the first version.
- [ ] **B4 — What makes a room operationally available?** Finalise category versus
  tier, any eligibility restriction, operational status labels, and cleaning
  turnaround. Decide whether expected cleaning completion is enough or staff
  must mark the room ready. Specify how an out-of-service room affects existing
  reservations. Clarify whether claiming/checking into a room needs its own
  record; the arrival/departure logbook is deferred.
- [ ] **B5 — What ends a key's access?** Decide whether keys are retained after
  deactivation, and approve or replace the draft's `deactivated_at` field. Explain
  shortening/extending stays, moving rooms, and cancelling a booking. The key
  only references a room today: there is no stay link to distinguish keys for
  different visits to that room. Decide how the application finds the keys to
  change without inventing a guest owner or a door-lock integration.

**Done when:** we can walk through a room change, guest departure, and booking
cancellation without losing the original agreement or leaving unintended access.

## C. Activities and changes to the schedule

**Current gap:** the draft retains one reservation per guest. The alternative
party reservation with a quantity is still open.

- [ ] **C1 — What is one activity reservation?** Per guest, or a party quantity?
  Keep the party association either way. Decide how attendee identification,
  individual itineraries, age checks and partial cancellations work. Minimum
  booking size applies to one request/group, not necessarily to each stored row;
  explain a four-person request when records are per guest. No extra group-size
  steps or minimum total attendance rule is needed.
- [ ] **C2 — How is venue capacity used?** Decide whether activities may overlap
  at one venue, and how they share space. An unlimited activity currently has
  a mandatory venue with finite capacity: resolve whether it is still limited
  by that venue or represents a different kind of setting. Decide whether a
  guest can book overlapping activities and whether age is evaluated at booking
  or attendance using the guest age we store.
- [ ] **C3 — What edits are permitted after reservations exist?** Consider time,
  venue, cancellation, age limits and a reduced capacity. Decide whether existing
  bookings remain valid, require staff review, or need alternatives. Identify
  which changes are recorded and which trigger notification; activity fields
  are mutable today and there is no activity-change history. Decide what the
  notification needs to retain about the old and new values.
- [ ] **C4 — Can an activity reservation be reinstated?** Terminal cancellation
  is decided for the parent booking only. Either make activity cancellation
  terminal too, or require a fresh capacity check to reactivate it. Define the
  parent statuses that count for future activity access. Today's view excludes
  cancelled bookings but still includes `error` and `completed`; that is not
  an approved complete eligibility rule. Historical reporting must not apply
  today's parent status retrospectively to every past activity.

**Done when:** we can book several attendees, cancel one, and reschedule their
activity with a clear result for capacity and communication.

## D. Prices, quotes and payment evidence

**Current gap:** rate versions are modelled, but a rate is not a full quote or
proof of payment.

- [ ] **D1 — When is the quote fixed?** At drafting, holding, or confirmation?
  Decide what happens when a rate changes while a draft is open, how long a quote
  is honoured, and how an amendment gets priced. Room reservations pin a rate
  version, but calculation of nights and an agreed total is not yet defined.
  Activity pricing needs a unit: per participant, party, or slot.
- [ ] **D2 — Who shares and manages a price?** Decide whether a price belongs to
  one hotel or can be shared across hotels, and who may change it. Review the
  current-version rule, supported currencies, amount representation and currency
  changes. The draft has no explicit pricing unit on the shared price object;
  agree how to prevent accidentally treating a nightly rate as an activity fee.
- [ ] **D3 — What is the minimum payment story?** Choose staff-recorded external
  payment, explicit simulation, or both. Decide whether a booking can be
  confirmed without payment (A3), how a payer/contact is identified without
  restoring `primary_guest_id`, and whether the evidence references a draft or
  booking. Specify amount, currency, source, reference, reported outcome and time
  if those are needed. No payment provider, live collection, refund engine or
  card storage is required for this pass. Cancelling a booking is not itself
  evidence of a refund.

**Done when:** the demo can explain what was agreed, why confirmation was allowed,
and what evidence of payment it actually has.

## E. Contacts, provenance, permissions and party details

**Current gap:** we removed the primary guest link but have not replaced the
contact concept. Revision timestamps do not identify who took an action.

- [ ] **E1 — Who receives a notification?** One party contact, all participating
  guests, or staff forwarding the message? Decide where contact details live and
  what happens when none are present. Removing a guest reference from booking
  does not settle this. Delivery records, a change/recipient identifier to avoid
  duplicates, retry outcomes, and genuine versus simulated email are outstanding.
  The agent may invoke a notification tool; the service still needs a reliable
  rule for changes made directly through the UI.
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
| `error` is an allowed booking label; completed is not terminal in SQL | B2 |
| One party per booking is enforced as “at most one”; first revision and guests must be created by an operation | A3, B3 |
| Guest names, ages, dietary requirements and party details are mutable without history | B3, E4 |
| One staff member belongs to one hotel | E2 |
| Venues and prices have no hotel-owner field | C2, D2, E2 |
| Room `max_occupants`; freeform category, tier and operational status | B4 |
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

Suggested next review: **A, using a two-person, one-room stay.** Decide what is
saved before confirmation, what holds the room, what permits confirmation and
what survives abandonment. Then consider the same stay with one room change.
This settles several links without requiring the runtime or a payment provider.
