# Moseby

Moseby is a Python experiment in helping resort staff look after their guests.
The aim is an agent that can manage bookings, arrange activities and follow up
when something needs attention.

The terminal app saves conversations, calls a model and runs a room-search tool.
Guest lookup, room search and activity browsing also work over HTTP. The database
and repository methods cover the wider domain; more tools and API handlers will
connect those capabilities to the concierge.

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

Set these three environment variables before starting a conversation:

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

Initialise the demo hotel and rooms, then start a conversation:

```sh
.venv/bin/python -m moseby init
.venv/bin/python -m moseby chat
```

Try “Show me the available room tiers and prices.” The terminal prints the saved
thread ID. Use `/exit` to leave, then reopen it with:

```sh
.venv/bin/python -m moseby chat --thread thread_...
```

For one message, use `chat --message "Show me the rooms"`. To choose a database,
put `--database /path/to/demo.db` before `init` or `chat`. Initialisation preserves
existing demo data.

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
The provider uses the application API key. The conversation runtime checks current
staff permissions and thread ownership before inference and tool execution. It
saves each inference attempt and the history records included in its input.

## Define an agent

An [agent definition](moseby/agents/models.py) contains its ID, version, display name,
description, system prompt, tool names, permission limits and per-run budgets.
Pydantic checks it when it is constructed, and it can be saved as JSON. The
[concierge prompt](moseby/agents/prompts/concierge.v1.md) is a bundled text file,
loaded with `concierge_prompt()`.

[`create_agent`](moseby/agents/agent.py) combines a definition with current staff
identity, saved thread context and a catalogue of tool definitions. Only the
thread creator can use it, and their current permissions must still cover the
thread's original permissions. The agent's own limits can narrow that access.
Tools are offered only when all of their required permissions are covered.

The service supplies identity and permissions from trusted staff data. The worker
checks them again when executing tools. Thread storage already records the
creator and original permissions. Threads and runs also have `agent_id` and
`agent_version` columns for evaluation queries. The creation record keeps the same
selection; `AgentThreadContext.from_creation_record()` restores it. Database
constraints keep these values consistent and prevent attribution from changing.
`index_agent_definitions()` rejects duplicate ID/version pairs. Keep each released
agent definition and prompt version unchanged so existing threads retain their settings.

The domain context names the acting staff member and hotel. The thread context
holds the saved selection and access limits. Threads without a saved agent selection
remain readable with empty attribution fields, but agent construction requires an
explicit selection. The thread and run repositories provide
`find_all_by_agent_id()`, with an optional version filter and forward pagination.

`max_turns` limits generation requests in a run. The loop adds up the provider’s
reported input and output tokens and checks `token_budget` before the next call.
One reply can exceed the remaining budget. If usage is missing, a final answer
can finish the run, but the loop stops before making another request.

## Define a tool

A [tool](moseby/tools/definitions.py) combines Pydantic argument and result models,
required permissions and an async handler. Its model-facing JSON Schema comes
from the argument model used during execution. The handler receives trusted staff,
thread and job context separately from the model's arguments.

[`execute_tool`](moseby/tools/execution.py) refreshes access, checks that the tool
is offered, validates arguments and calls the handler. Invalid arguments return
field-level errors. A handler can raise `ToolFailure` with a safe explanation of a
business conflict. Unexpected errors and invalid handler output reach the worker's
failure handling.

The [room tool](moseby/tools/rooms.py) binds `search_rooms` to the application's
database engine. Its [service](moseby/services/rooms.py) checks room read access,
keeps queries within the caller's hotel and maps database rows into the room
contract. The async handler runs synchronous database work in a worker thread.
The local worker executes saved tool tasks one at a time. Room search is the
concierge’s current tool; the other domain tools still need connecting.

## Follow a turn

The [turn loop](moseby/runtime/loop.py) is an explicit `while` loop:

1. Save the user message and start one run on its thread.
2. Build model input from saved conversation history and the current agent context.
3. Save the inference attempt, then call the provider.
4. Save the reply and any tool jobs together. Claim each task, execute it and
   save its result back into the conversation.
5. Call the model again with those results, until it answers or reaches a limit.

[Context assembly](moseby/runtime/context.py) selects messages the model needs.
Control records stay in history, and provider continuation data stays with its
assistant reply. [Conversation storage](moseby/runtime/storage.py) keeps database
transactions short: network calls and tool handlers run after they commit.

Inference is awaited directly by the loop. While the HTTP request waits, the
event loop can run other work, but inference has no queued job or worker claim.
Moving inference onto the durable queue is a separate runtime step.

The [tool worker](moseby/runtime/tool_worker.py) reads the saved task payload and
uses the existing claim, completion and delivery operations. A stale claim cannot
commit a result. Normal cancellation records outcomes for accepted calls so the
next turn has a complete exchange. A process killed before cleanup can leave an
unfinished run; automatic recovery and replay are still to be built.

## Use the HTTP gateway

`moseby.contracts.api.create_app()` accepts a database engine, `staff_member_id`
and `hotel_id` from the application host. These identify the single acting staff
member for the demo. The engine must point to a migrated, seeded database; its
owner closes it when the application stops.

`QUERY /rooms` accepts the existing `{ "request_id": "…", "payload": { … } }`
contract and calls the same room-search service as the agent tool. The gateway
loads the staff member's current role for each request. Concierge staff receive
room, guest and activity read access; unknown roles receive none. Client headers cannot select staff
identity or grant permissions. This is a single-staff demo binding, not login
authentication.

Available reads:

- `QUERY /rooms` and `GET /rooms/{id}`.
- `GET /guests`, `GET /guests/{id}` and `QUERY /guests`.
- `GET /activities`, `GET /activities/{id}` and `QUERY /activities`.

Guest searches accept IDs, party IDs, booking IDs and words in a name. Name
search uses the same FTS5 keyword matching as party notes. Every whole-word
keyword must appear in a first, last or preferred name; case and Latin accents
are ignored. Filters run before pagination. Activity
results include current prices and reserved-place counts across the shared
schedule; guest details remain scoped to the staff member's hotel.

The no-argument app supports contract generation. These reads return 503 until
configured; other operations remain 501 stubs. Reads return 400 for invalid
cursors, 403 for denied access and 422 for invalid request fields. Single-resource
reads return 404 for missing IDs or IDs outside the caller's hotel.

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
make test-agents
make test-tools
```

Database tests use freshly migrated databases with sample data. They cover hotel
boundaries, concurrent bookings, cancellation, paging and worker claims. Inference
tests use HTTPX's `MockTransport` to supply responses without contacting a model.
Those tests check our request handling; model accuracy needs a separate live check.

## What remains

The terminal loop works with one local worker. Runtime HTTP handlers, background
workers and recovery still need connecting. Guest lookup, room search and activity
browsing have working HTTP handlers; other API routes return HTTP 501 until their
service operations are connected.

Inference should move onto durable jobs so execution can continue after a client
disconnects. Streaming will need ordered, saved response chunks and a client
cursor, allowing another session or device to resume reading. The current
provider returns complete replies; it does not stream tokens.

The database includes tables for schedules and notifications, but their execution
still needs to be built. The demo booking flow will confirm stays without
collecting payment. Its service and tool still need connecting, as do guest-note
classification jobs using Jev and the web interface. Payment integration is
separate work. Search and uniqueness constraints already have some indexes;
further performance indexes will follow the queries that need them.

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
