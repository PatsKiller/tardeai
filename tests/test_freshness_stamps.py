"""Stamp first, block second — and a producer that stamps must be believed.

Measured 2026-08-27 against the live snapshot: 15 AVAILABLE domains, 9 with no
`as_of` and therefore never age-checked. Two of those nine are required by a
run purpose that currently PASSES: `retirement` and `watch_intelligence`.
(Not four. `risk` is required only by RISK_OR_STOP_EVENT, which is blocked on
defense_stops_protection; `health_data_quality` and `open_cio_actions` are
DATA_UNAVAILABLE, so there is nothing to stamp.)

Neither was a missing producer. Both had a timestamp the reader did not look at.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "scripts", ROOT / "scripts" / "lib"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

SNAP = (ROOT / "scripts/lib/cio_financial_snapshot.py").read_text(encoding="utf-8")
PORT = (ROOT / "scripts/lib/data_broker/cio_portfolio.py").read_text(encoding="utf-8")


def test_a_dict_adapter_stamping_generated_at_is_not_called_unstamped():
    """get_watch_intelligence returns the projection dict, whose stamp is
    `generated_at` (mirrored to `last_assessed_at`). The snapshot read only
    `as_of`, so a domain with a perfectly good timestamp reported
    freshness_unverified."""
    i = SNAP.index("r_as_of = (")
    block = SNAP[i:i + 260]
    assert 'result.get("as_of")' in block
    assert 'result.get("generated_at")' in block
    assert 'result.get("last_assessed_at")' in block


def test_as_of_still_wins_over_the_fallbacks():
    """Order matters: an explicit as_of is the producer's considered answer."""
    i = SNAP.index("r_as_of = (")
    block = SNAP[i:i + 260]
    assert block.index('get("as_of")') < block.index('get("generated_at")')


def test_retirement_reads_a_key_the_roadmap_actually_has():
    """It read `config_version_timestamp`, which the file has never carried, so
    the stamp was always '' -- while the roadmap records generated_at and as_of."""
    i = PORT.index("def _domain_retirement")
    block = PORT[i:PORT.index("\ndef ", i + 10)]
    assert "config_version_timestamp" not in block or "not a key" in block
    assert 'roadmap.get("generated_at")' in block
    assert "st_mtime" in block, "fall back to when the policy file last changed"


def test_retirement_never_stamps_now():
    """`now` would assert freshness the source has not earned -- the exact way a
    freshness gate is made meaningless."""
    i = PORT.index("def _domain_retirement")
    block = PORT[i:PORT.index("\ndef ", i + 10)]
    assert "datetime.now" not in block
    assert "Never `now`" in block


def test_a_precise_stamp_is_preferred_over_a_date_only_one():
    """The roadmap has both: generated_at '2026-08-26T09:18:47' and as_of
    '2026-08-26'. A date-only stamp is the holdings_detail trap from PR #566 --
    it ages from midnight and reports stale data as fresh, or fresh as stale."""
    i = PORT.index("def _domain_retirement")
    block = PORT[i:PORT.index("\ndef ", i + 10)]
    assert block.index('get("generated_at")') < block.index('get("as_of")')


def test_the_flag_is_still_advisory_not_blocking():
    """Phase 1 stamps. Flipping the gate stays an operator decision -- measured
    consequence today: 5 PASS before, 5 PASS after, zero purposes lost."""
    # Scope to where the flag is CONSUMED. A wider window spills into the age
    # check, which legitimately sets STALE for a parseable-but-old stamp (the
    # fail-closed fix from PR #566) -- that is correct, not a violation.
    i = SNAP.index("if freshness_unverified:")
    block = SNAP[i:SNAP.index("supported.add(domain_id)", i)]
    assert 'rec["freshness_unverified"] = True' in block
    assert "quality_state" not in block, "the flag must annotate, never coerce state"
