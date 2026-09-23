---
first_committed: "2026-09-17T18:21:46+01:00"
first_commit: "b009619"
---

# Learning from Codex steering

## Objective

Understand how staff could change a request while Moseby was already working,
without starting two competing runs on the same conversation.

We read the public Codex Rust source at
[revision fcf05456](https://github.com/openai/codex/tree/fcf05456bb27e6c3d5677550f54011db6a2a0817).
These findings describe that revision, including its terminal interface.
We read the relevant tests; we did not run them.

## What the source showed

| Action | What it means |
| --- | --- |
| Queue | Save this message for after the current run. |
| Steer | Give the current run this message when it can next use input. |
| Interrupt | Ask the run to stop. Completed actions are not undone. |

- An ordinary steer targets a particular active turn. A delayed request should
  not quietly steer a different one.
- Codex puts the message into pending input and signals that input has arrived.
  The loop takes it into history before a later model request.
- This does not rewrite a request already being processed. Its answer and tool
  work can arrive before the steer is included in the next request.
- Some waiting tools can return early when input arrives. That responsiveness
  comes from the tool's implementation, not merely from using async functions.
- The terminal also has a stronger interrupt-and-resubmit path. It ends the
  old turn rather than simply adding a message to that turn's next request.
- The inspected pending-input path uses memory before recording the message.
  That alone does not establish that an accepted steer survives a restart.

Source references: [steer handler](https://github.com/openai/codex/blob/fcf05456bb27e6c3d5677550f54011db6a2a0817/codex-rs/core/src/session/turn_input.rs#L624-L707),
[pending-input loop](https://github.com/openai/codex/blob/fcf05456bb27e6c3d5677550f54011db6a2a0817/codex-rs/core/src/session/turn.rs#L416-L445),
[sleep tool](https://github.com/openai/codex/blob/fcf05456bb27e6c3d5677550f54011db6a2a0817/codex-rs/core/src/tools/handlers/sleep.rs#L108-L158),
and [resubmission after interruption](https://github.com/openai/codex/blob/fcf05456bb27e6c3d5677550f54011db6a2a0817/codex-rs/tui/src/chatwidget/input_restore.rs#L299-L359).

## What this suggested for Moseby

Suppose a taxi request is pending and staff add, “The guest needs an accessible
vehicle.” Save that instruction, let the wait return early, and give the model
both the new instruction and the fact that confirmation is still pending.
Keep tracking the original request so its later result is not lost or confused
with confirmation of a replacement.

This requires separate ways to request transport and wait for it. Adding an
inbox alone would not make a single blocking booking call behave that way.
One active run per thread is still enough.

## Questions left open at this stage

- Which waits should listen for new input?
- What should happen if the targeted run has already ended?
- What should staff see while a saved message is waiting to reach the model?
- When is input saved durably, and how do we avoid adding it twice after a retry?
- What should happen when an old external result arrives after the plan changes?

The later [runtime review](06-runtime-review.md) records the chosen delivery rules.
Wiring those rules into the running engine remains in [follow-ups](11-follow-ups.md).
