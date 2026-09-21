from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, JsonValue

from moseby.common.types import NonemptyText

from .common import InferenceModel, JsonObject, Probability


class ClassificationKind(StrEnum):
    BOOLEAN = "CLASSIFICATION_KIND_BOOLEAN"
    CHOICE = "CLASSIFICATION_KIND_CHOICE"


class BooleanQuestion(InferenceModel):
    """Ask for the probability that a statement is true."""

    kind: Literal[ClassificationKind.BOOLEAN] = ClassificationKind.BOOLEAN
    instructions: NonemptyText
    criteria: dict[Literal["true", "false"], NonemptyText] = Field(
        min_length=2, max_length=2
    )


class ChoiceQuestion(InferenceModel):
    """Ask the classifier to choose one of the supplied labels."""

    kind: Literal[ClassificationKind.CHOICE] = ClassificationKind.CHOICE
    instructions: NonemptyText
    criteria: dict[NonemptyText, NonemptyText] = Field(min_length=2, max_length=255)


type ClassificationQuestion = Annotated[
    BooleanQuestion | ChoiceQuestion, Field(discriminator="kind")
]


class ClassificationRequest(InferenceModel):
    state: str | JsonObject | list[JsonValue] = Field(
        description="Evidence and candidate data for the questions."
    )
    questions: dict[NonemptyText, ClassificationQuestion] = Field(min_length=1)


class BooleanAnswer(InferenceModel):
    kind: Literal[ClassificationKind.BOOLEAN]
    probability: Probability = Field(description="Probability that the answer is true.")


class ChoiceAnswer(InferenceModel):
    kind: Literal[ClassificationKind.CHOICE]
    choice: NonemptyText
    confidence: Probability
    probabilities: dict[NonemptyText, Probability]


type ClassificationAnswer = Annotated[
    BooleanAnswer | ChoiceAnswer, Field(discriminator="kind")
]


class ClassificationOutput(InferenceModel):
    answers: dict[NonemptyText, ClassificationAnswer]

    def check_questions(self, request: ClassificationRequest) -> None:
        """Each answer must match a question and use only that question's choices."""
        if self.answers.keys() != request.questions.keys():
            raise ValueError(
                "classification answers must match the requested questions"
            )
        for name, answer in self.answers.items():
            question = request.questions[name]
            if answer.kind != question.kind:
                raise ValueError(
                    "classification answer type does not match the question"
                )
            if isinstance(answer, ChoiceAnswer):
                if answer.choice not in question.criteria:
                    raise ValueError("classification answer contains an unknown choice")
                if answer.probabilities.keys() != question.criteria.keys():
                    raise ValueError(
                        "classification probabilities must cover the choices"
                    )
