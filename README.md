# Moseby

A Python experiment in proactive, staff-facing resort operations.
The project is in contract design; the SQL draft is not yet a complete application.

## Current contracts

- [Resource and API contract](docs/api-overview.md): selected conventions, resources
  and remaining route/payload choices.
- [Runtime contract](docs/runtime-review.md): threads, jobs/tasks, claims, records,
  schedules and durable publication.
- [Permissions and tools](docs/permissions-and-tools.md): accepted access boundaries
  and the proposed operation map for the next short review.
- [Remaining decisions](docs/design-review.md): local open choices and SQL drift.

These contracts supersede older alternatives in the supporting discussion.
Accepted rules and proposals are labelled separately; no route example silently
selects an implementation or changes the domain model.

## Supporting material

- [Domain notes](docs/data-modelling.md)
- [Checkout and room-change diagrams](docs/checkout-lifecycle.md)
- [Earlier runtime discussion](docs/agent-runtime.md)
- [Codex steering research](docs/steering.md)
- [Schema guide](schema/README.md) and [older SQL draft](schema/draft.sql)

No runtime code, server/framework, scheduler library or performance indexes have
yet been selected/implemented. The current pass records decisions before that work.
