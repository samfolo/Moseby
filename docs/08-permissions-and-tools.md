---
first_committed: "2026-09-19T19:04:32+01:00"
first_commit: "cf7f04a"
---

# Deciding what the concierge may do

## Objective

Let the agent help staff without giving it every action the application might
support. Keep access checks in code, even when a tool is hidden from the model.

## Thinking at this stage

- Start with one seeded staff member. The application supplies that identity to
  services and jobs; the model cannot choose who it acts as.
- The agent works within the staff member's authority and its own configured tools.
  Jev decisions do not get a separate permission bypass.
- A thread belongs to its creator and records the permissions it started with.
  Current authority must still cover them. New grants need a new thread; revoked
  grants must not survive just because an old thread recorded them.
- Apply thread access to its input, records and results too. Checking only the
  thread list would leave other ways to read the same information.
- Permission to read a resource does not mean permission to read every hotel's
  records. Check the hotel or owner as well as the requested action.

### How the permission names developed

We first grouped operations, then gave the groups names such as
`moseby.guests:read` and `moseby.bookings:write`.

- Bookings cover room allocations and keys. Guests cover parties and their notes.
  Activities stay separate because an itinerary reveals more than a guest's name.
- Names start with lowercase `moseby`, use dot-separated path segments, and end
  in `:read`, `:write` or `:execute`. Those actions are independent.
- A grant covers the same path or a child path with the same action.
  `moseby.rooms:write` covers `moseby.rooms.configuration:write`; a sibling does not.
- Broad grants such as `moseby:write` therefore include configuration. Leaving a
  specific grant out would not help if a broader grant already allowed it.
- We chose a validated permission type and resolver instead of scattered string
  splitting. The [implementation](../moseby/permissions.py) owns that comparison.

Route metadata can describe required permissions in OpenAPI. It does not enforce
them. The service must make the check, including when called directly by a tool.

### Tools and direct staff actions

- Load only tools the agent is allowed to use. Check permission again on execution.
- Describe each tool's input, result, permission and retry behaviour. The offered
  tools should be useful actions, rather than a copy of every table or HTTP route.
- During later review we made the concierge boundary explicit: help guests use
  existing rooms and activities; leave beds, room configuration and activity
  creation to a different administrative role or agent.
- Some controls need a direct user action through any interface. We changed the
  wording from “UI-only” to “user-only”; the caller cannot grant this by setting a flag.
- Scheduled work would also need current permission checks and an explicit
  destination. It must never deliver into whichever thread happens to be open.

## Questions left open at this stage

- What should the full role-to-permission map contain?
- Which controls require a direct user action, and how is caller origin established?
- How should the system handle permission changes during work already in progress?
- How much guest information should each tool return for the task at hand?

The demo later implemented service checks with a fixed staff identity. Login,
role administration, full auditing and a guest-facing access model remain in
[follow-ups](11-follow-ups.md). A classifier may flag a suspicious request, but
it cannot replace those access checks.
