---
type: regex
target: trace
# The pattern requires the notation attached to a step slug of THIS
# feature, and that is the whole point of it. A bare match on the
# notation alone was unsound -- `trace` includes every file the model
# read, the frame skill documents the notation with worked example
# steps of its own, and so the grader went green the moment the skill
# was opened, whether or not a plan was ever drafted. It did exactly
# that on the run of 2026-09-19, which produced four clarifying
# questions and no plan at all. It also broke the ablation it was
# written for, because deleting the instruction from the skill deletes
# the skill's examples with it -- the grader would have gone red over
# the missing file text rather than over the model's own output.
#
# No slug in the skill's examples, or in canon_mcp's copy of them,
# contains any of the words below, and a backtick or an asterisk is
# allowed only between the slug and the notation -- never in place of
# the slug -- so prose that quotes the skill cannot satisfy this
# either. Only a step line naming a piece of this blog's search work
# can.
pattern: '(search|index|endpoint|result|page|web|api|storage)[a-z0-9_-]*[`*_\]]*\s*\(after:'
flags: i
---
