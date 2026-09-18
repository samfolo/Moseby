# Data modelling notes

Moseby is a lightweight experiment in proactivity for resort scheduling.
This document records the current thinking. It is a draft, not a finished
database schema. Open questions are left open so we can work through them.

For the consolidated list of questions to review, use
[Remaining design decisions](design-review.md). This document supplies context;
the checklist separates current decisions, provisional SQL, and deferred scope.

The executable [SQLite draft](../schema/draft.sql) now captures the reviewed
hotel-side structure: hotels, staff, confirmed bookings, parties, guests, party
details, rooms, keys, activities, and versioned prices and reservations.
Its [guide](../schema/README.md) labels provisional representations and the
boundaries still to model. Drafts/holds, payments, external jobs and the agent
runtime do not yet have final DDL. No performance indexes are being added now.

## Who uses Moseby?

Hotel staff and concierges use the application. They can see operational
details and use their judgement when communicating with guests. They provide
a buffer between the agent and the guest experience.

We want to know which staff member handled an interaction or action. A
reservation belongs to the hotel and can be managed by several staff members.
It is not owned by the staff member who took the booking.

## Journeys covered here

- As a concierge, I want to record a party's stay and its point of contact.
- As a concierge, I want to know who is coming and allocate suitable rooms.
- As a concierge, I want to see room categories, eligibility, and nightly prices.
- As a concierge, I want to issue several keys for a room and handle a lost key.
- As a colleague, I want to know who handled a guest's request.

## Staff

Use `hotel_staff_members` as the current table name. A staff member needs:

- A unique staff ID for the application.
- A human-readable staff code, possibly ten uppercase hexadecimal characters.
- First name and last name, with a proposed limit of 2,048 characters each.
- An optional freeform title.
- A role, initially concierge.

The code format need not have a database format constraint. Its uniqueness
scope remains to be settled now that hotels are explicit. Login, account
management, and exact audit links have not been designed yet.

## Hotels

Keep a lightweight hotel record with an ID, name, and address. Address lines,
city, and postcode were proposed. A country code was suggested; the exact
address format is still open. No structure above the hotel is needed now.

## Drafts, holds, and confirmed bookings

The [checkout lifecycle diagrams](checkout-lifecycle.md) capture the latest A/B
review. Use checkout for the former draft-booking concept. It holds proposed
payer, guest and party information. Shopping does not reserve capacity; entering
payment requires a hold. A held checkout cannot be edited without first backing
out. Confirmed payment is required before creating the booking; staff approval
is also requested and its ordering is being reviewed. No late confirmation may
consume an expired hold. Quote amounts and agreed adjustments must be preserved.

The latest direction separates a draft booking from a confirmed booking.
The draft covers preparation and awaiting confirmation. A booking record is
created already confirmed. This replaces the earlier proposal to put
`in_progress` and `awaiting_confirmation` on the confirmed booking itself.

The draft is the proposed arrangement. A hold temporarily secures capacity for
that arrangement. They are different concepts; their exact tables and links
are not settled.

The accepted term is **consumed** when a hold is used to confirm a booking.
Released and expired describe the other proposed ways for a hold to end.
Its expiry deadline is separate from the check-in and checkout dates of the
rooms being held. One hold per room versus one hold for a set of rooms remains
open.

Proposed correctness requirements: confirmation must not briefly release the
capacity while converting the hold into reservations; an expired hold must
stop blocking availability even if cleanup has not run. An expired or already
consumed hold cannot be used again. Enforcement will be designed with the DDL
and transaction rules.

A confirmed booking has:

- Booking ID.
- Hotel ID.
- Human-readable `name`.
- Immutable creation timestamp.
- Current status, with an append-only history as the intended direction.
- Freeform cancellation reason when relevant.

There is no primary guest reference and no owning staff member. Confirmed
replaces settled; under revision replaces under review. Confirmed can become
cancelled or completed. Whether under revision remains a booking status is now
being reconsidered. Technical errors belong to operations, not the booking.
The existing SQL still has `error`; remove it in the next DDL revision.

Cancellation is now terminal: a cancelled booking cannot be reinstated. Booking
again creates a different booking. History retains the cancellation, but no
special reinstatement revision is needed. The SQL enforces this on booking
revision history. This does not yet decide whether a separately cancelled
activity reservation can be reinstated under an otherwise valid booking.

Before this split, awaiting confirmation held capacity, in progress did not,
and under revision retained an existing allocation. We need to carry those
intentions into the draft/hold design. In particular, rejection or expiry of
an amendment must not accidentally erase the original confirmed stay.

