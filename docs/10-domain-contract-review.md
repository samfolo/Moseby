---
first_committed: "2026-09-19T22:13:38+01:00"
first_commit: "9da0f99"
---

# Checking the rest of the domain

## Objective

Extend the small contract sample across bookings, guests, activities, notes and
keys. Check that names and rules still mean the same thing from one file to another.

## Decisions reached during review

- Keep guest → party → booking → hotel. Returning people get new visit records.
- Include room allocations in booking responses. A stable allocation ID lets
  keys refer to the reservation while its dates or other allowed details change.
- Keep current activity details separate from the price agreed when reserving.
- Use one date-range shape and one set of shared amount and identifier types.
- Treat activity types as lookup records, so adding a type needs no migration.
- Keep booking statuses to confirmed, cancelled and completed. A pending amendment
  leaves the accepted stay intact; a technical failure belongs to the attempted action.

### Reservations and time

- One activity reservation represents one guest. Permit at most one effective
  reservation for the same guest and activity.
- Record cancellation separately from time passing. An event ending does not
  require updating every reservation to a completed or expired state.
- “Effective” means uncancelled and still allowed by its booking. It does not mean
  upcoming, currently happening or attended. Date filters answer those time questions.
- Confirmed and completed bookings preserve uncancelled activity reservations;
  a cancelled booking releases them. Rebooking creates a new reservation ID.
- A reservation must fit within the guest's stay when created, and relevant date
  changes must preserve that rule. Guest clashes remain advisory.
- Search returns effective reservations by default, with explicit options to inspect
  ineffective or all records. Filters still combine: cancelled and effective matches none.
- Count effective reservations for capacity, not their historical revisions.
  Unlimited capacity is different from zero remaining places.

### Keys

- A key refers to a room reservation and has no separate validity dates or guest owner.
- It is effective only while the booking is confirmed, the reservation is uncancelled
  and covers the current time, and the key has not been explicitly revoked.
- An extension therefore extends its keys too. Revoked keys stay revoked.
- Cancelling a booking removes access without inventing a deactivation time for
  every key. That timestamp records an explicit revocation.
- A move replaces the room allocation. Keys for the old allocation cannot open the
  replacement room. A response describes access when read; actual use needs a fresh check.

### Notes and validation

We proposed saving a note first, then classifying its guest references outside
the write transaction. Pending, resolved, ambiguous and failed outcomes made
uncertainty visible instead of throwing away the note.

The first proposal only attached IDs to resolved decisions. Later live review
showed why clear matches should survive alongside an ambiguous name in the same note.

Pydantic can reject malformed IDs, reversed ranges or an invalid update mask.
It cannot prove that a guest belongs to a party or that two requests cannot take
the last place. Those checks need the database and a transaction.

## Questions left open at this stage

- How should a group reservation be accepted together, and what does its price cover?
- Which action marks a stay complete, and what may change afterwards?
- How should staff clarify an uncertain note without creating a duplicate?
- Which creation and amendment routes are actually needed for the demo?

The later implementation added the stay and activity journeys. Payments, physical
locks, automatic notifications and note corrections remained outside the first
working version. See [follow-ups](11-follow-ups.md) for what remains.
