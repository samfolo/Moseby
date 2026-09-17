# Data modelling notes

Moseby is a lightweight experiment in proactivity for resort scheduling.
This document records the current thinking. It is a draft, not a finished
database schema. Open questions are left open so we can work through them.

There is now an executable [SQLite draft](../schema/draft.sql) for the first
tables. Its [guide](../schema/README.md) lists the draft choices and missing rules.

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

A staff member needs:

- A unique staff ID for the application.
- A human-readable staff code, such as a badge number or a code used elsewhere.
- First name and last name.
- An optional title, such as Mr or Mrs.

These are the only staff details proposed for this exercise. Login and account
management have not been designed yet.

## Reservations and parties

A reservation records a stay, including its arrival and departure dates.
The current proposal is that each reservation has a new party with its own ID.

A party is the group attending under that reservation. Booking again creates
a new party, even if exactly the same guests return. Two separate reservations
for consecutive stays also have separate parties.

A party:

- Has a unique party ID.
- Belongs to a hotel.
- Contains one or more guests.
- Has a point of contact, linked to a guest record.

Use primary guest for the guest responsible for paying for the booking.
The booking references that guest by ID. We initially considered the name
cardholder. Whether a separate point of contact is needed remains open.

The bookings table has an ID, a human-readable party name, an immutable creation
time, a status, and a primary guest reference. It has no owning staff member.

Proposed booking statuses are in progress, awaiting confirmation, awaiting
payment, settled, cancelled, completed, error, and under review. Settled was
suggested as code 3 and cancelled as code 4; the other codes are not settled.
The first SQL draft uses text labels so it does not invent the remaining codes.

The intent is that a booking awaiting payment is already locked in. Amendments
may put it under review. We still need to define the transitions and what each
state means for room availability. The payment provider's own lifecycle is
outside this exercise.

The proposal is to make parties immutable. We still need to define what that
means if someone joins or leaves the group, or a staff member corrects a mistake.

We have not decided how much separate information belongs on the reservation
and the party. We also have not decided whether an explicit hotel or location
reference is needed for the first version. Multiple locations remain a possible
future concern.

## Guests

A guest represents a person attending one booking. A return visit creates a
new guest record with a new ID. We will not try to recognise the same person
across separate stays. This replaces the earlier idea of reusing guest records.

Proposed details:

- Unique guest ID.
- The booking they belong to.
- First name and last name.
- Optional preferred name.
- Age, because some activities may have age restrictions.
- Dietary requirements, as freeform text.
- Other accommodations, as freeform text.

Agents can reason over the freeform requirements and accommodations. We are not
designing a structured classification for them now.

Identity documents and copies are outside the model. Comparing ages across
visits is also outside the current scope, given the decision to keep visits
separate.

Discounts, special treats, bans, and missing-person reports were raised as things
staff might do. They are not being added as guest properties or workflows now.

## Memory during a booking

A possible later feature is a memory store attached to a booking. It could record
comments such as Alice enjoying a particular item, so staff can look for a way
to offer it again during the stay.

This is a stretch goal. The storage and retrieval approach has not been chosen,
and it does not imply matching guests across future bookings.

## Rooms and allocations

A room is a physical room in the hotel. Proposed details include:

- A unique room ID.
- A room number that staff and guests recognise.
- A description.
- Number of beds and number of bathrooms, as separate columns.
- Room category: twin, master, or presidential.

Room numbers are human-readable labels that can be printed on passes. They
are separate from the room's unique ID. The description can explain the room
to staff and guests, including its features and appeal.

Use room reservations for the rooms attached to a booking. Each has a reservation
ID, booking ID, room ID, agreed check-in and check-out times, and a status.
A booking can reserve several rooms.

We will not assign individual guests to rooms in the database. The party can
decide who uses each room and can swap without updating guest-room assignments.
Keys still need their own validity tracking. Requests such as breakfast delivery
can identify a destination room without creating a permanent guest-room link.

The proposed room reservation history is append-only. Extending a stay adds
a revision under the same reservation ID with a later checkout time. Removing
a room from a booking adds a revision with a changed status. The latest revision
is the current state. Adding another room creates a separate reservation.

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

Prices should be separate from room descriptions so they can be changed without
changing the room itself. The proposed starting point is a simple price list:

- Price record ID.
- Room ID.
- Price per night.
- Creation timestamp.

Pricing room classes or sets of room characteristics was considered. The current
preference is a simpler list of prices for individual room IDs. Changing a price
adds a row, and the latest row by creation time supplies the current price.
The ordering of rows with equal timestamps still needs to be settled.

Effective-from and effective-until dates were considered but are deferred.
Discounts are also deferred. The money representation and currency have not
been chosen. We still need to decide how an agreed booking price is retained
when the price list changes.

A room reservation should eventually reference a separate record of the amount
charged or paid for that room at that time. The exact record and its relationship
to pricing are still open, so the SQL draft does not invent a payment table.

## Room keys and claiming a room

We want to know whether a party has claimed its allocated room. The exact
meaning of claimed, checked in, and checked out needs to be settled.

