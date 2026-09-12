"""The health predicate should read the served SHA itself.

GG-038. `timer_health(served_sha=...)` takes the SHA as an optional caller
argument, so a caller who does not pass it gets

    served_sha: null
    epoch_agreement: UNPROVEN

even when the answer is sitting in CURRENT/SOURCE_COMMIT. My own observation
script passes it and gets AGREES; the validator called the predicate plainly and
got nothing. The optionality was deliberate — UNPROVEN is the honest answer when
the SHA is genuinely unknowable, and there is a test for that — but when it IS
knowable the predicate should not depend on the caller remembering.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from scripts.lib.free_first_scheduler_health import timer_health


def _iso(dt): return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _receipt(root, *, finished_at, source_sha):
    d = root / "data" / "cio"; d.mkdir(parents=True, exist_ok=True)
    (d / "free_first_last_run.json").write_text(json.dumps({
        "mode": "FREE_FIRST_ONLY", "finished_at": finished_at,
        "source_sha": source_sha, "run_id": "t", "paid_dispatch_entered": 0}))


def test_it_derives_the_served_sha_when_the_caller_omits_it(tmp_path):
    """The defect: a plain call could not bind the epoch."""
    (tmp_path / "SOURCE_COMMIT").write_text("71f4e7a71440dba95b0910b43a86ca9f685a68f5\n")
    _receipt(tmp_path, finished_at=_iso(datetime.now(timezone.utc) - timedelta(minutes=5)),
             source_sha="71f4e7a71440dba95b0910b43a86ca9f685a68f5")
    out = timer_health(tmp_path)          # no served_sha argument
    assert out["served_sha"] == "71f4e7a71440dba95b0910b43a86ca9f685a68f5"
    assert out["epoch_agreement"] == "AGREES"


def test_a_derived_mismatch_still_fails(tmp_path):
    (tmp_path / "SOURCE_COMMIT").write_text("71f4e7a71440dba95b0910b43a86ca9f685a68f5\n")
    _receipt(tmp_path, finished_at=_iso(datetime.now(timezone.utc) - timedelta(minutes=5)),
             source_sha="deda1e1ae40515b6879225555b0f808b943bf98b")
    out = timer_health(tmp_path)
    assert out["epoch_agreement"] == "DISAGREES"
    assert "receipt_from_prior_epoch" in out["unhealthy_reasons"]


def test_an_explicit_argument_still_wins(tmp_path):
    """A caller that knows better than the filesystem must be able to say so."""
    (tmp_path / "SOURCE_COMMIT").write_text("aaaaaaa\n")
    _receipt(tmp_path, finished_at=_iso(datetime.now(timezone.utc) - timedelta(minutes=5)),
             source_sha="bbbbbbb")
    out = timer_health(tmp_path, served_sha="bbbbbbb")
    assert out["served_sha"] == "bbbbbbb"
    assert out["epoch_agreement"] == "AGREES"


def test_unprovable_stays_unproven(tmp_path):
    """The original control, preserved: with no SOURCE_COMMIT and no argument,
    UNPROVEN is still the honest answer and must not become a manufactured
    failure."""
    _receipt(tmp_path, finished_at=_iso(datetime.now(timezone.utc) - timedelta(minutes=5)),
             source_sha="whatever")
    out = timer_health(tmp_path)
    assert out["epoch_agreement"] == "UNPROVEN"
    assert "receipt_from_prior_epoch" not in out["unhealthy_reasons"]
