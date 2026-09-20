"""Runtime contract routes; ownership and permission checks belong to the service."""

from typing import Annotated, Literal, Never

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from moseby.identifiers import (
    IncomingThreadRecordId,
    JobId,
    NotificationId,
    RunId,
    ScheduleId,
    ScheduleOccurrenceId,
    ThreadId,
    ThreadRecordId,
)

from .common import Page, PageRequest
from .jobs import CreateJobRequest, Job, ListJobsRequest
from .notifications import (
    CreateNotificationRequest,
    ListPublishedEventsRequest,
    Notification,
    PublishedEventPage,
)
from .route_metadata import access, query_body
from .runs import CancelRunRequest, ListRunsRequest, Run
from .schedules import (
    CreateScheduleRequest,
    ListScheduleOccurrencesRequest,
    ListSchedulesRequest,
    Schedule,
    ScheduleOccurrence,
    UpdateScheduleRequest,
)
from .threads import (
    CancelIncomingThreadRecordRequest,
    ConversationRecord,
    CreateIncomingThreadRecordRequest,
    CreateThreadRequest,
    IncomingThreadRecord,
    IncomingThreadRecordReceipt,
    SearchIncomingThreadRecordsRequest,
    SearchThreadRecordsRequest,
    SteerIncomingThreadRecordRequest,
    Thread,
)

router = APIRouter(
    tags=["Runtime"],
    responses={
        403: {"description": "The caller lacks permission for this operation."},
        404: {
            "description": "The resource does not exist or is outside the caller's scope."
        },
        409: {
            "description": "The lifecycle or revision changed, or the request ID was reused with different input."
        },
    },
)
Pagination = Annotated[PageRequest, Query()]


def runtime_access(
    permission: str,
    ownership: Literal[
        "thread_creator", "actor_and_thread_creator", "notification_audience", "actor"
    ],
    *,
    user_only: bool = False,
    body: type[BaseModel] | None = None,
    registered_operation: bool = False,
) -> dict:
    """Declare scope separately from capability; broad grants still require both."""
    metadata = (
        query_body(body, permission, hotel_scoped=False)
        if body
        else access(permission, hotel_scoped=False)
    )
    return metadata | {
        "x-ownership": ownership,
        "x-current-authority-required": True,
        "x-user-only": user_only,
        "x-operation-permissions-required": registered_operation,
    }


def not_implemented() -> Never:
    raise HTTPException(501, "Contract draft; operation is not implemented.")


@router.get(
    "/threads",
    operation_id="listThreads",
    openapi_extra=runtime_access("moseby.threads:read", "thread_creator"),
)
def list_threads(pagination: Pagination) -> Page[Thread]:
    not_implemented()


@router.get(
    "/threads/{id}",
    operation_id="getThread",
    openapi_extra=runtime_access("moseby.threads:read", "thread_creator"),
)
def get_thread(id: ThreadId) -> Thread:
    not_implemented()


@router.post(
    "/threads",
    operation_id="createThread",
    status_code=201,
    description="Create a thread for the acting staff member with its permission snapshot.",
    openapi_extra=runtime_access(
        "moseby.threads:write", "thread_creator", user_only=True
    ),
)
def create_thread(request: CreateThreadRequest) -> Thread:
    not_implemented()


@router.post(
    "/incoming-thread-records",
    operation_id="createIncomingThreadRecord",
    status_code=201,
    description="Save input before acknowledging it. A steer whose target has ended waits as a follow-up without changing its target reference.",
    openapi_extra=runtime_access(
        "moseby.threads:write", "thread_creator", user_only=True
    ),
)
def create_incoming_thread_record(
    request: CreateIncomingThreadRecordRequest,
) -> IncomingThreadRecordReceipt:
    not_implemented()


@router.get(
    "/incoming-thread-records/{id}",
    operation_id="getIncomingThreadRecord",
    openapi_extra=runtime_access("moseby.threads:read", "thread_creator"),
)
def get_incoming_thread_record(id: IncomingThreadRecordId) -> IncomingThreadRecord:
    not_implemented()


