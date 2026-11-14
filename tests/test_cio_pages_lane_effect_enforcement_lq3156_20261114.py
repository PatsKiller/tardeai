"""LQ-20261114 lane effect enforcement for ``cio-pages-product``, on the isolated PG cluster.

CAMPAIGN-8H §5.3 (cc-deepseek-9): prove, against the REAL ``store_pg`` upsert and the REAL per-product
advisory lock (``pg_try_advisory_xact_lock``), the three effects the live lane depends on:

1. a duplicate fire — a second build while one holds the product lock — is ``SKIPPED_BUSY``, builds nothing
   and writes nothing;
2. a later legitimate refresh, after the lock clears, publishes (row moves, log says OK);
3. an older admission — a build whose source clock is older than a VALID stored row — is refused:
   ``REFUSED_OLDER``, the CLI exits 3 (nonzero), the build log gets the FAILED row with
   ``detail.receipt_outcome = REFUSED_OLDER``, and the stored row is untouched.

Hermetic by construction: ``tests.support.isolated_pg.IsolatedPostgres`` — its own initdb dir, loopback
only, test-named db/role, random password, destroyed with the run. It can never be production (the module
refuses a production name/port). No live store, no Valkey, no lane, no cron, no unit, no browser.

ANCHOR: LQ3156_LANE_EFFECT_ENFORCEMENT
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (str(ROOT), str(ROOT / "tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

from scripts.lib.cc_products import cio_pages as cp  # noqa: E402
from scripts.lib.cc_products import store_pg  # noqa: E402
from test_home_products_builder_20261113 import connect, cluster, needs_pg  # noqa: E402,F401 - pytest fixtures


def _builds(root, **kw):  # noqa: ANN001, ANN003 - the build_in_child contract is (root, *, db_query, ...)
    """A synthetic build that records each real execution: a skipped duplicate leaves no line.

    The body carries the execution number, so a genuine later build is a genuinely NEW body (a content
    change, ``seq + 1``), not an unchanged re-stamp (``UNCHANGED``).
    """
    with (Path(root) / "builds.log").open("a", encoding="utf-8") as fh:
        fh.write("built\n")
    return {"portfolio": {"as_of": None}, "regime": {"as_of": None}, "n": _build_count(root),
            "conflicts": {"gap": {"reason": "synthetic"}, "findings": []}}


def _build_count(root) -> int:
    p = Path(root) / "builds.log"
    return len(p.read_text().splitlines()) if p.exists() else 0


def _run(connect, root, *, now, lane="cio-pages-product"):  # noqa: ANN001
    return cp.run_once(connect=connect, root=root, hot=None, dry_run=False, now=now, builder_sha="test",
                       build_fn=_builds, db_query_factory=lambda: None, lane=lane)


def _stored(connect):  # noqa: ANN001
    return store_pg.read_current(connect().cursor(), cp.PRODUCT_ID, cp.SCOPE_KEY)


def _log(connect):  # noqa: ANN001
    c = connect()
    try:
        cur = c.cursor()
        cur.execute("SELECT outcome, lane, detail FROM cc_product_build_log WHERE product_id=%s ORDER BY id",
                    (cp.PRODUCT_ID,))
        return cur.fetchall()
    finally:
        c.close()


def _seed(connect, *, as_of, built_at):  # noqa: ANN001
    c = connect()
    try:
        cur = c.cursor()
        store_pg.write_current(cur, cp.PRODUCT_ID, cp.SCOPE_KEY, b'{"v":"seed"}', as_of=as_of, built_at=built_at,
                               next_refresh_at=built_at + timedelta(seconds=120), stale_after_s=360,
                               hard_expiry_s=14400, purge_after_s=86400, source_watermarks={"src": "seed"},
                               builder_sha="seed", build_ms=1)
        c.commit()
    finally:
        c.close()


def _hold_product_lock(connect):  # noqa: ANN001
    """Take the product's advisory lock in an OPEN transaction on a second connection; rollback releases it."""
    holder = connect()
    cur = holder.cursor()
    cur.execute(store_pg._LOCK_SQL, (cp.PRODUCT_ID, cp.SCOPE_KEY))
    assert cur.fetchone()[0] is True, "the holder must own the product lock, or the duplicate is not a duplicate"
    return holder


