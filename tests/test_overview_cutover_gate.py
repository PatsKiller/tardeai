"""INC-OVW / OP-041: the cutover gate refuses a stored-only reader it cannot prove is fed.

Every case is synthetic: a release directory holding just enough of ``scripts/api_v2.py`` for the reader-mode
read, a projection document and a LaneRunReceipt@v2 written from fixtures into a tmp state root. No DB, no
network, no live state root, isolated clocks.

The gate's teeth are what matter here: a missing projection, a wrong schema/status, another release's body, an
expired body, a body with no source clocks, and a receipt that does not exist / failed / is another release's /
is older than one max gap must each be a refusal ON THEIR OWN. One positive case and one rollback case keep it
from being a gate that simply refuses everything.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import check_overview_cutover as G
from scripts.lib import overview_lane_contract as C

ROOT = Path(__file__).resolve().parents[1]
SHA = "cafebabe1234567890abcdef1234567890abcdef"
NOW = datetime.fromisoformat("2026-11-16T15:00:00+00:00").timestamp()   # a Monday, in-hours

STORED_ONLY_SRC = '''
def _overview_served():
    """serves the projection; never computes"""
    if _overview_projection is None:
        return _overview_with_today_move()
    return _overview_projection.serve(
        None,  # explicit: there is no compute fallback
        identity=_OVERVIEW_CODE_IDENTITY[0],
        invalidated_at_fn=_overview_projection.invalidation_reader(_ovp_swr),
    )


def research_ticker(symbol):
    return symbol
'''

INLINE_SRC = '''
def _overview_served():
    """R6: computes inline when the projection is not servable"""
    if _overview_projection is None:
        return _overview_with_today_move()
    return _overview_projection.serve(
        _overview_with_today_move,
        identity=_OVERVIEW_CODE_IDENTITY[0],
        invalidated_at_fn=_overview_projection.invalidation_reader(_ovp_swr),
    )
'''

UNKNOWN_SRC = '''
def _overview_served():
    return _overview_projection.serve(something_else, identity="x")
'''


def _release(tmp_path: Path, src: str, window: float | None = 5400.0) -> Path:
    """A release directory: the served route's source, its build sha, and - for a stored-only release - its own
    module with the last-good window the gate reads from the RELEASE (never from the tree it is run in)."""
    rel = tmp_path / "release"
    (rel / "scripts" / "lib").mkdir(parents=True, exist_ok=True)
    (rel / "scripts" / "api_v2.py").write_text(src)
    (rel / "BUILD_SHA").write_text(SHA + "\n")
    if window is not None:
        (rel / "scripts" / "lib" / "overview_projection.py").write_text(
            f'"""synthetic release copy"""\nSCHEMA = "OverviewProjection@v1"\nLAST_GOOD_MAX_S = {window}\n')
    return rel


def _body(with_clocks: bool = True, future_clock: bool = False) -> dict:
    """A synthetic body in the REAL shape (flat: the producer stores what the route computes, not the envelope)."""
    body = {"as_of": "2026-11-13T16:00:00-05:00", "data_as_of": "2026-11-13", "lookthrough_as_of": "2026-11-13",
            "journal": {"last_close_date": "2026-11-10"},
            "clock_provenance": {"positions": {"as_of": "2026-11-13T16:00:00Z"}, "day_pnl": {"as_of": None}},
            "market_session": {"as_of": "2026-11-16T15:00:00Z", "latest_open_session": "2026-11-13"}}
    if future_clock:
        body["as_of"] = "2030-01-01T00:00:00Z"
    return body


def _write_projection(root: Path, *, built_at: float, sha: str = SHA, status: str = "ok",
                      schema: str = "OverviewProjection@v1", with_clocks: bool = True,
                      future_clock: bool = False) -> Path:
    path = root / "data" / "runtime" / "overview_projection.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = _body(with_clocks=with_clocks, future_clock=future_clock)
    doc = {
        "schema": schema, "status": status, "started_at_epoch": built_at - 1.0, "built_at_epoch": built_at,
        "built_at": datetime.fromtimestamp(built_at, tz=timezone.utc).isoformat(),
        "started_at": datetime.fromtimestamp(built_at - 1.0, tz=timezone.utc).isoformat(), "build_ms": 1000,
        "code_identity": f"sha:{sha}", "inputs": {},
        "body": body,
    }
    if with_clocks:
        doc["source_clocks"] = C.source_clocks(body)
    path.write_text(json.dumps(doc))
    return path


def _write_receipt(root: Path, *, ok_at: float = NOW - 30, sha: str = SHA, status: str = "ok") -> Path:
    path = root / "data" / "runtime" / "overview-projection_last.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema": "LaneRunReceipt@v2", "lane_id": "overview-projection", "mode": "live", "status": status,
        "ok_at": datetime.fromtimestamp(ok_at, tz=timezone.utc).isoformat(),
        "finished_at": datetime.fromtimestamp(ok_at, tz=timezone.utc).isoformat(),
        "code_sha": sha, "consecutive_failures": 0 if status == "ok" else 3, "empty_reason": None,
    }))
    return path


def _gate(tmp_path: Path, src: str = STORED_ONLY_SRC, **over) -> dict:
    root = tmp_path / "state"
    root.mkdir(exist_ok=True)
    rel = over.pop("release", None) or _release(tmp_path, src)
    kw = dict(release_dir=rel, state_root=root, now=NOW, sha=SHA)
    kw.update(over)
    return G.check(**kw)


def _codes(verdict: dict) -> set[str]:
    return {r["code"] for r in verdict["refusals"]}


# ── the positive case ──────────────────────────────────────────────────────────────────────────────────────────
def test_a_fed_stored_only_reader_is_admitted(tmp_path):
    root = tmp_path / "state"
    (root / "data" / "runtime").mkdir(parents=True)
    _write_projection(root, built_at=NOW - 40)
    _write_receipt(root)
    verdict = _gate(tmp_path)
    assert verdict["admit"] is True, verdict["refusals"]
    assert verdict["reader_mode"] == G.READER_STORED_ONLY
    # the verdict describes the RELEASE, not the tree the gate happens to run in: the release's own window decides
    assert verdict["checks"]["release_window_s"] == 5400.0


# ── each refusal on its own ───────────────────────────────────────────────────────────────────────────────────
def test_a_missing_projection_is_refused(tmp_path):
    verdict = _gate(tmp_path)
    assert _codes(verdict) >= {"no_receipt", "projection_missing"}


@pytest.mark.parametrize("kw,code", [
    ({"schema": "SomethingElse@v1"}, "projection_schema"),
    ({"status": "failed"}, "projection_status"),
    ({"sha": "deadbeef"}, "projection_code_mismatch"),
    ({"with_clocks": False}, "source_clocks_absent"),
    ({"future_clock": True}, "source_clock_in_future"),
])
def test_a_bad_projection_is_refused(tmp_path, kw, code):
    root = tmp_path / "state"
    _write_projection(root, built_at=NOW - 40, **kw)
    _write_receipt(root)
    verdict = _gate(tmp_path, state_root=root)
    assert code in _codes(verdict), verdict["refusals"]
    assert verdict["admit"] is False


def test_an_expired_projection_is_refused(tmp_path):
    rel = _release(tmp_path, STORED_ONLY_SRC)
    window = G.release_window(rel)
    assert window == 5400.0

    root = tmp_path / "state"
    _write_projection(root, built_at=NOW - (window + 60))
    _write_receipt(root)
    verdict = _gate(tmp_path, release=rel, state_root=root)
    assert "projection_expired" in _codes(verdict)


@pytest.mark.parametrize("kw,code", [
    ({"sha": "deadbeef"}, "receipt_code_mismatch"),
    ({"status": "failed"}, "receipt_failed"),
    ({"ok_at": NOW - 4000}, "receipt_stale"),
])
def test_a_bad_receipt_is_refused(tmp_path, kw, code):
    root = tmp_path / "state"
    _write_projection(root, built_at=NOW - 40)
    _write_receipt(root, **kw)
    verdict = _gate(tmp_path, state_root=root)
    assert code in _codes(verdict), verdict["refusals"]


def test_an_unknown_reader_is_refused(tmp_path):
    root = tmp_path / "state"
    _write_projection(root, built_at=NOW - 40)
    _write_receipt(root)
    verdict = _gate(tmp_path, src=UNKNOWN_SRC, state_root=root)
    assert "reader_mode_unknown" in _codes(verdict)
    assert verdict["admit"] is False


def test_the_release_window_is_judged_against_the_derived_floor(tmp_path):
    """The incident's release, verbatim: LAST_GOOD_MAX_S 1800 s against a 5040 s floor.

    The floor comes from the fold tree's config; the window from the release's own module. The refusal must name
    the verified patch that raises it - an operator reading the log should not have to work out which artifact
    fixes it. The same projection and receipt with the patched window are admitted: the gate's teeth are the
    number, not a blanket refusal.
    """
    root = tmp_path / "state"
    _write_projection(root, built_at=NOW - 40)
    _write_receipt(root)
    unpatched = _release(tmp_path, STORED_ONLY_SRC, window=1800.0)
    verdict = G.check(release_dir=unpatched, state_root=root, now=NOW, sha=SHA)
    assert verdict["admit"] is False and "contract_unsatisfied" in _codes(verdict)
    detail = next(r["detail"] for r in verdict["refusals"] if r["code"] == "contract_unsatisfied")
    assert C.PATCH_REL in detail and "5400" in detail, detail
    assert verdict["checks"]["release_window_s"] == 1800.0

    patched = _release(tmp_path / "patched", STORED_ONLY_SRC, window=5400.0)
    admitted = G.check(release_dir=patched, state_root=root, now=NOW, sha=SHA)
    assert admitted["admit"] is True, admitted["refusals"]


def test_a_stored_only_release_without_a_window_is_refused(tmp_path):
    """No constant, no window to judge: fail closed rather than assume the body can be served for ever."""
    root = tmp_path / "state"
    _write_projection(root, built_at=NOW - 40)
    _write_receipt(root)
    verdict = G.check(release_dir=_release(tmp_path, STORED_ONLY_SRC, window=None), state_root=root, now=NOW, sha=SHA)
    assert "release_window_absent" in _codes(verdict)
    assert verdict["admit"] is False


def test_an_inline_reader_is_admitted_even_when_the_contract_cannot_be_read(tmp_path, monkeypatch):
    """A rollback must not need the registry row or the window to exist: the R8 reader computes on the thread."""
    def boom(*_a, **_k):
        raise C.ContractError("registry row missing")

    monkeypatch.setattr(C, "contract", boom)
    verdict = G.check(release_dir=_release(tmp_path, INLINE_SRC), state_root=tmp_path / "state", now=NOW, sha=SHA)
    assert verdict["admit"] is True, verdict["refusals"]
    assert any(w["code"] == "contract::contract_unreadable" for w in verdict["warnings"])


def test_a_tree_that_describes_another_reader_names_the_skew(tmp_path):
    """The contract block is the TREE's; the verdict is the RELEASE's.

    An R7 tree judging an inline release would otherwise print a stored-only window (ok=false) right beside an
    inline verdict and invite an operator to read the wrong number as the one being activated.
    """
    root = tmp_path / "state"
    _write_projection(root, built_at=NOW - 40)
    _write_receipt(root)
    skew = dict(C.contract(ROOT), reader="stored_only", last_good_max_s=1800.0, headroom_s=-3240.0, ok=False)
    verdict = G.check(release_dir=_release(tmp_path, INLINE_SRC), state_root=root, now=NOW, sha=SHA,
                      contract_doc=skew)
    assert verdict["admit"] is True
    assert any(w["code"] == "contract::reader_skew" for w in verdict["warnings"]), verdict["warnings"]


def test_a_matching_reader_draws_no_skew_warning(tmp_path):
    """The same words, spelled for the release: no warning. (The tree's own reader mode is not asserted here -
    on the R7 tree it is stored-only and on the R8 fold it is inline, and this test must read the same on both.)"""
    root = tmp_path / "state"
    _write_projection(root, built_at=NOW - 40)
    _write_receipt(root)
    matching = dict(C.contract(ROOT), reader="stored_only", last_good_max_s=5400.0, headroom_s=360.0, ok=True)
    verdict = G.check(release_dir=_release(tmp_path, STORED_ONLY_SRC), state_root=root, now=NOW, sha=SHA,
                      contract_doc=matching)
    assert verdict["admit"] is True, verdict["refusals"]
    assert not any(w["code"] == "contract::reader_skew" for w in verdict["warnings"]), verdict["warnings"]


# ── rollback compatibility: R6 computes inline, so the gate must never block it ───────────────────────────────
def test_an_inline_reader_is_admitted_even_with_a_missing_projection(tmp_path):
    """A rollback to R6 must not be blocked by this gate's state: there, the projection is an optimisation."""
    verdict = _gate(tmp_path, src=INLINE_SRC)
    assert verdict["admit"] is True, verdict["refusals"]
    assert verdict["reader_mode"] == G.READER_INLINE
    assert any(w["code"] == "inline_fallback_reader" for w in verdict["warnings"])


