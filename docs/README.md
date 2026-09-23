# Design notes

These notes follow the conversations that shaped Moseby. They explain what we
wanted, what changed as we thought it through, and which questions remained.
Start with the project [README](../README.md) to use the demo.

The numbers follow each document's first Git commit. The date in its front matter
is that commit's timestamp, not the date every decision was made. Notes grew over
several reviews; later decisions are labelled where they change the earlier thinking.
We shortened them on 23 September 2026. The [original versions](https://github.com/samfolo/Moseby/tree/9bbd19af6d9b612e0e375cdf14501b93e5497728/docs)
remain in Git.

| Stage | Main question |
| --- | --- |
| [01 · Hotel model](01-data-modelling.md) | What do staff need to know about a guest's stay? |
| [02 · Conversation loop](02-agent-runtime.md) | How does a conversation become work? |
| [03 · Steering](03-steering.md) | How can staff change a request while work is running? |
| [04 · Design review](04-design-review.md) | Which decisions still need an answer? |
| [05 · Checkout](05-checkout-lifecycle.md) | When do we hold rooms and confirm a stay? |
| [06 · Runtime](06-runtime-review.md) | Who owns work, and how does its result reach the thread? |
| [07 · API](07-api-overview.md) | Which actions should callers be able to take? |
| [08 · Permissions](08-permissions-and-tools.md) | What should the concierge be allowed to do? |
| [09 · Python contract](09-python-contract.md) | How do we describe and validate those requests? |
| [10 · Domain review](10-domain-contract-review.md) | Do the rules still fit together? |
| [11 · Follow-ups](11-follow-ups.md) | What would we work on next? |

Earlier open questions are part of the history, not a second backlog. Use the
follow-ups for remaining work. Scheduling and notification work is preserved on
the [extensions branch](https://github.com/samfolo/Moseby/tree/extensions) for reference.