Open questions:

- Does a draft have explicit preparation and awaiting-confirmation states, or
  is readiness represented through its hold and other information?
- How do a party and its guests exist before the confirmed booking does?
- How does an amendment draft reference the existing booking and confirmed
  agreement? Which changes take effect only after approval?
- Does history contain full booking snapshots or individual changes?
- How are failed operations represented separately from the valid booking?

Payment collection and the distinction between booking contact, guest, and
payer remain open. The payment provider's internal lifecycle is outside scope.

## Parties

Keep parties separate from bookings even though the intended relationship is
one-to-one. A party has its own ID, a booking association, and one or more
guests. The booking has the hotel association. A return visit creates a new
party and new guest records, even for the same people.

Guests reference the party; they do not also need a direct booking reference.
The party's association before confirmation is unresolved because drafts now
exist before bookings. We have not chosen a nullable link or another structure.

The earlier proposal to make parties immutable still needs reconciliation with
membership changes and corrections.

The latest discussion considered creating parties and guests only on
confirmation, then raised the need to resume an unfinished checkout. Possible
approaches were separate draft data or temporary party/guest records retained
while attached to a live hold or booking. Short retention and periodic cleanup
were suggested, not selected. Retention duration, resuming an expired draft,
and deletion rules remain open; no legal-compliance conclusion has been made.

The latest direction places proposed party information in checkout until the
booking is confirmed. The draft payload versus child-row representation is
still open. Additional travellers can have a separate booking and party;
socially travelling together does not require a shared database party. Early
departures and corrections remain open. See the lifecycle review for why
temporary persisted checkout data is not a blanket zero-retention guarantee.

## Guests

A guest represents a person in one party for one stay. A return visit creates a
new guest record with a new ID. We will not try to recognise the same person
across separate stays. This replaces the earlier idea of reusing guest records.

Proposed details:

- Unique guest ID.
- Party ID.
- First name and last name.
- Optional preferred name.
- Age, because some activities may have age restrictions.
- Dietary requirements, as freeform text.

Dietary requirements stay on the individual guest. General accommodations move
to party details below. We are not creating a dietary taxonomy now.

Identity documents and copies are outside the model. Comparing ages across
visits is also outside the current scope, given the decision to keep visits
separate.

Discounts, special treats, bans, and missing-person reports were raised as things
staff might do. They are not being added as guest properties or workflows now.

## Party details and referenced guests

Party details are now part of the intended design, rather than only a possible
future memory feature. They can contain general accommodations, observations,
or information about the party during its stay.

Proposed properties:

- Detail ID.
- Party ID.
- Original freeform detail text.
- A list of referenced guest IDs.

Keep one detail with a list of IDs rather than duplicating the detail for each
guest. The storage format of the list is not chosen. Every referenced guest
must belong to the party; application validation will check this.

The selected experiment is to call **Jev** when the API adds a party detail.
Give it the text and candidate guests from that party, with their IDs and
relevant identifying context. Ordinary code constructs and validates the
referenced-ID list from its decisions.

