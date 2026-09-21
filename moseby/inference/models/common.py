from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from moseby.common.types import JsonObject

type Probability = Annotated[float, Field(ge=0, le=1)]


class InferenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class InferenceResult[Output](InferenceModel):
    output: Output
    request: JsonObject = Field(description="JSON body sent to the inference provider.")
    response: JsonObject = Field(
        description="Original response, including provider identity and token usage."
    )
