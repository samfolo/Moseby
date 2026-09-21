# Moseby

Moseby is a Python experiment in helping resort staff look after their guests.
The aim is an agent that can manage bookings, arrange activities and follow up
when something needs attention.

The database and repository methods are in place, and the inference provider can
make model requests. The agent loop, working API handlers and user interface still
need to be connected. This is a work in progress.

## Get started

Use Python 3.14:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[contract,dev]'
make migrate
make check
```

`make migrate` creates or updates the local SQLite database, `moseby.db`. Git
ignores this file. To use another location:

```sh
MOSEBY_DATABASE_URL=sqlite:////absolute/path/moseby.db make migrate
```

[Ruff](https://docs.astral.sh/ruff/) keeps the Python code consistent.
`make format` sorts imports and formats the code. `make check` checks formatting
and catches common mistakes. To use another Python environment, pass
`PYTHON=/path/to/python` to either command.

## Call a model

Set these three environment variables before running the Python example below:

```sh
export OPENROUTER_API_KEY='your-key'
export MOSEBY_GENERATION_MODEL='provider/model'
export MOSEBY_CLASSIFICATION_MODEL='typesafe/jev-1.13'
```

Replace `provider/model` with an OpenRouter model that supports tool calls.
[Settings](moseby/config.py) require all three values. The key uses Pydantic's
`SecretStr` type and is excluded when settings are printed or exported normally.
If you keep settings in a `.env` file, load it through your shell or process
launcher. Moseby reads the environment directly, and Git ignores `.env` files.

The [provider interface](moseby/inference/provider.py) has two methods:

- `generate` returns an assistant reply, which may include tool calls.
- `classify` answers questions about supplied information. It can estimate
  whether a statement is true or choose one item from a list.

The [OpenRouter implementation](moseby/inference/providers/openrouter.py) uses
HTTPX to make requests. It translates our models into the provider's JSON format
and validates the replies. Tool arguments stay as dictionaries in our code and
become JSON strings when sent to the provider. External URLs are listed in
[endpoints.py](moseby/inference/providers/endpoints.py).

```python
import asyncio
import httpx

from moseby.config import InferenceSettings
from moseby.inference.models.generation import GenerationRequest, TextMessage
from moseby.inference.providers.openrouter import OpenRouterProvider


async def main():
    settings = InferenceSettings.from_environment()
    async with httpx.AsyncClient() as client:
        provider = OpenRouterProvider(settings, client)
        result = await provider.generate(
            GenerationRequest(
                messages=[TextMessage(role="user", content="Hello, Moseby.")]
            )
        )
        print(result.output.text)


