# Changelog

All notable changes to Canon are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Canon uses [semantic versioning](https://semver.org/spec/v2.0.0.html).

Paragraphs here are deliberately written as single long lines rather than wrapped to 80 columns like the rest of this repository's Markdown. Each version's section is read verbatim into its GitHub release body by `.github/workflows/release.yml`, and GitHub renders a newline inside a paragraph as a real line break — wrapped source arrives there as a dozen ragged short lines. The destination decides the formatting.

Versions before 1.0.0 may change behaviour a plugin install depends on. Canon is usable now; the interfaces below are not yet frozen.

## [0.1.0] - 2026-09-17

Canon keeps agentic development on track without a stored state machine. A plan approved in plan mode is written into the repository, a verification gate re-runs the repository's own command rather than taking the agent's word, and review happens in a fresh context that never sees the conversation that produced the diff. It rides on primitives the agent platform already has — hooks, plan mode, subagents, MCP — so there is no dashboard, no separate CLI, and no task database to fall out of sync.

First public release, for [Claude Code](https://claude.com/claude-code) and [Codex](https://developers.openai.com/codex).

### Added

- **Plan persistence.** An approved plan is written into the repository at the moment of approval — `.canon/plans/<branch>.md` for a branch, `.canon/plans/features/<slug>.md` for a multi-branch feature — so it survives context compaction and session restarts. On Claude Code a `PostToolUse:ExitPlanMode` hook saves it; Codex has no such tool, so there the agent writes the file and a hook derives its header.
- **A verification gate.** A turn cannot end on the claim that tests pass unless the repository's own verify command actually ran and came back green. The command is asked for once, on the first turn that would otherwise end unverified, and stored in `.canon/config.json`.
- **Independent review.** A reviewer subagent reads the diff, the plan and the evidence in a fresh context — never the conversation that produced them — so review cannot inherit the writer's blind spots. A second brief, `risk-reviewer`, covers one-way doors.
- **`canon-mcp`,** a small MCP server answering "where does this stand" by reading git, GitHub and the plan file directly. Nothing is stored, so nothing can drift. Five tools: `canon_position`, `canon_plan`, `canon_review`, `canon_evidence`, `canon_ship`.
- **Branch guards.** Editing on the default branch, or branching again from a branch you made on purpose, is caught before the first edit. `git push --force`, branch deletion, and `gh pr merge`/`close`/`review --approve` are refused outright — Canon never merges, approves or closes a pull request.
- **Skills:** `frame`, `plan`, `decide`, `review`, `review-change`, `ship` and `testing-craft`.
- **`canon-companion`,** a separate opt-in plugin for code-quality skills that should not load with the workflow core. Its first skill, `audit-google-python-style`, performs a read-only audit and requires explicit approval before applying any remediation. Installable on both Claude Code and Codex.

### Fixed

- A branch named `features/<x>` had its plan read from the feature-plan namespace by every reader, so the "no plan is saved for this branch" gate could pass on a same-slug feature plan and `canon_ship` could report the plan invariant satisfied from the wrong file. All eight read sites now resolve the path through the same rule the save side uses. (#54)
- The `Co-Authored-By:` trailer stripper could return a command with unbalanced quotes, or glue a surviving quote character onto a heredoc terminator — either of which turns a clean commit into a shell parse error, from a hook whose purpose was to make the commit clean. (#58)

### Known limitations

- **Custom MCP servers connect intermittently under Codex.** This is a Codex-side bug, reproduced against a dependency-free test server and independent of how `canon_mcp` is packaged: roughly a third of connection attempts either hang or complete without the tools present. Start a fresh session if the `canon` tools are missing. Every hook, skill and reviewer subagent works without it. See `docs/codex-hook-surface.md`.
- **Codex cannot bundle a subagent,** so the two reviewer briefs ship as TOML files with a one-time manual copy into `.codex/agents/`. See `plugins/codex/README.md`.
- **The eval suite is Claude-only** and is deliberately not a CI gate. See `docs/decisions/0003-eval-suite-is-not-a-ci-gate.md`.

[0.1.0]: https://github.com/urban233/Canon/releases/tag/v0.1.0