def test_an_inline_reader_with_a_corrupt_projection_still_admits(tmp_path):
    root = tmp_path / "state"
    path = root / "data" / "runtime" / "overview_projection.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{broken")
    verdict = _gate(tmp_path, src=INLINE_SRC, state_root=root)
    assert verdict["admit"] is True
    assert any(w["code"].startswith("projection::") for w in verdict["warnings"])


# ── the bounded wait: a receipt that lands during the wait admits ─────────────────────────────────────────────
def test_the_wait_admits_a_receipt_that_lands_while_waiting(tmp_path):
    root = tmp_path / "state"
    _write_projection(root, built_at=NOW - 40)
    rel = _release(tmp_path, STORED_ONLY_SRC)
    clock = {"t": NOW}

    def fake_sleep(seconds: float) -> None:
        clock["t"] += seconds
        if not (root / "data" / "runtime" / "overview-projection_last.json").exists():
            _write_receipt(root, ok_at=clock["t"] - 5)

    verdict = G.check(release_dir=rel, state_root=root, sha=SHA, now=NOW, wait_s=420,
                      sleep=fake_sleep, clock=lambda: clock["t"])
    assert verdict["admit"] is True, verdict["refusals"]


def test_the_wait_gives_up_and_refuses(tmp_path):
    root = tmp_path / "state"
    _write_projection(root, built_at=NOW - 40)
    rel = _release(tmp_path, STORED_ONLY_SRC)
    clock = {"t": NOW}
    verdict = G.check(release_dir=rel, state_root=root, sha=SHA, now=NOW, wait_s=60,
                      sleep=lambda s: clock.__setitem__("t", clock["t"] + s), clock=lambda: clock["t"])
    assert verdict["admit"] is False and "no_receipt" in _codes(verdict)
    assert clock["t"] - NOW >= 60


# ── the CLI contract the deploy script relies on ──────────────────────────────────────────────────────────────
def test_cli_exit_codes(tmp_path, capsys):
    root = tmp_path / "state"
    _write_projection(root, built_at=NOW - 40)
    _write_receipt(root)
    rel = _release(tmp_path, STORED_ONLY_SRC)
    import time as _time
    real_now = _time.time()
    # the fixture clock is 2026-11-16T15:00Z; the CLI reads the real clock, so age it relative to that
    _write_projection(root, built_at=real_now - 40)
    _write_receipt(root, ok_at=real_now - 30)
    rc = G.main(["--release-dir", str(rel), "--state-root", str(root), "--sha", SHA, "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0 and out["admit"] is True, out["refusals"]
    rc = G.main(["--release-dir", str(rel), "--state-root", str(tmp_path / "empty"), "--sha", SHA, "--json"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 2 and out["admit"] is False
