"""Core query metadata. Handwritten migrations own schema creation and constraints."""

from sqlalchemy import JSON, Boolean, Column, Integer, MetaData, Table, Text

metadata = MetaData()

hotels = Table(
    "hotels",
    metadata,
    Column("id", Text),
    Column("created_at", Integer),
    Column("updated_at", Integer),
    Column("name", Text),
    Column("address_line_1", Text),
    Column("address_line_2", Text),
    Column("city", Text),
    Column("postcode", Text),
    Column("country_code", Text),
)
staff_members = Table(
    "staff_members",
    metadata,
    Column("id", Text),
    Column("created_at", Integer),
    Column("updated_at", Integer),
    Column("hotel_id", Text),
    Column("staff_code", Text),
    Column("first_name", Text),
    Column("last_name", Text),
    Column("title", Text),
    Column("role", Text),
)
rooms = Table(
    "rooms",
    metadata,
    Column("id", Text),
    Column("created_at", Integer),
    Column("updated_at", Integer),
    Column("hotel_id", Text),
    Column("label", Text),
    Column("description", Text),
    Column("tier", Text),
    Column("number_of_bathrooms", Integer),
    Column("in_service", Boolean),
    Column("price_id", Text),
)
beds = Table(
    "beds",
    metadata,
    Column("id", Text),
    Column("created_at", Integer),
    Column("updated_at", Integer),
    Column("room_id", Text),
    Column("type", Text),
)
prices = Table(
    "prices",
    metadata,
    Column("id", Text),
    Column("created_at", Integer),
)
venues = Table(
    "venues",
    metadata,
    Column("id", Text),
    Column("created_at", Integer),
    Column("updated_at", Integer),
    Column("name", Text),
    Column("capacity", Integer),
    Column("address_line_1", Text),
    Column("address_line_2", Text),
    Column("city", Text),
    Column("postcode", Text),
    Column("country_code", Text),
)
activity_types = Table(
    "activity_types",
    metadata,
    Column("code", Text),
    Column("name", Text),
    Column("created_at", Integer),
    Column("updated_at", Integer),
)
party_details = Table(
    "party_details",
    metadata,
    Column("id", Text),
    Column("created_at", Integer),
    Column("updated_at", Integer),
    Column("party_id", Text),
    Column("text", Text),
    Column("referenced_guest_ids_json", JSON),
    Column("reference_format_version", Integer),
    Column("reference_status", Text),
)

party_details_fts = Table(
    "party_details_fts",
    metadata,
    Column("detail_id", Text),
    Column("text", Text),
)

bookings = Table(
    "bookings",
    metadata,
    Column("id", Text),
    Column("hotel_id", Text),
    Column("name", Text),
    Column("created_at", Integer),
    Column("updated_at", Integer),
)
booking_revisions = Table(
    "booking_revisions",
    metadata,
    Column("booking_id", Text),
    Column("revision", Integer),
    Column("status", Text),
    Column("cancellation_reason", Text),
    Column("created_at", Integer),
)
parties = Table(
    "parties",
    metadata,
    Column("id", Text),
    Column("booking_id", Text),
    Column("created_at", Integer),
)
guests = Table(
    "guests",
    metadata,
    Column("id", Text),
    Column("party_id", Text),
    Column("first_name", Text),
    Column("last_name", Text),
    Column("preferred_name", Text),
    Column("age", Integer),
    Column("dietary_requirements", Text),
    Column("phone", Text),
    Column("email", Text),
    Column("contact_preference", Text),
    Column("created_at", Integer),
    Column("updated_at", Integer),
)
room_reservations = Table(
    "room_reservations",
    metadata,
    Column("id", Text),
    Column("booking_id", Text),
    Column("room_id", Text),
    Column("created_at", Integer),
)
room_reservation_revisions = Table(
    "room_reservation_revisions",
    metadata,
    Column("room_reservation_id", Text),
    Column("revision", Integer),
    Column("min_date", Integer),
    Column("max_date", Integer),
    Column("cancelled", Boolean),
    Column("cancellation_reason", Text),
    Column("price_id", Text),
    Column("price_revision", Integer),
    Column("created_at", Integer),
)
price_versions = Table(
    "price_versions",
    metadata,
    Column("price_id", Text),
    Column("revision", Integer),
    Column("amount_minor", Integer),
    Column("currency", Text),
    Column("created_at", Integer),
)
room_keys = Table(
    "room_keys",
    metadata,
    Column("id", Text),
    Column("room_reservation_id", Text),
    Column("code", Text),
    Column("deactivated_at", Integer),
    Column("deactivation_reason", Text),
    Column("created_at", Integer),
    Column("updated_at", Integer),
)
activities = Table(
    "activities",
    metadata,
    Column("id", Text),
    Column("created_at", Integer),
    Column("updated_at", Integer),
    Column("venue_id", Text),
    Column("title", Text),
    Column("type", Text),
    Column("description", Text),
    Column("min_date", Integer),
    Column("max_date", Integer),
    Column("capacity", Integer),
    Column("min_booking_size", Integer),
    Column("max_booking_size", Integer),
    Column("minimum_age", Integer),
    Column("price_id", Text),
    Column("price_unit", Text),
)
activity_reservations = Table(
    "activity_reservations",
    metadata,
    Column("id", Text),
    Column("created_at", Integer),
    Column("party_id", Text),
    Column("guest_id", Text),
    Column("activity_id", Text),
)
activity_reservation_revisions = Table(
    "activity_reservation_revisions",
    metadata,
    Column("activity_reservation_id", Text),
    Column("revision", Integer),
    Column("cancelled", Boolean),
    Column("cancellation_reason", Text),
    Column("price_id", Text),
    Column("price_revision", Integer),
    Column("price_unit", Text),
    Column("created_at", Integer),
)

