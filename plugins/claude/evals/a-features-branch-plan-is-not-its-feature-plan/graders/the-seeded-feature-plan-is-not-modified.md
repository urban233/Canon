---
type: regex
target: {source: file, path: .canon/plans/features/public-permalinks.md}
# The feature plan is the decoy in this fixture, and it has to come out
# of the run byte-identical -- a model that "tidies up" the two
# same-slug documents into one has failed the case even if it says the
# right thing. The suite is invoked with Write and Edit allowed on top
# of what prompt.md lists, so this is not a formality.
#
# The span covers the header AND the opening of the body deliberately.
# A header-only pattern was not enough, because `format_feature_header()`
# emits precisely those same two header lines -- so any rewrite that
# went through `feature_plan_path` would satisfy it. The title and the
# `## Why` line are the part nothing else in this fixture reproduces.
pattern: 'status: approved\nsteps:\n---\n\n# Public Permalinks\n\n## Why\nPeople need to cite datasets by a link that outlives a reorg\.'
match: contains
---
