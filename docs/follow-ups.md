# Follow-ups

This is the working backlog collected from the design conversations and code review.
The older notes explain the decisions; their unchecked boxes are not a current task list.
Items below are grouped by when we would tackle them, rather than treated as release promises.

## Working now

The [concierge definition](../moseby/agents/concierge.py) exposes thirteen tools:
room search, guest search, saving party notes with Jev reference classification,
activity search, itinerary search, reserving activity places, cancelling them,
stay lookup/creation/amendment/cancellation/completion, and guest updates.
The CLI runs persistent conversations and saved tool jobs, with permission checks,
request deduplication, and run limits. Reopening a conversation works; automatically
recovering an interrupted run is separate work.

## Finish the main concierge surface

These three tool names are the remaining proposed grouping of the agreed journeys.
The repositories already support much of this; each tool still needs a shared service,
permissions, request deduplication for writes, HTTP wiring, and a journey test.

| Proposed tool | Journey |
| --- | --- |
| `search_party_details` | Retrieve saved notes and their guest references using the existing full-text search. |
| `issue_room_key` | Issue a key tied to a room reservation. |
| `deactivate_room_key` | Deactivate a key with a reason. |

Add issued keys to the stay overview when the key tools are connected.

Activity changes can already be expressed by reserving and cancelling. If a staff member
asks to replace a reservation, define a safe order or an atomic replacement so a failed
new reservation does not lose their existing place.

Sources: [domain journeys](data-modelling.md), [tool boundaries](permissions-and-tools.md),
[stay operations](../moseby/db/operations/stays.py), and [repositories](../moseby/db/repositories).
Room, bed and activity configuration belong to a separate back-office profile.

## Make the demo easier to use and review

- **Interface:** tidy CLI output and show tool progress. A small web client, calendar or job board can follow; generate TypeScript types from OpenAPI when needed.
- **Gateway:** connect the remaining advertised routes to shared services, including runtime routes. A declared contract is not an implemented endpoint.
- **Behaviour checks:** turn the room-booking and activity transcripts into useful evaluation cases: search before asking, clarify ambiguous names, avoid repeated confirmation, and report actual outcomes.
- **Tool output:** compare concise tables or text with JSON for model-facing results. Measure token use and task accuracy while preserving IDs, versions, amounts and pagination; keep the HTTP contract structured.
- **Tool errors:** separate the problem, affected resources and suggested next action; review errors across the full tool set.
- **Guest-reference corrections:** let staff clarify an existing note and rerun classification while retaining the original evidence and previous decision.
- **Documentation:** keep setup instructions short, clearly distinguish the working demo from planned features, and revisit older design notes before public release.

Sources: the CLI transcript reviews, the guest-reference review, and the README discussion.

## Durable execution and proactivity

- **Background inference:** run model work independently of the client connection. Python can support this; the current loop simply awaits the response.
- **Restart recovery:** resume unfinished jobs and runs, reclaim expired claims, and apply bounded retries with exponential backoff and jitter. Treat uncertain external outcomes carefully before retrying.
- **Streaming:** retain response events with a cursor so reconnecting clients can catch up without losing chunks.
- **Steering and cancellation:** connect queued input, assertive delivery, cancellation and wake-up rules to the running engine and user-facing API.
- **Scheduling:** select a cron library and dialect; implement due-work polling, occurrence/job creation, missed-run handling, and current-permission checks. Keep timed work distinct from suspending an existing run.
- **External work:** simulate a breakfast or taxi request that returns a job ID, then reports progress, failure, completion or a need for more information.
- **Notifications:** implement controlled dispatch and recipient processing, then optional email/phone integrations. Cover activity-change notices and checkout reminders; distinguish a saved or simulated dispatch from actual delivery.

Sources: [runtime review](runtime-review.md), [steering](steering.md),
[thread lifecycle](agent-runtime.md), and [service requests](data-modelling.md#room-services-and-work-done-elsewhere).

## Operational follow-ups

- **Access and audit:** replace the fixed staff identity with authentication; complete role administration and read/write auditing. A guest-facing interface needs a verified guest or party identity and narrower permissions. Jev may flag suspicious requests; service checks enforce access.
- **Sensitive data:** review field-level disclosure, storage and retention, including draft guest details, inference snapshots and any future cross-thread search.
- **Budgets:** distinguish token limits from spending limits. Track generation and classification usage separately, with optional per-purpose spending limits and defined handling of missing usage.
- **Observability:** add useful traces and evaluations, configurable logging, and optional OTLP export.
- **Performance:** inspect real query plans and access patterns before adding performance indexes. Revisit long-history loading, caching and compaction when needed.
- **Agent versions:** retain reproducible agent configuration and prompt versions once released; extend the existing agent ID/version attribution when evaluation needs it.
- **Small inference tasks:** generate thread titles and summaries without creating extra chat threads.
- **Timezones:** add hotel-local dates and daylight-saving rules beyond the initial UTC convention.

Sources: the configuration, migration, permissions, attribution and turn-loop reviews;
[permissions](permissions-and-tools.md) and [time context](data-modelling.md#dates-and-time-context).

## Deferred product ideas and experiments

- **Payments:** drafts, roughly five-minute holds, asynchronous payment outcomes and receipts through an external or simulated provider. Refunds, room credit, incidental charges, discounts and seasonal pricing remain separate work.
- **Packages:** grouped trips, partial failure handling, and reserved VIP/standard activity capacity.
- **Physical operations:** door-lock integration, key-use evidence, arrival/departure logs and attendance tracking; richer venue subdivision and activity eligibility rules.
- **Memory and retrieval:** semantic search (including the suggested Turbopuffer experiment), personalisation from notes, and any reconsideration of cross-visit guest identity.
- **Agent experiments:** permission-filtered tool discovery, broader Jev routing and classification (including cancellation reasons), subagents, side questions, code execution through an SDK, and generative interfaces/forms.
- **Spatial features:** floor-plan upload, OCR, vector geometry and spatial queries were removed from the current scope.
- **Other agents:** housekeeping, inventory and resort configuration belong to separately scoped agents if pursued.

Sources: [deferred scope](design-review.md#explicitly-outside-the-current-review),
[stretch goals](data-modelling.md#stretch-goals-and-experiments), and the original product discussion.
