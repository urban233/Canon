# Changelog

All notable changes to Canon are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and Canon uses [semantic versioning](https://semver.org/spec/v2.0.0.html).

Paragraphs here are deliberately written as single long lines rather than wrapped to 80 columns like the rest of this repository's Markdown. Each version's section is read verbatim into its GitHub release body by `.github/workflows/release.yml`, and GitHub renders a newline inside a paragraph as a real line break — wrapped source arrives there as a dozen ragged short lines. The destination decides the formatting.

Versions before 1.0.0 may change behaviour a plugin install depends on. Canon is usable now; the interfaces below are not yet frozen.

## [Unreleased]

### Changed

- **The git guard lets an agent update a branch, and still never merges a pull request** ([ADR 0011](docs/decisions/0011-update-a-branch-never-merge-a-pull-request.md)). `git merge` on a feature branch is now allowed, so is `git push --force-with-lease` to one, and so is fast-forwarding the default branch to its own remote. Together these are how a stacked branch takes its parent step or is replayed onto it. A merge into the default branch, a `git pull` of another branch into it, a lease push to it, every plain `--force`/`-f`/`+refspec` push, and `gh pr merge`/`close`/approve are still refused. Previously every `git merge` and every `--force-with-lease` was refused, which blocked branch updates in recorded sessions.

### Removed

- **The plan gate** ([ADR 0012](docs/decisions/0012-no-gate-before-the-first-edit.md)). `plan_gate.py` no longer refuses an edit with no saved plan, an edit or commit on the default branch, or a branch cut from another feature branch, on any platform. In one field repository it refused 25 times and prevented no mistake: 14 refusals came from the plan-save bug fixed in 0.2.1, and 11 blocked each deliberately stacked step. A plan is still required before shipping: `canon_ship` refuses a branch without an approved one. The `guard_default_branch` config key is now ignored.

## [0.3.0] - 2026-09-28

Canon now understands stacked branches. It was built from a field session in which an agent took a multi-step feature through Canon one stacked branch at a time, and every claim it made about Canon was checked against the repository before anything changed (`docs/field-reports/2026-09-28-open-protein-platform-movie-export.md`). Each step is now measured from its parent step rather than from `main`. A reviewer's verdict answers only for its own branch. Evidence that neither CI nor the `Stop` hook can run, such as a display-bound suite, can be declared and verified against HEAD's tree. Re-review after a READY verdict costs only the delta. After updating, add `.canon/hooks/` to your `.gitignore` if it isn't already; Canon now tells you at session start when it isn't.

### Added

- **Stacked branches are measured from their parent step.** A branch cut from another feature branch now reports its plan's `base`, the SessionStart diff, `canon_review`'s changed paths and `canon_position`'s commit count against that parent, not against the default branch. Previously every step of a stack reported the whole stack: in one field session, all thirteen plans had the same `base`, and one step's diff was 326 files. The parent is derived from git's reflog, never stored, and recorded as an editable `stacked_on:` line in the saved plan's header.
- **Declared ship evidence, verified by git tree** ([ADR 0010](docs/decisions/0010-ship-evidence-is-verified-not-stored.md)). For evidence too slow for `verify` and unable to run in CI, `.canon/config.json` can declare `ship_evidence: {command, result}`. Canon never runs the command. It reads the result file your command wrote, and `canon_ship` is ready only when its recorded tree is HEAD's, on a clean tree, and passed. Canon still stores nothing.
- **Reviewer models in config.** `reviewers: {"reviewer": {"model": "sonnet"}}` is reported by `canon_review` under `models`, and the review skill dispatches on it.
- **`canon_review` counts review rounds** (`rounds`, the CHANGES REQUIRED verdicts per reviewer on this branch), so the two-round stop survives a compaction.
- **SessionStart reports a decisions log git would commit**, and names the `.gitignore` fix. It never applies the fix itself.

### Changed

- **After a READY verdict, a reviewer confirms only the delta.** When the only commits since a reviewer's READY verdict close its notes, the review skill asks for `<head>..HEAD` alone, rather than a full re-review of the branch. The verdict is still fresh at HEAD. In the field, each such follow-up had cost a full round of about 350k tokens.
- **The ship skill takes the plan's approach section under whatever name the plan uses** (`## Design`, `## Shape`), instead of demanding a `## Approach` section that the plan skill never asks for.

### Fixed

- **A reviewer verdict answers only for the branch it was captured on.** A new branch stacked on a reviewed step used to report the parent's verdicts as its own. Records now carry their branch. Records written before this are matched by git ancestry instead, so an existing log neither leaks a parent's verdict nor counts the whole repository's history as one branch's rounds.
- **`base` is measured from the remote default branch as well as the local one.** A stale local `main` used to widen every diff, scope and review range built on it.

## [0.2.1] - 2026-09-26

A hotfix for Claude Code. Plan persistence — the feature the rest of Canon's position-tracking reads from — never worked there: an approved plan was never written into the repository, and nothing said so. Codex and Antigravity are unaffected; they save plans by a different route. Update the plugin and approve a plan once to confirm `.canon/plans/<branch>.md` appears.

### Fixed

- **An approved plan is now actually saved on Claude Code.** `save_plan.py` recognised an approval only when the hook's `tool_response` was the text the model reads (`"## Approved Plan:"` followed by the body), but Claude Code hands a `PostToolUse` hook the tool's structured output instead, `{"plan", "isAgent", "filePath"}`. Every real approval therefore failed the hook's string check and was dropped silently, and `.canon/plans/` was never written. The hook now reads that object, still preferring the file at `filePath` that the developer approved on screen, and keeps the string form as a fallback. `StructuredToolResponseTests` pins the recorded payload shape.
- **Hook commands survive a plugin path containing a space.** Every command in the Claude Code plugin's `hooks.json` now quotes `${CLAUDE_PLUGIN_ROOT}`; unquoted, a space in the install path split the command and broke every hook. Claude Code 2.1.283's `claude plugin validate --strict` rejects the unquoted form.

## [0.2.0] - 2026-09-20

Canon now ships for a third platform, [Antigravity](https://antigravity.google), alongside Claude Code and Codex — built from a probe of what that platform actually does rather than from what its documentation implies, and honest in the README about the two things that are weaker there. The reviewer also stops hunting bugs itself on Claude Code and consumes the host's own code review instead, and a `verify` command can no longer smuggle a shell in through `sh -c`.

### Added

- **A third plugin, for [Antigravity](https://antigravity.google)**, at `plugins/antigravity/`. The same four primitives as the other two plugins, mapped onto Antigravity's own customization surface: `hooks.json` lifecycle hooks, a bundled `agents/` directory for the two reviewer subagents, `mcp_config.json` for the vendored `canon-mcp`, and `rules/AGENTS.md`. Install it with `agy plugin install ./plugins/antigravity`.
- **`tools/check_antigravity_plugin.py`**, a stdlib validator for the Antigravity plugin's manifests, run by `just validate-plugin`. It checks the things that produce a plugin which loads cleanly and then does nothing: a hook bound to the deprecated `PreInvocation`, a hook command naming a file the plugin does not ship, an MCP path that will not resolve, a skill or agent with no `description`. `agy plugin validate` is the better check and is the real loader, but it is an IDE-bundled binary with no install path on a CI runner.
- **`docs/decisions/0008-the-eval-suite-belongs-to-the-claude-code-plugin.md`**, recording that eval cases are a Claude Code capability rather than a Canon one — `claude plugin eval` is a CLI feature and the cases are written in Claude Code's tool vocabulary — so a port carrying none is complete rather than outstanding. What keeps a port's instruction text trustworthy instead is minimised divergence, enforced by `just sync-check`.
- **`canon-mcp` asks the MCP client which workspace it is serving**, through the protocol's own `roots/list`, preferring that answer over `CLAUDE_PROJECT_DIR`, `git rev-parse` and the process cwd. This is a fix for every host whose client populates roots, not only Antigravity. The resolver is guarded on the client's declared capability because the SDK raises rather than degrades at a client that did not declare it — which would have turned all five tools into errors on Claude Code. `tools/check_mcp_roots.py` (`just check-mcp-roots`) verifies both arms against a real server. Reasoning in `docs/decisions/0007-how-canon-mcp-learns-its-workspace-on-antigravity.md`.
- **`docs/antigravity-hook-surface.md`**, the probe write-up the port was built from — what was captured from live `agy` sessions, what came from `agy plugin validate`, what came from Antigravity's own bundled documentation, and what is still open. Antigravity's payload envelope is camelCase but its tool arguments are PascalCase; `workspacePaths` can be empty; a hook runs with its working directory set to the plugin, not the repository; and `PreInvocation` is deprecated and has no effect. None of those would report an error if assumed wrong. Two later measurements settled the things the plugin would be pointless or broken without: the `Stop` gate genuinely blocks a stop and re-enters the loop, and a hook that writes nothing reaches Antigravity as "no opinion" rather than as a refusal — though a bare `{}` *is* a refusal, with no reason attached.

### Changed

- **Hook logic is shared across all three platforms rather than forked per platform.** The Antigravity dialect — camelCase envelope, PascalCase tool arguments, a flat `{"decision": ...}` result, and a `Stop` decision spelled inversely to Claude Code's — is handled by an adapter inside the one canonical `src/canon_hooks/_common.py`, so the other ten hook modules stay byte-identical on every platform. `just sync-hooks`, `just sync-mcp`, `just sync-skills` and `just sync-check` all cover `plugins/antigravity/` too, and `just validate-plugin` checks it with `tools/check_antigravity_plugin.py`.
- **`normalize_plan.py` moved to `src/canon_hooks/`** and is now shared between Codex and Antigravity, which both lack an `ExitPlanMode` tool whose result a hook could read. It was previously maintained only in `plugins/codex/hooks/`.
- **The edit-tool list every gate matches on is defined once**, in `_common.EDIT_TOOL_NAMES`, instead of being written out separately in `fast_check.py`, `check_scope.py` and `plan_gate.py`. It gains Antigravity's family: `write_to_file`, `replace_file_content`, `multi_replace_file_content`, `edit_file` and `notebook_edit`.
- **The reviewer takes its findings from the host's own code review** rather than hunting bugs itself, on Claude Code. `/code-review` fans out across several angles, scales with diff size and verifies findings before reporting; run against this repository it found a real defect in `git_guard.py` that the reviewer, its tests and two repair rounds had all passed. The reviewer brief is now mostly a deletion: it consumes a review it did not perform and applies the judgement only Canon has — the plan's `## Non-goals`, whether verification actually ran, whether the change can be taken back out, and which verdict to end on. Codex and Antigravity have no reachable equivalent and keep reading the diff themselves.
- **A finding now has a bar to clear.** Nothing said what earned the word, so a true observation about code the branch never touched arrived in the same ranked list as a defect the branch introduced. Five conditions now hold together: a concrete code path demonstrates it, this change introduced or exposed it, it has a plausible runtime consequence, the location can be named, and the violated invariant can be stated. Anything short of that is a suspicion and goes in the residual risks, where a human can weigh it without being asked to act.
- **Two instruction lines were cut** because they survived their own ablation. Canon's rule is that no instruction ships without an eval that fails when it is removed; these scored identically with and without, twice.

### Fixed

- **A `verify` command can no longer hand its work to a shell.** `"verify": "sh -c \"ruff check . && pytest\""` passed the compound-command check, because `shlex.split` turns it into three clean tokens — so the chain reached a real shell anyway and the Stop gate was back to being unable to say which half went red. A model wrote exactly that one turn after correctly explaining why the bare compound form had been refused: the refusal taught it the shape of the workaround. Now refused as its own distinct fault, with its own message, rather than by widening the metacharacter rule and taking a wall of false refusals with it. See `docs/decisions/0005-verify-command-never-runs-through-a-shell.md`.
- **Stripping a `Co-Authored-By` trailer no longer breaks the command it was in.** The rewrite kept a line's quote characters so the command's quote structure would survive, but dropped the backslash that made an escaped quote an inert literal — promoting it to a real quoting toggle, so a command that parsed before the rewrite did not parse after it. The backslash run now travels with the quote it escapes.

### Known limitations

- **Review verdicts are not captured on Antigravity.** No event fires when a subagent finishes, and `PostToolUse` on `invoke_subagent` does not carry the tool's result, so `capture_review.py` ships but is bound to nothing and `canon_review` reports no stored verdict. The `review` skill quotes the reviewer's closing line in-session instead. This is a real weakening of the no-self-graded-review invariant on that platform.
- **`canon-mcp`'s five tools should still be treated as unavailable on Antigravity.** The server now asks the client for its workspace, and that mechanism is tested — but Antigravity's client, which advertises the capability, answered with an empty list in every session measured, exactly as `workspacePaths` did. If a real IDE session populates either, the tools work there. Every hook, skill and reviewer subagent works without them.

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

[0.3.0]: https://github.com/urban233/Canon/releases/tag/v0.3.0
[0.2.1]: https://github.com/urban233/Canon/releases/tag/v0.2.1
[0.2.0]: https://github.com/urban233/Canon/releases/tag/v0.2.0
[0.1.0]: https://github.com/urban233/Canon/releases/tag/v0.1.0
