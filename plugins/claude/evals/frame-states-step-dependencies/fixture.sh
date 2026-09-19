#!/usr/bin/env bash
# A repository on its default branch with no feature plan yet -- where
# `frame` runs.
#
# The tree is deliberately a working blog rather than three stub files.
# On the run of 2026-09-19 the first version of this fixture seeded
# near-empty modules, and the model spent the whole case asking four
# entirely fair questions instead of drafting anything: what shape is a
# post (nothing had a title), what does a search result look like on the
# wire, where is this signed-off mock, and is there any write path an
# index could hook into at all. A real repository answers all four by
# itself, and the case is about the SHAPE of the step dependencies, not
# about whether the model can guess a data model. So:
#
#   * a post carries a title, a slug and a body, and posts are seeded;
#   * storage is a module with a write path and a revision counter, so
#     "rebuild or maintain incrementally" is a question about the index
#     rather than a question about whether storage can be watched;
#   * the api has a `public_post` serialiser and a routing table, so the
#     response convention for a new endpoint is visible;
#   * the designer's signed-off mock is in the tree, next to the fixed
#     example results it was drawn against and a README that says the
#     mock is what a page is built and reviewed against before the
#     endpoint behind it exists.
#
# The last one matters most: it is what makes the prompt's premise --
# the results page does not have to wait for the endpoint -- checkable
# in the code rather than merely asserted in the prompt.
set -euo pipefail

git init -q
git symbolic-ref HEAD refs/heads/main
mkdir -p src/blog/storage src/blog/api src/blog/web/mocks

cat > README.md <<'EOF'
# blog

A small self-hosted blog. Three packages, one job each.

- `src/blog/storage` -- the post store. Every read and every write goes
  through it; nothing outside it touches the posts themselves.
- `src/blog/api` -- JSON endpoints. A handler returns plain dicts and
  `public_post()` is the one place that decides which stored fields a
  reader may see.
- `src/blog/web` -- server-rendered pages. A page renders from those
  same dicts.

## How a page gets built

Design hands over a static mock plus the fixed example data it was drawn
against, both in `src/blog/web/mocks/`. The template is built and
reviewed against that data, and any endpoint behind it is written to
match the same shape afterwards -- so a page never has to wait for a
route to exist before anyone can look at it. See
`src/blog/web/mocks/README.md` for what is signed off.

## Today

A reader reaches a post from the archive list, which shows titles only.
Nothing reads a post's body except the post page itself.
EOF

cat > src/blog/storage/__init__.py <<'EOF'
"""The post store."""

from .posts import add_post, all_posts, delete_post, get, get_by_slug, revision

__all__ = ["add_post", "all_posts", "delete_post", "get", "get_by_slug", "revision"]
EOF

cat > src/blog/storage/posts.py <<'EOF'
"""Posts, and the only supported way to read or change one.

An in-memory dict today -- the module boundary is what matters. Every
write goes through `add_post` or `delete_post`, and each one ticks
`revision()`, so anything that caches a view of the posts (an archive
page, a count, an index) can tell whether what it holds is still
current without polling the store itself.

A post is a plain dict, because that is what the api serialises and what
the web templates render:

    {
        "id": 3,
        "slug": "grinding-for-espresso",
        "title": "Grinding for espresso",
        "body": "Grind size is the one variable ...",
        "published_at": "2024-03-19",
    }
"""

FIELDS = ("id", "slug", "title", "body", "published_at")

_POSTS: dict[int, dict] = {}
_REVISION = 0


def revision() -> int:
    """Ticks on every write. A cache that stored this value alongside
    what it derived can tell, in one comparison, whether it is stale."""
    return _REVISION


def get(post_id: int) -> dict | None:
    return _POSTS.get(post_id)


def get_by_slug(slug: str) -> dict | None:
    for post in _POSTS.values():
        if post["slug"] == slug:
            return post
    return None


def all_posts() -> list[dict]:
    """Every post, newest first."""
    return sorted(_POSTS.values(), key=lambda post: post["published_at"], reverse=True)


def add_post(post: dict) -> dict:
    """Store a post. Raises if a field is missing or the slug is taken."""
    global _REVISION
    missing = [field for field in FIELDS if field not in post]
    if missing:
        raise ValueError(f"post is missing {', '.join(missing)}")
    existing = get_by_slug(post["slug"])
    if existing is not None and existing["id"] != post["id"]:
        raise ValueError(f"slug already taken: {post['slug']}")
    _POSTS[post["id"]] = dict(post)
    _REVISION += 1
    return _POSTS[post["id"]]


def delete_post(post_id: int) -> bool:
    global _REVISION
    if post_id not in _POSTS:
        return False
    del _POSTS[post_id]
    _REVISION += 1
    return True


_SEED = [
    {
        "id": 1,
        "slug": "hello-world",
        "title": "Hello, world",
        "body": "A first post, mostly so the archive page has something in it.",
        "published_at": "2024-01-05",
    },
    {
        "id": 2,
        "slug": "a-year-of-sourdough",
        "title": "A year of sourdough",
        "body": (
            "The starter lives in a jar on the counter. Twelve months in, the "
            "crumb is finally open and the crust stopped shattering."
        ),
        "published_at": "2024-02-11",
    },
    {
        "id": 3,
        "slug": "grinding-for-espresso",
        "title": "Grinding for espresso",
        "body": (
            "Grind size is the one variable worth owning. A burr grinder and a "
            "scale beat a better machine, every time."
        ),
        "published_at": "2024-03-19",
    },
]

for _post in _SEED:
    add_post(_post)
EOF

cat > src/blog/api/__init__.py <<'EOF'
"""JSON endpoints."""
EOF

