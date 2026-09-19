---
max_turns: 16
timeout_seconds: 420
allowed_tools: [Read, Glob, Grep, Bash]
---

I want to add full-text search to this blog. It's for readers, who today
can only find a post if they already know its title -- success is a reader
finding a post from a phrase in its body. Out of scope: ranking quality
beyond "the obvious match is first", and anything to do with search across
other people's blogs.

Three pieces of work, as far as I can tell. An index built over
`src/blog/storage`. A `/search` endpoint in `src/blog/api` that queries the
index. And a results page in `src/blog/web` -- our designer has already
signed off a static mock for that (`src/blog/web/mocks/search-results.html`),
so it can be built and reviewed against fixed example results without the
endpoint existing.

This obviously doesn't fit in one pull request. Plan it out for me --
draft the steps now rather than checking with me first. Where
something is genuinely open, note it inline in the step it affects
and carry on.
