# SPDX-License-Identifier: BSD-3-Clause
"""Tests for src/canon_relay/canon_relay/store.py."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from canon_relay.store import Store, hash_token


class StoreTests(unittest.TestCase):
    def _set_up(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "relay.sqlite3"
        self.store = Store(self.path)
        self.addCleanup(self.store.close)

    def test_a_slack_identity_is_one_developer(self) -> None:
        self._set_up()
        first = self.store.developer("T1", "U1")
        again = self.store.developer("T1", "U1")
        other_team = self.store.developer("T2", "U1")
        self.assertEqual(first.id, again.id)
        self.assertNotEqual(first.id, other_team.id)
        self.assertFalse(first.away)

    def test_a_linked_token_authenticates_to_its_owner(self) -> None:
        self._set_up()
        developer = self.store.developer("T1", "U1")
        token = self.store.link(developer.id, "laptop")
        assert token is not None
        found = self.store.authenticate(token)
        assert found is not None
        device, owner = found
        self.assertEqual(device.name, "laptop")
        self.assertEqual(owner.slack_user, "U1")
        self.assertIsNotNone(device.last_seen)

    def test_only_the_hash_is_stored(self) -> None:
        self._set_up()
        developer = self.store.developer("T1", "U1")
        token = self.store.link(developer.id, "laptop")
        assert token is not None
        with closing(sqlite3.connect(str(self.path))) as db:
            stored = [row[0] for row in db.execute("SELECT token_hash FROM devices")]
        self.assertEqual(stored, [hash_token(token)])
        self.assertNotIn(token, stored)

    def test_an_unknown_token_does_not_authenticate(self) -> None:
        self._set_up()
        self.assertIsNone(self.store.authenticate("crd_nope"))
        self.assertIsNone(self.store.authenticate("not-even-prefixed"))

    def test_a_revoked_device_stops_authenticating(self) -> None:
        self._set_up()
        developer = self.store.developer("T1", "U1")
        token = self.store.link(developer.id, "laptop")
        assert token is not None
        self.assertTrue(self.store.revoke(developer.id, "laptop"))
        self.assertIsNone(self.store.authenticate(token))
        self.assertFalse(self.store.revoke(developer.id, "laptop"))

    def test_device_names_are_unique_per_developer(self) -> None:
        self._set_up()
        alice = self.store.developer("T1", "UA")
        bob = self.store.developer("T1", "UB")
        self.assertIsNotNone(self.store.link(alice.id, "laptop"))
        self.assertIsNone(self.store.link(alice.id, "laptop"))
        self.assertIsNotNone(self.store.link(bob.id, "laptop"))

    def test_revoking_cannot_touch_someone_elses_device(self) -> None:
        self._set_up()
        alice = self.store.developer("T1", "UA")
        bob = self.store.developer("T1", "UB")
        token = self.store.link(bob.id, "laptop")
        assert token is not None
        self.assertFalse(self.store.revoke(alice.id, "laptop"))
        self.assertIsNotNone(self.store.authenticate(token))

    def test_next_device_name_skips_taken_ones(self) -> None:
        self._set_up()
        developer = self.store.developer("T1", "U1")
        self.assertEqual(self.store.next_device_name(developer.id), "device-1")
        self.store.link(developer.id, "device-1")
        self.assertEqual(self.store.next_device_name(developer.id), "device-2")

    def test_presence_survives_a_restart(self) -> None:
        self._set_up()
        developer = self.store.developer("T1", "U1")
        self.store.set_away(developer.id, True)
        self.store.close()
        self.store = Store(self.path)
        self.assertTrue(self.store.developer("T1", "U1").away)


if __name__ == "__main__":
    unittest.main()