@router.api_route(
    "/incoming-thread-records",
    methods=["QUERY"],
    operation_id="searchIncomingThreadRecords",
    description="Read input for one owned thread in arrival order. Pending steers remain visible after their target run ends.",
    openapi_extra=runtime_access(
        "moseby.threads:read", "thread_creator", body=SearchIncomingThreadRecordsRequest
    ),
)
def search_incoming_thread_records(
    request: SearchIncomingThreadRecordsRequest,
) -> Page[IncomingThreadRecord]:
    not_implemented()


@router.post(
    "/incoming-thread-records/{id}:steer",
    operation_id="steerIncomingThreadRecord",
    description="Promote pending user input to assertive delivery for the named run in the same thread.",
    openapi_extra=runtime_access(
        "moseby.threads:write", "thread_creator", user_only=True
    ),
)
def steer_incoming_thread_record(
    id: IncomingThreadRecordId, request: SteerIncomingThreadRecordRequest
) -> IncomingThreadRecord:
    not_implemented()


@router.post(
    "/incoming-thread-records/{id}:cancel",
    operation_id="cancelIncomingThreadRecord",
    description="Withdraw pending user input. Appended input returns a conflict; repeated cancellation retains the original receipt.",
    openapi_extra=runtime_access(
        "moseby.threads:write", "thread_creator", user_only=True
    ),
)
def cancel_incoming_thread_record(
    id: IncomingThreadRecordId, request: CancelIncomingThreadRecordRequest
) -> IncomingThreadRecordReceipt:
    not_implemented()


@router.get(
    "/thread-records/{id}",
    operation_id="getThreadRecord",
    description="Read a user message, assistant message or tool result from an owned thread.",
    openapi_extra=runtime_access("moseby.threads:read", "thread_creator"),
)
def get_thread_record(id: ThreadRecordId) -> ConversationRecord:
    not_implemented()


@router.api_route(
    "/thread-records",
    methods=["QUERY"],
    operation_id="searchThreadRecords",
    description="Read conversation records for one owned thread in sequence order. Internal-only record kinds are omitted, so sequence gaps are valid.",
    openapi_extra=runtime_access(
        "moseby.threads:read", "thread_creator", body=SearchThreadRecordsRequest
    ),
)
def search_thread_records(
    request: SearchThreadRecordsRequest,
) -> Page[ConversationRecord]:
    not_implemented()


@router.get(
    "/runs",
    operation_id="listRuns",
    openapi_extra=runtime_access("moseby.threads:read", "thread_creator"),
)
def list_runs(pagination: Annotated[ListRunsRequest, Query()]) -> Page[Run]:
    not_implemented()


@router.get(
    "/runs/{id}",
    operation_id="getRun",
    openapi_extra=runtime_access("moseby.threads:read", "thread_creator"),
)
def get_run(id: RunId) -> Run:
    not_implemented()


@router.post(
    "/runs/{id}:cancel",
    operation_id="cancelRun",
    status_code=202,
    description="Save a stop request. The run may still be executing; completed external actions and independent scheduled jobs remain intact.",
    openapi_extra=runtime_access(
        "moseby.threads:write", "thread_creator", user_only=True
    ),
)
def cancel_run(id: RunId, request: CancelRunRequest) -> Run:
    not_implemented()


@router.get(
    "/jobs",
    operation_id="listJobs",
    openapi_extra=runtime_access("moseby.jobs:read", "actor_and_thread_creator"),
)
def list_jobs(pagination: Annotated[ListJobsRequest, Query()]) -> Page[Job]:
    not_implemented()


@router.get(
    "/jobs/{id}",
    operation_id="getJob",
    openapi_extra=runtime_access("moseby.jobs:read", "actor_and_thread_creator"),
)
def get_job(id: JobId) -> Job:
    not_implemented()


