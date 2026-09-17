# SQLite schema draft

[draft.sql](draft.sql) turns the current discussion into SQL that we can read,
run, and revise. It is not yet a complete booking system or a migration plan.

## What is included

| Table or view | Purpose |
| --- | --- |
| `staff` | Staff identity, human-readable code, name, and title |
| `guests` | The guest details already discussed, including age |
| `bookings` | Party name, primary guest, creation time, and proposed booking status |
| `rooms` | Room number, description, bed and bathroom counts, and category |
| `room_reservations` | The history of each room reserved under a booking |
| `current_room_reservations` | The latest revision of each room reservation |

The latest guest, price, key, and activity proposals are recorded in the
[design notes](../docs/data-modelling.md). They have not been added to this SQL
draft yet. In particular, the guest table still needs its booking link,
preferred name, dietary requirements, and other accommodations.

Guests are not assigned to rooms. A service request can name a destination room
without establishing a permanent guest-to-room relationship.

## Draft choices to review

- IDs use caller-supplied text. We have not chosen UUIDs or another ID format.
- The draft assumes one hotel. Staff codes and room numbers are unique within it.
- Timestamps use whole Unix seconds, representing UTC instants. This storage
  format is a draft choice; the UI and API formats remain open.
- A booking needs an existing primary guest. Decide later whether incomplete
  bookings should be allowed before that guest is known.
- Booking statuses use readable text. The proposed numbers for settled (3) and
  cancelled (4) are recorded in the design notes. No complete number mapping
  has been selected.
- The booking status check lists proposed labels. It does not define which
  transitions are allowed or settle the meaning of each label.
- The room-reservation status list remains open. For now, the SQL requires only
  a non-empty label.
- A room reservation keeps the same booking and room across its revisions.
  A different room gets a new reservation ID.

## How room reservation history works

`id` identifies the reservation. Together, `id` and `revision` identify one
historical row. Every revision contains the full state of the reservation.

An extension adds revision 2 with a later checkout time. Cancelling that room
adds revision 3 with a changed status. Both earlier rows remain available.
The current view selects revision 3, even if the timestamps on the revisions
are equal. The revision number determines their order.

This is an ordinary view: a named query. It does not store a separate copy of
the results or need to be refreshed like a materialised view.

Triggers reject updates, deletes, replacement of existing revisions, and gaps
in revision numbers. They also keep the reservation tied to its original
booking and room. Choosing and retrying revision writes in the application
still needs to be designed.

## Rules still missing

The schema does not yet prevent overlapping room reservations or coordinate a
booking cancellation with all its room reservations. Status transition rules,
concurrent booking behaviour, and the effect of booking status on availability
are still open.

Price records, payment references, party membership, keys, the arrival logbook,
activities, jobs, permissions, and agent threads still need their own passes.
The payment provider's internal lifecycle is outside this exercise.

## Inspect the draft

From the repository root, using SQLite 3.37 or later:

```sh
sqlite3 :memory: '.read schema/draft.sql' '.schema'
```

Every database connection must enable `PRAGMA foreign_keys = ON` before starting
a transaction. The setting at the top of the draft covers the connection that
loads the script, not future connections.

SQLite supports [CHECK constraints](https://www.sqlite.org/lang_createtable.html#check_constraints),
[STRICT tables](https://www.sqlite.org/stricttables.html), and
[triggers](https://www.sqlite.org/lang_createtrigger.html).
See also its [foreign key documentation](https://www.sqlite.org/foreignkeys.html).
