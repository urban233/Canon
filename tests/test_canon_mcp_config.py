# SPDX-License-Identifier: BSD-3-Clause
"""Tests for src/canon_mcp/canon_mcp/_config.py.

Only `interaction_mode` gets a dedicated direct test here -- the rest
of this module (`load_config`, `has_verification_signal`) is already
exercised indirectly, via mocking, in `test_canon_mcp_evidence.py` and
`test_canon_mcp_position.py`.
"""

from __future__ import annotations

import unittest

from canon_mcp import _config


class InteractionModeTests(unittest.TestCase):
    def test_defaults_to_solo_when_no_config(self) -> None:
        self.assertEqual(_config.interaction_mode(None), "solo")

    def test_defaults_to_solo_when_key_absent(self) -> None:
        self.assertEqual(_config.interaction_mode({}), "solo")

    def test_defaults_to_solo_on_an_unrecognized_value(self) -> None:
        self.assertEqual(_config.interaction_mode({"mode": "yolo"}), "solo")

    def test_reads_pair(self) -> None:
        self.assertEqual(_config.interaction_mode({"mode": "pair"}), "pair")

    def test_reads_async(self) -> None:
        self.assertEqual(_config.interaction_mode({"mode": "async"}), "async")


if __name__ == "__main__":
    unittest.main()
