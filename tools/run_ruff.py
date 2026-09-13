# SPDX-License-Identifier: BSD-3-Clause
"""Locates and execs ruff's bundled native binary.

ruff ships as a wheel with no `console_scripts` entry point -- confirmed
directly (its METADATA has none) -- so `py_console_script_binary` cannot
wrap it; the compiled binary instead lives in a `bin/` directory that is
a *sibling* of the `ruff` package's own `site-packages/` directory inside
the pip hub's extracted repo. ruff's bundled `ruff._find_ruff.find_ruff_bin()`
doesn't know about that layout -- it assumes a plain `pip install`, not
Bazel's runfiles tree, and fails to find the binary there (confirmed by
running it) -- so this resolves the path directly instead of relying on it.
"""

import os
import sys

import ruff


def _bin_path() -> str:
    package_dir = os.path.dirname(os.path.abspath(ruff.__file__))
    site_packages_dir = os.path.dirname(package_dir)
    repo_root = os.path.dirname(site_packages_dir)
    return os.path.join(repo_root, "bin", "ruff")


if __name__ == "__main__":
    exe = _bin_path()
    os.execv(exe, [exe, *sys.argv[1:]])
