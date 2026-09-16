---
name: audit-google-python-style
description: Audit Python code against the Google Python Style Guide with a bundled deterministic checker, then apply only an explicitly approved remediation plan. Invoke only when the developer explicitly requests a Google Python Style audit or invokes $audit-google-python-style.
license: BSD-3-Clause
metadata:
  author: Martin Urban <martin.urban@studmail.w-hs.de>, Hannah Kullik <hannah.kullik@studmail.w-hs.de>
---

# Google Python Style Audit

Use this skill only for an explicit Google Python Style audit. It is not a
general code review, ordinary linting, or implementation workflow.

The workflow has two phases. Phase A is read-only and always ends with
`APPROVAL REQUIRED`. Enter Phase B only after the developer explicitly approves
the exact Phase A plan. Never infer approval from an automated environment,
previous request, or a request to run the audit.

Never inspect, invoke, copy, import, or rely on evaluation-only verifier or
oracle scripts. The bundled supplemental checker is independent of evals.

## Phase A: Audit And Plan

1. Read repository instructions, configuration, generated-code policy,
   documented exceptions, and working-tree state. Define the Python scope,
   including tests unless the developer explicitly excludes them. Exclude
   dependencies, caches, build output, vendored code, or generated code only
   with repository evidence.
2. Run applicable repository checks in check-only mode. Prefer documented
   wrappers; if `pymake` exists, use `pymake lint`,
   `pymake format dry_run=true`, and `pymake check_types`. Otherwise use the
   repository's documented Ruff commands. Do not install dependencies and do
   not claim an unavailable check passed.
3. Locate the `scripts/check_google_rules.py` file shipped beside this skill
   and run it with `--root <approved-scope-root>`. Do not copy that script into
   the audited repository. Derive the root from `pyproject.toml`, `setup.py`,
   or the top-level Python source directory (`src/` when present, otherwise the
   repository root).
4. Treat checker findings as deterministic evidence for syntax, imports,
   naming, mutable defaults, type comments, docstrings, comments, markup, and
   punctuation. Independently assess contextual concerns such as resources,
   state, annotations, public APIs, behavior, and intentional exceptions.
   Read `references/check-matrix.md` for the complete ownership and exception
   boundary.
5. Produce a grouped remediation plan that names exact files, rule families,
   exact edits, Ruff-assisted versus manual ownership, exclusions,
   behavior/API safeguards, and post-fix validation. Do not edit files or run
   write-mode formatters. End the report exactly with `APPROVAL REQUIRED`.

## Phase B: Approved Remediation

Enter this phase only after explicit approval of the exact Phase A plan.
Re-check the approved scope and rerun the supplemental checker. If the inputs
or findings differ materially from the plan, stop and report
`CLARIFICATION REQUIRED`.

Apply only approved style changes. Preserve behavior, tests, public APIs,
dependencies, configuration, generated sources, and unrelated user changes.
Use repository wrappers for Ruff's formatter and safe fixes when their complete
target is approved. Otherwise use the repository's documented Ruff commands,
or `ruff check --fix --extend-select UP,I,B,SIM <scope>` followed by
`ruff format <scope>`. Use `--extend-select`, never `--select`, so repository
configuration remains in force.

Resolve remaining violation-level findings with targeted edits:

- Split multi-symbol imports, replace wildcard imports with confirmed used
  symbols, use absolute imports, and replace direct class imports with module
  imports and qualified references.
- Rename style violations while preserving public compatibility; update
  in-scope callers for private renames and report external-caller risk.
- Replace confirmed mutable defaults with a `None` sentinel and appropriate
  optional annotation.
- Convert type comments to annotations.
- Complete module, class, function, and method documentation and comment
  punctuation without changing excluded headers or markers.

Repeat the checker until it reports no violation-level findings in the approved
scope. Apply review-level fixes only when the improvement is unambiguous; note
any intentionally retained review-level pattern.

Rerun repository checks, the supplemental checker, and affected tests when
available. Inspect `git diff --name-only` and `git diff --check`. If a change
alters behavior, revert that change and investigate. Report exact commands,
changed files, residual findings, and one of `COMPLETED`, `PARTIALLY COMPLETED`,
or `CLARIFICATION REQUIRED`.
