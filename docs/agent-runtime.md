# Thread and runtime notes

These notes capture the current discussion. They are not a schema or an
implementation plan. Proposed details and open questions are labelled below.

## Thread records and threads

Use thread records for the durable history and threads for the current-state
projection. Each record has its own ID and belongs to a stable thread ID.

Thread records are the source of truth for the conversation and its execution
history. Booking, room, and activity records remain the source of truth for
hotel operations.

The thread projection contains deterministic values computed from the records.
It is not an inference-generated summary. Append the record and update the
projection in the same transaction. The purpose is to read current state
without scanning the full history each time.

Rebuilding a projection must preserve the thread's identity. The exact foreign
keys and how the projection is rebuilt are still open.

The history includes user messages, assistant messages with their tool calls,
tool results, and injected input. If cancellation, suspension, and recovery
state must also be rebuildable, their transitions need records too. The exact
record types are still to be defined.

Records need a clear order within a thread. Tool results must be linked to the
tool calls they answer. JSON payloads are the current direction; the columns
and format are not settled.

Titles may help staff navigate. They must not override the history when a
conversation changes direction.

## Thread lifetime and runs

A chat thread can receive more input later. It can be archived, but completing
a turn does not complete the thread permanently.

The proposed meaning of a run is one execution of the agent loop in response
to accepted user or scheduled input. A run may include several inference calls
and tool calls, with waits between them. Its exact start and end boundaries
still need confirmation.

The proposed first version allows one active run per thread and concurrent work
across different threads. This limit has not yet been accepted as a decision.
An active run can be waiting; it need not be occupying a worker continuously.

## Ordinary execution

The current outline is:

1. Persist the incoming input and initialise the thread if needed.
2. When the input can be handled, reconstruct the model context.
3. Select the permitted tool definitions and make the inference request.
4. Stream the response, assembling complete messages and tool calls.
5. Persist the output, validate tool calls, and dispatch their work.
6. Persist tool results and continue the same run with another inference call.
7. When the assistant ends its turn, leave the thread available for later input.

The runtime owns execution on the server. Clients observe it. Closing a tab
should not cancel the run, and several clients may observe the same thread.
Recovery after a server restart is a separate requirement to design.

The tool registry is intended to describe names, descriptions, input schemas,
output schemas, permissions, and their handler bindings. The provider request
uses the fields supported by that provider. Enforcement stays in application
code. The model receives complete tool results on a later inference request;
it does not need an open connection while a tool is running.

## Suspension and claimable work

Suspension means there is no agent continuation ready to execute. It does not
mean that a worker must remain occupied waiting.

Different situations can make a continuation runnable:

- Its scheduled wake time arrives.
- A required tool result is recorded.
- A control request, such as cancellation, needs handling.

Waiting for user input after a completed turn is different from a run waiting
on a tool. A suspended run may also have no known wake time if it is waiting
for an external result.

Tool work must remain executable while the agent waits for it. Suspending the
agent continuation must not block the very task that will produce its result.
Cancellation handling must also remain possible during suspension.

A worker should claim eligible work before executing it. A due timestamp alone
does not establish that work is ready or that another worker has not claimed it.
The claim mechanism and the choice between scanning threads and scanning a
separate work table are still open.

## Queued input

The current preference is to queue new conversational input when a run is
already in flight, and handle it on the next turn. This includes scheduled
input. The queue must preserve the input's source and order.

A tool result continues the run that requested it. It is not another queued
user turn. Mid-run steering, such as incorporating a by-the-way message at a
tool boundary, remains a possible later feature.

## Proposed projection fields

The other implementation includes fields worth considering here:

| Field | Intended meaning | Still to settle |
| --- | --- | --- |
| `cancel_requested_at` | When cancellation was requested | Which run the request targets |
| `cancel_requested_by` | Who requested cancellation | Representation of a staff or system actor |
| Recovery attempts | How often recovery has been attempted | Whether the count belongs to a run or a particular work item |
| Format version | How stored data should be interpreted | Record format versus projection format |
| `wake_at` | When a timed continuation may become eligible | Consumption, clearing, and interaction with other wait reasons |

Cancellation intent is not proof that work has stopped or been undone. A request
and its outcome need to remain distinguishable. An old cancellation request
must not accidentally cancel a later run in the same thread.

Likewise, recovery attempts and wake times need a clear scope. The projection
may expose the current run's values without making them lifetime totals or
permanent properties of the conversation.

These are candidate properties, not a final column list. Failure handling,
retry policies, and cancellation behaviour are the next discussion.

## Scheduling and proactivity

Schedules use UTC. Cron expressions are intended for recurring work. One-time
wakes also matter, for example a checkout reminder.

A scheduled action may run an application operation directly, queue input for
an existing thread, or create a thread to handle work. Unrelated threads do
not need messages about every scheduled action.

Thread `wake_at` could handle a timed continuation. It does not by itself
describe recurring schedules, independent actions, or several future actions
targeting the same thread. Those schedules need their own representation.

Schedule discovery and editing should be exposed as tools. The cron dialect,
validation library, scheduler library, and process arrangement are not chosen.
An application-level scheduler is preferred over custom database hooks.

Execution records should allow us to see when work was due, when it actually
started, its outcome, and how many times it ran. Editing a schedule should not
erase that history.

Skipping scheduled occurrences missed during downtime is an acceptable initial
trade-off. This is separate from keeping schedule definitions and recovering
work already accepted before shutdown. The exact restart rules remain open.

## Permissions, formats, and model context

Keep a record of the permissions used for execution. Historical permissions
must be distinguished from current authority to perform another action.
Threads and live subscriptions also need access checks because their content
can contain retrieved information or information supplied directly by staff.

Provider name, model name, and format metadata should be recorded. Our stored
format version is distinct from a provider API version or model identifier.
The exact placement of these values is still open.

Choose one affordable chat model. Its exact provider and model ID are not yet
confirmed. Jev remains a possible separate classification experiment.

Compaction is separate from the state projection: it controls how much history
is sent to the model. It does not require discarding the durable records.
Compaction and partial-stream persistence have not been designed yet.

## Scope and telemetry

Use lexical retrieval for now; embeddings are deferred. Use Markdown for the
initial interface. Generative widgets, code execution, and subagents are later
possibilities. No parent-child task schema has been selected.

Telemetry should help answer concrete questions about execution, such as how
long a run waited or why it resumed. The metrics, evaluation approach, and
libraries are still open. Recording lifecycle events does not commit us to an
observability platform.

Before designing failure handling, confirm the number of active runs allowed
per thread and whether an explicit timed sleep resumes the same run. We can
then work through cancellation, failed tools, retries, and interrupted execution
using those definitions.
