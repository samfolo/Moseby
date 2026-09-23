---
first_committed: "2026-09-19T17:13:34+01:00"
first_commit: "ca69ff4"
---

# Choosing the API shape

## Objective

Give the data model a set of actions that we could review before implementing
handlers. An API resource need not mirror a table, and an agent tool need not
mirror an HTTP endpoint.

## Conventions settled during review

- Use plural resource names and kebab-case paths, such as `/party-details`.
- `GET /resources` lists a collection; `GET /resources/{id}` reads one item.
- Use `QUERY /resources` with a structured body for searches, without a `/search` suffix.
- Put command data in `payload`. Use `request_id` to recognise retries of the same command.
- Use PATCH for partial updates. The `update_mask` names exactly the supplied fields;
  it does not permit changes to fields the caller is forbidden to edit.
- Prefer named actions for cancellation, approval or deactivation over arbitrary
  status updates. We discussed colon action paths and `:batchGet`.
- Search ID lists mean any ID within a list, combined with the other filters.
  They return matching records, not every possible combination of IDs.
- Keep one forward cursor over a flat result list. Batch lookup and search have
  different jobs; a search is not a promise to return every requested ID in order.

## Proposed resource groups

| Group | What callers need |
| --- | --- |
| Rooms | Beds, tier, current price and availability for requested dates. |
| Bookings | The party's stay, its room allocations, and allowed amendments. |
| Room keys | Issue, inspect and deactivate keys tied to a reservation. |
| Guests and parties | Find the right people and update their visit details. |
| Party details | Save and search notes, with any identified guest references. |
| Activities | Discover dated events, prices and remaining capacity. |
| Activity reservations | Reserve or cancel places and look up an itinerary. |
| Threads and input | Create a conversation, send input, read history or request a stop. |
| Jobs | Inspect accepted work and its outcome. |
| Schedules and notifications | Arrange future work and inspect what was published. |

Hotels, staff and venues supplied supporting information. Beds, price versions,
room allocations, claims and payment attempts did not each need a public API.
Booking operations own the changes that need to happen together.

### Details that mattered

- Room search joins the current price and applies availability before pagination.
  Finding a room does not hold it.
- An itinerary can be a reservation search by guest and date, with activity details
  included. It does not need a separately stored itinerary.
- A shared venue or activity has no hotel owner. A guest's reservation still belongs
  to the hotel through their booking and needs the corresponding access check.
- Request validation cannot prove membership, available capacity or permission.
  Those checks need the saved state and service logic.
- Model-facing tools should express useful actions. Administration and internal
  worker operations do not become concierge tools just because an API exposes them.

## Questions left open at this stage

- Which setup and checkout operations were needed for the first working journey?
- What should batch lookup do with missing IDs, and how should cursors be encoded?
- Which actions require direct staff input rather than an agent call?
- Which permissions and fields belong on each operation?

The [Python contract](09-python-contract.md) made these conventions concrete.
Later we wired tools and HTTP handlers to shared services. Runtime routes,
scheduling and notification proposals were removed from the focused main branch;
they remain on the extensions branch. The generated [OpenAPI](../openapi.yaml)
describes the HTTP surface kept on main.
