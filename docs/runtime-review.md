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

Proposed rule: persist accepted tool calls and their runnable job records in one
local transaction, or use durable dispatch intents with recoverable delivery.
Choose one mechanism in the schema pass. There must be no unprotected gap where
history says a call exists but its job was never queued. Dead-letter storage
only represents work the queue already knows about; it cannot close this gap.

Proposed rule: logical operations have stable request IDs reused across retries.
Handlers/provider integrations must make repeating an ID return the original
outcome, or reconcile an unknown outcome before retrying. One logical call can
have several attempts, but only one accepted terminal result. Progress records
are separate. Exponential backoff changes timing, not duplicate-side-effect risk.

### Cancellation is scoped

Desired behaviour: stop the current run and its cancellable work; preserve useful
late outcomes. The exact run/job scope remains to be selected. Do not interpret
this as cancelling unrelated hotel work or permanently closing the thread.

Stopping a local wait or network connection does not prove that a remote booking,
message or payment was cancelled. Disposable read output can be discarded, but
side-effect outcomes may still need reconciliation. Record late outcomes without
automatically reviving a cancelled run. Callback delivery and held connections
are transport choices, not evidence that cancellation succeeded remotely.

### Worker claims and recovery

Proposed rule: a worker owns a time-limited claim renewed by heartbeats. Recovery
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
2. Atomic work creation and completion, claim expiry/token checks, safe retries,
   attempt limits, cancellation scope and unknown external outcomes.
3. Schedule/occurrence identity, handover, overlapping occurrences, timing and
   consuming wake conditions once when a steer/result also wakes a run.
4. Context construction, complete versus partial streamed output, and the initial
   classifier's ambiguity/failure outcome. Compaction can stay deferred.

These are bounded implementation decisions. They do not require another hotel
feature review. Original domain questions that were parked remain in the
central checklist; this walkthrough does not mark them silently resolved.
