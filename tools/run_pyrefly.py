# SPDX-License-Identifier: BSD-3-Clause
"""Locates and execs pyrefly's bundled native binary.

Same story as `run_ruff.py`: pyrefly's wheel has no `console_scripts`
entry point, and its own bundled locator (`pyrefly.__main__.get_pyrefly_bin`)
only checks the *current interpreter's* scripts directory via `sysconfig`,
which has nothing to do with where pip.parse extracted the wheel -- so it
falls through to just `"pyrefly"` on `PATH`, which doesn't exist in a
hermetic sandbox. This resolves the real path directly instead.
"""

import os
import sys

import pyrefly


def _bin_path() -> str:
    package_dir = os.path.dirname(os.path.abspath(pyrefly.__file__))
    site_packages_dir = os.path.dirname(package_dir)
    repo_root = os.path.dirname(site_packages_dir)
    return os.path.join(repo_root, "bin", "pyrefly")


if __name__ == "__main__":
    exe = _bin_path()
    os.execv(exe, [exe, *sys.argv[1:]])
