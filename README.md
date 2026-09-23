# Moseby

Hotel staff have a lot to keep track of: who is staying, what each guest needs,
and what everyone has planned. Moseby is an assistant they can talk to while
organising a guest's stay. It helps with room bookings, activities, itineraries
and notes, so staff can keep up with several guests and give each one personal
attention.

A concierge might ask it to find something for a guest to do tomorrow, book their
chosen activity, or remember a dietary requirement. Staff stay in charge of the
conversation with the guest and decide how best to help them.

## Try it

You'll need Python 3.14 and an OpenRouter API key. From the repository root:

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -e '.[contract,dev]'
cp .env.example .env
```

Put your API key in `.env`. That file also lets you choose the models. Load those
settings into your shell, create the demo hotel, and start a conversation:

```sh
set -a
source .env
set +a
.venv/bin/python -m moseby init
.venv/bin/python -m moseby chat
```

The demo comes with made-up guests, rooms and activities. Take the concierge's
role and try: “Find Dan Patel and show me activities tomorrow afternoon.” Choose
an activity, ask Moseby to book it, then check Dan's itinerary. You can cancel the
reservation afterwards. You'll see the names of the tools Moseby uses as it works.

Use `/exit` to leave. To return to a saved conversation, use `chat --thread THREAD_ID`
with the ID printed when you started. For a single request, use
`chat --message "Show me the rooms"`. Use `--help` for other options.

## What to expect

- You use the demo through the terminal as one staff member. There is no login step, and it does not take payments or programme real door locks.
- Conversations are saved. If the programme stops halfway through a task, it won't automatically pick up where it left off. You also wait for the full reply rather than seeing it appear word by word.
- When you save a note about a group, we use Jev, a decision model, to work out which guests it mentions. Sometimes it's hard to tell. We still save the note because it's useful even when we can't confidently link it to a person.
- Times use UTC unless you specify another timezone. Moseby has a limit on how much model work it can do for each message you send; that is not a cap on your API bill.

## Your local setup

The app reads settings from environment variables. The commands above load them
from `.env`; you can also supply them directly when starting the programme. After
changing models or other settings, load them again and restart chat. The optional
reasoning and output settings are listed in `.env.example`.

Your local database is `moseby.db`. Neither it nor `.env` is tracked by Git.
Running `init` again adds missing demo data and keeps changes you've already made.
To start over, stop chat, run `make clean-db`, then run `init` again. This deletes
saved conversations and bookings too.

Use a fresh database when switching from the extensions branch. To choose a different
database file, put `--database PATH` before `init` or `chat`. If you change what an
agent is allowed to do, start a new conversation to use those permissions.

## Working on the code

| Task | Command |
| --- | --- |
| Format | `make format` |
| Lint and check formatting | `make check` |
| Run tests | `make test-db test-models test-contracts test-inference test-agents test-tools` |
| Apply migrations | `make migrate` |
| Delete the default database (stop chat first) | `make clean-db` |
| Regenerate OpenAPI | `.venv/bin/python -m moseby.contracts.export` |

Tests use scripted model replies, so they run without an API key. They check how
the application behaves; they don't tell us how reliably a live model will handle
a guest's request.

Tools and HTTP endpoints call the same services, which check permissions and apply
changes to the database. To host the HTTP API, supply a database and staff identity
to `create_app`. The code is organised into [agents](moseby/agents),
[tools](moseby/tools), [runtime](moseby/runtime), [inference](moseby/inference),
[services](moseby/services), [HTTP gateway](moseby/gateway),
[contracts](moseby/contracts) and [database](moseby/db).

[Design notes](docs) contain earlier discussions, including ideas we set aside.
The [extensions branch](https://github.com/samfolo/Moseby/tree/extensions) keeps
the broader scheduling and notification work for later reference.
