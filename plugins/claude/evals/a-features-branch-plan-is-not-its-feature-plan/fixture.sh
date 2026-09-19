#!/usr/bin/env bash
# A branch named "features/<slug>" -- the one shape whose plain
# `.canon/plans/<branch>.md` formula collides with a feature plan of the
# same slug (`.canon/plans/features/<slug>.md`). Canon redirects the
# branch's own plan to `.canon/plans/branches/features/<slug>.md` to keep
# the two apart (docs/decisions/0004). This fixture puts BOTH documents
# on disk at once, which is the state that redirect creates and the state
# a reader has to be right about: a feature plan and a branch plan,
# sharing one slug, one commit apart.
#
# The question this case asks is the one no unit test can ask -- whether
# the *model* keeps them straight. `session_start.py` names the branch
# plan's redirected path in the context every session opens with, but a
# grep of `.canon/plans/` finds the same-slug feature plan too, and it is
# the one sitting at the path the naive formula predicts.
#
# The repository underneath is real because the case reads better against
# real code and because the first version of this fixture -- a one-line
# README and nothing else -- provoked a clarifying round instead of an
# answer on 2026-09-19. Step 1 of the seeded feature plan ("slug-model: a
# slug column and a uniqueness constraint") is *already built* here:
# src/permalinks/models.py holds a `slug` column with a UNIQUE constraint
# on it, store.py uses it, a test covers it, README.md describes it. Step
# 2 (the resolver) is deliberately not built, so the feature plan still
# has somewhere to go and the branch plan has something to be about.
set -euo pipefail

git init -q
git symbolic-ref HEAD refs/heads/main
cat > README.md <<'EOF'
# permalinks

Stable, citable links to datasets. A dataset gets a slug; the slug is
what a paper or a wiki cites, and it is meant to go on resolving across
any reorg of the underlying storage.

## The slug model

`src/permalinks/models.py` holds it: the `slugs` table, and the `Slug`
record one row of it becomes. The slug itself is a text column with a
uniqueness constraint on it, because two datasets answering to the same
permalink is the one failure this library exists to prevent.

`src/permalinks/store.py` is the thin layer over that table -- create a
slug, look one up, list them. `tests/test_store.py` covers it.

```python
from permalinks import store

connection = store.connect("permalinks.db")
store.create(connection, "rainfall-2019", dataset_id="ds-114")
store.get(connection, "rainfall-2019")
```

## Not built yet

Resolution. Nothing here turns a slug into an HTTP route or a redirect
-- that is the next step of the feature plan in
`.canon/plans/features/public-permalinks.md`.
EOF

mkdir -p src/permalinks tests
cat > src/permalinks/__init__.py <<'EOF'
"""permalinks -- stable, citable links to datasets."""

__version__ = "0.2.0"
EOF

cat > src/permalinks/models.py <<'EOF'
"""The slug model: one row per dataset permalink."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

# The uniqueness constraint is the point of the table: a permalink that
# can answer to two datasets is not a permalink.
SCHEMA = """
CREATE TABLE IF NOT EXISTS slugs (
    id          INTEGER PRIMARY KEY,
    slug        TEXT    NOT NULL,
    dataset_id  TEXT    NOT NULL,
    created_at  TEXT    NOT NULL,
    UNIQUE (slug)
);
"""

COLUMNS = "slug, dataset_id, created_at"


@dataclass(frozen=True)
class Slug:
    """A permalink's slug, as stored in the `slugs` table."""

    slug: str
    dataset_id: str
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Slug":
        return cls(
            slug=row["slug"],
            dataset_id=row["dataset_id"],
            created_at=row["created_at"],
        )


def create_schema(connection: sqlite3.Connection) -> None:
    """Create the `slugs` table if it is not there yet."""
    connection.executescript(SCHEMA)
EOF