The [TypeSafe documentation](https://docs.typesafe.ai/introduction) confirms that
Jev answers typed questions rather than generating freeform text. A
[Choice](https://docs.typesafe.ai/primitives/choice) selects one supplied option;
[Noul](https://docs.typesafe.ai/primitives/noul) evaluates a yes/no proposition
and returns a probability. Several questions can share one request. For several
guest references, asking whether each candidate is referenced is one possible
design to test. A single Choice does not select an arbitrary subset of guests.
The integration, thresholds, and handling of ambiguous references remain open.

A restricted candidate list prevents accepting invented or out-of-party IDs,
but does not establish that a valid ID is the right person. Two guests called
Dan can still be ambiguous. Abstaining or requesting clarification is the
recommended behaviour; the exact output and API handling remain open.

Also open: distinguishing no guest reference from an unresolved reference,
what happens if classification fails, correction of generated references, and
whether source, author, and timestamps are recorded on details. Inferred
references should not silently rewrite dietary requirements or other guest
facts. How details relate to those facts remains to be designed.

Retrieval remains lexical for now. Cross-visit memory and automatic
personalisation from these details are not implied by recording them.

## Rooms and allocations

A room is a physical room in the hotel. Proposed details include:

- A unique room ID.
- Hotel association.
- A room number that staff and guests recognise.
- An `in_service` boolean; availability is calculated for requested dates.
- A description.
- Number of bathrooms. Beds are separate mutable rows associated with the room,
  rather than a JSON configuration or a separately maintained bed count.
- Room category; the earlier twin/master/presidential list is being reconsidered
  because it mixes bed arrangement and room class.
- A possible separate tier, such as VIP; its meaning is not settled.
- Capacity derived from beds is the preferred direction; see the distinction
  between sleeping capacity and an independent room limit below.
- Shared price ID, following the pricing direction below.

Room numbers are human-readable labels that can be printed on passes. They
are separate from the room's unique ID. The description can explain the room
to staff and guests, including its features and appeal.

Rooms are manually curated. Availability uses the in-service flag, overlapping
room reservations and live holds. Do not store available/booked/held as one
mutable status on the room: those answers depend on dates. Handling existing
reservations when a room goes out of service remains open. Housekeeping and
cleaning schedules are outside this version; staff prepare rooms externally.

### Bed relationship: latest review

Use one room to many beds. Each bed row has a local ID, room ID and bed type,
and can be updated directly. The ID identifies a database entry; it does not
require a physical asset tag or maintenance inventory. A bed status was raised,
but its purpose and values are not selected. No new status system is implied.

Rooms containing a king bed can be found in one query using `EXISTS` or a join
with distinct room IDs. Separate queries are possible but unnecessary. Bed
counts can be derived. Index selection remains deferred.

The proposed capacity rule is the SUM of associated beds' sleeping capacities,
not the largest single bed capacity. A central bed-type capacity mapping could
live in a small table or application code; its location and values are open.
A shared type table would be normalisation, not denormalisation.

An independently imposed maximum occupancy is a different fact: a room could
have four sleeping places but a hotel-set limit of three. Deriving the only room
capacity from beds is valid for the demo if we explicitly assume no separate
room limit. This assumption still needs acceptance before removing
`max_occupants` from the SQL. Repository access can enforce the chosen rule,
but cannot make these two meanings equivalent.

Pricing remains a shared price anchor with versions; do not derive the price
from bed types or bathroom count. Tier remains separate from bed configuration.
Category is still under review. An ensuite means a bathroom attached to the
bedroom; a bathroom count alone does not express that relationship. Detailed
bathroom layout is not required for this version.

The SQL has not yet been revised: it still contains `number_of_beds`,
`max_occupants` and `operational_status`, and no beds table.

The proposed occupancy rule is that the rooms reserved for a party provide
enough total capacity for its guests throughout the stay. A single guest may
reserve a larger room or several rooms. Maximum occupants per room was suggested
as sufficient; minimum capacity, exact fields, and when to enforce this check
remain open. We still do not assign guests to rooms or infer guest count from
the number of keys issued.

Use room reservations for the rooms attached to a booking. Each has a reservation
ID, booking ID, room ID, agreed check-in and check-out times, and a status.
A booking can reserve several rooms.

We will not assign individual guests to rooms in the database. The party can
decide who uses each room and can swap without updating guest-room assignments.
Keys still need their own validity tracking. Requests such as breakfast delivery
can identify a destination room without creating a permanent guest-room link.

The proposed room reservation history is append-only. Its revision number is
separate from any booking revision number. Extending a stay adds
a revision under the same reservation ID with a later checkout time. Removing
a room from a booking adds a revision with a changed status. The latest revision
is the current state in the existing SQL draft. With proposed amendments, we
must distinguish the latest accepted reservation from an unconfirmed proposal.
Adding another room creates a separate reservation.

A room change is now explicitly within the existing booking. The proposed
procedure secures the replacement room reservation before cancelling the old
room allocation. The party, activity reservations and details remain attached
to the same booking. Replacing an entire booking is a different operation and
invalidates the old entitlements; it does not erase their history. The detailed
room-change and price-adjustment procedure is still under review.

Active, cancelled, expired, and voided were discussed as possible room statuses.
The final set is still open. The SQL draft accepts non-empty labels until that
choice is settled. Whether expiry should be a stored status or derived from
the dates is also open.

For this experiment, separate parties do not share a room at the same time.
The same room can be allocated to other parties on other dates. The exact date
properties and overlap checks are still to be worked through.

## Room eligibility and pricing

Some room categories may be restricted to guests or bookings with a particular
tier, such as VIP. We have not decided whether that tier belongs to the guest,
party, or reservation.

The latest direction is a shared price resource with a stable ID and separate
price versions. A room references the price ID. Several rooms can share it;
the direction is not to put a room ID on each price record. Equal amounts alone
do not mean two rooms must share a price resource.

The stable price ID does not change when its amount changes. Changing which
price resource a room uses is a separate operation from publishing a new
version of its existing price.

Properties discussed for pricing:

- Stable price ID.
- Version identity or revision number; its exact shape is open.
- Price per night.
- Currency.
- Creation timestamp.
- Update timestamp was considered; its role on an anchor or version is open.

The intent is to preserve historical prices, so a price change creates a new
version rather than overwriting an old amount. The executable draft uses the
highest revision as current, without a mutable pointer. This is a provisional
representation recorded in the schema guide, not a timestamp tie-break rule.

An agreed reservation must retain its agreed price when the shared price changes.
The SQL draft references the exact price ID and revision. When a draft locks
its quote, and what happens if prices change before confirmation, are open.

Price sharing across hotels was raised; hotel ownership and permissions for a
shared price remain open. Money representation is also open. Effective date
ranges, discounts, room charges, credit, and payment accounting are deferred.
Price versions describe quoted rates, not proof of a charge or payment.

## Room keys and claiming a room

We want to know whether a party has claimed its allocated room. The exact
meaning of claimed, checked in, and checked out needs to be settled.

A room can have several keys, so keys need separate records. A single status
on the room would not describe each issued key.

A lost key should be deactivated, with the loss recorded as the reason.
Lost is not a separate key status.

An issued key opens one specific room. It references that room, not the whole
booking, and does not need an individual guest owner. This replaces the earlier
proposal to attach keys to bookings. Staff can issue another key for the same
room without changing the booking or charging for it.

Proposed details are a key ID, a room ID, an optional human-readable code, an
effective-from time, an effective-to time, and a deactivation reason when
relevant. The effective times are independent of room-reservation times because
keys can be issued or replaced during a stay. The latest choice is a freeform
deactivation reason and no separate active/inactive status column.

Keeping disabled keys is now being questioned, superseding the earlier
append-only preference. We still need to settle how revocation is represented
and whether its history is retained. We track issued access, not blank cards.

The key journey is:

1. Staff issue one or more keys for an allocated room.
2. A guest may report a particular key lost.
3. Staff deactivate that key and can issue a replacement.

We have not yet chosen the final key properties or how they link to room access.
Tracking which individual guest sleeps in a room is outside the model.
Integration with physical door locks is not specified.

Entry and exit taps are a possible later source of information for staff. An
event could identify a key, its room, the time, and the direction of travel.
This would show when a key was used. It would not establish which individual
carried it or prove that a particular guest is currently on the premises.

## Arrival and departure logbook: deferred

The logbook is now out of scope. Guests can leave without tapping a card, so
room-entry events do not reliably establish departures or presence at the
hotel. There is no current source for a complete arrival/departure history.
Nothing in the initial system should depend on this logbook. Manual arrival
records and key-use evidence can be reconsidered later as separate features.

Checkout reminders are a possible stretch goal. They would demonstrate that
the scheduling machinery can trigger an alert as well as schedule activities.
No scheduler or cron implementation has been selected.

## Activity schedules and the calendar

Separate venues from the activities held at them. A venue has an ID, a name,
address information, and a capacity. Remove activity type from venues because
they can be multipurpose. Minimum and maximum booking sizes belong to the
activity, not the venue.

Activities are manually curated. A scheduled activity has an ID, title, type,
venue, start time, end time, description, and its own capacity. For example,
a venue might hold 2,000 people while a rooftop event is limited to 600. The activity capacity
must fit within the venue capacity. Whether activities can share a venue at the
same time and how their combined capacity is handled remain open.

Activity capacity may be null, meaning no activity-level attendance limit.
How this interacts with a finite venue capacity remains open; null must not
accidentally bypass an intended venue limit. Add minimum age. Maximum age is
not required in the current direction.

The first activities remain tennis, pottery, and guided tours. The current
direction is to make each dated activity bookable, such as pottery on Thursday
at 14:00. We have not added a separate recurring-activity template model.

Keep minimum and maximum booking size. Minimum participants per booking means
the same thing as minimum booking size. Extra group-size rules, steps, and
allowed-number lists are out of scope. A minimum total attendance requirement
for an activity to run has not been requested.

Activity reservations are separate from activities. The latest preference is
to associate them with a party rather than directly with a booking. Proposed
details are:

- Reservation ID.
- Party ID.
- Guest ID under the earlier per-guest design; see the open choice below.
- Activity and slot reference.
- Status: active or cancelled.
- Cancellation reason, required when cancelled.

Open choice: retain one logical reservation per guest and aggregate by party,
or make one party reservation for a quantity of places. Replacing booking ID
with party ID does not itself require changing the unit of a reservation. The
quantity-only design would need an answer for individual itineraries, age
checks, and partial cancellations. No choice has been made yet.

If individual guests remain identified on reservations, their planned itinerary
can be derived from those reservations and the scheduled activities. Expose
that query through the repository layer. A quantity alone gives a party-level
itinerary. Neither records proof of attendance.

Activity tariffs should follow the shared price resource and price-version
model used for rooms. The pricing unit, placement of the price reference, and
retention of the agreed version still need defining. Discounts can wait.

Keep an append-only activity-reservation history, including cancellations and
possible reactivations. Whether rows are full revisions or individual events
remains open. Attendance tracking is outside scope; active does not mean that
the guest actually turned up.

The latest cancellation direction is to retain activity history and include
parent-booking validity when deciding whether a reservation is effective. This
avoids inserting a cancellation revision into every activity reservation just
because the parent booking was cancelled. All availability and operational
queries must use the same rule. Which booking states qualify is still open.

The parent booking cannot be restored after cancellation. If individual activity
reactivation is supported under a valid booking, it must not silently reclaim
capacity that has since been reserved elsewhere. Historical reports also need
the booking state at the time being reported, rather than applying today's
status to all past activity.

The preference is to handle activity availability and capacity checks in the
application layer. Append-only history does not remove conflicting writes or
the need to check and commit safely together. SQLite still permits only one
writer at a time; see its [transaction documentation](https://www.sqlite.org/lang_transaction.html).
Reactivating a reservation needs the same capacity checks as a new reservation.

Require a reason on an explicit cancellation record. We still need to settle
whether active records must have no reason. Where a parent cancellation makes
the activity ineffective, the parent supplies that cancellation history.

For reads, an ordinary view can select the latest full revision per reservation
if that is the chosen history format. A view names a query; it does not cache
its results. A separately maintained current-state table is another option,
updated in the same transaction as history. Neither requires loading the whole
history into Python for every read. See
[SQLite views](https://www.sqlite.org/lang_createview.html).

The SQL pass now uses full revisions and ordinary current-state views. It also
includes a view applying the parent-cancellation predicate. That view is not a
complete availability calculation and does not resolve other booking states.

Use an existing calendar library for the interface. Building a calendar renderer
is not a goal of the exercise. We need to understand the data it expects before
choosing one. No calendar library has been selected.

### Activity change notifications

When a scheduled activity changes, notify the affected guests/parties. Record
email delivery and an agent-accessible notification operation as work to build.
No email tool or provider has been selected or implemented. Recipient contact
details, party contact versus individual recipients, delivery results, and
retry rules remain open. Cancelling through a parent-booking predicate does
not itself send messages or cancel work in external systems.

## Room services and work done elsewhere

For breakfast delivery and similar requests, the demo can record that a job
has been sent for another team or system to handle. For example, the record
could say that breakfast needs to be taken to particular rooms.

Real kitchen or service integrations can come later. The demo must make clear
when it has only logged a dispatch rather than contacted an external system.

Model the asynchronous work even while dispatch is simulated. The system needs
to accept progress updates and reports that work has completed or failed. The
exact states for stored, queued, and in-progress work are still open. Recording
a dispatch does not by itself mean that the service was completed.

A Kanban view is a possible interface for this work. That is a display choice;
it does not determine the underlying records or require the calendar library
to provide it.

Keep this as an explicit next design task. The required behaviour is to submit
work through a tool, retain a job reference, and later receive progress,
completion, failure, or a request for more input. Simulate asynchronous work
before building real integrations. Integration configuration, update records,
and resuming the appropriate run still need design; they should not block the
remaining walkthrough. No arbitrary-endpoint integration registry is selected.

## Payments: minimum model still to design

Do not build a payment provider or set up Stripe in this pass. We need enough
information to distinguish the agreed charge from evidence of payment. The
[schema guide](../schema/README.md#payment-evidence--proposed-minimum-no-provider-integration)
records a proposed small payment-evidence record, with amount, currency, source,
reference and outcome. Its association before booking confirmation remains open.
These are proposed fields, not selected DDL. A simulated payment is explicitly
simulation; it does not mean money moved. Room-credit and full payment accounting
remain deferred.

## Grouped trips and package capacity: deferred

This idea originally grouped the pieces of an entire experience.
For example, a two-week all-expenses-paid trip could include accommodation,
amenities, and activities spread across several days.

If the trip is cancelled, the system needs to cancel the associated bookings
and release their reserved capacity. We need a way to identify which bookings
belong to that trip.

One proposal is a higher-level record that acts as a recipe, with a workflow
that works through its steps. This is an idea to explore, not a chosen workflow
library or schema. We still need to define what happens when only some steps
succeed, and what cancelling a group means for work already in progress.

Packaged holidays and reserved standard/VIP activity quotas are now explicitly
stretch goals. Do not add activity reservation tiers or capacity buckets to
the initial schema. Grouping a trip does not require those tiers. Local database
changes may share a transaction; external work cannot be made atomic merely by
putting a list of commands in a database transaction.

## Threads and the audit record

The developing lifecycle is recorded in [Thread and runtime notes](agent-runtime.md).
Use thread records for the durable history and threads for its deterministic
current-state projection. The notes separate decisions from proposed details.

Durable agent threads remain part of the plan. Titles are likely to be useful,
but a title or booking-type label should not define what the thread is about.
The user's goal can change during the conversation.

For example, someone may start by asking for an all-expenses-paid trip and
later choose a regular booking. The transcript should preserve that change
of intent. A stale title or category must not override it.

Thread records preserve conversational context and execution history. Booking
and service records establish operational state. Their links and the exact
thread properties are still being designed.

## Dates and time context

Use UTC for the demo. Structured timestamps in agent threads should also use
UTC. Hotel-local time handling is deferred.

Relative dates in requests, such as tomorrow, still need a clear interpretation.
The approach is open. Ideas include dynamic date syntax, system-prompt context,
validation, or a notice that supplies the current time and relevant world state.

We need to examine how that context stays accurate when a thread resumes later.
No date syntax, notice format, or conversion mechanism has been selected.

## Storage and concurrent bookings

SQLite is the current preference for storage. The number of concepts alone
does not settle how booking conflicts should be handled.

Several concierges could try to book the same room for overlapping dates.
We need to prevent conflicting allocations even though the application is
staff-facing.

Locking was raised as a possible approach. Before choosing one, we need to
check SQLite's transaction behaviour and decide how to make the availability
check and booking write safe together. No locking strategy is settled here.

SQLite allows one simultaneous write transaction per database. It can contain
many row changes, and different connections can take turns writing. This does
not require a single permanent worker. The capacity transaction and contention
handling still need design; do not keep a database write transaction open while
waiting for model inference or an external service. See
[SQLite transactions](https://www.sqlite.org/lang_transaction.html).

## Topics still to work through

The active questions are centralised in [Remaining design decisions](design-review.md).
Use that checklist rather than maintaining a second task list here. Grouped
trips, the logbook, and other stretch goals are listed there as deferred, not
requirements for the next schema pass.

## Architecture and tools: the next phase

After data modelling, list the actions the application needs to support.
That list will guide the API and the tools exposed to the agent. The project
author will lead that work; these notes do not define the tool list.

Plan for two separate boundaries: the application API and the inference or
agent gateway. Design permissions while working through those interfaces.
The traditional API comes after the data modelling, followed by the inference
gateway. Their responsibilities and implementation are still open.

Use lexical retrieval for search in the first version. Embeddings are deferred.

## Stretch goals and experiments

- Checkout alerts from the scheduling machinery.
- Automatic personalisation using party details.
- Room-key entry and exit events, if a source of those events is added later.
- Arrival/departure logging if a reliable source is introduced later.
- Grouping freeform key deactivation reasons.
- Further Jev classification experiments. Guest-reference classification for
  new party details is now selected above; API details still need investigation.
- Code mode: let the agent write code against a small SDK. This comes after
  the other stretch goals and is not part of the initial tool interface.

## How we will develop this

Python, Pydantic, a manually implemented turn loop, and durable threads are
agreed directions. The remaining libraries and implementation details are
still open.

We will work through the design in small steps. Documentation should use plain
language and make the reasoning easy to follow. Commits should be small, with
short conventional commit messages, so the history shows how the design develops.

Keep the current focus on data modelling. Record new proposals in the notes
before implementing them. The existing room-reservation triggers and view are
accepted. Tests and further implementation should wait until requested.

The intended application design uses a repository layer for database access.
The API and agent will use its operations rather than execute arbitrary SQL.
The existing triggers add checks at the database boundary as well.
