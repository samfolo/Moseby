from .activities import ActivityTypeCode
from .common import Row


class ActivityTypeRow(Row):
    code: ActivityTypeCode
    name: str
    created_at: int
    updated_at: int
