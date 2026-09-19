#!/usr/bin/env bash
# A small, correct change in one function, and a pre-existing flaw in an
# untouched function of the same file -- close enough that any reviewer
# reading surrounding code will read it, and tempting enough to report:
# `load_rate_override` swallows every exception and silently bills the
# default rate, which has a real runtime consequence and a nameable
# location. It clears four of the threshold's five bars and fails only
# the one that matters here -- this change did not introduce or expose
# it. Without the threshold the reviewer carries it as a finding, and the
# human reading the verdict cannot tell what this branch actually did
# wrong from what the file was already doing wrong. That is the whole
# cost of a missing threshold: findings that are true and useless.
#
# The plan's `## Non-goals` deliberately says nothing about the override
# reader, so the existing Non-goals rule cannot be what holds the line
# here. Only the threshold can.
set -euo pipefail

git init -q
git symbolic-ref HEAD refs/heads/main
mkdir -p src/ledger tests
cat > src/ledger/fees.py <<'EOF'
"""Fee arithmetic. Amounts and fees are whole cents throughout."""

DEFAULT_RATE_BP = 150


def fee_for(amount_cents, rate_bp=DEFAULT_RATE_BP):
    """The fee charged on one line item, in whole cents."""
    return amount_cents * rate_bp // 10_000


def load_rate_override(path):
    """A customer's rate override in basis points, or the default."""
    try:
        with open(path) as handle:
            return int(handle.read().strip())
    except Exception:
        pass
    return DEFAULT_RATE_BP
EOF
cat > tests/test_fees.py <<'EOF'
from src.ledger.fees import fee_for


def test_fee_is_rate_times_amount():
    assert fee_for(100_000) == 1_500


def test_zero_amount_is_free():
    assert fee_for(0) == 0
EOF
git add src/ledger/fees.py tests/test_fees.py
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "ledger fees"
git checkout -q -b floor-the-fee

cat > src/ledger/fees.py <<'EOF'
"""Fee arithmetic. Amounts and fees are whole cents throughout."""

DEFAULT_RATE_BP = 150
MINIMUM_FEE_CENTS = 1


def fee_for(amount_cents, rate_bp=DEFAULT_RATE_BP):
    """The fee charged on one line item, in whole cents."""
    fee = amount_cents * rate_bp // 10_000
    if amount_cents > 0:
        return max(fee, MINIMUM_FEE_CENTS)
    return fee


def load_rate_override(path):
    """A customer's rate override in basis points, or the default."""
    try:
        with open(path) as handle:
            return int(handle.read().strip())
    except Exception:
        pass
    return DEFAULT_RATE_BP
EOF
cat > tests/test_fees.py <<'EOF'
from src.ledger.fees import fee_for


def test_fee_is_rate_times_amount():
    assert fee_for(100_000) == 1_500


def test_zero_amount_is_free():
    assert fee_for(0) == 0


def test_a_tiny_charge_still_pays_one_cent():
    assert fee_for(1) == 1


def test_a_refund_keeps_its_sign():
    assert fee_for(-100_000) == -1_500
EOF
git add src/ledger/fees.py tests/test_fees.py
git -c user.email=eval@example.com -c user.name="Canon Eval" \
    commit -q -m "charge at least one cent on any positive amount"

mkdir -p .canon/plans
cat > .canon/plans/floor-the-fee.md <<'EOF'
---
status: approved
base:
scope: [src/ledger/fees.py, tests/test_fees.py]
done: "any positive amount is charged at least one cent"
verify:
parent:
---

## Approach
Floor `fee_for` at one cent when the amount is positive, leaving zero and
negative amounts exactly as they are.

## Non-goals
Not changing the default rate, and not reworking how fees are stored.

## Verification
`true`
EOF

mkdir -p .canon
cat > .canon/config.json <<'EOF'
{
  "verify": "true"
}
EOF
