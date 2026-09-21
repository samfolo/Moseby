# Moseby

A Python experiment in proactive, staff-facing resort operations.
The project has reviewed gateway contracts, hand-authored migrations, domain
repositories, and durable job/task storage. Gateway handlers and the agent turn
loop remain to be connected.

## Formatting and linting

Use Python 3.14 and the pinned [Ruff](https://docs.astral.sh/ruff/) version for
formatting, import ordering and linting:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[contract,dev]'
make format
make check
```

`make format` sorts imports and formats Python. `make check` reports lint and
formatting problems without changing files. Rules live in `pyproject.toml`:
88-column formatting, basic errors, unused names and common bug patterns.
Docstrings remain concise; no mandatory docstring boilerplate is imposed.
For another environment, pass `PYTHON=/path/to/python` to either command.

## Database

Hand-authored [Alembic migrations](moseby/db/migrations/versions) define the SQLite
schema. The first migration covers domain tables and immutable revision history.
The second covers threads, records, queued work, schedules and notification
publication. The third adds cancellation of pending user input. The fourth adds
FTS5 keyword search for party evidence, kept in sync by database triggers.
Checkout storage and payment handling remain to be implemented.
Other performance indexes are deferred until we review the queries; primary-key and
uniqueness indexes enforce data rules already, including one active run per thread.
`schema/draft.sql` is historical and is not used to initialize the database.

```sh
make migrate
make test-db
```

The default database is `moseby.db` (ignored by Git). To choose another SQLite file:

```sh
MOSEBY_DATABASE_URL=sqlite:////absolute/path/moseby.db make migrate
```

Inspect SQL without creating a database:

```sh
.venv/bin/python -m alembic upgrade head --sql
```

## Repository reads

[Repositories](moseby/db/repositories) are resource modules with connection-first
functions. Python modules provide the namespace; a class of static methods would
add no state or behaviour here. Each resource has its own module. Hotel-owned
resources require a hotel scope supplied by the service; activities, activity
types, venues and prices are shared catalogues. Repositories apply scope but do
not authenticate the caller.

```python
from moseby.db.pagination import PageRequest
from moseby.db.repositories import bookings, guests
from moseby.db.transaction import transaction

with transaction(engine) as connection:
    booking = bookings.find_by_id(connection, booking_id, hotel_id=hotel_id)
    guest_page = guests.find_all_by_booking_id(
        connection, booking_id, hotel_id=hotel_id, page=PageRequest(limit=50)
    )
```

`find_by_id` returns one typed row or `None`. `find_by_ids` returns a dictionary
of found IDs, omitting missing and out-of-scope resources; batches accept up to
100 input IDs. `find_all_by_*` returns a flat page. Repositories share the caller's
connection and never commit or acquire another one.

[Pagination](moseby/db/pagination.py) orders by `(created_at, id)` ascending.
Continue with `PageRequest(cursor=page.next_cursor)` until the cursor is null.
Tokens bind to the query and its scope/filters; changing page size is allowed.
Tokens are continuation positions, not credentials or snapshots. Every page
reapplies scope. Rows may change between requests, and inserts behind the cursor
require a refresh to see. Sequence-based runtime feeds have their own ordering.

[Database read models](moseby/db/models) are frozen Pydantic models, separate from
gateway shapes. Shared [domain enums](moseby/domain/enums.py) supply choices to
both layers and repository queries; migrations keep their original values.
Read models retain integer UTC-microsecond timestamps; service mapping
converts them for the API. Reservation reads include their exact agreed price
version. Key reads take `now` in UTC microseconds and derive access from the
current booking, reservation dates and revocation state.

Activity searches accept ID, venue, type, overlapping-date and available-place
filters. Reservation searches produce flat guest/party itineraries and default to
effective reservations. Their agreed prices stay fixed while catalogue prices can
change. Capacity counts include all hotels, including results beyond the current
page; individual reservation reads remain hotel-scoped.

Room reads attach the current price and fetch all beds for a returned page in one
additional query. Room search applies IDs, tiers, bed types/counts, bathrooms,
service status, currency-specific price bounds and reservation availability before
pagination. It requires every requested bed type; other lists match any value.
Availability uses current reservations on confirmed bookings and allows touching
stay boundaries. Checkout holds remain unimplemented; their eventual storage must
join the same availability check before the gateway supports checkout. Search
does not reserve a room, and booking must recheck capacity in its write transaction.
Price lookups also support an exact saved revision.
Party-evidence searches filter saved guest references and FTS5 whole-word keywords.
All keywords must match, in any order; case and Latin accents are ignored.
Punctuation separates words, and query operators are treated as ordinary words.
Results keep the same creation-time order and hotel scope. The small activity-type catalogue is returned
in full, ordered by code; ordinary resource lists use the shared paginator.

Thread, run, history and incoming-input repositories require the thread creator's
staff member ID. Services also check current permissions before exposing those
rows. History and input pages follow their saved sequence, using shared cursor
handling in `pagination.py`. History reads include internal events; services
select conversation kinds for public responses and validate payloads by kind and
format version. A waiting run remains active, and a pending steer remains visible
after its target run ends. These reads neither deliver input nor advance a run.

Job, task, claim and completion reads require the acting staff member to own the
job and any linked thread. Request lookups use the actor, operation and request ID
together. Claims remain readable after expiry; worker writes must check the token
and expiry in the write itself. Completion searches show undelivered results by
default, including results for stopped runs.

Schedule reads include disabled definitions. Recorded occurrences keep their
original job and thread scope after a schedule changes. Notifications and events
are visible to their author or staff recipient within the recipient's hotel.
Event reads resume after a saved publication sequence, allowing gaps; consumers
track processing separately. These reads do not execute schedules or publish messages.

`make test-db` exercises the reads against freshly migrated, seeded databases,
including cross-hotel lookups, cursor boundaries, cancellation and more than 100
keys or activity reservations.

## Domain writes

Resource repositories own SQL; [domain operations](moseby/db/operations/stays.py)
compose them on the caller's `transaction(engine, write=True)` connection:

- Create a confirmed stay with its party, guests and room allocations together.
- Update guest details and record dietary changes with their original evidence.
- Save notes as pending, then validate and save the classifier's guest references.
- Move or extend room allocations, and issue or deactivate reservation-bound keys.
- Create/edit activities, reserve a whole group atomically, and cancel places.

Writes check room overlap, activity capacity, guest age and stay coverage under
SQLite's write lock. Guest activity overlaps are allowed. Room capacity comes
from bed types: single/twin sleeps one, double/queen/king sleeps two, and unknown
contributes zero. The party must have sufficient sleeping places throughout its
stay; independent room occupancy limits are outside the demo.

Mutable edits require the saved `updated_at`; revisioned edits require the saved
revision. [Command execution](moseby/db/operations/commands.py) stores a request,
its local effects and its response together, so retries replay the response.
Services must check current permissions before calling it, including on retries.

Confirmed-stay creation records an accepted booking; it does not verify payment.
Room, venue and price catalogue setup remains separate. Moving a booked activity's
time or venue is rejected until the notification workflow can accompany it.
These repository methods do not yet make the HTTP handlers operational.

## Queue writes

Use `transaction(engine, write=True)` and capture `now` after entering it. This
starts SQLite's write transaction before checking mutable state. Repository
methods share the connection and never commit on their own.

- `request_deduplication.accept` returns whether the command is new. Reusing its
  actor/operation/request key with different input raises `IdempotencyConflict`.
- For a new command, call `jobs.create`, `tasks.create` and `save_response` in that
  same transaction. For a replay, check current permissions and return the saved
  job or response.
- `task_claims.claim` and `claim_next` start one attempt with a fresh token.
  Commit before running the handler or calling an external service.
- `renew` extends a live lease. After execution, use `task_claims.guard` around
  related local changes and `tasks.succeed`, `fail` or `retry`. Each outcome write
  also checks the token and expiry itself. An exception rolls back the guarded
  group, even if the caller catches it.

A waiting run pauses agent-driving work but permits its linked tool jobs. A stop
request blocks new attempts; already running tasks can still save evidence while
their job remains unfinished. Local claim checks do not make external side effects
idempotent; the integration must use its own stable effect identity.

`db.operations.job_completions.finish` saves a settled job's outcome and pending
delivery together. Every task must be terminal, and success requires all tasks to
have succeeded. The handler decides when its workflow has reached its final phase.
`deliver` then saves one history record, the supplied thread summary and the receipt
together. It checks the history and projection positions used to build that summary.
Retries return the existing outcome or record. Delivery never resumes a stopped run.
These operations use the caller's transaction and compose the resource repositories;
worker-driven domain changes and task outcomes belong in the same guarded transaction.

## Current contracts

- [Runtime routes](moseby/contracts/runtime_api.py) cover threads, incoming input,
  runs, jobs, schedules, occurrences and notifications. They generate the runtime
  sections of [OpenAPI](openapi.yaml); handlers return 501 until services are wired.
  Run their contract checks with `make test-contracts`.
- [Runtime message models](moseby/runtime/models/thread_records.py) validate the
  stored record kinds and payloads. [Thread contracts](moseby/contracts/threads.py)
  and [run contracts](moseby/contracts/runs.py) define gateway representations.
  Run their validation tests with `make test-models`.
- [Next domain models](docs/domain-contract-review.md): review the hotel, staff,
  booking, party, key and activity models after the approved foundation.
- [Python contract draft](docs/python-contract.md): first Pydantic models,
  proposed endpoint permissions and verified QUERY generation behaviour.
- [Generated OpenAPI](openapi.yaml): domain resources and proposed endpoint permissions.
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

The Python contract draft uses FastAPI to generate OpenAPI. Its handlers return
501; application services, workers and the scheduler remain unimplemented.
Repository writes cover the domain operations above, command acceptance, job/task
creation, task attempts and job-result delivery.
Workflow handlers, run/input transitions and schedule/notification writes remain to be built.
The wider contracts above still distinguish accepted decisions from proposals.
