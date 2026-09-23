---
first_committed: "2026-09-15T23:52:43+01:00"
first_commit: "7e82411"
---

# Starting with the hotel

## Objective

Help a concierge keep up with several guests: organise their stays, remember
what matters to them, and help them choose things to do. Staff speak to the
guest and use their own judgement. The agent helps them carry out the work.

## Starting thoughts

- Start with booking a stay, finding suitable rooms, and issuing or replacing keys.
- Record which staff member acted. The booking belongs to the hotel, so colleagues
  should be able to help with it too.
- Keep prices separate from room descriptions. Changing a price should not rewrite
  what an existing guest agreed to pay.
- Use SQLite, Python and Pydantic, with a small agent loop we can understand.
- Two concierges might request the same room. Check availability and reserve it
  together, so both cannot succeed with conflicting bookings.

## How the model changed during the walkthrough

### Bookings, parties and guests

- We first considered keeping one guest identity across visits. We then chose
  a new guest record for each visit, even when the same person returns.
- The relationship became hotel → booking → party → guests. Each booking has one
  party. Each guest belongs to one party. There is no primary guest on the booking.
- A party can reserve several rooms. We dropped individual guest-to-room assignments:
  the system would not reliably know who was sleeping in which room.
- We separated a draft checkout from a confirmed booking. Cancelling a booking
  became final; booking again creates new records rather than reviving old access.

### Rooms, prices and keys

- A room has a label, beds, bathrooms and a tier. Separate bed rows make it easy
  to find rooms with a particular bed type. Tier and bed layout are different things.
- For the demo, sleeping capacity comes from adding up the beds' capacities.
  A separate occupancy limit would need its own rule if we introduced one.
- A room can be out of service. Whether it is available also depends on the
  requested dates; booked or held should not be permanent room statuses.
- Rooms can share a price ID. New price versions preserve old amounts, and each
  reservation keeps the version it agreed to. Activity prices follow the same idea.
- Keys need their own IDs so one lost key can be revoked. We changed their link
  from the room to its reservation, so a later booking cannot revive an old key.
- Keys follow the reservation's dates. We do not know who is holding each key,
  and a key being used would not prove that a particular guest was present.

### Guest notes and activities

- Save a note once against the party. Use Jev to suggest which guests it mentions,
  choosing only from that party's guests. Save the note even when this is unclear.
- A note is something someone reported. Linking a name does not prove the report
  is true or automatically change a guest's dietary requirements.
- Guests have their own dietary and contact details. Choosing email or phone as
  a contact preference requires that detail to be present.
- An activity is a dated event at a venue. One reservation represents one guest;
  a group request can create several reservations together.
- Guests may deliberately book overlapping activities. Warn about clashes, but
  do not forbid them. Sharing a venue also does not automatically mean a clash.
- Enforce activity capacity, group-size limits and minimum age. A null capacity
  means unlimited places. Venue capacity is a separate administration concern.
- Cancelling a booking releases its activity places through the booking's state.
  We do not need to write a cancellation against every historical reservation.

## Questions left open at this stage

- What survives an unfinished checkout, and how long should rooms be held?
- How do room changes, extra guests and early departures affect the original stay?
- What happens when an outside service accepts work but has not finished it?
- How should reminders, activity changes and notifications reach staff or guests?
- Which checks belong in transactions, and which need staff judgement?

We gathered these into the [design review](04-design-review.md). Payments,
physical locks, housekeeping, packages, semantic search and cross-visit memory
were possibilities to revisit, rather than requirements for the first demo.