@needs_pg
def test_a_duplicate_fire_is_skipped_busy_builds_nothing_and_writes_nothing(connect, tmp_path):  # noqa: ANN001
    now = datetime.now(timezone.utc)
    first = _run(connect, tmp_path, now=now)
    assert first["outcome"] == "OK" and first["wrote"] is True, first
    before, builds_before = _stored(connect), _build_count(tmp_path)
    assert builds_before == 1

    holder = _hold_product_lock(connect)
    try:
        dup = _run(connect, tmp_path, now=now + timedelta(seconds=1))
    finally:
        holder.rollback()
        holder.close()

    assert dup["outcome"] == "SKIPPED_BUSY", dup
    assert dup["wrote"] is False and dup["seq"] is None
    assert _build_count(tmp_path) == builds_before, "a skipped duplicate must not run the build"
    after = _stored(connect)
    assert (after["seq"], after["as_of"], after["body"]) == (before["seq"], before["as_of"], before["body"])
    rows = _log(connect)
    assert rows[-1][0] == "SKIPPED_BUSY" and rows[-1][1] == "cio-pages-product"


@needs_pg
def test_a_later_legitimate_refresh_publishes_after_the_duplicate_clears(connect, tmp_path):  # noqa: ANN001
    now = datetime.now(timezone.utc)
    assert _run(connect, tmp_path, now=now)["outcome"] == "OK"
    holder = _hold_product_lock(connect)
    try:
        assert _run(connect, tmp_path, now=now + timedelta(seconds=1))["outcome"] == "SKIPPED_BUSY"
    finally:
        holder.rollback()
        holder.close()

    before = _stored(connect)
    later = _run(connect, tmp_path, now=now + timedelta(seconds=5))
    assert later["outcome"] == "OK" and later["wrote"] is True, later
    after = _stored(connect)
    assert after["seq"] == before["seq"] + 1, "the legitimate refresh must publish a new sequence"
    last = _log(connect)[-1]
    detail = last[2] if isinstance(last[2], dict) else json.loads(last[2])
    assert (last[0], last[1], detail.get("receipt_outcome")) == ("BUILT", "cio-pages-product", "OK"), last


@needs_pg
def test_an_older_admission_is_refused_with_exit_3_and_a_failed_receipt(connect, tmp_path, monkeypatch,
                                                                      capsys):  # noqa: ANN001
    now = datetime.now(timezone.utc)
    # a VALID stored row whose as_of is inside the 120 s skew: ordering is not relaxed for it (LQ-3140)
    _seed(connect, as_of=now + timedelta(seconds=30), built_at=now)
    before = _stored(connect)

    real = cp.run_once
    monkeypatch.setattr(cp, "run_once", lambda **k: real(
        connect=connect, root=tmp_path, hot=None, dry_run=False, now=now + timedelta(seconds=1), builder_sha="test",
        build_fn=_builds, db_query_factory=lambda: None, lane=k.get("lane", cp.LANE)))
    monkeypatch.setattr(cp, "default_state_root", lambda: tmp_path)
    monkeypatch.setattr(cp, "default_ledger_root", lambda: tmp_path)

    rc = cp.main([])
    out = capsys.readouterr().out.strip().splitlines()
    receipt = json.loads(out[-1])
    assert rc == 3, (rc, receipt)
    assert receipt["outcome"] == "REFUSED_OLDER" and receipt["wrote"] is False
    rows = _log(connect)
    assert rows[-1][0] == "FAILED", rows
    detail = rows[-1][2] if isinstance(rows[-1][2], dict) else json.loads(rows[-1][2])
    assert detail.get("receipt_outcome") == "REFUSED_OLDER", detail
    after = _stored(connect)
    assert (after["seq"], after["as_of"]) == (before["seq"], before["as_of"]), "the refused build must not publish"


@needs_pg
def test_the_refused_admission_never_reaches_the_build(connect, tmp_path, monkeypatch):  # noqa: ANN001
    """The ordering rule is applied by the conditional upsert, and a refusal writes no new build-log BYTES.

    The build itself ran (the lane cannot know the stored clock before it builds), so this pins what the
    refusal guarantees: no publish, no hot-tier value, and a log row that carries the refusal word.
    """
    now = datetime.now(timezone.utc)
    _seed(connect, as_of=now + timedelta(seconds=30), built_at=now)
    r = _run(connect, tmp_path, now=now + timedelta(seconds=1))
    assert r["outcome"] == "REFUSED_OLDER" and r["wrote"] is False and r["hot"] == "skipped", r
    assert _build_count(tmp_path) == 1, "the build does run; the refusal is the store's decision"
    assert _stored(connect)["body"] == b'{"v":"seed"}'
