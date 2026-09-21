from typing import Annotated

from pydantic import AfterValidator, Field, JsonValue

type NonemptyText = Annotated[str, Field(min_length=1)]
type JsonObject = dict[str, JsonValue]


def sorted_choices[T: str](values: list[T]) -> list[T]:
    """Give equivalent selections the same order, ignoring repeated choices."""
    return sorted(set(values))


type EnumChoices[T] = Annotated[
    list[T], Field(min_length=1), AfterValidator(sorted_choices)
]
