"""Permission grammar, ancestor matching and metadata use the same rules."""

import unittest

from pydantic import ValidationError

from moseby.contracts.route_metadata import access
from moseby.permissions import Permission, PermissionAction, PermissionResolver
from moseby.runtime.models.thread_records import ThreadCreatedPayload


class PermissionTests(unittest.TestCase):
    def test_constructor_validates_canonical_names(self):
        for name in (
            "moseby:read",
            "moseby:write",
            "moseby:execute",
            "moseby.rooms.configuration:write",
            "moseby.staff-members:read",
        ):
            with self.subTest(name=name):
                permission = Permission(name)
                self.assertEqual(permission.model_dump(), name)
                self.assertEqual(
                    Permission.model_validate_json(permission.model_dump_json()),
                    permission,
                )
        for name in (
            "",
            "mosby:read",
            "other:read",
            "Moseby:read",
            "moseby:READ",
            "moseby:delete",
            "moseby:read:write",
            "moseby.rooms",
            "moseby.:read",
            "moseby..rooms:read",
            "moseby/rooms:read",
            "moseby.rooms.*:read",
            "moseby.room_keys:read",
            "moseby.-rooms:read",
            "moseby.rooms-:read",
            "moseby.1room:read",
            " moseby:read",
            "moseby:read ",
            "moseby:read\n",
            "moseby: read",
            "moseby.röoms:read",
            b"moseby:read",
            1,
            None,
        ):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                Permission(name)

    def test_validated_permission_is_frozen_and_destructures(self):
        permission = Permission("moseby.rooms.configuration:write")
        self.assertEqual(permission.path, ("moseby", "rooms", "configuration"))
        self.assertEqual(permission.action, PermissionAction.WRITE)
        with self.assertRaises(ValidationError):
            permission.root = "moseby:read"

    def test_matching_is_directional_and_uses_complete_segments(self):
        required = Permission("moseby.a.b.c:read")
        for name in (
            "moseby.a.b.c:read",
            "moseby.a.b:read",
            "moseby.a:read",
            "moseby:read",
        ):
            self.assertTrue(PermissionResolver.matches(Permission(name), required))
        for name in (
            "moseby.a.c:read",
            "moseby.a.b.c.d:read",
            "moseby.a.b.c:write",
            "moseby.a.b.c:execute",
            "moseby.a.bc:read",
            "moseby.ab:read",
        ):
            self.assertFalse(PermissionResolver.matches(Permission(name), required))
        self.assertFalse(
            PermissionResolver.matches(
                Permission("moseby.room:read"), Permission("moseby.rooms:read")
            )
        )
        self.assertTrue(
            PermissionResolver.matches(
                Permission("moseby:execute"), Permission("moseby.jobs:execute")
            )
        )
        self.assertFalse(PermissionResolver.allows([], required))
        self.assertTrue(
            PermissionResolver.allows(
                [Permission("moseby:write"), Permission("moseby.a:read")], required
            )
        )

    def test_metadata_resolves_every_ancestor(self):
        required = Permission("moseby.rooms.configuration:write")
        expected = [
            "moseby.rooms.configuration:write",
            "moseby.rooms:write",
            "moseby:write",
        ]
        grants = PermissionResolver.covering_grants(required)
        self.assertEqual([grant.root for grant in grants], expected)
        self.assertTrue(
            all(PermissionResolver.matches(grant, required) for grant in grants)
        )
        self.assertEqual(access(required)["x-permissions"]["anyOf"], expected)
        self.assertEqual(
            access("moseby:read")["x-permissions"]["anyOf"], ["moseby:read"]
        )
        with self.assertRaisesRegex(ValueError, "Unknown permission"):
            access("moseby.unregistered:read")
        with self.assertRaises(ValidationError):
            access("moseby..rooms:read")

    def test_thread_snapshots_validate_and_keep_the_string_storage_format(self):
        payload = dict(
            creator_staff_member_id="staff_member_" + "0" * 26,
            permissions=["moseby.guests:read"],
        )
        parsed = ThreadCreatedPayload.model_validate(payload)
        self.assertEqual(parsed.model_dump()["permissions"], ["moseby.guests:read"])
        self.assertIsInstance(parsed.permissions[0], Permission)
        for names in (["other:read"], ["moseby:read", "moseby:read"]):
            with self.assertRaises(ValidationError):
                ThreadCreatedPayload.model_validate(payload | {"permissions": names})

    def test_narrow_profile_does_not_inherit_room_configuration(self):
        configuration = Permission("moseby.rooms.configuration:write")
        grants = [Permission("moseby.rooms:read"), Permission("moseby.bookings:write")]
        self.assertFalse(PermissionResolver.allows(grants, configuration))
        self.assertTrue(
            PermissionResolver.allows(
                [*grants, Permission("moseby:write")], configuration
            )
        )
