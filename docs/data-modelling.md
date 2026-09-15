# Data modelling notes

Moseby is a lightweight experiment in proactivity for resort scheduling.
This document records the current thinking. It is a draft, not a finished
database schema. Open questions are left open so we can work through them.

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

The point of contact is the person who makes the reservation. We initially
considered calling them the cardholder. Whether the contact and payer must be
the same person is still open.

The proposal is to make parties immutable. We still need to define what that
means if someone joins or leaves the group, or a staff member corrects a mistake.

We have not decided how much separate information belongs on the reservation
and the party. We also have not decided whether an explicit hotel or location
reference is needed for the first version. Multiple locations remain a possible
future concern.

## Guests

A guest represents a person. The same guest can return for several stays and
therefore belong to several parties over time.

Proposed details:

- Unique guest ID.
- First name and last name.
- Age, because some activities may have age restrictions.

Age is the current proposal. We still need to decide how it stays accurate for
returning guests.

Identity documents or identity verification details were considered, but are
not a requirement at this point. No decision has been made to store document
copies or identifiers.

Individual preferences, dietary requirements, and other accommodations are
part of the wider guest journey. Their properties will be discussed separately.

## Rooms and allocations

A room is a physical room in the hotel. Proposed details include:

- A unique room ID.
- A room number that staff and guests recognise.
- A description.
- Bed details and number of bathrooms.
- Room category, such as twin, master, or presidential.

A room allocation connects one room to one party for a stay. It also records
which guests from that party use the room. A party can have several room
allocations, and a room allocation can contain several guests.

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

Effective-from and effective-until dates were considered but are deferred.
Discounts are also deferred. The money representation and currency have not
been chosen. We still need to decide how an agreed booking price is retained
when the price list changes.

## Room keys and claiming a room

We want to know whether a party has claimed its allocated room. The exact
meaning of claimed, checked in, and checked out needs to be settled.

A room can have several keys, so keys need separate records. A single status
on the room would not describe each issued key.

Possible key states discussed were active, inactive, reported lost, and
deactivated. The final states have not been chosen. We also need to decide
whether losing a key is a status, a recorded event, or both.

The key journey is:

1. Staff issue one or more keys for an allocated room.
2. A guest may report a particular key lost.
3. Staff deactivate that key and can issue a replacement.

We have not yet chosen the key properties or how keys relate to an allocation
and individual guests. Integration with physical door locks is not specified.

## Storage and concurrent bookings

SQLite is the current preference for storage. The number of concepts alone
does not settle how booking conflicts should be handled.

Several concierges could try to book the same room for overlapping dates.
We need to prevent conflicting allocations even though the application is
staff-facing.

Locking was raised as a possible approach. Before choosing one, we need to
check SQLite's transaction behaviour and decide how to make the availability
check and booking write safe together. No locking strategy is settled here.

## Topics still to work through

- Activity schedules, capacity, and participant rules for tennis, pottery,
  and guided tours.
- Breakfast delivery and other room services.
- Charges, the responsible payer, and payment collection.
- Guest comments, their sources, and any interpretation of sentiment.
- Hotel-local dates, time zones, and UTC timestamps.
- Booking changes, cancellations, and unavailable rooms.
- The audit record for staff actions and agent actions.
- Durable threads, messages, tool calls, and pending work.

## How we will develop this

Python, Pydantic, a manually implemented turn loop, and durable threads are
agreed directions. The remaining libraries and implementation details are
still open.

We will work through the design in small steps. Documentation should use plain
language and make the reasoning easy to follow. Commits should be small, with
short conventional commit messages, so the history shows how the design develops.
