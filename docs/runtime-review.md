# Current runtime contract

Canonical runtime decisions after the complete walkthrough. This replaces earlier
alternatives in [runtime notes](agent-runtime.md). The [API contract](api-overview.md)
and [permission/tool review](permissions-and-tools.md) cover their own boundaries.
**Selected** means accepted in discussion; **proposed** means still reviewable.
No runtime DDL, application code or dependency selection is included.

## Selected architecture and scope

- Python, Pydantic, a manually implemented turn loop and durable thread history.
- One main inference provider behind an inference gateway. Core storage uses our
  own schema, not the provider's message schema. Jev is a separate classifier.
- One active run per thread, including sleeping runs; concurrency across threads.
- Thread records are ordered source history; threads are deterministic projections.
- Seed one staff member. Thread creator and creation-time permissions are stored;
  creator-only access and current-authority checks apply. Raised permissions need
  a new thread. Complete authentication/audit infrastructure is deferred.
- Queued input is a thread mailbox/inbox. Ordinary input waits; consume the current
  eligible batch in order. Steering may interrupt a wait without cancelling its job.
- SQLite stores work and published events. No separate notification broker.
- Jobs and tasks are separate for the explicit learning goal of worker orchestration.
  **This supersedes one job as the worker's claimable unit.** Workers claim tasks.
- Claims have their own table. Schedule occurrences also have their own table and
  are accessible through the gateway. Exact DDL comes after the contract review.

## Jobs, tasks and claims

| Concept | Meaning and proposed minimum data |
| --- | --- |
| Job | Overall operation: ID, registered job type, actor/request/call/run links, input, workflow state, result/error, timestamps |
| Task | Executable piece: ID, job ID, registered handler, input, readiness/state, result/error, attempt count, available/start/finish times |
| Claim | Current ownership of one task: task ID, worker, unique token, heartbeat and expiry |

Job and task separation is selected; the listed fields and exact state enums are
proposals. Each initial job may have one task. A bounded job handler can later
create several ready tasks and combine their results. No arbitrary workflow DSL,
general dependency editor or separate task microservice is required.

The queue handles readiness, claims, delivery and retries. A job-type handler
knows what task outcomes mean and which work follows. The queue does not need
hotel business logic. Task inputs/results use registered schemas. Slow external
work and parallel execution must not keep a database transaction open.

A booking and its reservations must be created by one compound domain operation
when they need one transaction. Independent task/tool/API calls do not share a
transaction merely because they belong to the same job. Fan out independent
work; do not split an atomic domain change just to demonstrate concurrency.

### Proposed completion rules for the learning implementation

1. Persist a queued tool call, its job and initial tasks together.
2. Claim one ready task atomically. Only its current, unexpired token may heartbeat
   or commit protected changes. A replacement claim invalidates the old token.
3. Persist task outcome and update the parent workflow/create successor tasks in
   one transaction. Concurrent branch completions must not schedule the next
   phase twice or lose each other's progress.
4. Emit the one logical job result when the job reaches its selected terminal
   outcome; individual tasks are not multiple final answers to the same tool call.
5. Save that job result and completion-outbox intent together. Consume the intent,
   append the linked thread record and update its projection together. A duplicate
   delivery finds the same result identity instead of appending a second result.

The atomic boundaries are selected; exact parent aggregation/branch failure and
cancellation rules still need a small state-machine pass. A job with no more work
must not finish while other required branches can still generate tasks. Example
rule for review: success requires all required tasks to succeed and no further
phase to remain. This is not yet a chosen general workflow policy.

### Retries

An attempt is another execution of the same logical task. Task attempt counters,
last error and timing are enough initially; no separate attempts table or public
resource is required. A job can expose aggregated retries. A single job counter
cannot independently govern two parallel branches' retry budgets. Restarting a
whole job is different from retrying one task and must not be implicit.

Backoff and jitter are selected; attempt limits and retryable error categories
remain open. Stable task/effect identities survive retries. Reclaim expired
leases, not every claim when one process restarts. Stale-token checks protect
local writes, not external side effects; handlers still need deduplication or
unknown-outcome reconciliation. Job type/input do not authorise arbitrary code.

## Request IDs, deduplication and outbox

`request_id` is the selected client idempotency key, not a second parallel field.
Its practical meaning requires persistent evidence of the accepted operation:
ID scope, operation and input identity, and resulting resource/job/outcome.
That information may live on the affected operation/job or an internal shared
ledger. There is no selected standalone request-receipts resource or API.

Proposed rules: atomically admit one logical command; retries return its accepted
job/result; the same ID with different input is rejected. Retention, conflict
responses and sync-operation storage are still to be defined. Multiple effects
from one request need stable child identities, e.g. one notification per recipient.

A completion outbox is different: it records a result that still needs delivering
to its thread. It does not answer whether a client request was previously accepted.
Neither the ID string alone nor the presence of an outbox proves exactly-once
external effects. Notification publication is defined below.

## Durable record schema versus provider schema

Selected: persist our own versioned record kinds. A discriminated envelope is
proposed, with record ID, thread ID, sequence, kind, format version, recorded time,
optional run linkage and a payload validated according to kind/version.

