# Moseby

A Python experiment in proactive, staff-facing resort operations.
The project has reviewed gateway contracts, hand-authored migrations and the first
read repositories. Gateway handlers and runtime workers remain to be implemented.

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
publication. The third adds cancellation of pending user input.
Checkout storage and repository mutations remain to be implemented.
Performance indexes are deferred until we review the queries; primary-key and
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
add no state or behaviour here. Bookings, parties, guests, room reservations and
room keys have separate modules. Each query requires a hotel scope supplied by
the service. Repositories use that scope but do not authenticate the caller.

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
gateway shapes. They retain integer UTC-microsecond timestamps; service mapping
converts them for the API. Reservation reads include their exact agreed price
version. Key reads take `now` in UTC microseconds and derive access from the
current booking, reservation dates and revocation state.

`make test-db` exercises the reads against freshly migrated, seeded databases,
including cross-hotel lookups, cursor boundaries and more than 100 keys per stay.

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
501; application services, workers, scheduler and mutation repositories remain unimplemented.
The wider contracts above still distinguish accepted decisions from proposals.
