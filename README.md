# Moseby

A Python experiment in proactive, staff-facing resort operations.
The project has reviewed gateway contracts and hand-authored database migrations.
The gateway handlers and repositories are not yet implemented.

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
Repositories, workers and checkout storage remain to be implemented.
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
501; application services, workers, scheduler and database access remain unimplemented.
The wider contracts above still distinguish accepted decisions from proposals.