asyncio.run(main())
```

Each result includes the request and response bodies so the runtime can save what
happened. Assistant replies also keep provider data needed for the next call,
such as reasoning signatures. The provider returns complete replies; streaming
is still to be added.

Classification uses OpenRouter's
[Decisions API](https://openrouter.ai/docs/api/api-reference/alphadecisions/submit-a-decisions-questions-and-answers-request).
For example, one request can contain a guest note, the party's guest list and a
question about each guest. The application must decide how confident an answer
needs to be before saving a reference. A high score alone does not prove that the
model identified the right person.

The calling code manages the HTTP client and decides when to retry. Requests
allow 10 seconds to connect and 60 seconds for network reads or writes.
The provider uses the application API key. The service and runtime still need
to connect staff permission checks, thread ownership and a record of who requested
each call.

## How the data layer works

[Hand-written Alembic migrations](moseby/db/migrations/versions) define the SQLite
tables, constraints and triggers. They cover hotel data, thread history, queued
work and keyword search. Constraints catch invalid writes even if application
code makes a mistake. Changes that need history are saved as new revisions.

To read the migration SQL without creating a database:

```sh
.venv/bin/python -m alembic upgrade head --sql
```

### Read data through repositories

Each resource has a [repository module](moseby/db/repositories), such as
`bookings` or `guests`. Its functions take a database connection as their first
argument. The caller opens the transaction and decides when to commit it.

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

`find_by_id` returns one row or `None`. `find_by_ids` accepts up to 100 IDs and
returns a dictionary of the records it found. `find_all_by_*` returns a page.
Hotel-owned data is filtered by hotel, and private thread data by its creator.
The service must check the caller's permissions before using these methods.

[Pagination](moseby/db/pagination.py) normally sorts by creation time, then ID.
Pass `page.next_cursor` to the next request until it is null. Keep the same filters
when following a cursor. Results can change between requests; a cursor does not
freeze the data. Thread history uses its saved sequence to preserve record order.

Room searches filter by price, tier, beds, bathrooms and availability before
paging the results. Activity searches include capacity and date filters.
[Party-note search](moseby/db/full_text.py) uses SQLite's FTS5 keyword search.
All supplied words must match, but case, word order and Latin accents do not matter.

### Change related records together

[Domain operations](moseby/db/operations/stays.py) combine repository methods in
one transaction. For example, creating a stay saves the booking, party, guests
and room reservations together. If any step fails, all of those changes roll back.
SQL stays in the data layer.

Writes check room overlap, activity capacity, guest age and whether an activity
fits within the stay. Guests may book overlapping activities. For this demo,
single and twin beds sleep one person; double, queen and king beds sleep two.
An unknown bed type contributes zero places. The party needs enough sleeping
places throughout its stay.

Edits supply the last `updated_at` value or revision number they read. This lets
the repository reject an edit if someone else changed the record first.
[Command handling](moseby/db/operations/commands.py) saves a request, its changes
and its response together. Repeating the same command returns the saved response.
Permission checks still apply to a repeated request.

Finding an available room does not reserve it: the write checks availability
again. Checkout holds and payments still need to be added. Moving an activity
that already has reservations is blocked until we can notify affected guests.

### Claim work and save results

Jobs describe the work to do. Tasks are the pieces that workers can claim.
A claim gives one worker a token and an expiry time. The worker must present a
valid token when it saves results, so a worker that lost its claim cannot overwrite
newer work.

Queue changes use `transaction(engine, write=True)`, which takes SQLite's write
lock before reading the state needed for a change. Capture `now` after entering
that transaction. Commit the claim before doing slow work or calling an external
service. Afterward, use `task_claims.guard` to save related changes and the task
outcome together. External services need their own duplicate-request protection.

[Job completion](moseby/db/operations/job_completions.py) saves the outcome and a
pending delivery together. Delivery then adds the result to thread history and
updates its summary in one transaction. Repeated delivery returns the record
already saved. Late results can be recorded after a run stops without restarting it.

## Run the checks

```sh
make test-db
make test-models
make test-contracts
make test-inference
```

Database tests use freshly migrated databases with sample data. They cover hotel
boundaries, concurrent bookings, cancellation, paging and worker claims. Inference
tests use HTTPX's `MockTransport` to supply responses without contacting a model.
Those tests check our request handling; model accuracy needs a separate live check.

## What remains

The next step is to connect the agent loop, services and worker execution so a
staff message can lead to a model reply and tool calls. The API routes currently
return HTTP 501, meaning they are defined but not implemented.

The database includes tables for schedules and notifications, but their execution
still needs to be built. Checkout, payment handling and a user interface are also
unfinished. Search and uniqueness constraints already have some indexes; further
performance indexes will follow the queries that need them.

## Find your way around

- [API models and routes](moseby/contracts), plus the [generated OpenAPI file](openapi.yaml).
- [Runtime message models](moseby/runtime/models/thread_records.py).
- [Database models](moseby/db/models), [repositories](moseby/db/repositories) and
  [operations that combine them](moseby/db/operations).
- [Permissions and tools](docs/permissions-and-tools.md).
- [Domain design notes](docs/data-modelling.md) and [runtime notes](docs/runtime-review.md).
- [Checkout diagrams](docs/checkout-lifecycle.md) and [steering research](docs/steering.md).

The design notes include earlier proposals as well as accepted decisions. The
migrations define the working database; `schema/draft.sql` is an older sketch.
