"""Thread history, queued work, schedules and published notifications.

Times use UTC microseconds. JSON payloads use versioned application formats.
Migration-local helpers keep schema creation repeatable.
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_runtime"
down_revision = "0001_domain"
branch_labels = None
depends_on = None


def _identity(prefix: str, timestamp: str = "created_at") -> tuple:
    """Give each record a prefixed ULID and a creation time."""
    start = len(prefix) + 2
    return (
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column(timestamp, sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{prefix}"),
        sa.CheckConstraint(
            f"length(id) = {len(prefix) + 27} AND substr(id, 1, {start - 1}) = '{prefix}_' "
            f"AND substr(id, {start}, 1) GLOB '[0-7]' "
            f"AND substr(id, {start}) NOT GLOB '*[^0-9A-HJKMNP-TV-Z]*'",
            name=f"ck_{prefix}_id",
        ),
    )


def _json(name: str, *, shape: str = "object", nullable: bool = False) -> tuple:
    """Check JSON can be read and has the expected outer shape."""
    return (
        sa.Column(name, sa.Text(), nullable=nullable),
        sa.CheckConstraint(
            f"{name} IS NULL OR CASE WHEN json_valid({name}) "
            f"THEN json_type({name}) = '{shape}' ELSE 0 END",
            name=f"ck_{name}_{shape}",
        ),
    )


def _updated_at() -> tuple:
    """Repositories set this on creation and on every subsequent update."""
    return (
        sa.Column("updated_at", sa.Integer(), nullable=False),
        sa.CheckConstraint("updated_at >= created_at", name="ck_updated_at"),
    )


def _status(
    prefix: str,
    choices: tuple[str, ...],
    *,
    column: str = "status",
    name: str | None = None,
) -> sa.CheckConstraint:
    """Allow only the status values understood by this migration."""
    values = ", ".join(f"'{prefix}_{choice}'" for choice in choices)
    return sa.CheckConstraint(
        f"{column} IN ({values})", name=name or f"ck_{prefix.lower()}"
    )


def _trigger(name: str, event: str, table: str, body: str, when: str = "") -> None:
    """Run a named check before a write."""
    condition = f"WHEN {when}" if when else ""
    op.execute(
        f"CREATE TRIGGER {name} BEFORE {event} ON {table} {condition} BEGIN {body} END"
    )


def _fixed(table: str, columns: tuple[str, ...]) -> None:
    """Keep the listed fields fixed after insertion."""
    _trigger(
        f"{table}_keep_identity",
        "UPDATE",
        table,
        "SELECT RAISE(ABORT, 'These fields cannot change');",
        " OR ".join(f"NEW.{column} IS NOT OLD.{column}" for column in columns),
    )


def _append_only(table: str) -> None:
    """Keep saved history unchanged."""
    for event in ("UPDATE", "DELETE"):
        _trigger(
            f"{table}_no_{event.lower()}",
            event,
            table,
            "SELECT RAISE(ABORT, 'Saved history cannot be changed or deleted');",
        )


def upgrade() -> None:
    """Create history first, then work, schedules and notification delivery."""
    _create_threads_and_runs()
    _create_thread_records()
    _create_incoming_and_inference()
    _create_requests_and_work()
    _create_schedules()
    _create_notifications()
    _create_rules()


def _create_threads_and_runs() -> None:
    """Keep the thread's identity separate from each run of its agent loop."""
    op.create_table(
        "threads",
        *_identity("thread"),
        *_updated_at(),
        sa.Column(
            "creator_staff_member_id",
            sa.Text(),
            sa.ForeignKey("staff_members.id", name="fk_thread_creator"),
            nullable=False,
        ),
        *_json("permissions_json", shape="array"),
        sa.Column("title", sa.Text()),
        sa.Column("archived_at", sa.Integer()),
        # These fields are updated alongside the records they summarize.
        sa.Column("projection_sequence", sa.Integer(), nullable=False),
        sa.Column("projection_format_version", sa.Integer(), nullable=False),
        *_json("projection_json"),
        sa.CheckConstraint(
            "projection_sequence >= 0", name="ck_thread_projection_sequence"
        ),
        sa.CheckConstraint(
            "projection_format_version = 1", name="ck_thread_projection_version"
        ),
        sa.CheckConstraint(
            "archived_at IS NULL OR archived_at >= created_at",
            name="ck_thread_archived_at",
        ),
        sqlite_strict=True,
    )
    op.create_table(
        "runs",
        *_identity("run"),
        *_updated_at(),
        sa.Column(
            "thread_id",
            sa.Text(),
            sa.ForeignKey("threads.id", name="fk_run_thread"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("wake_at", sa.Integer()),
        sa.Column("cancel_requested_at", sa.Integer()),
        sa.Column(
            "cancel_requested_by_staff_member_id",
            sa.Text(),
            sa.ForeignKey("staff_members.id", name="fk_run_cancel_actor"),
        ),
        sa.Column("recovery_attempts", sa.Integer(), nullable=False),
        sa.Column("finished_at", sa.Integer()),
        sa.UniqueConstraint("id", "thread_id", name="uq_run_thread"),
        _status(
            "RUN_STATUS",
            ("QUEUED", "RUNNING", "WAITING", "COMPLETED", "FAILED", "CANCELLED"),
        ),
        sa.CheckConstraint("recovery_attempts >= 0", name="ck_run_recovery_attempts"),
        sa.CheckConstraint(
            "wake_at IS NULL OR status = 'RUN_STATUS_WAITING'", name="ck_run_wake"
        ),
        sa.CheckConstraint(
            "(cancel_requested_at IS NULL AND cancel_requested_by_staff_member_id IS NULL) OR (cancel_requested_at IS NOT NULL AND cancel_requested_at >= created_at AND cancel_requested_by_staff_member_id IS NOT NULL)",
            name="ck_run_cancel_request",
        ),
        sa.CheckConstraint(
            "(status IN ('RUN_STATUS_COMPLETED', 'RUN_STATUS_FAILED', 'RUN_STATUS_CANCELLED')) = (finished_at IS NOT NULL)",
            name="ck_run_finished",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= created_at",
            name="ck_run_finish_time",
        ),
        sqlite_strict=True,
    )
    # Enforce one active run per thread, including a sleeping run.
    op.create_index(
        "uq_run_active_thread",
        "runs",
        ["thread_id"],
        unique=True,
        sqlite_where=sa.text(
            "status IN ('RUN_STATUS_QUEUED', 'RUN_STATUS_RUNNING', 'RUN_STATUS_WAITING')"
        ),
    )


def _create_thread_records() -> None:
    """One ordered history for messages, results and runtime events."""
    op.create_table(
        "thread_records",
        *_identity("thread_record"),
        sa.Column(
            "thread_id",
            sa.Text(),
            sa.ForeignKey("threads.id", name="fk_record_thread"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("format_version", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Text()),
        sa.Column(
            "actor_staff_member_id",
            sa.Text(),
            sa.ForeignKey("staff_members.id", name="fk_record_actor"),
        ),
        # One source record can request several tools; the call ID selects one.
        sa.Column("source_record_id", sa.Text()),
        sa.Column("tool_call_id", sa.Text()),
        *_json("payload_json"),
        sa.UniqueConstraint("thread_id", "sequence", name="uq_record_sequence"),
        sa.UniqueConstraint("id", "thread_id", name="uq_record_thread"),
        sa.UniqueConstraint(
            "source_record_id", "tool_call_id", name="uq_record_tool_result"
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "thread_id"], ["runs.id", "runs.thread_id"], name="fk_record_run"
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id", "thread_id"],
            ["thread_records.id", "thread_records.thread_id"],
            name="fk_record_source",
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_record_sequence"),
        sa.CheckConstraint("format_version = 1", name="ck_record_format_version"),
        sa.CheckConstraint(
            "kind IN ('THREAD_RECORD_KIND_THREAD_CREATED', 'THREAD_RECORD_KIND_USER_MESSAGE', 'THREAD_RECORD_KIND_ASSISTANT_MESSAGE', 'THREAD_RECORD_KIND_TOOL_RESULT', 'THREAD_RECORD_KIND_CLASSIFIER_DECISION', 'THREAD_RECORD_KIND_INFERENCE_REQUEST', 'THREAD_RECORD_KIND_CONTROL_EVENT')",
            name="ck_record_kind",
        ),
        sa.CheckConstraint(
            "(kind = 'THREAD_RECORD_KIND_TOOL_RESULT' AND source_record_id IS NOT NULL AND tool_call_id IS NOT NULL AND length(tool_call_id) > 0) OR (kind != 'THREAD_RECORD_KIND_TOOL_RESULT' AND tool_call_id IS NULL)",
            name="ck_record_tool_link",
        ),
        sqlite_strict=True,
    )


def _create_incoming_and_inference() -> None:
    """Receiving input, appending it, and using it in a request are separate steps."""
    op.create_table(
        "incoming_thread_records",
        *_identity("incoming_thread_record"),
        *_updated_at(),
        sa.Column(
            "thread_id",
            sa.Text(),
            sa.ForeignKey("threads.id", name="fk_incoming_thread"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        # Assertive input joins the active run at a safe point between execution steps.
        sa.Column("delivery_mode", sa.Text(), nullable=False),
        sa.Column("target_run_id", sa.Text()),
        sa.Column(
            "actor_staff_member_id",
            sa.Text(),
            sa.ForeignKey("staff_members.id", name="fk_incoming_actor"),
            nullable=False,
        ),
        # HTTP input carries a request ID; internal input uses its source identity.
        sa.Column("request_id", sa.Text()),
        sa.Column("format_version", sa.Integer(), nullable=False),
        *_json("payload_json"),
        sa.Column("record_id", sa.Text()),
        # Time this input was accepted into permanent thread history.
        sa.Column("appended_at", sa.Integer()),
        sa.UniqueConstraint("thread_id", "sequence", name="uq_incoming_sequence"),
        sa.UniqueConstraint(
            "thread_id",
            "actor_staff_member_id",
            "request_id",
            name="uq_incoming_request",
        ),
        sa.UniqueConstraint("record_id", name="uq_incoming_record"),
        sa.ForeignKeyConstraint(
            ["target_run_id", "thread_id"],
            ["runs.id", "runs.thread_id"],
            name="fk_incoming_target_run",
        ),
        sa.ForeignKeyConstraint(
            ["record_id", "thread_id"],
            ["thread_records.id", "thread_records.thread_id"],
            name="fk_incoming_record",
        ),
        sa.CheckConstraint(
            "sequence >= 1 AND (request_id IS NULL OR length(request_id) > 0)",
            name="ck_incoming_sequence_request",
        ),
        sa.CheckConstraint("format_version = 1", name="ck_incoming_version"),
        sa.CheckConstraint(
            "kind IN ('INCOMING_THREAD_RECORD_KIND_USER_MESSAGE', 'INCOMING_THREAD_RECORD_KIND_SCHEDULED_INPUT')",
            name="ck_incoming_kind",
        ),
        sa.CheckConstraint(
            "delivery_mode IN ('INCOMING_THREAD_RECORD_DELIVERY_MODE_POLITE', 'INCOMING_THREAD_RECORD_DELIVERY_MODE_ASSERTIVE')",
            name="ck_incoming_delivery_mode",
        ),
        sa.CheckConstraint(
            "(delivery_mode = 'INCOMING_THREAD_RECORD_DELIVERY_MODE_ASSERTIVE') = (target_run_id IS NOT NULL)",
            name="ck_incoming_target_run",
        ),
        sa.CheckConstraint(
            "kind = 'INCOMING_THREAD_RECORD_KIND_USER_MESSAGE' OR delivery_mode = 'INCOMING_THREAD_RECORD_DELIVERY_MODE_POLITE'",
            name="ck_incoming_scheduled_delivery",
        ),
        sa.CheckConstraint(
            "(record_id IS NULL) = (appended_at IS NULL)", name="ck_incoming_append"
        ),
        sa.CheckConstraint(
            "appended_at IS NULL OR appended_at >= created_at",
            name="ck_incoming_append_time",
        ),
        sqlite_strict=True,
    )
    op.create_table(
        "inference_requests",
        *_identity("inference_request"),
        *_updated_at(),
        # Each row records an individual inference attempt and its outcome.
        # _identity supplies created_at; started_at marks the provider call.
        # Thread and run links are optional for standalone inference, such as titles.
        sa.Column(
            "thread_id",
            sa.Text(),
            sa.ForeignKey("threads.id", name="fk_inference_thread"),
        ),
        sa.Column("run_id", sa.Text()),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("format_version", sa.Integer(), nullable=False),
        *_json("request_json"),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.Integer()),
        sa.Column("finished_at", sa.Integer()),
        *_json("response_json", nullable=True),
        *_json("error_json", nullable=True),
        sa.UniqueConstraint("id", "thread_id", name="uq_inference_thread"),
        sa.ForeignKeyConstraint(
            ["run_id", "thread_id"],
            ["runs.id", "runs.thread_id"],
            name="fk_inference_run",
        ),
        sa.CheckConstraint(
            "run_id IS NULL OR thread_id IS NOT NULL", name="ck_inference_run_thread"
        ),
        sa.CheckConstraint(
            "purpose IN ('INFERENCE_REQUEST_PURPOSE_MAIN', 'INFERENCE_REQUEST_PURPOSE_CLASSIFIER', 'INFERENCE_REQUEST_PURPOSE_TITLE')",
            name="ck_inference_purpose",
        ),
        sa.CheckConstraint(
            "purpose != 'INFERENCE_REQUEST_PURPOSE_MAIN' OR run_id IS NOT NULL",
            name="ck_inference_main_run",
        ),
        sa.CheckConstraint(
            "length(provider) > 0 AND length(model) > 0",
            name="ck_inference_provider_model",
        ),
        sa.CheckConstraint("format_version = 1", name="ck_inference_version"),
        _status(
            "INFERENCE_STATUS",
            ("PREPARED", "IN_FLIGHT", "SUCCEEDED", "FAILED", "UNKNOWN"),
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR started_at >= created_at", name="ck_inference_start"
        ),
        sa.CheckConstraint(
            "(status = 'INFERENCE_STATUS_PREPARED') = (started_at IS NULL)",
            name="ck_inference_started",
        ),
        sa.CheckConstraint(
            "(status IN ('INFERENCE_STATUS_SUCCEEDED', 'INFERENCE_STATUS_FAILED', 'INFERENCE_STATUS_UNKNOWN')) = (finished_at IS NOT NULL)",
            name="ck_inference_finished",
        ),
        sa.CheckConstraint(
            "(status = 'INFERENCE_STATUS_SUCCEEDED') = (response_json IS NOT NULL)",
            name="ck_inference_response",
        ),
        sa.CheckConstraint(
            "status != 'INFERENCE_STATUS_FAILED' OR error_json IS NOT NULL",
            name="ck_inference_error",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR (started_at IS NOT NULL AND finished_at >= started_at)",
            name="ck_inference_finish",
        ),
        sqlite_strict=True,
    )
    # Link each request to the saved thread records selected as its input.
    # sequence orders the selected records within this request.
    op.create_table(
        "inference_request_records",
        sa.Column("inference_request_id", sa.Text(), nullable=False),
        sa.Column("record_id", sa.Text(), nullable=False),
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint(
            "inference_request_id", "record_id", name="pk_inference_request_records"
        ),
        sa.UniqueConstraint(
            "inference_request_id", "sequence", name="uq_inference_record_sequence"
        ),
        sa.ForeignKeyConstraint(
            ["inference_request_id", "thread_id"],
            ["inference_requests.id", "inference_requests.thread_id"],
            name="fk_context_request",
        ),
        sa.ForeignKeyConstraint(
            ["record_id", "thread_id"],
            ["thread_records.id", "thread_records.thread_id"],
            name="fk_context_record",
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_context_sequence"),
        sqlite_strict=True,
    )


def _create_requests_and_work() -> None:
    """Save accepted commands, job progress, task ownership and undelivered results."""
    op.create_table(
        "request_deduplication",
        sa.Column(
            "actor_staff_member_id",
            sa.Text(),
            sa.ForeignKey("staff_members.id", name="fk_dedup_actor"),
            nullable=False,
        ),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        *_updated_at(),
        # Include path parameters as well as the body in this saved request.
        *_json("request_json"),
        *_json("response_json", nullable=True),
        sa.PrimaryKeyConstraint(
            "actor_staff_member_id",
            "operation",
            "request_id",
            name="pk_request_deduplication",
        ),
        sa.CheckConstraint(
            "length(operation) > 0 AND length(request_id) > 0", name="ck_dedup_names"
        ),
        sqlite_strict=True,
    )
    op.create_table(
        "jobs",
        *_identity("job"),
        *_updated_at(),
        sa.Column(
            "actor_staff_member_id",
            sa.Text(),
            sa.ForeignKey("staff_members.id", name="fk_job_actor"),
            nullable=False,
        ),
        # The requested action; handler below selects its registered implementation.
        sa.Column("operation", sa.Text(), nullable=False),
        # Used for idempotency, whether the command came from HTTP or internally.
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column(
            "thread_id", sa.Text(), sa.ForeignKey("threads.id", name="fk_job_thread")
        ),
        sa.Column("run_id", sa.Text()),
        sa.Column("source_record_id", sa.Text()),
        sa.Column("tool_call_id", sa.Text()),
        # Coordinates the job's tasks and decides what follows their results.
        sa.Column("handler", sa.Text(), nullable=False),
        # Workflow step used by the coordinator to select the next work.
        sa.Column("phase", sa.Text(), nullable=False),
        sa.Column("format_version", sa.Integer(), nullable=False),
        *_json("input_json"),
        sa.Column("status", sa.Text(), nullable=False),
        # Whole-operation outcome, retained for callers and scheduled occurrences.
        *_json("result_json", nullable=True),
        *_json("error_json", nullable=True),
        sa.Column("finished_at", sa.Integer()),
        sa.UniqueConstraint("id", "thread_id", name="uq_job_thread"),
        sa.UniqueConstraint(
            "actor_staff_member_id", "operation", "request_id", name="uq_job_request"
        ),
        sa.UniqueConstraint(
            "source_record_id", "tool_call_id", name="uq_job_tool_call"
        ),
        sa.ForeignKeyConstraint(
            ["actor_staff_member_id", "operation", "request_id"],
            [
                "request_deduplication.actor_staff_member_id",
                "request_deduplication.operation",
                "request_deduplication.request_id",
            ],
            name="fk_job_request",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "thread_id"], ["runs.id", "runs.thread_id"], name="fk_job_run"
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id", "thread_id"],
            ["thread_records.id", "thread_records.thread_id"],
            name="fk_job_source",
        ),
        sa.CheckConstraint(
            "run_id IS NULL OR thread_id IS NOT NULL", name="ck_job_run_thread"
        ),
        sa.CheckConstraint(
            "(source_record_id IS NULL AND tool_call_id IS NULL) OR (source_record_id IS NOT NULL AND tool_call_id IS NOT NULL AND length(tool_call_id) > 0 AND run_id IS NOT NULL)",
            name="ck_job_tool_link",
        ),
        sa.CheckConstraint(
            "length(handler) > 0 AND length(phase) > 0", name="ck_job_handler_phase"
        ),
        sa.CheckConstraint("format_version = 1", name="ck_job_version"),
        _status(
            "JOB_STATUS",
            ("QUEUED", "RUNNING", "WAITING", "SUCCEEDED", "FAILED", "CANCELLED"),
        ),
        sa.CheckConstraint(
            "(status IN ('JOB_STATUS_SUCCEEDED', 'JOB_STATUS_FAILED', 'JOB_STATUS_CANCELLED')) = (finished_at IS NOT NULL)",
            name="ck_job_finished",
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= created_at",
            name="ck_job_finish_time",
        ),
        sqlite_strict=True,
    )
    # Agent-driving work and tool work share this queue and worker pool.
    op.create_table(
        "tasks",
        *_identity("task"),
        *_updated_at(),
        sa.Column(
            "job_id",
            sa.Text(),
            sa.ForeignKey("jobs.id", name="fk_task_job"),
            nullable=False,
        ),
        # Stable name within the job; retries reuse it to avoid duplicate tasks.
        sa.Column("step_key", sa.Text(), nullable=False),
        # Selects the handler that a worker executes for this task.
        sa.Column("handler", sa.Text(), nullable=False),
        sa.Column("format_version", sa.Integer(), nullable=False),
        *_json("input_json"),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.Integer()),
        sa.Column("finished_at", sa.Integer()),
        *_json("result_json", nullable=True),
        *_json("error_json", nullable=True),
        sa.UniqueConstraint("job_id", "step_key", name="uq_task_step"),
        sa.CheckConstraint(
            "length(step_key) > 0 AND length(handler) > 0", name="ck_task_names"
        ),
        sa.CheckConstraint("format_version = 1", name="ck_task_version"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_task_attempts"),
        _status(
            "TASK_STATUS",
            ("READY", "RUNNING", "WAITING", "SUCCEEDED", "FAILED", "CANCELLED"),
        ),
        sa.CheckConstraint(
            "(status IN ('TASK_STATUS_SUCCEEDED', 'TASK_STATUS_FAILED', 'TASK_STATUS_CANCELLED')) = (finished_at IS NOT NULL)",
            name="ck_task_finished",
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR started_at >= created_at", name="ck_task_start"
        ),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= created_at",
            name="ck_task_finish_time",
        ),
        sqlite_strict=True,
    )
    op.create_table(
        "task_claims",
        sa.Column("created_at", sa.Integer(), nullable=False),
        *_updated_at(),
        sa.Column(
            "task_id",
            sa.Text(),
            sa.ForeignKey("tasks.id", name="fk_claim_task"),
            nullable=False,
        ),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("worker_id", sa.Text(), nullable=False),
        sa.Column("claimed_at", sa.Integer(), nullable=False),
        sa.Column("heartbeat_at", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("task_id", name="pk_task_claims"),
        sa.UniqueConstraint("token", name="uq_claim_token"),
        sa.CheckConstraint(
            "length(token) > 0 AND length(worker_id) > 0", name="ck_claim_owner"
        ),
        sa.CheckConstraint(
            # Checks stored time order only. Renewal must also match the current
            # token and require the previous expires_at > now in the same write.
            "claimed_at >= created_at AND heartbeat_at >= claimed_at AND expires_at > heartbeat_at",
            name="ck_claim_times",
        ),
        sqlite_strict=True,
    )
    op.create_table(
        "completion_outbox",
        *_identity("completion"),
        *_updated_at(),
        # Saved with job completion; delivered into thread history afterwards.
        sa.Column("job_id", sa.Text(), nullable=False),
        sa.Column("thread_id", sa.Text(), nullable=False),
        sa.Column("format_version", sa.Integer(), nullable=False),
        *_json("payload_json"),
        sa.Column("record_id", sa.Text()),
        sa.Column("appended_at", sa.Integer()),
        sa.UniqueConstraint("job_id", name="uq_completion_job"),
        sa.UniqueConstraint("record_id", name="uq_completion_record"),
        sa.ForeignKeyConstraint(
            ["job_id", "thread_id"],
            ["jobs.id", "jobs.thread_id"],
            name="fk_completion_job",
        ),
        sa.ForeignKeyConstraint(
            ["record_id", "thread_id"],
            ["thread_records.id", "thread_records.thread_id"],
            name="fk_completion_record",
        ),
        sa.CheckConstraint("format_version = 1", name="ck_completion_version"),
        sa.CheckConstraint(
            "(record_id IS NULL) = (appended_at IS NULL)", name="ck_completion_append"
        ),
        sa.CheckConstraint(
            "appended_at IS NULL OR appended_at >= created_at",
            name="ck_completion_append_time",
        ),
        sqlite_strict=True,
    )


def _create_schedules() -> None:
    """A schedule defines future work; an occurrence records one accepted firing."""
    op.create_table(
        "schedules",
        *_identity("schedule"),
        *_updated_at(),
        sa.Column(
            "actor_staff_member_id",
            sa.Text(),
            sa.ForeignKey("staff_members.id", name="fk_schedule_actor"),
            nullable=False,
        ),
        # This row is updated in place; each edit increments its revision.
        sa.Column("revision", sa.Integer(), nullable=False),
        # SQLite stores booleans as 0/1; enabled controls acceptance of new work.
        sa.Column("enabled", sa.Integer(), nullable=False),
        # A one-off UTC time, mutually exclusive with the recurring cron fields.
        sa.Column("due_at", sa.Integer()),
        # Recurrence rule used by the scheduler to calculate due times in UTC.
        sa.Column("cron_expression", sa.Text()),
        # Names the parser's rules, including field count and weekday interpretation.
        sa.Column("cron_dialect", sa.Text()),
        sa.Column(
            "thread_id",
            sa.Text(),
            sa.ForeignKey("threads.id", name="fk_schedule_thread"),
        ),
        # The scheduler creates work for this handler in the shared job/task queue.
        sa.Column("handler", sa.Text(), nullable=False),
        sa.Column("format_version", sa.Integer(), nullable=False),
        *_json("input_json"),
        sa.CheckConstraint(
            "revision >= 1 AND enabled IN (0, 1)", name="ck_schedule_revision_enabled"
        ),
        sa.CheckConstraint(
            "(due_at IS NOT NULL AND cron_expression IS NULL AND cron_dialect IS NULL) OR (due_at IS NULL AND cron_expression IS NOT NULL AND length(cron_expression) > 0 AND cron_dialect IS NOT NULL AND length(cron_dialect) > 0)",
            name="ck_schedule_timing",
        ),
        sa.CheckConstraint(
            "format_version = 1 AND length(handler) > 0", name="ck_schedule_payload"
        ),
        sqlite_strict=True,
    )
    op.create_table(
        "schedule_occurrences",
        *_identity("occurrence"),
        sa.Column(
            "schedule_id",
            sa.Text(),
            sa.ForeignKey("schedules.id", name="fk_occurrence_schedule"),
            nullable=False,
        ),
        # Revision used at acceptance; it stays unchanged when the schedule is edited.
        sa.Column("schedule_revision", sa.Integer(), nullable=False),
        # Intended firing time; created_at is when we actually accepted the work.
        sa.Column("due_at", sa.Integer(), nullable=False),
        sa.Column("format_version", sa.Integer(), nullable=False),
        # Accepted rule and handler input, preserved with this occurrence.
        *_json("snapshot_json"),
        # Follow this job for status, result, errors and its individual tasks.
        sa.Column(
            "job_id",
            sa.Text(),
            sa.ForeignKey("jobs.id", name="fk_occurrence_job"),
            nullable=False,
        ),
        # Accept each scheduled due time once across schedule revisions.
        sa.UniqueConstraint("schedule_id", "due_at", name="uq_occurrence_due"),
        sa.UniqueConstraint("job_id", name="uq_occurrence_job"),
        sa.CheckConstraint(
            "schedule_revision >= 1 AND format_version = 1",
            name="ck_occurrence_versions",
        ),
        sa.CheckConstraint("created_at >= due_at", name="ck_occurrence_time"),
        sqlite_strict=True,
    )


def _create_notifications() -> None:
    """Save notification intent and durable publications for consumers to process."""
    op.create_table(
        "notification_requests",
        *_identity("notification"),
        *_updated_at(),
        sa.Column(
            "actor_staff_member_id",
            sa.Text(),
            sa.ForeignKey("staff_members.id", name="fk_notification_actor"),
            nullable=False,
        ),
        # Stable identity for this recipient effect, shared by delivery retries.
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column(
            "recipient_staff_member_id",
            sa.Text(),
            sa.ForeignKey("staff_members.id", name="fk_notification_staff"),
        ),
        sa.Column(
            "recipient_guest_id",
            sa.Text(),
            sa.ForeignKey("guests.id", name="fk_notification_guest"),
        ),
        sa.Column("format_version", sa.Integer(), nullable=False),
        *_json("payload_json"),
        sa.Column("published_at", sa.Integer()),
        sa.UniqueConstraint(
            "actor_staff_member_id", "request_id", name="uq_notification_request"
        ),
        sa.CheckConstraint(
            "(recipient_staff_member_id IS NOT NULL) != (recipient_guest_id IS NOT NULL)",
            name="ck_notification_recipient",
        ),
        sa.CheckConstraint(
            "length(request_id) > 0 AND format_version = 1",
            name="ck_notification_request_version",
        ),
        sa.CheckConstraint(
            "published_at IS NULL OR published_at >= created_at",
            name="ck_notification_published",
        ),
        sqlite_strict=True,
    )
    op.create_table(
        "published_events",
        # Use a persistent increasing sequence as the publication cursor.
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("sequence", name="pk_published_events"),
        sa.Column(
            "notification_id",
            sa.Text(),
            sa.ForeignKey("notification_requests.id", name="fk_event_notification"),
            nullable=False,
        ),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("format_version", sa.Integer(), nullable=False),
        *_json("payload_json"),
        sa.UniqueConstraint("notification_id", name="uq_event_notification"),
        sa.CheckConstraint("format_version = 1", name="ck_event_version"),
        sqlite_strict=True,
        sqlite_autoincrement=True,
    )


def _create_rules() -> None:
    """Protect saved history and the links used to resume work safely."""
    for table in (
        "thread_records",
        "inference_request_records",
        "schedule_occurrences",
        "published_events",
    ):
        _append_only(table)

    fixed = {
        "threads": ("id", "created_at", "creator_staff_member_id", "permissions_json"),
        "runs": ("id", "created_at", "thread_id"),
        "task_claims": ("task_id", "created_at"),
        "incoming_thread_records": (
            "id",
            "created_at",
            "thread_id",
            "sequence",
            "kind",
            "actor_staff_member_id",
            "request_id",
            "format_version",
            "payload_json",
        ),
        "inference_requests": (
            "id",
            "created_at",
            "thread_id",
            "run_id",
            "purpose",
            "provider",
            "model",
            "format_version",
            "request_json",
        ),
        "request_deduplication": (
            "actor_staff_member_id",
            "operation",
            "request_id",
            "created_at",
            "request_json",
        ),
        "jobs": (
            "id",
            "created_at",
            "actor_staff_member_id",
            "operation",
            "request_id",
            "thread_id",
            "run_id",
            "source_record_id",
            "tool_call_id",
            "handler",
            "format_version",
            "input_json",
        ),
        "tasks": (
            "id",
            "created_at",
            "job_id",
            "step_key",
            "handler",
            "format_version",
            "input_json",
        ),
        "completion_outbox": (
            "id",
            "created_at",
            "job_id",
            "thread_id",
            "format_version",
            "payload_json",
        ),
        "schedules": ("id", "created_at", "actor_staff_member_id"),
        "notification_requests": (
            "id",
            "created_at",
            "actor_staff_member_id",
            "request_id",
            "recipient_staff_member_id",
            "recipient_guest_id",
            "format_version",
            "payload_json",
        ),
    }
    for table, columns in fixed.items():
        _fixed(table, columns)

    # Thread history: append in order and retain the source of each result.
    for table in ("thread_records", "incoming_thread_records"):
        _trigger(
            f"{table}_next_sequence",
            "INSERT",
            table,
            f"""
            -- Append at the next position in this thread.
            SELECT CASE
                WHEN NEW.sequence != (
                    SELECT coalesce(max(sequence), 0) + 1
                    FROM {table}
                    WHERE thread_id = NEW.thread_id
                )
                THEN RAISE(ABORT, 'Append the next sequence for this thread')
            END;
            """,
        )

    _trigger(
        "thread_records_check_source",
        "INSERT",
        "thread_records",
        """
        -- Start each history with exactly one thread-created record.
        SELECT CASE
            WHEN (NEW.sequence = 1) != (NEW.kind = 'THREAD_RECORD_KIND_THREAD_CREATED')
            THEN RAISE(ABORT, 'Start the history with one thread-created record')
        END;

        -- Link sources to earlier records in the same thread.
        SELECT CASE
            WHEN NEW.source_record_id IS NOT NULL AND NOT EXISTS (
                SELECT 1
                FROM thread_records
                WHERE id = NEW.source_record_id
                  AND thread_id = NEW.thread_id
                  AND sequence < NEW.sequence
            )
            THEN RAISE(ABORT, 'The source must be an earlier record in this thread')
        END;

        -- Tool results answer assistant or classifier calls from the same run.
        SELECT CASE
            WHEN NEW.kind = 'THREAD_RECORD_KIND_TOOL_RESULT' AND NOT EXISTS (
                SELECT 1
                FROM thread_records
                WHERE id = NEW.source_record_id
                  AND kind IN (
                      'THREAD_RECORD_KIND_ASSISTANT_MESSAGE',
                      'THREAD_RECORD_KIND_CLASSIFIER_DECISION'
                  )
                  AND run_id IS NOT NULL
                  AND run_id IS NEW.run_id
            )
            THEN RAISE(ABORT, 'A tool result must answer a call from the same run')
        END;
        """,
    )

    # Inference: freeze the selected input at dispatch and preserve known outcomes.
    _trigger(
        "inference_records_prepared_only",
        "INSERT",
        "inference_request_records",
        """
        -- Select the context while the inference request is being prepared.
        SELECT CASE
            WHEN NOT EXISTS (
                SELECT 1
                FROM inference_requests
                WHERE id = NEW.inference_request_id
                  AND status = 'INFERENCE_STATUS_PREPARED'
            )
            THEN RAISE(ABORT, 'Save the context before sending the request')
        END;
        """,
    )
    _trigger(
        "inference_keep_dispatch",
        "UPDATE",
        "inference_requests",
        "SELECT RAISE(ABORT, 'A dispatched request cannot become unsent');",
        "OLD.started_at IS NOT NULL AND NEW.started_at IS NOT OLD.started_at",
    )
    _trigger(
        "inference_keep_outcome",
        "UPDATE",
        "inference_requests",
        "SELECT RAISE(ABORT, 'A known inference outcome cannot be replaced');",
        "OLD.status IN ('INFERENCE_STATUS_SUCCEEDED', 'INFERENCE_STATUS_FAILED')",
    )

    # Finished work keeps its outcome, including when a late result arrives.
    for table, terminal in {
        "runs": "'RUN_STATUS_COMPLETED', 'RUN_STATUS_FAILED', 'RUN_STATUS_CANCELLED'",
        "jobs": "'JOB_STATUS_SUCCEEDED', 'JOB_STATUS_FAILED', 'JOB_STATUS_CANCELLED'",
        "tasks": "'TASK_STATUS_SUCCEEDED', 'TASK_STATUS_FAILED', 'TASK_STATUS_CANCELLED'",
    }.items():
        _trigger(
            f"{table}_keep_finished",
            "UPDATE",
            table,
            "SELECT RAISE(ABORT, 'Finished work cannot be changed');",
            f"OLD.status IN ({terminal})",
        )

    # Delivery: retain the accepted mode and the receipt for each completed handoff.
    _trigger(
        "incoming_keep_delivery",
        "UPDATE",
        "incoming_thread_records",
        "SELECT RAISE(ABORT, 'Delivered input cannot change delivery mode');",
        """
        OLD.record_id IS NOT NULL AND (
            NEW.delivery_mode IS NOT OLD.delivery_mode
            OR NEW.target_run_id IS NOT OLD.target_run_id
        )
        """,
    )
    for table, marker, companions in (
        ("incoming_thread_records", "record_id", ("appended_at",)),
        ("completion_outbox", "record_id", ("appended_at",)),
        ("request_deduplication", "response_json", ()),
        ("notification_requests", "published_at", ()),
    ):
        changed = " OR ".join(
            f"NEW.{field} IS NOT OLD.{field}" for field in (marker, *companions)
        )
        _trigger(
            f"{table}_keep_receipt",
            "UPDATE",
            table,
            "SELECT RAISE(ABORT, 'A saved receipt cannot be replaced');",
            f"OLD.{marker} IS NOT NULL AND ({changed})",
        )

    _trigger(
        "jobs_check_tool_source",
        "INSERT",
        "jobs",
        """
        -- Keep each tool job attached to the record and run that requested it.
        SELECT CASE
            WHEN NEW.source_record_id IS NOT NULL AND NOT EXISTS (
                SELECT 1
                FROM thread_records
                WHERE id = NEW.source_record_id
                  AND kind IN (
                      'THREAD_RECORD_KIND_ASSISTANT_MESSAGE',
                      'THREAD_RECORD_KIND_CLASSIFIER_DECISION'
                  )
                  AND run_id IS NEW.run_id
            )
            THEN RAISE(ABORT, 'A tool job must refer to the run that requested it')
        END;
        """,
    )

    for event in ("INSERT", "UPDATE"):
        _trigger(
            f"incoming_check_record_{event.lower()}",
            event,
            "incoming_thread_records",
            """
            -- A delivered input links to a conversational or control record.
            SELECT CASE
                WHEN NEW.record_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1
                    FROM thread_records
                    WHERE id = NEW.record_id
                      AND kind IN (
                          'THREAD_RECORD_KIND_USER_MESSAGE',
                          'THREAD_RECORD_KIND_CONTROL_EVENT'
                      )
                )
                THEN RAISE(ABORT, 'The incoming record must point to its accepted input record')
            END;
            """,
        )
        _trigger(
            f"completion_check_job_{event.lower()}",
            event,
            "completion_outbox",
            """
            -- Save completion delivery after the job reaches a terminal outcome.
            SELECT CASE
                WHEN NOT EXISTS (
                    SELECT 1
                    FROM jobs
                    WHERE id = NEW.job_id
                      AND finished_at IS NOT NULL
                )
                THEN RAISE(ABORT, 'Finish the job before saving its completion')
            END;

            -- Link the receipt to this job's run and matching result record.
            SELECT CASE
                WHEN NEW.record_id IS NOT NULL AND NOT EXISTS (
                    SELECT 1
                    FROM thread_records r
                    JOIN jobs j ON j.id = NEW.job_id
                    WHERE r.id = NEW.record_id
                      AND r.run_id IS j.run_id
                      AND (
                          -- Tool jobs answer their specific source call.
                          (j.tool_call_id IS NOT NULL
                              AND r.kind = 'THREAD_RECORD_KIND_TOOL_RESULT'
                              AND r.source_record_id = j.source_record_id
                              AND r.tool_call_id = j.tool_call_id)
                          OR
                          -- Other jobs deliver their outcome as a control event.
                          (j.tool_call_id IS NULL
                              AND r.kind = 'THREAD_RECORD_KIND_CONTROL_EVENT')
                      )
                )
                THEN RAISE(ABORT, 'The completion must point to this job result')
            END;
            """,
        )
        _trigger(
            f"notification_check_event_{event.lower()}",
            event,
            "notification_requests",
            """
            -- A publication receipt points to the event saved at that time.
            SELECT CASE
                WHEN NEW.published_at IS NOT NULL AND NOT EXISTS (
                    SELECT 1
                    FROM published_events
                    WHERE notification_id = NEW.id
                      AND created_at = NEW.published_at
                )
                THEN RAISE(ABORT, 'Save the published event before marking publication')
            END;
            """,
        )

    # Schedules: track edits and accept occurrences against the current rule.
    _trigger(
        "schedule_next_revision",
        "UPDATE",
        "schedules",
        """
        -- Each edit advances the schedule by one revision.
        SELECT CASE
            WHEN NEW.revision != OLD.revision + 1
            THEN RAISE(ABORT, 'A schedule edit needs the next revision')
        END;
        """,
    )
    _trigger(
        "occurrence_current_schedule",
        "INSERT",
        "schedule_occurrences",
        """
        -- Accept work from the enabled revision checked by the scheduler.
        SELECT CASE
            WHEN NOT EXISTS (
                SELECT 1
                FROM schedules
                WHERE id = NEW.schedule_id
                  AND enabled = 1
                  AND revision = NEW.schedule_revision
                  AND (due_at IS NULL OR due_at = NEW.due_at)
            )
            THEN RAISE(ABORT, 'Accept work from the current enabled schedule')
        END;
        """,
    )


def downgrade() -> None:
    """Remove runtime tables, leaving the domain migration in place."""
    # Cross-table triggers must go before their referenced tables disappear.
    for event in ("insert", "update"):
        for name in (
            "incoming_check_record",
            "completion_check_job",
            "notification_check_event",
        ):
            op.execute(f"DROP TRIGGER {name}_{event}")
    for table in (
        "published_events",
        "schedule_occurrences",
        "inference_request_records",
        "thread_records",
    ):
        op.execute(f"DROP TRIGGER {table}_no_delete")
    for table in (
        "published_events",
        "notification_requests",
        "schedule_occurrences",
        "schedules",
        "completion_outbox",
        "task_claims",
        "tasks",
        "jobs",
        "request_deduplication",
        "inference_request_records",
        "inference_requests",
        "incoming_thread_records",
        "thread_records",
        "runs",
        "threads",
    ):
        op.drop_table(table)
