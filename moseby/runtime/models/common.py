from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from moseby.json_types import JsonObject

# A handler validates the specific argument or result schema for its operation.
type ToolCallId = Annotated[str, Field(min_length=1)]


class RuntimeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ErrorDetails(RuntimeModel):
    code: str = Field(min_length=1, description="Machine-readable error category.")
    message: str = Field(min_length=1)
    details: JsonObject | None = None
