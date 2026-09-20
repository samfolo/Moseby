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
  itineraries expose different information. Staff data is separate from hotel
  information.
- Semantic operations handle lifecycle changes; PATCH masks never bypass field
  immutability, permission checks, or domain validation.

## Proposed operation families for the next short review

| Family | Read examples | Write examples | Tool exposure direction |
| --- | --- | --- | --- |
| Hotels / staff members | Read hotel, acting staff | Setup changes only if needed | Domain reads; staff administration can stay out |
| Rooms | Get/search/batch rooms with beds, prices and availability | Edit configuration/in-service state | Configuration belongs to a privileged profile; excluded from the concierge agent |
| Bookings / checkout / keys | View stay, quote and issued access | Checkout, approve/pay, amend/cancel stay, issue/deactivate key | Domain operations, never raw history edits |
| Guests / parties / details | Search guests, read details | Correct guest fields, add details | Normal operations with field and membership checks |
| Activities / reservations | Search activities/reservations, derived itinerary/counts | Reserve/cancel/reschedule and selected configuration | Reservation versus activity-admin capabilities need review |
| Threads | Read owned thread and records | Create/send/steer/cancel | Cross-thread search deferred; no forged internal records |
| Jobs / notifications | Read permitted operation/progress/events | Submit registered job or notification | Constrained operation types; no arbitrary code or endpoints |
| Schedules / occurrences | List/get definitions and recorded firings | Create/edit/disable schedules | Recheck current authority before future work executes |

This table sketches future operations. The current routes use the namespaced
permission codes listed below. Creator-only is an ownership check in
addition to capability checks. Hotel/data scopes must not be reduced to a global
set of permission strings. With one seeded staff member the implementation can
stay small while preserving the check boundary.

## Current contract permissions

This is the permission registry for domain and runtime routes. The registry
lives in `moseby/contracts/route_metadata.py`; unknown codes fail contract generation.

| Permission | Capability |
| --- | --- |
| `moseby:read` | Read any Moseby resource within the caller's data scope |
| `moseby:write` | Write any Moseby resource within the caller's data scope |
| `moseby:execute` | Execute registered actions within the caller's data scope |
| `moseby.hotels:read` | Read hotel information |
| `moseby.staff-members:read` | Read staff information |
| `moseby.rooms:read` | Read/search rooms, including beds, prices and availability |
| `moseby.rooms.configuration:write` | Configure rooms; excluded from the concierge agent profile |
| `moseby.venues:read` | Read shared venues |
| `moseby.bookings:read` | Read bookings, embedded room reservations and keys |
| `moseby.bookings:write` | Issue and deactivate room keys |
| `moseby.guests:read` | Read/search guests, parties and party details |
| `moseby.guests:write` | Update guest fields and add party details |
| `moseby.activities:read` | Read/search activities and guest reservations |
| `moseby.activities:write` | Cancel activity reservations |
| `moseby.threads:read` | Read owned threads, incoming input, conversation records and runs |
| `moseby.threads:write` | Create threads, send or steer input, cancel pending input and request run cancellation |
| `moseby.jobs:read` | Read permitted jobs and outcomes |
| `moseby.jobs:write` | Submit publicly registered operations |
| `moseby.schedules:read` | Read owned schedules and accepted occurrences |
| `moseby.schedules:write` | Create, edit and disable permitted schedules |
| `moseby.notifications:read` | Read permitted notifications and published events |
| `moseby.notifications:write` | Request notifications for permitted recipients |

`Permission` in `moseby/permissions.py` validates names on construction and
serializes as a string. Names begin with lowercase `moseby`; dot-separated
segments contain lowercase letters, digits and single internal hyphens, starting
with a letter. A colon separates the path from `read`, `write` or `execute`.

`PermissionResolver.matches(granted, required)` compares complete path segments
and requires the same action. A grant covers itself and its descendants:
`moseby.rooms.configuration:write` accepts that exact grant,
`moseby.rooms:write`, or `moseby:write`. It does not accept a sibling path,
a descendant grant, or a different action. Read, write and execute are independent.

The concierge profile omits room configuration and its tool. Its grants must also
omit `moseby.rooms:write` and `moseby:write`, since either would grant configuration
access. Broad grants still require hotel scope, thread ownership and lifecycle
checks. An unknown staff role grants no permissions.

`x-permissions.anyOf` lists the exact permission and every covering ancestor,
nearest first. `x-hotel-scoped: true`
additionally requires records to belong to the acting staff member's hotel,
possibly through their booking. Shared venue/activity definitions use false
because they have no hotel owner; their read permission is still required.
Reservations remain hotel-scoped even when the activity itself is shared.

These are Moseby's custom OpenAPI annotations, not framework authorization.
The earlier `shared-catalogue` scope label is removed. Role grants and enforcement
remain to be implemented; adding a permission annotation alone does not secure a route.

### Runtime scope annotations

`x-ownership` describes the additional row-level check:

- `thread_creator`: the acting staff member created the thread; its permission
  snapshot must still be covered by their current authority.
- `actor_and_thread_creator`: the acting staff member owns the job or schedule,
  and any associated thread passes the same thread-access check. Occurrences
  follow their original job's thread, including after a schedule is edited.
- `notification_audience`: the caller authored the notification or is its staff
  recipient; any referenced guest or hotel data must also remain authorised.
- `actor`: the service supplies the authenticated actor and checks the recipient's
  data scope before accepting the notification.

`x-current-authority-required` applies to reads as well as execution.
`x-operation-permissions-required` means a registered job or schedule handler must
also check the permissions for the actual action; queue access alone is insufficient.
`x-user-only` requires a direct user action through any interface. The service
checks trusted caller origin separately from identity and permissions; sharing a
staff identity does not make an agent call a user action. Caller origin must not
come from an untrusted request flag. These operations stay out of agent tool sets.
These annotations describe service checks and do not implement them.

Editing or disabling a schedule, or stopping a waiting run, does not cancel work
already accepted from that schedule. Each accepted job retains its original
destination thread. A handler that delivers conversational input requires that
thread explicitly; it never uses whichever thread a user happens to have open.
Current authority and thread access still apply. Revoked authority blocks
execution or access, while the accepted job and its outcome remain recorded.

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