@router.post(
    "/jobs",
    operation_id="createJob",
    status_code=202,
    description="Accept a publicly registered operation and its initial work atomically. Validate operation arguments and permissions in addition to job admission permission.",
    openapi_extra=runtime_access(
        "moseby.jobs:write", "actor_and_thread_creator", registered_operation=True
    ),
)
def create_job(request: CreateJobRequest) -> Job:
    not_implemented()


@router.get(
    "/schedules",
    operation_id="listSchedules",
    openapi_extra=runtime_access("moseby.schedules:read", "actor_and_thread_creator"),
)
def list_schedules(
    pagination: Annotated[ListSchedulesRequest, Query()],
) -> Page[Schedule]:
    not_implemented()


@router.get(
    "/schedules/{id}",
    operation_id="getSchedule",
    openapi_extra=runtime_access("moseby.schedules:read", "actor_and_thread_creator"),
)
def get_schedule(id: ScheduleId) -> Schedule:
    not_implemented()


@router.post(
    "/schedules",
    operation_id="createSchedule",
    status_code=201,
    description="Validate timing with the registered parser and input with the registered handler. Recheck authority when scheduled work executes.",
    openapi_extra=runtime_access(
        "moseby.schedules:write", "actor_and_thread_creator", registered_operation=True
    ),
)
def create_schedule(request: CreateScheduleRequest) -> Schedule:
    not_implemented()


@router.patch(
    "/schedules/{id}",
    operation_id="updateSchedule",
    description="Apply masked fields only if expected_revision matches, then increment revision. Edits and disabling preserve accepted jobs and their original destination threads.",
    openapi_extra=runtime_access(
        "moseby.schedules:write", "actor_and_thread_creator", registered_operation=True
    ),
)
def update_schedule(id: ScheduleId, request: UpdateScheduleRequest) -> Schedule:
    not_implemented()


@router.get(
    "/schedule-occurrences",
    operation_id="listScheduleOccurrences",
    description="Read accepted firings for an owned schedule; associated job and thread access is also required.",
    openapi_extra=runtime_access("moseby.schedules:read", "actor_and_thread_creator"),
)
def list_schedule_occurrences(
    pagination: Annotated[ListScheduleOccurrencesRequest, Query()],
) -> Page[ScheduleOccurrence]:
    not_implemented()


@router.get(
    "/schedule-occurrences/{id}",
    operation_id="getScheduleOccurrence",
    openapi_extra=runtime_access("moseby.schedules:read", "actor_and_thread_creator"),
)
def get_schedule_occurrence(id: ScheduleOccurrenceId) -> ScheduleOccurrence:
    not_implemented()


@router.get(
    "/notifications",
    operation_id="listNotifications",
    openapi_extra=runtime_access("moseby.notifications:read", "notification_audience"),
)
def list_notifications(pagination: Pagination) -> Page[Notification]:
    not_implemented()


@router.get(
    "/notifications/{id}",
    operation_id="getNotification",
    openapi_extra=runtime_access("moseby.notifications:read", "notification_audience"),
)
def get_notification(id: NotificationId) -> Notification:
    not_implemented()


@router.post(
    "/notifications",
    operation_id="createNotification",
    status_code=201,
    description="Save one notification intent for an authorised recipient. Publication and recipient processing happen separately.",
    openapi_extra=runtime_access("moseby.notifications:write", "actor"),
)
def create_notification(request: CreateNotificationRequest) -> Notification:
    not_implemented()


@router.get(
    "/published-events",
    operation_id="listPublishedEvents",
    description="Replay visible publications in sequence order. Consumers advance their own cursor after handling each page; an empty page is not the end of the stream.",
    openapi_extra=runtime_access("moseby.notifications:read", "notification_audience"),
)
def list_published_events(
    pagination: Annotated[ListPublishedEventsRequest, Query()],
) -> PublishedEventPage:
    not_implemented()