A room can have several keys, so keys need separate records. A single status
on the room would not describe each issued key.

A lost key should be deactivated, with the loss recorded as the reason.
Lost is not a separate key status.

An issued key belongs to a booking and does not need an individual guest owner.
Proposed details are a key ID, an optional human-readable code, an effective-from
time, an effective-to time, and a deactivation reason when relevant. Keep an
append-only record. We track issued access, not the stock of blank physical cards.

Active and inactive were proposed as statuses. Whether those are stored or
derived from the validity period remains open. The relationship between a key
and the rooms it opens also needs to be settled.

A freeform deactivation reason was the earlier preference. A fixed list has now
been raised again, with examples including stolen, checkout, damaged, cancelled,
and returned. The choice between text and an enum is open.

The key journey is:

1. Staff issue one or more keys for an allocated room.
2. A guest may report a particular key lost.
3. Staff deactivate that key and can issue a replacement.

We have not yet chosen the final key properties or how they link to room access.
Tracking which individual guest sleeps in a room is outside the model.
Integration with physical door locks is not specified.

## Arrival and departure logbook

Keep an append-only record of guests signing in and signing out, including
the time of each event. Show these actual times alongside the agreed check-in
and check-out times.

The logbook is a record in the application; it does not need to look like a
physical book. Its exact relationship to guests, parties, and room allocations
still needs to be worked through.

Checkout reminders are a possible stretch goal. They would demonstrate that
the scheduling machinery can trigger an alert as well as schedule activities.
No scheduler or cron implementation has been selected.

## Activity schedules and the calendar

Start with a simple calendar using start and end times. The first activities
remain tennis, pottery, and guided tours. Their capacity and participant rules
still need properties and checks.

An activity has an ID, a type, and minimum and maximum booking sizes. Total
capacity and the definition of a bookable slot still need to be worked through.

Activity reservations are separate from activities. Each logical reservation
represents one guest attending a slot under a booking. Proposed details are:

- Reservation ID.
- Booking ID.
- Guest ID.
- Activity and slot reference.
- Status: active or cancelled.
- Cancellation reason when cancelled, subject to the constraint discussion.

Booking several guests creates separate reservations. Cancellation adds a new
row to the history of the affected reservation. Attendance tracking is outside
the scope; active does not mean that the guest actually turned up.

Cancelling the parent booking must invalidate its activity reservations. The
mechanism is still open: we have not chosen how that interacts with the separate
reservation histories.

The preference is to handle activity availability and capacity checks in the
application layer. The way to check and commit safely together remains open.

A cancellation reason could remain in the conversation, but the latest proposal
is to keep it on the cancellation record and require it when the status is
cancelled. We still need to settle whether active records must have no reason.

Use an existing calendar library for the interface. Building a calendar renderer
is not a goal of the exercise. We need to understand the data it expects before
choosing one. No calendar library has been selected.

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

## Booking changes and grouped work

Keep grouped bookings in mind while designing individual reservations.
For example, a two-week all-expenses-paid trip could include accommodation,
amenities, and activities spread across several days.

If the trip is cancelled, the system needs to cancel the associated bookings
and release their reserved capacity. We need a way to identify which bookings
belong to that trip.

One proposal is a higher-level record that acts as a recipe, with a workflow
that works through its steps. This is an idea to explore, not a chosen workflow
library or schema. We still need to define what happens when only some steps
succeed, and what cancelling a group means for work already in progress.

## Threads and the audit record

Durable agent threads remain part of the plan. Titles are likely to be useful,
but a title or booking-type label should not define what the thread is about.
The user's goal can change during the conversation.

For example, someone may start by asking for an all-expenses-paid trip and
later choose a regular booking. The transcript should preserve that change
of intent. A stale title or category must not override it.

The intended source of conversational context is the transcript. We still
need to define how it connects to booking records, tool results, and the audit
record of what actually happened. Thread properties and audit properties have
not been designed yet.

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

Research whether SQLite can enforce the booking rules we need before committing
to it. Postgres is an alternative to evaluate if needed. This research is still
pending.

## Topics still to work through

- Remaining activity properties and capacity checks.
- Party changes and room availability rules.
- Charges, the responsible payer, and payment collection.
- Guest comments, their sources, and any interpretation of sentiment.
- The detailed records for the logbook, jobs, grouped bookings, and cancellations.
- Thread messages, tool calls, pending work, and their links to the audit record.
- How to supply and validate time context for the agent.

## Architecture and tools: the next phase

After data modelling, list the actions the application needs to support.
That list will guide the API and the tools exposed to the agent. The project
author will lead that work; these notes do not define the tool list.

Plan for two separate boundaries: the application API and the inference or
agent gateway. Design permissions while working through those interfaces.
The traditional API comes after the data modelling, followed by the inference
gateway. Their responsibilities and implementation are still open.

## Stretch goals and experiments

- Checkout alerts from the scheduling machinery.
- Memory attached to a booking to help staff personalise the stay.
- Grouping freeform key deactivation reasons.
- Trying Jev for classification. The project author has API access and describes
  it as a cheap system-one model. A useful classification task and the API's
  details still need to be explored.
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