Proposed kinds (not a final exhaustive enum):

| Kind | Purpose | Main-model context treatment |
| --- | --- | --- |
| User message | Accepted conversational content | Eligible conversational input |
| Assistant message | Text and complete tool calls with call IDs/arguments | Translate via inference adapter |
| Tool result | Call-linked result or error; job link where asynchronous | Translate respecting call/result ordering |
| Classifier decision | Routing/classification input references, decision or unresolved outcome | Exclude by default; selected operation/result has its own record |
| Inference request | What a specific main-model request submitted | Internal execution evidence, not another user message |
| Run/job control event | Wait, cancellation, recovery or other execution transition | Internal by default; select contextual notices deliberately |

Use explicit record-kind selection when constructing context, not a client-set
flag that lets arbitrary internal events become model instructions. Thread history
is a superset of model context. Classifier provider payloads never need to masquerade
as chat messages. UI/main API response schemas are also distinct from storage types.

Format version can be defined by a code constant, but persist the version on each
record/payload envelope so future code can interpret old data. Provider model/API
versions and our format version are separate. No format-version registry table
is required. Party-reference JSON version placement remains a DDL detail.

### An inference request is not a user message

It can include system instructions, selected conversation/tool results, offered
tool schemas, model/options and fresh runtime context. One user input may lead to
many requests; a classifier-only path may produce none. Record identities must
distinguish those calls and their results.

Proposed first approach: retain the exact outbound request snapshot, including
provider/model metadata and record links, as internal execution data. Alternative:
retain immutable inputs sufficient to reconstruct it. Exact payload storage and
retention remain open. A full snapshot improves reproducibility but duplicates
sensitive content and must follow thread access/retention rules. It must never
be copied into model context as though the user said it.

A persisted tool result proves a recorded outcome, not that the model saw it or
that the operation succeeded. A missing result does not prove the remote action
never occurred. Partial streams and crash recovery of completed calls still need
an implementation policy. Compaction stays separate from persistent history.

## Accepted wake rules

| Event | Behaviour |
| --- | --- |
| Due continuation for a waiting run | Resume that same run |
| Old timer for a cancelled run | Consume/ignore it; never revive the run |
| Late result for a cancelled run | Record/reconcile without automatic continuation |
| New user message | Start a new run when the thread is free |
| Independent scheduled input | Start a new run when free, otherwise queue |

Scheduled work may call an application handler without starting an agent run.
A steer targeting an ended run becomes ready input subject to any newer active
run. Cancellation is terminal for that run, not for the thread. Cancelling a
wait does not prove the remote action stopped. Exact task cancellation scope and
handling of already-queued user input remain open; do not silently lose input.

## Schedules and occurrence records

A schedule is the recurrence rule/action. A schedule occurrence is one due firing
accepted by the scheduler, recorded before the work succeeds. It may still be
queued, running, failed or skipped. We do not prepopulate all hypothetical future
matches. The separate occurrences table and gateway access are selected.

Proposed fields: occurrence ID, schedule ID/revision, intended due time, acceptance
time, input snapshot, job link and outcome. Choose one unique occurrence identity
and create it with the initial work atomically. Repeated ticks cannot make duplicate
jobs. Schedule edits do not retract accepted occurrences/jobs. Earlier scope allows
skipping missed ticks during downtime while recovering already accepted work.

Use an existing recurrence representation and parser. Classic cron timing fields
are covered by [POSIX crontab](https://pubs.opengroup.org/onlinepubs/9699919799/utilities/crontab.html).
The iCalendar recurrence alternative is [RFC 5545](https://www.rfc-editor.org/info/rfc5545/).
Cron is not one universal IETF dialect: seconds/year extensions and matching
semantics vary. Recommendation: a named five-field cron dialect in UTC, with a
separate timestamp for one-off actions. Dialect and library remain unselected;
verify their matching semantics, not just the number of fields. No custom parser
or shell command execution is implied.

A tick finds due work; task workers execute it. They may run in one process with
bounded concurrency. Reminder tasks recheck the expected booking/activity facts;
record irrelevant reminders as skipped. Classifier relevance is optional and
cannot override failed deterministic validity/permission checks.

## Publication

SQLite notification publication is a durable event append plus published state
in one transaction. Consumers read retained events by cursor and own handling
and cursor advancement. Replay returns the same event identity. Publication does
not wait for consumer acknowledgement. Notification requests/recipient effects
have stable request identities. Exact ordering, retention and audience scoping
are still to define. Actual email/phone delivery is simulated, not asserted by
a published event. A future external adapter owns its separate delivery boundary.

## Remaining implementation choices

- Final job/task/run transitions; parallel-branch aggregation/failure/cancellation;
  initial fan-out demonstration and who schedules successor tasks.
- Exact record envelopes, inbox consumption, partial streams, inference snapshot
  storage and classifier ambiguity/failure handling.
- Lease durations, retry limits, request-ID scope/retention and occurrence identity.
- API permission matrix, tool exposure, then framework/database/cron/test packages.

These are local implementation choices. The SQL is not yet a runtime implementation.
