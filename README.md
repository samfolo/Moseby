# Moseby

A Python experiment in proactive, staff-facing resort operations.
The project is in contract design; the SQL draft is not yet a complete application.

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

## Current contracts

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
