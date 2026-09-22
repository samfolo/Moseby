"""Guest contact choices follow the same rules at both input boundaries."""

import unittest

from pydantic import ValidationError

from moseby.contracts.guests import GuestDetails
from moseby.db.models.guests import GuestValues
from moseby.domain.enums import ContactPreference


class GuestContactTests(unittest.TestCase):
    def test_every_contact_preference_is_supported_by_both_models(self):
        """A new enum choice must have a validation rule before either model accepts it."""
        for model in (GuestDetails, GuestValues):
            for preference in ContactPreference:
                with self.subTest(model=model.__name__, preference=preference):
                    model(
                        first_name="Sam",
                        last_name="Guest",
                        age=30,
                        phone="123",
                        email="sam@example.test",
                        contact_preference=preference,
                    )

    def test_selected_channel_requires_its_own_contact_details(self):
        """Having an email cannot satisfy a phone preference, and vice versa."""
        for model in (GuestDetails, GuestValues):
            for preference, contacts in (
                (ContactPreference.PHONE, {"email": "sam@example.test"}),
                (ContactPreference.EMAIL, {"phone": "123"}),
            ):
                with self.subTest(model=model.__name__, preference=preference):
                    with self.assertRaises(ValidationError):
                        model(
                            first_name="Sam",
                            last_name="Guest",
                            age=30,
                            contact_preference=preference,
                            **contacts,
                        )
            model(first_name="Sam", last_name="Guest", age=30, contact_preference=None)
