---
first_committed: "2026-09-18T18:20:16+01:00"
first_commit: "64fc0a9"
---

# Bringing the open questions together

## Objective

Stop losing decisions in a long conversation. Review one part of the system at
a time, and decide what actually needs an answer before building the demo.
An unanswered question was not an instruction to add another feature.

## Thinking at this stage

The main relationships were settled: a hotel has bookings, each booking has a
party, and each guest belongs to that party for one visit. Prices keep versions.
Cancelling a booking is final. Thread history and hotel records serve different purposes.

We divided the remaining review into eight questions:

| Area | Question to answer |
| --- | --- |
| Checkout | What information survives an unfinished booking, and when is capacity held? |
| Changes and keys | What stays valid while a room change is being arranged? |
| Activities | What does one reservation represent, and who can attend? |
| Prices and payment | What price was agreed, and what proves payment happened? |
| People and permissions | Who may act, see a detail, or receive a notification? |
| Conversation | How does saved input become a run and then a response? |
| Work and recovery | Who owns a task, and what happens if that worker disappears? |
| Scheduling | How does a due time become work without being accepted twice? |

### Checks worth making explicit

- A reference to a guest and a reference to a party do not by themselves prove
  the guest belongs to that party. Check the relationship too.
- Creating a booking should also create its party, guests and allocations together.
  A foreign key cannot make those required child records appear.
- Capacity must cover the party throughout the stay. Adding up rooms booked for
  different dates could give a misleading total.
- Check the last available room or activity place in the transaction that takes it.
  Appending history does not remove the possibility of a booking race.
- Reject edits based on an old revision. Giving an outdated edit a new revision
  number would still overwrite somebody else's decision.
- Keep network and model calls outside database write transactions.
- Decide when records may be deleted before promising both permanent history
  and automatic deletion of personal data.

## Questions left open at this stage

The eight areas above were the review agenda. In particular, checkout storage,
payment uncertainty, activity changes, note classification failures, worker
recovery and schedule handover still needed concrete rules.

Packages, physical locks, identity documents, floor plans, semantic search,
subagents and a full billing system were set aside. Indexes would follow the
queries we actually needed, rather than being guessed during this review.

## Where the review led

- [Checkout](05-checkout-lifecycle.md) separated shopping, a temporary hold and payment.
- [The runtime review](06-runtime-review.md) worked through jobs, claims and delivery.
- [The API](07-api-overview.md) and [permissions](08-permissions-and-tools.md) gave
  those actions a reviewable shape.
- [The domain contract](10-domain-contract-review.md) resolved reservation and key rules.
- To finish a usable demo, we later deferred checkout, payments and proactivity.
  The [follow-ups](11-follow-ups.md) collect that remaining work in one place.
