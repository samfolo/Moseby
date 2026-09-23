---
first_committed: "2026-09-22T11:14:53+01:00"
first_commit: "8f61cc5"
---

# What we would work on next

## Objective

Keep useful ideas from the walkthrough and live trials without treating all of
them as promises. This is the remaining-work list; older notes record how we got here.

## Where we got to

The [concierge](../moseby/agents/concierge.py) can search rooms and guests, manage
stays and activity reservations, update guest details, save and search notes,
and issue or deactivate demo keys. Conversations and tool outcomes are saved.
Reopening a conversation works; recovering a run interrupted halfway through is separate work.

Scheduling and notification code is preserved on the
[extensions branch](https://github.com/samfolo/Moseby/tree/extensions).
Use it as a reference when revisiting those features; the main branch has since changed.

## Make the existing journeys better

- Turn the trial transcripts into evaluation cases: search before asking, clarify
  shared names, avoid repeated confirmation, and report what actually happened.
- Let staff clarify an existing note. Find it by party, text and time, then use its
  saved ID and check for intervening changes. Keep the original note and previous decision.
- Check Jev's accuracy on full names and shared first names. Uncertainty should
  not discard a clear match or cause a duplicate note.
- Make activity replacement safe: a failed new reservation must not lose the old place.
- Give tool errors separate problem, affected-resource and suggested-action fields.
- Compare concise text or tables with JSON for tool results. Preserve IDs, versions,
  prices and cursors, and measure whether any token saving hurts accuracy.
- Improve the CLI if needed. A web client, calendar or job board could follow;
  generate its types from OpenAPI rather than copying the contract.

Sources: the trial transcripts, [domain review](10-domain-contract-review.md) and
[API review](07-api-overview.md).

## Finish recovery before adding more background work

- Run inference independently of the client. Python supports this; the current
  loop simply waits for the response.
- On startup and periodically, find unfinished work and reclaim expired claims.
  Do not steal live claims. Use bounded retries with exponential backoff and jitter;
  check uncertain external outcomes before repeating an action.
- Save streamed events with a cursor so reconnecting clients can catch up.
  Show reasoning or answer progress when the provider reports it.
- Connect pending input, steering, cancellation and wake rules to the running engine.
- Choose a cron dialect and library. Define missed-run behaviour, create each
  occurrence with its job, and recheck facts and permissions before acting.
- Demonstrate an outside request, such as a taxi, returning a job ID and later
  reporting completion, failure or a need for more information.
- Add controlled notifications for activity changes and reminders. Publishing a
  local event, processing it and delivering an email are separate outcomes.

Sources: [runtime review](06-runtime-review.md) and [steering research](03-steering.md).

## Make deployment and operation safer

- Replace the fixed staff identity with login and role management; add useful auditing.
  A guest-facing interface needs verified guest identity and much narrower access.
- Review what tools disclose and how long personal details remain in notes, logs
  and saved inference requests. A classifier cannot replace access checks.
- Keep per-run token limits separate from API spending. Track generation and
  classification costs, cache usage, reasoning and missing usage reports explicitly.
- Add useful traces, configurable logging and optional OTLP export.
- Inspect query plans before adding performance indexes. Revisit long-history
  loading, caching and context compaction when they become a real problem.
- Preserve released agent and prompt versions for comparison. Keep the existing
  agent ID/version links useful for later evaluation.
- Generate titles or summaries through small inference calls when needed.
- Add hotel-local dates and daylight-saving rules beyond the initial UTC convention.

Sources: the migration, configuration and live reviews, plus [permissions](08-permissions-and-tools.md).

## Ideas deliberately set aside

- Checkout, roughly five-minute holds and an external or simulated payment receipt.
  Refunds, incidental charges, credit, discounts and seasonal rates need separate decisions.
- Packages and reserved activity places for particular booking types.
- Real door locks, key-use evidence, arrivals, departures and attendance tracking.
- Richer venue and eligibility rules; housekeeping and inventory belong to other agents.
- Semantic search, including the suggested Turbopuffer experiment, personalisation
  from notes, and any return to cross-visit guest identities.
- Permission-filtered tool discovery, more Jev routing, subagents, side questions,
  code execution, generated forms and other interfaces.
- Floor-plan upload, OCR and spatial queries.

Sources: [initial modelling](01-data-modelling.md), [checkout](05-checkout-lifecycle.md)
and [the scope review](04-design-review.md).

## Questions for the next pass

Which failures do the trial transcripts expose most often? Can a fresh user
complete the demo without help? What must recovery guarantee before we let the
agent act while nobody is watching? Those answers should set the next priorities.