cat > src/blog/api/routes.py <<'EOF'
"""JSON endpoints.

A handler returns a plain dict; the server serialises it. Every handler
that hands a post to a reader goes through `public_post`, which is the
one place that decides what is public -- a body is returned only by the
single-post endpoint, never in a list.
"""

from ..storage import posts

ROUTES = {
    "GET /posts": "list_posts",
    "GET /posts/<post_id>": "get_post",
}


def public_post(post: dict, *, body: bool = False) -> dict:
    """The reader-facing view of a stored post."""
    public = {
        "id": post["id"],
        "slug": post["slug"],
        "title": post["title"],
        "published_at": post["published_at"],
    }
    if body:
        public["body"] = post["body"]
    return public


def get_post(post_id: int) -> dict | None:
    post = posts.get(post_id)
    if post is None:
        return None
    return {"post": public_post(post, body=True)}


def list_posts() -> dict:
    return {"posts": [public_post(post) for post in posts.all_posts()]}
EOF

cat > src/blog/web/__init__.py <<'EOF'
"""Server-rendered pages."""
EOF

cat > src/blog/web/templates.py <<'EOF'
"""Server-rendered pages.

Every template takes the same dicts the api returns, which is what lets
a page be built and reviewed against the example data in `mocks/` before
the endpoint that will eventually supply it exists. `example_data` is
how a template test loads that data.
"""

import json
from pathlib import Path

MOCKS = Path(__file__).parent / "mocks"


def example_data(name: str) -> dict:
    """The fixed example data a mock was drawn against."""
    return json.loads((MOCKS / f"{name}.json").read_text(encoding="utf-8"))


def render_post(post: dict) -> str:
    return (
        "<article>"
        f"<h1>{post['title']}</h1>"
        f"<time>{post['published_at']}</time>"
        f"<div class=\"body\">{post['body']}</div>"
        "</article>"
    )


def render_archive(data: dict) -> str:
    items = "".join(
        f"<li><a href=\"/posts/{post['slug']}\">{post['title']}</a>"
        f"<time>{post['published_at']}</time></li>"
        for post in data["posts"]
    )
    return f"<h1>Archive</h1><ul class=\"archive\">{items}</ul>"
EOF

cat > src/blog/web/mocks/README.md <<'EOF'
# Static mocks

Design hands over two files per page: a static HTML mock, and the fixed
example data it was drawn against. The template is built against that
JSON and reviewed against the HTML side by side, before whatever
endpoint will eventually produce that data exists. That is also how the
response shape gets settled -- the example data *is* the contract, and
the endpoint is written to match it.

A mock is only signed off once its example data is final. Signed off
means the shape will not move.

| mock                  | example data          | signed off | by             |
| --------------------- | --------------------- | ---------- | -------------- |
| `archive.html`        | `archive.json`        | 2024-01-22 | Priya (design) |
| `search-results.html` | `search-results.json` | 2024-03-02 | Priya (design) |

`search-results` is signed off ahead of the search work itself: the page
it describes has no endpoint behind it yet.
EOF

cat > src/blog/web/mocks/archive.json <<'EOF'
{
  "posts": [
    {
      "id": 3,
      "slug": "grinding-for-espresso",
      "title": "Grinding for espresso",
      "published_at": "2024-03-19"
    },
    {
      "id": 2,
      "slug": "a-year-of-sourdough",
      "title": "A year of sourdough",
      "published_at": "2024-02-11"
    }
  ]
}
EOF

cat > src/blog/web/mocks/archive.html <<'EOF'
<!-- Signed off 2024-01-22 by Priya (design). Drawn against
     archive.json in this directory. -->
<h1>Archive</h1>
<ul class="archive">
  <li>
    <a href="/posts/grinding-for-espresso">Grinding for espresso</a>
    <time>2024-03-19</time>
  </li>
  <li>
    <a href="/posts/a-year-of-sourdough">A year of sourdough</a>
    <time>2024-02-11</time>
  </li>
</ul>
EOF

cat > src/blog/web/mocks/search-results.json <<'EOF'
{
  "query": "espresso",
  "total": 2,
  "results": [
    {
      "id": 3,
      "slug": "grinding-for-espresso",
      "title": "Grinding for espresso",
      "snippet": "Grind size is the one variable worth owning. A burr grinder and a scale beat a better machine, every time."
    },
    {
      "id": 2,
      "slug": "a-year-of-sourdough",
      "title": "A year of sourdough",
      "snippet": "The starter lives in a jar on the counter, next to the espresso machine."
    }
  ]
}
EOF

cat > src/blog/web/mocks/search-results.html <<'EOF'
<!-- Signed off 2024-03-02 by Priya (design). Drawn against
     search-results.json in this directory; nothing serves that data
     yet, and the page is reviewed against the file. -->
<h1>Results for &ldquo;espresso&rdquo;</h1>
<p class="count">2 posts</p>
<ol class="results">
  <li>
    <a href="/posts/grinding-for-espresso">Grinding for espresso</a>
    <p class="snippet">
      Grind size is the one variable worth owning. A burr grinder and a
      scale beat a better machine, every time.
    </p>
  </li>
  <li>
    <a href="/posts/a-year-of-sourdough">A year of sourdough</a>
    <p class="snippet">
      The starter lives in a jar on the counter, next to the espresso
      machine.
    </p>
  </li>
</ol>
<p class="empty" hidden>No posts matched.</p>
EOF

git add README.md src
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "blog: storage, api, web"

mkdir -p .canon
cat > .canon/config.json <<'EOF'
{
  "verify": "true"
}
EOF