threads = Table(
    "threads",
    metadata,
    Column("id", Text),
    Column("created_at", Integer),
    Column("updated_at", Integer),
    Column("creator_staff_member_id", Text),
    Column("permissions_json", JSON),
    Column("title", Text),
    Column("archived_at", Integer),
    Column("projection_sequence", Integer),
    Column("projection_format_version", Integer),
    Column("projection_json", JSON),
)

runs = Table(
    "runs",
    metadata,
    Column("id", Text),
    Column("created_at", Integer),
    Column("updated_at", Integer),
    Column("thread_id", Text),
    Column("status", Text),
    Column("wake_at", Integer),
    Column("cancel_requested_at", Integer),
    Column("cancel_requested_by_staff_member_id", Text),
    Column("recovery_attempts", Integer),
    Column("finished_at", Integer),
)

thread_records = Table(
    "thread_records",
    metadata,
    Column("id", Text),
    Column("created_at", Integer),
    Column("thread_id", Text),
    Column("sequence", Integer),
    Column("kind", Text),
    Column("format_version", Integer),
    Column("run_id", Text),
    Column("actor_staff_member_id", Text),
    Column("source_record_id", Text),
    Column("tool_call_id", Text),
    Column("payload_json", JSON),
)

incoming_thread_records = Table(
    "incoming_thread_records",
    metadata,
    Column("id", Text),
    Column("created_at", Integer),
    Column("updated_at", Integer),
    Column("thread_id", Text),
    Column("sequence", Integer),
    Column("kind", Text),
    Column("delivery_mode", Text),
    Column("target_run_id", Text),
    Column("actor_staff_member_id", Text),
    Column("request_id", Text),
    Column("format_version", Integer),
    Column("payload_json", JSON),
    Column("record_id", Text),
    Column("appended_at", Integer),
    Column("cancelled_at", Integer),
    Column("cancelled_by_staff_member_id", Text),
)

request_deduplication = Table(
    "request_deduplication",
    metadata,
    Column("actor_staff_member_id", Text),
    Column("operation", Text),
    Column("request_id", Text),
    Column("created_at", Integer),
    Column("updated_at", Integer),
    Column("request_json", JSON),
    Column("response_json", JSON),
)

jobs = Table(
    "jobs",
    metadata,
    Column("id", Text),
    Column("created_at", Integer),
    Column("updated_at", Integer),
    Column("actor_staff_member_id", Text),
    Column("operation", Text),
    Column("request_id", Text),
    Column("thread_id", Text),
    Column("run_id", Text),
    Column("source_record_id", Text),
    Column("tool_call_id", Text),
    Column("handler", Text),
    Column("phase", Text),
    Column("format_version", Integer),
    Column("input_json", JSON),
    Column("status", Text),
    Column("result_json", JSON),
    Column("error_json", JSON),
    Column("finished_at", Integer),
)

tasks = Table(
    "tasks",
    metadata,
    Column("id", Text),
    Column("created_at", Integer),
    Column("updated_at", Integer),
    Column("job_id", Text),
    Column("step_key", Text),
    Column("handler", Text),
    Column("format_version", Integer),
    Column("input_json", JSON),
    Column("status", Text),
    Column("attempt_count", Integer),
    Column("available_at", Integer),
    Column("started_at", Integer),
    Column("finished_at", Integer),
    Column("result_json", JSON),
    Column("error_json", JSON),
)

task_claims = Table(
    "task_claims",
    metadata,
    Column("created_at", Integer),
    Column("updated_at", Integer),
    Column("task_id", Text),
    Column("token", Text),
    Column("worker_id", Text),
    Column("claimed_at", Integer),
    Column("heartbeat_at", Integer),
    Column("expires_at", Integer),
)

completion_outbox = Table(
    "completion_outbox",
    metadata,
    Column("id", Text),
    Column("created_at", Integer),
    Column("updated_at", Integer),
    Column("job_id", Text),
    Column("thread_id", Text),
    Column("format_version", Integer),
    Column("payload_json", JSON),
    Column("record_id", Text),
    Column("appended_at", Integer),
)


schedules = Table(
    "schedules",
    metadata,
    Column("id", Text),
    Column("created_at", Integer),
    Column("updated_at", Integer),
    Column("actor_staff_member_id", Text),
    Column("revision", Integer),
    Column("enabled", Boolean),
    Column("due_at", Integer),
    Column("cron_expression", Text),
    Column("cron_dialect", Text),
    Column("thread_id", Text),
    Column("handler", Text),
    Column("format_version", Integer),
    Column("input_json", JSON),
)


schedule_occurrences = Table(
    "schedule_occurrences",
    metadata,
    Column("id", Text),
    Column("created_at", Integer),
    Column("schedule_id", Text),
    Column("schedule_revision", Integer),
    Column("due_at", Integer),
    Column("format_version", Integer),
    Column("snapshot_json", JSON),
    Column("job_id", Text),
)


notification_requests = Table(
    "notification_requests",
    metadata,
    Column("id", Text),
    Column("created_at", Integer),
    Column("updated_at", Integer),
    Column("actor_staff_member_id", Text),
    Column("request_id", Text),
    Column("recipient_staff_member_id", Text),
    Column("recipient_guest_id", Text),
    Column("format_version", Integer),
    Column("payload_json", JSON),
    Column("published_at", Integer),
)


published_events = Table(
    "published_events",
    metadata,
    Column("sequence", Integer),
    Column("notification_id", Text),
    Column("created_at", Integer),
    Column("format_version", Integer),
    Column("payload_json", JSON),
)
