"""LQ-20261107-1527 — one unusable hygiene receipt must not blind the whole directory.

Live evidence, 2026-11-09 (read through `scripts/disk_usage_monitor.py`'s own reader):

    standing_hygiene_status(...) -> {"status": "invalid_receipt"}     # every poll since 11-05
    disk_hygiene_alert intents from disk_usage_monitor.standing_hygiene:
        7, all on 2026-11-02, nothing since 2026-11-02T15:45Z
    data/runtime/disk_hygiene/disk_hygiene_standing_apply_20261105T000628Z_*.json:
        a refused run whose report carries "run_id": null

The loop returned on the FIRST bad file, so that one 2026-11-05 report made every later
poll answer invalid_receipt. The monitor's promise — the operator's own words, "I need to be
alerted on when it runs" — queued nothing for four days while `/` sat critical at 92.9%,
and the newest hygiene run (2026-11-09T12:45Z) was REFUSED with 25.0 GiB held: exactly the
alert that never reached him.

The contract pinned here: an unusable receipt is skipped and counted; `invalid_receipt` is
returned only when files exist and none is usable; a report older than the freshness bound
is not news (the monitor polls every 15 minutes, so a real run is never that old) and is
counted, never replayed. Everything is a temp directory: no DB, no network, no send.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import disk_usage_monitor as M  # noqa: E402
from scripts import disk_hygiene as DH  # noqa: E402

NOW = datetime(2026, 11, 9, 14, 20, tzinfo=timezone.utc)
RULES = {
    "manifest": {"dir": "data/runtime/disk_hygiene"},
    "standing_apply": {"manifest_max_age_hours": 2, "monitor": {"digest_kind": "disk_hygiene_digest"}},
}
PREV = {"run_id": "d:disk-hygiene:live:20261102T1017", "held_bytes": 4 * 1024**2,
        "seen_run_ids": ["d:disk-hygiene:live:20261102T1017"]}


def _dir(tmp_path):
    d = DH.manifest_dir(RULES, tmp_path / "state")
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(directory, name, *, finished_at, run_id="run", **extra):
    payload = {"run_id": run_id, "manifest_sha256": "sha-" + name, "held_bytes": 0,
               "finished_at": finished_at, "operator_digest": "digest " + name}
    payload.update(extra)
    (directory / f"disk_hygiene_standing_apply_{name}.json").write_text(json.dumps(payload))


def _stamp(minutes_ago):
    return (NOW - timedelta(minutes=minutes_ago)).isoformat()


def test_one_receipt_without_a_run_id_does_not_blind_the_directory(tmp_path):
    """The live defect: a refused run wrote run_id null and silenced four days of digests."""
    d = _dir(tmp_path)
    _write(d, "20261105T000628Z_refused", finished_at="2026-11-05T00:07:07+00:00", run_id=None,
           refused="manifest_evidence_mismatch")
    _write(d, "20261109T131702Z", finished_at=_stamp(35), run_id="d:disk-hygiene:live:20261109T0717",
           held_bytes=25 * 1024**3, refused="evidence_recheck_unavailable")

    result = M.standing_hygiene_status(RULES, tmp_path / "state", PREV, NOW, 92.87)

    assert result["status"] == "new_run", "one bad receipt must not hide the good ones"
    assert result["run_id"] == "d:disk-hygiene:live:20261109T0717"
    assert result["skipped_unusable"] == 1


def test_an_unreadable_receipt_is_skipped_not_fatal(tmp_path):
    """A torn file (a write in flight) is not proof of anything — and not fatal either."""
    d = _dir(tmp_path)
    (d / "disk_hygiene_standing_apply_20261106T000000Z_torn.json").write_text('{"run_id": "x", ')
    _write(d, "20261109T131702Z", finished_at=_stamp(35), run_id="fresh")

    result = M.standing_hygiene_status(RULES, tmp_path / "state", PREV, NOW, 92.87)

    assert result["status"] == "new_run" and result["run_id"] == "fresh"
    assert result["skipped_unusable"] == 1


def test_invalid_receipt_is_still_said_when_nothing_in_the_directory_is_usable(tmp_path):
    """The old answer survives for the state that actually means it: no readable run at all."""
    d = _dir(tmp_path)
    _write(d, "20261105T000628Z_refused", finished_at="2026-11-05T00:07:07+00:00", run_id=None)

    assert M.standing_hygiene_status(RULES, tmp_path / "state", PREV, NOW, 92.87) == {
        "status": "invalid_receipt", "skipped_unusable": 1}


def test_a_stale_report_is_not_news_and_is_not_replayed(tmp_path):
    """Four days of missed digests must not be dialled one poll at a time when the lane recovers."""
    d = _dir(tmp_path)
    _write(d, "20261105T004754Z", finished_at="2026-11-05T00:47:31+00:00", run_id="ancient")
    _write(d, "20261109T131702Z", finished_at=_stamp(35), run_id="fresh")

    result = M.standing_hygiene_status(RULES, tmp_path / "state", PREV, NOW, 92.87)

    assert result["run_id"] == "fresh", "the newest fresh run is what the operator needs"
    assert result["stale_skipped"] == 1


def test_the_freshness_bound_can_be_narrowed_by_the_monitor_block(tmp_path):
    rules = {**RULES, "standing_apply": {**RULES["standing_apply"],
                                         "monitor": {"max_report_age_hours": 0.5}}}
    d = _dir(tmp_path)
    _write(d, "20261109T131702Z", finished_at=_stamp(60), run_id="an-hour-old")

    result = M.standing_hygiene_status(rules, tmp_path / "state", PREV, NOW, 92.87)

    assert result["status"] == "already_observed" and result["stale_skipped"] == 1


def test_a_future_stamp_is_unusable_not_fatal(tmp_path):
    d = _dir(tmp_path)
    _write(d, "20261109T150000Z", finished_at=(NOW + timedelta(minutes=40)).isoformat(), run_id="from-the-future")
    _write(d, "20261109T131702Z", finished_at=_stamp(35), run_id="fresh")

    result = M.standing_hygiene_status(RULES, tmp_path / "state", PREV, NOW, 92.87)

    assert result["run_id"] == "fresh" and result["skipped_unusable"] == 1


def test_a_refused_run_still_reaches_the_operator(tmp_path):
    """The alert the operator asked for: the newest run refused and is holding 25 GiB."""
    d = _dir(tmp_path)
    _write(d, "20261109T121702Z", finished_at=_stamp(95), run_id="d:disk-hygiene:live:20261109T0717",
           held_bytes=25 * 1024**3, refused="evidence_recheck_unavailable")

    result = M.standing_hygiene_status(RULES, tmp_path / "state", PREV, NOW, 92.87)

    assert result["status"] == "new_run" and result["alert"] == "hygiene_refused"
    assert "evidence_recheck_unavailable" == result["refused"]


def test_no_receipts_at_all_is_not_measured(tmp_path):
    _dir(tmp_path)
    assert M.standing_hygiene_status(RULES, tmp_path / "state", {}, NOW, 92.87) == {
        "status": "not_measured", "state": {}}


def test_an_unconfigured_standing_apply_block_is_untouched(tmp_path):
    assert M.standing_hygiene_status({"manifest": {"dir": "x"}}, tmp_path / "state", PREV, NOW, 92.87) == {
        "status": "not_configured"}
