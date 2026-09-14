#!/usr/bin/env bash
# A repository on its default branch with no feature plan yet -- where
# `frame` runs. The tree is just enough for the three pieces in the
# prompt to be real places in a codebase rather than hypotheticals.
set -euo pipefail

git init -q
git symbolic-ref HEAD refs/heads/main
mkdir -p src/blog/{storage,api,web}
cat > src/blog/storage/posts.py <<'EOF'
POSTS = {}


def get(post_id):
    return POSTS.get(post_id)


def all_posts():
    return list(POSTS.values())
EOF
cat > src/blog/api/routes.py <<'EOF'
from ..storage import posts


def get_post(post_id):
    return posts.get(post_id)
EOF
cat > src/blog/web/templates.py <<'EOF'
def render_post(post):
    return f"<article>{post['body']}</article>"
EOF
git add src
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "blog: storage, api, web"

mkdir -p .canon
cat > .canon/config.json <<'EOF'
{
  "verify": "true"
}
EOF
