---
first_committed: "2026-09-17T16:28:43+01:00"
first_commit: "d3b987a"
---

# Working out the conversation loop

## Objective

Let a conversation continue across several requests and tool calls without
losing what happened. We also wanted to understand how waiting and later work
could fit around that loop.

## Thinking at this stage

- A thread is the conversation. A run is one stretch of agent work prompted by
  input. Finishing a run leaves the thread open for another message.
- Allow one active run per thread. Different threads can work at the same time.
- Thread records hold the history. The thread row holds a summary of its current
  state so we do not have to read all the history for every status check.
- Save a new record and update that summary in one transaction. Booking and guest
  tables still decide what is true about the hotel; chat history does not replace them.
- Keep tool calls and their results linked. Give records an explicit sequence
  within the thread; timestamps alone are not a dependable order.

The proposed loop was: save input, build the model's context, ask the model,
save its answer and tool calls, run the tools, save their results, then continue.
A title helps staff find the conversation; it should not decide what the agent does.

### Waiting and incoming messages

- Waiting for a tool is different from finishing a turn and waiting for the user.
  A sleeping run can still be active without occupying a worker.
- Tool work must keep running while the agent waits for its result.
- Queueing waits for the current run to finish. Steering gives that run new input
  at a point where it can use it. Stopping asks the run to end.
- Keep three moments separate: the message was saved, it entered the history,
  and it was included in a model request. None proves the model followed it.
- One part of the engine should own these rules. The API, poller and loop should
  not each invent their own way to advance a message.
- Poll saved input as well as wake times. A missed wake-up signal must not make
  an accepted message disappear.

### Later work

- Waking an existing run is different from scheduling a new action for later.
- A scheduler finds work that is due. Workers claim and execute it. Both can
  live in one process; these responsibilities do not require separate services.
- Ending a wait does not cancel the outside work being awaited.
- A title helper or side question could use a separate inference call against
  saved context. It need not create a second loop changing the same thread.
- Keep internal events and classifier decisions in history, but deliberately
  choose which records become messages for the language model.
- Reducing the context sent to the model need not delete the stored history.

## Questions left open at this stage

- Does an outside job keep the run waiting, or finish the turn and report back later?
- Which waits can end early when staff steer the run?
- What happens when a steer arrives after its intended run finishes?
- How are claims, retries, cancellation and missed schedule times represented?
- How do clients reconnect without losing partial replies?

The [steering research](03-steering.md) helped clarify the input behaviour.
The [runtime review](06-runtime-review.md) later chose jobs, tasks and claims.
Client-independent execution and automatic restart recovery remained goals;
the first CLI instead waits for each complete model response.
