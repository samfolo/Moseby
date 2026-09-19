# Permission and tool boundaries

This is a small contract review before implementation, not authentication setup
or a finished permission catalogue. It separates accepted rules from proposals.

## Selected

- Seed one acting staff member for now; no `/me`, JWT or OAuth dependency.
- Application code supplies actor identity through service calls and jobs/tasks.
- The agent uses the user's authority; a classifier has no privileged bypass.
- Threads record their creator and immutable creation-time permission snapshot.
- Thread access is creator-only. New grants require a new thread to use them.
- Current authority is still required. A snapshot cannot preserve revoked access;
  the conservative rule denies thread access when its snapshot is no longer
  covered. Apply thread access to records, inbox, results and associated events.
- Bookings permissions include room reservations and keys. Guests include parties
  and details; rooms include beds. Activities stay separately reviewable because
  itineraries expose different information. Exact codes and venue/hotel grouping
  remain open. Staff data is separate from hotel information.
- Semantic operations handle lifecycle changes; PATCH masks never bypass field
  immutability, permission checks, or domain validation.

## Proposed operation families for the next short review

| Family | Read examples | Write examples | Tool exposure direction |
| --- | --- | --- | --- |
| Hotels / staff members | Read hotel, acting staff | Setup changes only if needed | Domain reads; staff administration can stay out |
| Rooms | Get/search/batch rooms with beds, prices and availability | Edit configuration/in-service state | Search useful now; configuration requires an explicit decision |
| Bookings / checkout / keys | View stay, quote and issued access | Checkout, approve/pay, amend/cancel stay, issue/deactivate key | Domain operations, never raw history edits |
| Guests / parties / details | Search guests, read details | Correct guest fields, add details | Normal operations with field and membership checks |
| Activities / reservations | Search activities/reservations, derived itinerary/counts | Reserve/cancel/reschedule and selected configuration | Reservation versus activity-admin capabilities need review |
| Threads | Read owned thread and records | Create/send/steer/cancel | Cross-thread search deferred; no forged internal records |
| Jobs / notifications | Read permitted operation/progress/events | Submit registered job or notification | Constrained operation types; no arbitrary code or endpoints |
| Schedules / occurrences | List/get definitions and recorded firings | Create/edit/disable schedules | Recheck current authority before future work executes |

The precise family names, permission grammar and read/write versus action-specific
codes are not approved by this table. Creator-only is an ownership check in
addition to capability checks. Hotel/data scopes must not be reduced to a global
set of permission strings. With one seeded staff member the implementation can
stay small while preserving the check boundary.

## Tool contract to define now; implementation can follow

For each exposed operation record: name/description, input and output schema,
required permission(s), handler, sync result versus job response, mutation/retry
behaviour and request-ID propagation. Start with the operations needed for one
end-to-end demonstration. Not every HTTP route or table needs a tool.

Expose only currently usable tools, but enforce permissions again at execution.
The model's selection of a tool never establishes permission or argument validity.
Check delayed work against current authority too; do not execute indefinitely
under stale grants. A fixed thread snapshot remains a ceiling, not an authority
source by itself. Policy-change handling during already-running work is an
implementation detail still to specify.

Recommended next order: finish this small operation-permission-tool matrix,
choose the bill of materials, then implement one vertical path. Full role
administration, authentication and exhaustive tool descriptions can wait.
