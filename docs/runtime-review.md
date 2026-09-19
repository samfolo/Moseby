# Runtime review: accepted direction and remaining mechanics

This consolidates the final people/permissions and runtime walkthrough.
It supplements [runtime notes](agent-runtime.md) and the
[review checklist](design-review.md). Decisions and implementation proposals
are separated. No runtime tables, indexes or execution code are added here.

## Decisions and scope

- Seed one acting staff member for the demo and pass its ID through the service
  layer. Authentication and the complete audit system can wait. The application
  supplies identity; the model does not choose it.
- Staff belong to one hotel. A guest belongs to one party, a party to one booking,
  and a booking to one hotel. Returning people get new records for the new stay.
- The agent has the acting user's permissions. Define exact permission rules
  after API operations. Bookings cover room reservations and keys; guests cover
  parties; rooms cover beds. Activities are a separate candidate because guest
  itineraries disclose more than basic guest information. No separate agent
  endpoint for listing individual beds is required.
- Venues and prices have no hotel-owner field. Cross-hotel activity/venue use is
  allowed in this demo; this does not merge parties or remove room/booking links.
- Keys use `deactivated_at`. Amounts use integer currency minor units. Guest
  information and activity definitions are mutable without their own change
  histories. Party-detail guest references use a known, versioned JSON-array
  shape; where that version lives remains to be selected.
- Party details already have a table. Programmatic correction of their guest
  references is a later feature; classification failure/ambiguity still needs
  a first-version outcome. No semantic-search dependency is required.
- Tools generally invoke application/API operations through a dispatcher with
  policy checks. Cheap local operations may complete synchronously.
- Durable thread history is a superset of model context: user/assistant content,
  tool calls/results, job and control events can coexist. A context builder
  selects relevant records; not every event must be sent to the model.
- An optional classifier can route input to a bounded operation before the main
  model. Tool discovery and expanded-context access are later experiments.
  Classified calls still require valid arguments and permissions. Provider
  limits/prices mentioned in discussion have not been verified in this pass.
- Keep one active run per thread. An external job normally suspends that same
  run. Scheduling independent work for later is a separate operation.
- Ordinary input queues behind the current run. When eligible, take the current
  batch in order. Forced steering can end a wait while external work continues.
  A steer targeting an ended run becomes ready thread input, subject to any
  newer active run. No second concurrent owner may advance the thread.
- External work is durable, with job identity, tool-call association, status,
  claim token and heartbeat. Completion produces a linked thread record.
  Progress can be coarse. A per-job workflow/stage engine is not required.
- Accepted tool calls and job records are saved together in one database
  transaction. Completion saves its outcome and durable delivery intent together;
  consuming that intent and appending the thread record must also be atomic.
- Worker claims have their own table. Obsolete claim tokens must not authorise
  writes. Exact fields, expiry and claim-history retention remain to be designed.
- Every notification delivery has an idempotency key retained across retries.
  Simulation can record emission atomically in the database; real external
  delivery has a separate acknowledgement boundary, described below.
- Retry policy uses exponential backoff and jitter. Retry limits, timeouts and
  operation-specific safety are still to be defined; queue membership alone
  does not establish that an operation is safe to repeat.
- Editing a schedule does not retract already accepted work. The schedule is a
  trigger; existing jobs continue independently. Separate explicit cancellation
  may still target those jobs.
- Reminders recheck the facts that justified them before acting. If those facts
  no longer hold, record that the reminder was skipped. Classifier judgement is
  optional and cannot replace required state/permission checks.
- Notifications are initially simulated and logged as external work. No separate
  notification broker, subscription system or real provider is needed now.
- Token accounting and richer telemetry are deferred. Worker recovery and
  schedule-to-job handover still need concrete transaction rules.

## Corrections to assumptions, for implementation review

### A recorded result is one milestone

A matching tool-call ID establishes that a result has been saved for that call.
It does not prove success (the result may be an error), inclusion in a model
request, or handling by the model. Track these links separately where needed.
Tool name alone is not identity. Namespace provider call IDs by their request
or use an internal ID; several calls may invoke the same tool.

No saved result does not prove that the outside action never happened. A worker
can finish an external operation and crash before saving its result.

### Persisting work and replaying it safely

Accepted rule: persist accepted tool calls and their runnable job records in one
local transaction. On completion, persist the outcome and an outbox entry for
delivery to the thread together. The consumer appends the linked thread record,
updates the thread projection, and marks the outbox entry consumed in one local
transaction. Exact table/column names remain open. Retries must find the existing
result rather than append another copy. If completion writes the thread directly
in the same transaction, an extra outbox hop is unnecessary; that layout is still
an implementation choice, not a requirement for two independent result writes.

There must be no unprotected gap where history says a call exists but its job was
never queued. Dead-letter storage represents work the queue already knows about;
it cannot close this gap.

Proposed rule: logical operations have stable request IDs reused across retries.
Handlers/provider integrations must make repeating an ID return the original
outcome, or reconcile an unknown outcome before retrying. One logical call can
have several attempts, but only one accepted terminal result. Progress records
are separate. Exponential backoff changes timing, not duplicate-side-effect risk.

### Notifications and the external boundary

Notification idempotency is now selected. Recommended key scope is one logical
delivery to one recipient through one channel, for a specific event/change.
Retries reuse the key; a new notification has a new identity. Exact encoding is
open. A key stored locally only prevents local duplication; the provider or
receiver must honour it too if repeated external sends are to be deduplicated.

