"""Check the draft schema using Python's standard library only."""

from pathlib import Path
import sqlite3
import unittest


SCHEMA = Path(__file__).resolve().parents[1] / "schema" / "draft.sql"


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.executescript(SCHEMA.read_text())
        self.db.execute("INSERT INTO guests VALUES ('guest-1', 'Amara', 'Cole', 35)")
        self.db.execute(
            "INSERT INTO bookings (id, party_name, created_at, primary_guest_id) "
            "VALUES ('booking-1', 'Cole party', 100, 'guest-1')"
        )
        self.db.execute(
            "INSERT INTO rooms VALUES ('room-1', '012', 'Garden room', 2, 1, 'twin')"
        )

    def reserve(self, revision=1, checkout=300, status="active", **changes):
        values = {
            "id": "reservation-1",
            "revision": revision,
            "booking": "booking-1",
            "room": "room-1",
            "checkin": 200,
            "checkout": checkout,
            "status": status,
        }
        values.update(changes)
        self.db.execute(
            "INSERT INTO room_reservations "
            "(id, revision, booking_id, room_id, check_in_at, check_out_at, status) "
            "VALUES (:id, :revision, :booking, :room, :checkin, :checkout, :status)",
            values,
        )

    def test_room_categories_and_counts(self):
        for category in ("twin", "master", "presidential"):
            self.db.execute("UPDATE rooms SET category = ?", (category,))
        for column, value in (
            ("category", "gold"),
            ("number_of_beds", -1),
            ("number_of_bathrooms", -1),
            ("number_of_beds", 1.5),
        ):
            with self.subTest(column=column, value=value):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.db.execute(f"UPDATE rooms SET {column} = ?", (value,))

    def test_human_codes_are_unique_and_keep_their_format(self):
        self.db.execute("INSERT INTO staff VALUES ('s1', 'FRONT/001', 'Jo', 'Lee', NULL)")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO staff VALUES ('s2', 'FRONT/001', 'Sam', 'Lee', NULL)")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute(
                "INSERT INTO rooms VALUES ('room-2', '012', 'Other room', 1, 1, 'master')"
            )
        self.assertEqual(self.db.execute("SELECT room_number FROM rooms").fetchone()[0], "012")

    def test_required_foreign_keys(self):
        self.assertEqual(self.db.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE bookings SET primary_guest_id = 'missing'")
        for changes in ({"booking": "missing"}, {"room": "missing"}):
            with self.subTest(changes=changes):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.reserve(**changes)

    def test_creation_time_is_immutable_while_status_can_change(self):
        self.db.execute("UPDATE bookings SET status = 'under_review'")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE bookings SET created_at = 101")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE bookings SET status = 'unknown'")
        self.assertEqual(
            self.db.execute("SELECT created_at, status FROM bookings").fetchone(),
            (100, "under_review"),
        )

    def test_reservation_needs_a_positive_time_interval(self):
        for checkout in (199, 200):
            with self.subTest(checkout=checkout):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.reserve(checkout=checkout)

    def test_extension_then_cancellation_keeps_history(self):
        self.reserve()
        self.reserve(revision=2, checkout=400)
        self.reserve(revision=3, checkout=400, status="cancelled")
        self.assertEqual(
            self.db.execute(
                "SELECT revision, check_out_at, status FROM room_reservations ORDER BY revision"
            ).fetchall(),
            [(1, 300, "active"), (2, 400, "active"), (3, 400, "cancelled")],
        )
        self.assertEqual(
            self.db.execute(
                "SELECT revision, check_out_at, status FROM current_room_reservations"
            ).fetchall(),
            [(3, 400, "cancelled")],
        )

    def test_current_view_keeps_latest_revision_for_each_reservation(self):
        self.reserve()
        self.reserve(revision=2, checkout=400)
        self.reserve(id="reservation-2", checkin=500, checkout=600)
        self.assertEqual(
            self.db.execute(
                "SELECT id, revision FROM current_room_reservations ORDER BY id"
            ).fetchall(),
            [("reservation-1", 2), ("reservation-2", 1)],
        )

    def test_history_cannot_be_updated_deleted_or_replaced(self):
        self.reserve()
        statements = (
            "UPDATE room_reservations SET check_out_at = 400",
            "DELETE FROM room_reservations",
            "INSERT OR REPLACE INTO room_reservations "
            "SELECT id, revision, booking_id, room_id, check_in_at, 400, status, recorded_at "
            "FROM room_reservations",
        )
        for statement in statements:
            with self.subTest(statement=statement):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.db.execute(statement)
        self.assertEqual(
            self.db.execute("SELECT check_out_at FROM room_reservations").fetchall(),
            [(300,)],
        )

    def test_revision_numbers_cannot_skip_or_repeat(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.reserve(revision=2)
        self.reserve()
        for revision in (1, 3):
            with self.subTest(revision=revision):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.reserve(revision=revision)

    def test_revision_stays_with_its_original_booking_and_room(self):
        self.reserve()
        self.db.execute(
            "INSERT INTO bookings (id, party_name, primary_guest_id) "
            "VALUES ('booking-2', 'Another party', 'guest-1')"
        )
        self.db.execute(
            "INSERT INTO rooms VALUES ('room-2', '014', 'Lake room', 1, 1, 'master')"
        )
        for changes in ({"booking": "booking-2"}, {"room": "room-2"}):
            with self.subTest(changes=changes):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.reserve(revision=2, **changes)


if __name__ == "__main__":
    unittest.main()