cat > src/permalinks/store.py <<'EOF'
"""Creating and looking up slugs."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .models import COLUMNS, Slug, create_schema


class DuplicateSlug(Exception):
    """A slug already taken by another dataset."""


def connect(path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    create_schema(connection)
    return connection


def create(connection: sqlite3.Connection, slug: str, dataset_id: str) -> Slug:
    """Store `slug` for `dataset_id`, or raise `DuplicateSlug`."""
    try:
        connection.execute(
            f"INSERT INTO slugs ({COLUMNS}) VALUES (?, ?, ?)",
            (slug, dataset_id, datetime.now(timezone.utc).isoformat()),
        )
    except sqlite3.IntegrityError as error:
        raise DuplicateSlug(slug) from error
    connection.commit()
    stored = get(connection, slug)
    assert stored is not None
    return stored


def get(connection: sqlite3.Connection, slug: str) -> Slug | None:
    """The slug's record, or None if nothing answers to it."""
    row = connection.execute(
        f"SELECT {COLUMNS} FROM slugs WHERE slug = ?", (slug,)
    ).fetchone()
    return Slug.from_row(row) if row is not None else None


def list_slugs(connection: sqlite3.Connection) -> list[Slug]:
    """Every stored slug, in slug order."""
    rows = connection.execute(f"SELECT {COLUMNS} FROM slugs ORDER BY slug")
    return [Slug.from_row(row) for row in rows]
EOF

cat > tests/test_store.py <<'EOF'
"""The uniqueness constraint is what actually needs covering."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from permalinks import store  # noqa: E402


class StoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.connection = store.connect(":memory:")

    def test_a_stored_slug_reads_back(self) -> None:
        store.create(self.connection, "rainfall-2019", "ds-114")
        stored = store.get(self.connection, "rainfall-2019")
        self.assertIsNotNone(stored)
        self.assertEqual(stored.dataset_id, "ds-114")

    def test_the_same_slug_cannot_be_taken_twice(self) -> None:
        store.create(self.connection, "rainfall-2019", "ds-114")
        with self.assertRaises(store.DuplicateSlug):
            store.create(self.connection, "rainfall-2019", "ds-227")


if __name__ == "__main__":
    unittest.main()
EOF

git add README.md src tests
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "slug-model: a slug column and a uniqueness constraint"
git checkout -q -b features/public-permalinks

mkdir -p .canon/plans/features
cat > .canon/plans/features/public-permalinks.md <<'EOF'
---
status: approved
steps:
---

# Public Permalinks

## Why
People need to cite datasets by a link that outlives a reorg.

## Steps
1. slug-model: a slug column and a uniqueness constraint -- done, it is
   `src/permalinks/models.py`
2. resolver: a route that resolves a slug to its dataset -- not started
EOF

# The branch's OWN plan, at the path Canon's redirect puts it -- not at
# `.canon/plans/features/public-permalinks.md`, which the feature plan
# above already occupies. Its `done:` and its `## Non-goals` share no
# wording with the feature plan, so a reply can only be quoting one of
# the two documents and it is never ambiguous which.
mkdir -p .canon/plans/branches/features
cat > .canon/plans/branches/features/public-permalinks.md <<'EOF'
---
status: approved
base: main
scope: [src/permalinks/**]
done: "every slug row carries a resolves_at timestamp"
verify:
parent:
---

## Approach
Add a nullable `resolves_at` column to the `slugs` table and a matching
field on the `Slug` record. The resolver fills it in later; nothing
writes it yet.

## Non-goals
Not backfilling `resolves_at` for slugs that already exist, and not
touching the uniqueness constraint.

## Verification
The store tests still pass, and a freshly created slug reads back with
`resolves_at` empty.
EOF

git add .canon/plans/features/public-permalinks.md \
        .canon/plans/branches/features/public-permalinks.md
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "plans: the public-permalinks feature, and this branch"

mkdir -p .canon
cat > .canon/config.json <<'EOF'
{
  "verify": "true"
}
EOF