Publication now explicitly means appending to a retained event stream. Save that
record and published state in one transaction. Consumers read after their own
cursor and own handling/cursor advancement. A consumer crash does not undo the
publication; replay returns the same event. No receipt is required to mark the
producer's publication complete. Cursor scope/order and retention remain open.

Actual email/phone delivery is still simulated. With real email, HTTP or another
broker, network delivery
and a local database write do not share that transaction. Persist intent first,
send using the stable key, then record acknowledgement. If a crash happens after
remote acceptance but before that acknowledgement is saved, retry/reconcile the
same operation. Backoff alone does not resolve that unknown outcome.

Published/accepted is not proof that the final recipient received or read the
message. Lack of a delivery receipt alone must not trigger a new logical send.
The demo records simulated publication; real delivery receipts remain deferred.

### Cancellation is scoped

Desired behaviour: stop the current run and its cancellable work; preserve useful
late outcomes. The exact run/job scope remains to be selected. Do not interpret
this as cancelling unrelated hotel work or permanently closing the thread.

Stopping a local wait or network connection does not prove that a remote booking,
message or payment was cancelled. Disposable read output can be discarded, but
side-effect outcomes may still need reconciliation. Record late outcomes without
automatically reviving a cancelled run. Callback delivery and held connections
are transport choices, not evidence that cancellation succeeded remotely.

#### Accepted wake rules

The latest question is how a stopped run differs from a sleeping run. Keep the
distinction explicit: sleeping is a waiting active run; cancellation is terminal
for that run. The thread remains open. The following behaviour is now accepted:

| Incoming event | Behaviour |
| --- | --- |
| Due continuation for a waiting run | Resume that same run |
| Old wake timer for a cancelled run | Ignore/consume it; never revive that run |
| Late result for a cancelled run | Record/reconcile the outcome without automatic agent continuation |
| New explicit user message | Start a new run when the thread is free |
| Independent scheduled action targeting the thread | Start a new run when free, or queue behind its active run |

An independent scheduled action can also call an application handler directly;
it need not start an agent run. Existing scheduled work remains independent as
previously agreed. Event purpose and target run determine eligibility; arrival
after cancellation alone does not. Exact cancellation scope for dependent jobs,
consuming old wake conditions, and treatment of previously queued user input
remain to be specified. Do not silently discard already accepted input.

### Worker claims and recovery

Selected: claims live in a separate table, and stale tokens cannot commit.
Proposed fields are job ID, owner, unique claim token, heartbeat time and expiry.
One job may have only one current owner; how historical claims are retained is
open. The token check and protected writes must share the same transaction;
checking first and committing later would leave a race.

Proposed lease rule: a worker owns a time-limited claim renewed by heartbeats. Recovery
reclaims expired claims, not every claimed job whenever one process starts.
Other workers may still be alive. Each new claim gets a new token; local writes
from the old token must be rejected. This does not itself prevent duplicate
external side effects, which need the stable operation identity above.

Keep `created_at` distinct from `started_at`: queue age is not execution duration.
A job heartbeat indicates ownership, not business progress or external success.
Tool jobs remain eligible while their agent run is suspended.

### Scheduler responsibilities

A periodic tick finds due occurrences and makes jobs available; workers do the
work. A cron library can calculate times but does not by itself provide durable
handover, recovery, or duplicate prevention. This can initially live in one
process, with separate scheduling and execution tasks. Python still requires
bounded concurrency and coordination. Process topology is not selected.

Proposed occurrence identity: schedule ID, schedule revision and intended due
instant. Another equivalent identity is possible. Record the occurrence and
its accepted work together so repeated ticks cannot enqueue it twice. Keep the
accepted input snapshot when editing the schedule. Earlier notes allow skipping
occurrences missed during downtime; already accepted jobs must still recover.

Reminder checks should compare current booking/activity state with the expected
facts, such as the event still being active and its scheduled time unchanged.
Guest/activity change history is not necessary for that comparison, but the job
must retain the expected values (or a usable version). Logged notifications must
remain clearly distinguishable from messages actually delivered.

## Remaining decisions for the API/schema pass

1. Runtime record kinds, IDs, state transitions and links among runs, requests,
   tool calls, attempts, jobs and results; pending-input delivery and batching.
2. Translate accepted atomic work creation/completion and the separate claim
   table into constraints and repository operations. Specify claim expiry,
   safe retries, attempt limits, cancellation scope and unknown external outcomes.
3. Schedule/occurrence identity, handover, overlapping occurrences, timing and
   consuming wake conditions once when a steer/result also wakes a run.
4. Context construction, complete versus partial streamed output, and the initial
   classifier's ambiguity/failure outcome. Compaction can stay deferred.

These are bounded implementation decisions. They do not require another hotel
feature review. Original domain questions that were parked remain in the
central checklist; this walkthrough does not mark them silently resolved.

## Next: API operations before implementation

The author will supply paths. For each operation, specify its purpose, method,
validated input/output, required permission, transaction boundary, retry identity,
and whether it returns a result or a job reference. Decide which operations are
tools after this review; not every table needs a public CRUD endpoint.

Pydantic describes and validates input/output; it does not replace database
constraints or multi-record transactions. Service operations coordinate work
and repository calls within a shared transaction. Repositories should not each
commit independently when their writes form one atomic action.

Server, cron, database-access and testing libraries, folder structure and query
indexes remain choices for the implementation pass. No framework is selected by
these notes and no claim is made that the data-access layer already exists.

The consolidated [resource and API overview](api-overview.md) uses the selected
`request_id` plus `payload` convention. Stable request IDs replace a separate
client idempotency-key field; retry semantics and scope are proposed there.
