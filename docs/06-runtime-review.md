---
first_committed: "2026-09-19T16:33:55+01:00"
first_commit: "272b37d"
---

# Giving work a reliable lifecycle

## Objective

Follow a request from acceptance to a saved result. Make retries and worker
ownership explicit, so a timeout does not quietly create duplicate work.
This note includes decisions added as the runtime walkthrough continued.

## Thinking at this stage

- Keep our stored record format separate from the inference provider's format.
  History includes internal events that should not become messages to the model.
- Save a format version with each structured record. That version describes our
  data shape; it is separate from the provider or model version.
- An inference request can contain instructions, history, tool definitions and
  runtime context. Saving it explains what was sent; it is not another user message
  and does not by itself make an inference cache.
- Save the acting staff identity and thread permissions. The model does not pick
  its own identity, and historical permissions cannot preserve revoked access.

### Jobs, tasks and claims

We initially treated a job as the claimable unit. Later we kept jobs and tasks
separate to learn how one operation could coordinate several pieces of work.

| Concept | Meaning |
| --- | --- |
| Job | The overall operation and its outcome. |
| Task | A piece of work a worker can claim; one task per job is enough initially. |
| Claim | The worker's temporary ownership, recorded with a token and expiry. |

- The handler selects the code to run. An operation describes the requested action;
  one handler may support several operations. A phase records progress within a job.
- Only the current, unexpired claim may renew ownership or commit protected writes.
  Replacing a claim makes the old worker's token unusable.
- Retry the same logical task with bounded backoff and jitter. Retrying one task
  should not rerun its already completed neighbours.
- A local claim cannot prevent a duplicate external action. If an outside result
  is uncertain, the handler needs a way to check or safely repeat that action.

### What must be saved together

1. Accept the tool call and create its job and initial tasks in one transaction.
2. Save a task outcome together with the job's next step.
3. Save the final job outcome and an outbox entry saying its result needs delivery.
4. Append that result to the thread, update the thread's state, and mark delivery
   together. A repeated delivery should find the existing result.

The request ledger solves a different problem: recognising a repeated command.
Use the request ID with its operation and actor, compare the input, and return
the accepted result. Reusing that identity for different input should fail.
Separate tool calls do not share a transaction just because they belong to one job.

### Input and future work

- Ordinary input waits for a free thread. A steer targets a run; if that run has
  ended, keep the message as pending input rather than losing it.
- Staff can cancel input before it enters history. Appending and cancelling must
  compete in one transaction. Once appended, send a correction instead.
- A cancelled run stays cancelled. Record late results without reviving it.
  New user input or independent scheduled work can start a new run later.
- A schedule describes timing and an action. An occurrence records one due firing
  being accepted, not proof that its work succeeded. The linked job holds the outcome.
- Keep the accepted schedule revision and input. Editing or disabling the schedule
  should not rewrite work already accepted. Create the occurrence and its job together.
- Use an existing cron parser with an explicit dialect. A scheduler tick discovers
  work; a worker executes it. Missed ticks and accepted unfinished jobs need different rules.
- Publishing a local notification means saving an event and marking it published
  together. Consumers track their own cursor. This does not prove an email was delivered.

## Questions left open at this stage

- How should several task outcomes determine success, failure or the next phase?
- Which failures can be retried, with what limits and claim durations?
- How should partial replies, interrupted runs and old external results recover?
- Which cron dialect, missed-run policy and notification audience rules should we use?

The demo later kept saved tool jobs and claims but deferred automatic recovery.
Scheduling and notifications moved to the extensions branch; see [follow-ups](11-follow-ups.md).
