"""Contact rules shared by API and database input models."""

from .enums import ContactPreference


def validate_contact_preference(
    preference: ContactPreference | None, *, phone: str | None, email: str | None
) -> None:
    """Require contact details for the chosen channel; None permits any supplied channel."""
    match preference:
        case None:
            return
        case ContactPreference.PHONE:
            contact = phone
        case ContactPreference.EMAIL:
            contact = email
        case _:
            raise ValueError("Unsupported contact preference")
    if not contact:
        raise ValueError("contact_preference requires the selected contact")
