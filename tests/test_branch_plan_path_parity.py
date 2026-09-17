# SPDX-License-Identifier: BSD-3-Clause
"""Pins `canon_mcp`'s copy of the branch-plan path rule to the same
answer as `plan_header.branch_plan_path`/`branch_plan_relative` -- the
canonical, save-side implementation in
plugins/claude/hooks/plan_header.py (mirrored here from
src/canon_hooks/plan_header.py) -- across a table of branch names.

`canon_mcp` deliberately does not import `canon_hooks` (`_git.py`'s
module docstring: two delivery mechanisms that should not share a
dependency edge), so `canon_mcp._plan.branch_plan_relative` is a
documented copy of `plan_header`'s redirect logic, not an import of it.
Without this test the duplication is just duplication, silently free to
drift the moment either copy changes -- this is what makes the mirror
honest.
"""

from __future__ import annotations

import unittest

import plan_header

from canon_mcp import _plan

# Ordinary branch names, the reserved "features/" prefix that gets
# redirected, the nested and case-insensitive variants plan_header.py's
# own module docstring reasons about, and the one deliberately
# unresolved overlap it calls out ("branches/features/<x>" reduces to
# the same path a "features/<x>" branch redirects to).
_BRANCH_NAMES = [
    "main",
    "solo",
    "wip",
    "feature/widget",  # singular "feature/" -- does not collide
    "features/widget",  # the reserved prefix -- redirected
    "features/nested/widget",
    "Features/Widget",  # case-insensitive collision
    "FEATURES/WIDGET",
    "features",  # no further segment -- reduces to features.md, no collision
    "featuresx/widget",  # not the reserved segment, merely a prefix of it
    "branches/features/widget",  # the unresolved overlap
]


class BranchPlanPathParityTests(unittest.TestCase):
    def test_hooks_and_canon_mcp_agree_on_every_branch_name(self) -> None:
        for branch in _BRANCH_NAMES:
            with self.subTest(branch=branch):
                self.assertEqual(
                    plan_header.branch_plan_relative(branch),
                    _plan.branch_plan_relative(branch),
                )


if __name__ == "__main__":
    unittest.main()
