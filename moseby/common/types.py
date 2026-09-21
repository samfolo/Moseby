from typing import Annotated

from pydantic import Field, JsonValue

type NonemptyText = Annotated[str, Field(min_length=1)]
type JsonObject = dict[str, JsonValue]
