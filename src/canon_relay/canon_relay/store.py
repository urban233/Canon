# SPDX-License-Identifier: BSD-3-Clause
"""The relay's only durable state: who a device belongs to, and whether
that person is away.

Two tables and nothing else. A developer is a Slack identity (team and
user ID, both taken from Slack's own event payload rather than typed by
anyone). A device is one linked machine, stored as the SHA-256 of its
token, never the token itself. Presence (`away`) sits on the developer
because it is a fact about the person, not about any one machine.

Pending requests are deliberately *not* here -- see pending.py. They live
only as long as the hook connection waiting on them, so a restart drops
them and every waiting hook falls back to the local prompt, rather than a
stale approval surviving in a table.

Standard library only (`sqlite3`, `hashlib`, `secrets`), so it is tested
under Bazel like canon-mcp's pure modules.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
from pathlib import Path
from typing import NamedTuple

_SCHEMA = """
CREATE TABLE IF NOT EXISTS developers (
    id          INTEGER PRIMARY KEY,
    slack_team  TEXT NOT NULL,
    slack_user  TEXT NOT NULL,
    away        INTEGER NOT NULL DEFAULT 0,
    UNIQUE (slack_team, slack_user)
);
CREATE TABLE IF NOT EXISTS devices (
    id            INTEGER PRIMARY KEY,
    developer_id  INTEGER NOT NULL REFERENCES developers(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    token_hash    TEXT NOT NULL UNIQUE,
    created_at    REAL NOT NULL,
    last_seen     REAL,
    UNIQUE (developer_id, name)
);
"""

_TOKEN_PREFIX = "crd_"


class Developer(NamedTuple):
    id: int
    slack_team: str
    slack_user: str
    away: bool


class Device(NamedTuple):
    id: int
    developer_id: int
    name: str
    created_at: float
    last_seen: float | None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Store:
    def __init__(self, path: Path | str) -> None:
        self._db = sqlite3.connect(str(path), isolation_level=None)
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    def developer(self, slack_team: str, slack_user: str) -> Developer:
        """The developer for a Slack identity, created on first sight."""
        self._db.execute(
            "INSERT OR IGNORE INTO developers (slack_team, slack_user) VALUES (?, ?)",
            (slack_team, slack_user),
        )
        row = self._db.execute(
            "SELECT id, slack_team, slack_user, away FROM developers"
            " WHERE slack_team = ? AND slack_user = ?",
            (slack_team, slack_user),
        ).fetchone()
        return Developer(row[0], row[1], row[2], bool(row[3]))

    def developer_by_id(self, developer_id: int) -> Developer | None:
        row = self._db.execute(
            "SELECT id, slack_team, slack_user, away FROM developers WHERE id = ?",
            (developer_id,),
        ).fetchone()
        if row is None:
            return None
        return Developer(row[0], row[1], row[2], bool(row[3]))

    def set_away(self, developer_id: int, away: bool) -> None:
        self._db.execute(
            "UPDATE developers SET away = ? WHERE id = ?",
            (1 if away else 0, developer_id),
        )

    def link(self, developer_id: int, name: str) -> str | None:
        """Mint a token for a new device called `name`.

        Returns the token -- the only time it exists in the clear -- or
        None when this developer already has a device by that name.
        """
        token = _TOKEN_PREFIX + secrets.token_urlsafe(32)
        try:
            self._db.execute(
                "INSERT INTO devices (developer_id, name, token_hash, created_at)"
                " VALUES (?, ?, ?, ?)",
                (developer_id, name, hash_token(token), time.time()),
            )
        except sqlite3.IntegrityError:
            return None
        return token

    def next_device_name(self, developer_id: int) -> str:
        taken = {device.name for device in self.devices(developer_id)}
        number = 1
        while f"device-{number}" in taken:
            number += 1
        return f"device-{number}"

    def devices(self, developer_id: int) -> list[Device]:
        rows = self._db.execute(
            "SELECT id, developer_id, name, created_at, last_seen FROM devices"
            " WHERE developer_id = ? ORDER BY created_at",
            (developer_id,),
        ).fetchall()
        return [Device(row[0], row[1], row[2], row[3], row[4]) for row in rows]

    def revoke(self, developer_id: int, name: str) -> bool:
        cursor = self._db.execute(
            "DELETE FROM devices WHERE developer_id = ? AND name = ?",
            (developer_id, name),
        )
        return cursor.rowcount > 0

    def authenticate(self, token: str) -> tuple[Device, Developer] | None:
        """The device a bearer token belongs to, and its owner.

        Records `last_seen` as a side effect -- the one write on the hot
        path, and the only thing `devices` in Slack reports besides a name.
        """
        if not token.startswith(_TOKEN_PREFIX):
            return None
        row = self._db.execute(
            "SELECT d.id, d.developer_id, d.name, d.created_at, d.last_seen,"
            " v.slack_team, v.slack_user, v.away"
            " FROM devices d JOIN developers v ON v.id = d.developer_id"
            " WHERE d.token_hash = ?",
            (hash_token(token),),
        ).fetchone()
        if row is None:
            return None
        now = time.time()
        self._db.execute("UPDATE devices SET last_seen = ? WHERE id = ?", (now, row[0]))
        device = Device(row[0], row[1], row[2], row[3], now)
        developer = Developer(row[1], row[5], row[6], bool(row[7]))
        return device, developer
