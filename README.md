# Moseby

A Python concierge agent for resort staff.

An experiment in helping staff turn guest requests into actions they can check.
The model chooses tools; the application checks permissions and saves the outcomes.
Staff remain the point of contact with guests.

## Start here

Requires Python 3.14 and an OpenRouter API key. Run these from the repository root:

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -e '.[contract,dev]'
cp .env.example .env
```

Add your key to `.env`. The example uses **DeepSeek V4.1 Flash** for generation and
**Jev** for classification. Change the model IDs there to choose other models.

Settings come from `OPENROUTER_API_KEY`, `MOSEBY_GENERATION_MODEL` and
`MOSEBY_CLASSIFICATION_MODEL`. Supply them through your launch environment,
or load `.env` into your shell. Optional `MOSEBY_REASONING_EFFORT` defaults to `low`;
`MOSEBY_MAX_OUTPUT_TOKENS` defaults to 4096, shared by reasoning and the visible reply:

```sh
set -a
source .env
set +a
```

Initialise the demo data, then open a conversation:

```sh
.venv/bin/python -m moseby init
.venv/bin/python -m moseby chat
```

Try: “Find Dan Patel and show me activities this afternoon.” Then choose an
activity, reserve a place, inspect his itinerary and cancel the reservation.
Use `/exit` to leave. Reopen a conversation with `chat --thread THREAD_ID`,
or send one message with `chat --message "Show me the rooms"`.
Run `.venv/bin/python -m moseby --help` for command options.

## Development commands

| Task | Command |
| --- | --- |
| Format | `make format` |
| Lint and check formatting | `make check` |
| Run tests | `make test-db test-models test-contracts test-inference test-agents test-tools` |
| Apply migrations | `make migrate` |
| Regenerate OpenAPI | `.venv/bin/python -m moseby.contracts.export` |

## Things to know

- `.env` and the default `moseby.db` are ignored by Git. `.env` is loaded by your shell, not automatically by the app. Reload it and restart chat after changing models.
- Start with a fresh database when switching from the extensions snapshot; the prototype schema is smaller. `init` adds missing demo data and preserves existing rows. To use another database, put `--database PATH` before `init` or `chat`.
- Each user message starts a new run. Its token budget counts uncached input and all output; cached reads are tracked separately.
- Threads retain the permissions they were created with. Start a new chat after adding tools that need new permissions.
- This is a local, single-staff demo. The CLI runs the agent; HTTP routes expose domain operations. Interrupted runs require manual intervention.
- Dates use UTC unless an explicit timezone is supplied. Local tests use simulated model replies and need no API key.

## Project layout

- [Agents and prompts](moseby/agents), [tools](moseby/tools), [runtime](moseby/runtime) and [inference](moseby/inference).
- [HTTP gateway](moseby/gateway), [contracts](moseby/contracts) and [services](moseby/services).
- [Database migrations, models and repositories](moseby/db).
- [Design notes](docs) record the project's evolution; the code defines current behaviour.
- [Extensions snapshot](https://github.com/samfolo/Moseby/tree/extensions) preserves the broader scheduling and notification design.
