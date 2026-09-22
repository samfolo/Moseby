"""Check how classifier probabilities become guest references."""

import unittest

from moseby.domain.enums import GuestReferenceStatus
from moseby.inference.guest_references import (
    AMBIGUITY_QUESTION,
    GuestCandidate,
    prepare_request,
    resolve,
)
from moseby.inference.models.classification import (
    BooleanAnswer,
    ClassificationKind,
    ClassificationOutput,
)


class GuestReferencePolicyTests(unittest.TestCase):
    def setUp(self):
        self.guests = [
            GuestCandidate(
                id=f"guest_{number:026d}",
                first_name="Dan",
                last_name=name,
                preferred_name=None,
                age=30,
            )
            for number, name in ((1, "Morgan"), (2, "Patel"))
        ]
        self.request = prepare_request("Both Dans would like tea.", self.guests)

    def answers(self, **probabilities):
        return ClassificationOutput(
            answers={
                name: BooleanAnswer(kind=ClassificationKind.BOOLEAN, probability=value)
                for name, value in probabilities.items()
            }
        )

    def test_multiple_guests_can_match_and_thresholds_are_inclusive(self):
        """A clear group reference can identify both guests; boundary scores follow the policy."""
        output = self.answers(
            **{AMBIGUITY_QUESTION: 0.2, self.guests[0].id: 0.7, self.guests[1].id: 0.99}
        )
        self.assertEqual(
            resolve(self.request, output).guest_ids, [guest.id for guest in self.guests]
        )
        output.answers[self.guests[1].id] = BooleanAnswer(
            kind=ClassificationKind.BOOLEAN, probability=0.2
        )
        self.assertEqual(resolve(self.request, output).guest_ids, [self.guests[0].id])

    def test_ambiguity_preserves_clear_individual_matches(self):
        """A clear guest match is retained even when another reference is uncertain."""
        for ambiguity, second_guest in ((0.95, 0.01), (0.01, 0.5), (0.95, 0.5)):
            with self.subTest(ambiguity=ambiguity, second_guest=second_guest):
                output = self.answers(
                    **{
                        AMBIGUITY_QUESTION: ambiguity,
                        self.guests[0].id: 0.99,
                        self.guests[1].id: second_guest,
                    }
                )
                result = resolve(self.request, output)
                self.assertEqual(result.status, GuestReferenceStatus.AMBIGUOUS)
                self.assertEqual(result.guest_ids, [self.guests[0].id])

    def test_transcript_scores_resolve_patel_but_leave_morgan_uncertain(self):
        """The provisional thresholds accept the clear Patel score without forcing a weak Morgan match."""
        for probabilities, status, ids in (
            ((0.09, 0.04, 0.8), GuestReferenceStatus.RESOLVED, [self.guests[1].id]),
            ((0.31, 0.42, 0.04), GuestReferenceStatus.AMBIGUOUS, []),
        ):
            output = self.answers(
                **dict(
                    zip(
                        (AMBIGUITY_QUESTION, self.guests[0].id, self.guests[1].id),
                        probabilities,
                        strict=True,
                    )
                )
            )
            decision = resolve(self.request, output)
            self.assertEqual(decision.status, status)
            self.assertEqual(decision.guest_ids, ids)

    def test_unrequested_ids_and_oversized_input_are_rejected(self):
        """An invented answer cannot become a reference, and oversized notes cannot be dispatched."""
        output = self.answers(
            **{
                AMBIGUITY_QUESTION: 0.01,
                self.guests[0].id: 0.99,
                "guest_00000000000000000000000003": 0.99,
            }
        )
        with self.assertRaises(ValueError):
            resolve(self.request, output)
        with self.assertRaises(ValueError):
            prepare_request("a" * 24_000, self.guests)
