# How Codex handles steering

Research for discussion, not an implementation decision for Moseby.

Inspected the public Rust source at revision
[`fcf05456bb27e6c3d5677550f54011db6a2a0817`](https://github.com/openai/codex/tree/fcf05456bb27e6c3d5677550f54011db6a2a0817).
The findings below describe that source, including its terminal interface. They
do not establish that every released desktop version behaves identically.
Relevant tests were read, not run.

## Three different actions

| Action | Meaning |
| --- | --- |
| Queue | Keep this message for after the current run finishes. |
| Steer | Give this message to the current run when it can next read input. |
| Interrupt | Ask the current run to stop. This does not undo completed actions. |

Codex calls the active execution a turn. Here, that corresponds roughly to what
we have been calling a run: several model requests and tool calls can belong to
the same run.

The [user documentation](https://learn.chatgpt.com/docs/prompting#steering-and-queuing)
distinguishes queueing from steering. The terminal also keeps ordinary queued
messages and pending steers in separate lists. A message visible near the
composer may already have been sent as a steer, while still waiting to enter
the conversation history. See the
[pending-message display](https://github.com/openai/codex/blob/fcf05456bb27e6c3d5677550f54011db6a2a0817/codex-rs/tui/src/bottom_pane/pending_input_preview.rs#L13-L22).

## What an ordinary steer does

1. The server checks that the intended turn is still active. The app API
   requires its ID, so a delayed request cannot quietly steer a different turn.
2. The server puts the message in the active turn's pending-input list.
3. It signals that new input has arrived. Certain waiting tools listen for this.
4. At a later model-request boundary, the loop takes pending input from the
   list and records it in the history.
5. The next model request includes that history, including the new instruction.
   The same turn continues.

The relevant code is the
[steer handler](https://github.com/openai/codex/blob/fcf05456bb27e6c3d5677550f54011db6a2a0817/codex-rs/core/src/session/turn_input.rs#L624-L707),
[input notification](https://github.com/openai/codex/blob/fcf05456bb27e6c3d5677550f54011db6a2a0817/codex-rs/core/src/session/input_queue.rs#L259-L270),
and [loop reading pending input](https://github.com/openai/codex/blob/fcf05456bb27e6c3d5677550f54011db6a2a0817/codex-rs/core/src/session/turn.rs#L416-L445).
The app's required turn-ID check is declared in
[TurnSteerParams](https://github.com/openai/codex/blob/fcf05456bb27e6c3d5677550f54011db6a2a0817/codex-rs/app-server-protocol/src/protocol/v2/turn.rs#L293-L317).

This path does not rewrite a model request that is already running. It normally
lets the response and its running tools finish before making the next request.
There are also special delays around history compaction, where Codex shortens
the context sent to the model. Therefore, “received” does not mean “the model
has read this.”

One test deliberately sends a steer while reasoning is underway. The original
response still produces its tool call and answer, and the steer reaches the
following model request. See the
[test for continuing the current response](https://github.com/openai/codex/blob/fcf05456bb27e6c3d5677550f54011db6a2a0817/codex-rs/core/tests/suite/pending_input.rs#L1116-L1163)
and the [loop waiting for tool results](https://github.com/openai/codex/blob/fcf05456bb27e6c3d5677550f54011db6a2a0817/codex-rs/core/src/session/turn.rs#L2994-L3022).

## How a sleeping run can respond sooner

The sleep tool waits for either its timer or a new-input signal. If input arrives
first, the tool returns early with a result saying that new input interrupted
the sleep. That is a normal tool result; the run can then continue with the new
user message.

The tool that waits for other agents uses a similar approach. Ending that wait
does not itself stop those agents. This is the useful distinction:

**Stop waiting for the work** and **cancel the work** are separate operations.

See the [sleep implementation](https://github.com/openai/codex/blob/fcf05456bb27e6c3d5677550f54011db6a2a0817/codex-rs/core/src/tools/handlers/sleep.rs#L108-L158),
the [agent wait implementation](https://github.com/openai/codex/blob/fcf05456bb27e6c3d5677550f54011db6a2a0817/codex-rs/core/src/tools/handlers/multi_agents_v2/wait.rs#L180-L205),
and the [test of steering during an agent wait](https://github.com/openai/codex/blob/fcf05456bb27e6c3d5677550f54011db6a2a0817/codex-rs/core/tests/suite/pending_input.rs#L575-L635).

This behaviour has to be implemented by the waiting tool. It does not follow
automatically from using async functions, and it does not make every slow tool
responsive to steering.

## Interrupting to send immediately is a separate path

The terminal offers a stronger action when a steer is pending. It requests an
interrupt, waits for the interrupted-turn notification, then submits the pending
instructions again. This ends the old turn rather than simply adding input to
its next model request.

See the [interrupt shortcut](https://github.com/openai/codex/blob/fcf05456bb27e6c3d5677550f54011db6a2a0817/codex-rs/tui/src/chatwidget/interaction.rs#L180-L192)
and [resubmission after interruption](https://github.com/openai/codex/blob/fcf05456bb27e6c3d5677550f54011db6a2a0817/codex-rs/tui/src/chatwidget/input_restore.rs#L299-L359).
Stopping a run is still not a guarantee that an external action was cancelled.

## What this suggests for Moseby

These are proposals to discuss, not settled behaviour.

Suppose Moseby is waiting for a transport provider to confirm a taxi. A staff
member says, “The guest now needs an accessible vehicle.”

1. Save that message and identify the run it is meant to steer.
2. Let the wait return early, reporting that confirmation is still pending.
3. Give the model that result and the staff member's new instruction.
4. Let it decide what action to request next, within its permissions.
5. Keep track of the original transport request so its eventual result is not
   lost or mistaken for confirmation of the revised request.

That example assumes requesting transport and waiting for confirmation can be
tracked separately. We have not chosen that tool design yet. A single blocking
booking call would not gain this behaviour merely by adding a message queue.

One active run per thread still works. Steering changes what that run knows; it
does not require a second agent loop writing to the same thread.

Before adopting it, we should settle:

- Which waits can return early when staff send input?
- What happens if the intended run finishes before the steer arrives?
- What does the interface show while a message is received but not yet included
  in a model request? Inclusion also does not prove the model followed it.
- How do we save pending messages so a restart cannot lose an accepted steer?
- How do we handle an old external result after staff change the request?

The inspected Codex path initially buffers pending steers in memory and records
them later. That path alone is not evidence of restart-safe delivery. Moseby's
durable threads need an explicit answer to when input is saved and when it has
been used. See the
[pending-input structures](https://github.com/openai/codex/blob/fcf05456bb27e6c3d5677550f54011db6a2a0817/codex-rs/core/src/session/input_queue.rs#L75-L85)
and the history-recording loop linked above.
