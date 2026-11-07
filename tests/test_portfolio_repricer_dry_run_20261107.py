"""portfolio-repricer's ``--dry-run`` is a real, write-free proof (§23 onboarding step 5).

LQ-20261107-01 moves the lane from cron to n8n. The cutover allowlist needs a ``dry_run_arg`` that the
factory can execute against the live state root to prove the lane is wired and sane BEFORE n8n becomes the
runner. For a money writer that proof has to be stronger than "it exited 0": the whole point is that the
run reads the book, prices it exactly as a live pass would, prints the same before/after totals — and
writes nothing at all, so an operator can run it at 10:00 ET without touching ``holdings.json``.

What "writes nothing" has to mean for this lane, and what this file pins:

1. no holdings write lock (``/tmp/holdings_write.lock`` is itself a write, and a dry run must not queue
   behind a live writer),
2. no ``atomic_write_bytes`` on any ``holdings.json`` copy,
3. no ``finviz_quote_cache.json`` write (the count is computed and returned, the file is untouched and its
   directory is not created),
4. no ticker snapshot rebuild, no ``ticker_prices`` sync, no watchlist-membership sync,
5. no ``LaneRunReceipt`` (a dry run is not a run; a receipt written here would make the grader believe a
   real pass happened),
6. one ``LANE_OUTPUT`` line on stderr with ``mode=dry_run`` and ``empty_reason=dry_run``, so the executor
   can bind the attempt without a receipt.

Test 4 is the fail-on-old control: with the same fixture and no ``dry_run``, the run DOES write bytes and
DOES write a receipt. Without it, every "nothing changed" assertion below could pass on a run that never
did anything.

Hermetic: providers are stubbed, the state dir is ``tmp_path``, no live store, no broker, no network.
ANCHOR: REPRICER_DRY_RUN_20261107
"""
from __future__ import annotations

import io
import contextlib
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import portfolio_repricer as R  # noqa: E402
from scripts.lib import lane_output  # noqa: E402


# ── fixtures ─────────────────────────────────────────────────────────────────
def _state_dir(root: Path) -> Path:
    d = root / "data" / "portfolios" / "state"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _document() -> dict:
    """One priced holding in one account — enough for the coverage guard and the drift guard to pass."""
    return {
        "holdings": [{
            "account": "acct_a", "symbol": "ABC", "shares": 10, "price": 100.0,
            "market_value": 1000.0, "cost_basis": 900.0, "gain_loss": 100.0,
        }],
        "portfolio_totals": {"total_value": 1000.0, "day_change": 0.0},
        "account_summaries": {"acct_a": {"total_value": 1000.0, "day_change": 0.0, "cash": 0.0}},
    }


def _write_book(state: Path) -> Path:
    hp = state / "holdings.json"
    hp.write_text(json.dumps(_document(), indent=2), encoding="utf-8")
    # A stale cache entry so the dry run has a real delta to compute (and still must not write it).
    (state / "finviz_quote_cache.json").write_text(
        json.dumps({"ABC": {"symbol": "ABC", "price": 90.0, "change_pct": 0.0, "volume": 100},
                    "_meta": {"last_updated": "2026-11-06 15:00:00 ET", "symbols_cached": 1}},
                   indent=2),
        encoding="utf-8")
    return hp


def _receipt(root: Path) -> Path:
    return root / "data" / "runtime" / "portfolio-repricer_last.json"


def _snapshot(root: Path) -> dict:
    """Every file under the root: path → (bytes, mtime_ns). The proof is that this dict is unchanged."""
    out = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            st = p.stat()
            out[str(p.relative_to(root))] = (p.read_bytes(), st.st_mtime_ns)
    return out


def _stub_providers(monkeypatch, price: float = 110.0) -> None:
    monkeypatch.setattr(R, "_load_env", lambda root: None, raising=False)
    monkeypatch.setattr(R, "_fetch_finviz", lambda syms, root: {
        s: {"price": price, "change_pct": round((price / 100.0 - 1) * 100, 4),
            "prev_close": 100.0, "volume": 500, "source": "finviz_elite"} for s in syms
    }, raising=False)
    monkeypatch.setattr(R, "_fetch_data_broker_quotes", lambda syms, root, batch_reader=None: {}, raising=False)
    monkeypatch.setattr(R, "_fetch_fidelity_from_cache", lambda syms, root: {}, raising=False)
    # _load_intraday_fills reaches the database; this file must not.
    monkeypatch.setattr(R, "_load_intraday_fills", lambda *a, **k: {}, raising=False)
    # ticker_prices sync writes a real store; test_dry_run_calls_no_writer_and_takes_no_lock re-patches it with a
    # raising spy, so stubbing it here does not weaken the gate proof.
    monkeypatch.setattr(R, "_sync_ticker_prices", lambda *a, **k: None, raising=False)
    # The canonical-quote annotator reads the CIO store; this file is about writes, not annotations.
    monkeypatch.setattr(R, "_annotate_canonical_quotes", lambda holdings: None, raising=False)
    # The watchlist-membership sync is a real DB writer main() calls after the holdings write.
    fake_wl = types.ModuleType("sync_portfolio_watchlist_membership")
    fake_wl.sync_portfolio_watchlist_membership = lambda portfolio: {}
    monkeypatch.setitem(sys.modules, "sync_portfolio_watchlist_membership", fake_wl)


def _run(main_state, monkeypatch, *, dry_run: bool):
    """Run main() with stdout captured; returns (stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            R.main([main_state], dry_run=dry_run)
        except SystemExit as exc:  # a refusal/failure path still has to be inspected by the caller
            return out.getvalue(), err.getvalue(), exc.code
    return out.getvalue(), err.getvalue(), 0


# ── the proof ────────────────────────────────────────────────────────────────
def test_dry_run_changes_no_bytes_and_writes_no_receipt(monkeypatch, tmp_path):
    state = _state_dir(tmp_path)
    _write_book(state)
    _stub_providers(monkeypatch)
    before = _snapshot(tmp_path)

    stdout, _stderr, code = _run(state, monkeypatch, dry_run=True)

    assert code == 0, stdout
    assert _snapshot(tmp_path) == before, "a dry run must leave every byte (and mtime) where it was"
    assert not _receipt(tmp_path).exists(), "a dry run is not a run — it must not write a lane receipt"
    # It really did the work: the fetched marks were applied in memory (day change +$100 on 10 shares from
    # 100 → 110), the cache delta was computed, and the same totals a live pass would report were printed.
    # The portfolio total does not move because this lane reprices into `canonical_mark` /
    # `analytical_market_value` and deliberately never overwrites the broker's `market_value`.
    assert "DRY RUN — nothing written" in stdout
    assert "Quote cache: 1 symbols would update" in stdout
    assert "After: $1,000 | Day: $+100" in stdout


def test_dry_run_calls_no_writer_and_takes_no_lock(monkeypatch, tmp_path):
    state = _state_dir(tmp_path)
    _write_book(state)
    _stub_providers(monkeypatch)

    def _forbidden(*_a, **_k):
        raise AssertionError("a dry run must not call this writer")

    # Holdings write lock (its lockfile is itself a write) and the holdings payload writer.
    monkeypatch.setattr("scripts.lib.holdings_write_lock.holdings_write_lock", _forbidden, raising=False)
    monkeypatch.setattr("scripts.lib.atomic_json_store.atomic_write_bytes", _forbidden, raising=False)
    # ticker_prices sync and the receipt writer.
    monkeypatch.setattr(R, "_sync_ticker_prices", _forbidden, raising=False)
    monkeypatch.setattr(R, "_write_run_receipt", _forbidden, raising=False)
    # The two lazily-imported modules that write from inside reprice_portfolio / main.
    fake_snap = types.ModuleType("ticker_snapshot_builder")
    fake_snap.build_ticker_snapshot = _forbidden
    monkeypatch.setitem(sys.modules, "ticker_snapshot_builder", fake_snap)
    fake_wl = types.ModuleType("sync_portfolio_watchlist_membership")
    fake_wl.sync_portfolio_watchlist_membership = _forbidden
    monkeypatch.setitem(sys.modules, "sync_portfolio_watchlist_membership", fake_wl)

    stdout, _stderr, code = _run(state, monkeypatch, dry_run=True)

    assert code == 0, stdout
    assert "Ticker snapshot: would rebuild" in stdout
    assert "ticker_prices: would sync" in stdout


def test_dry_run_emits_one_lane_output_line(monkeypatch, tmp_path):
    state = _state_dir(tmp_path)
    _write_book(state)
    _stub_providers(monkeypatch)

    _stdout, stderr, code = _run(state, monkeypatch, dry_run=True)

    assert code == 0
    block = lane_output.parse(stderr)
    assert block is not None, f"no LANE_OUTPUT line on stderr: {stderr!r}"
    assert block["lane_id"] == "portfolio-repricer"
    assert block["mode"] == "dry_run"
    assert block["produced_count"] == 0
    assert block["attempted_count"] == 1
    assert block["empty_reason"] == "dry_run"
    assert stderr.count(lane_output.PREFIX) == 1, "exactly one line, in every mode"


def test_a_real_run_with_the_same_fixture_does_write(monkeypatch, tmp_path):
    """Fail-on-old control: strip the dry-run behaviour and the assertions above would be vacuous."""
    state = _state_dir(tmp_path)
    _write_book(state)
    _stub_providers(monkeypatch)
    before = _snapshot(tmp_path)

    stdout, _stderr, code = _run(state, monkeypatch, dry_run=False)

    assert code == 0, stdout
    after = _snapshot(tmp_path)
    assert after != before, "the control run must change something, or the dry-run proof proves nothing"
    assert _receipt(tmp_path).is_file(), "a real pass writes its lane receipt"
    assert json.loads(_receipt(tmp_path).read_text(encoding="utf-8"))["status"] == "ok"


def test_update_quote_cache_dry_run_creates_neither_dir_nor_file(tmp_path):
    """The cache writer is the one place a dry run could create a directory by accident."""
    state = tmp_path / "no-such-dir" / "state"
    cache = state / "finviz_quote_cache.json"
    n = R._update_quote_cache({"ABC": {"price": 110.0, "change_pct": 1.0, "prev_close": 108.9,
                                      "volume": 500, "source": "finviz_elite"}},
                              cache, "2026-11-07 10:00:00 ET", dry_run=True)
    assert n == 1
    assert not state.exists(), "a dry run must not create the cache directory"
    assert not cache.exists()


def test_missing_holdings_dry_run_exits_1_and_writes_no_receipt(tmp_path):
    state = _state_dir(tmp_path)
    stdout, _stderr, code = _run(state, None, dry_run=True)
    assert code == 1
    assert "holdings.json not found" in stdout
    assert not _receipt(tmp_path).exists()


def test_a_broker_only_quote_record_does_not_crash_the_cache(tmp_path):
    """Found by the first live ``--dry-run`` (2026-11-07): with Finviz unavailable the data-broker supplement
    prices every gap, and its record carries price/change/volume/source only. The cache writer then raised
    ``KeyError('analyst')`` and the whole lane died BEFORE its write — in a live pass too, not just the proof.
    An absent field must leave the cached Finviz value alone, never erase it."""
    cache = tmp_path / "finviz_quote_cache.json"
    cache.write_text(json.dumps({"ABC": {"symbol": "ABC", "price": 90.0, "volume": 100,
                                         "analyst": "Strong Buy"}}), encoding="utf-8")

    n = R._update_quote_cache(
        {"ABC": {"price": 110.0, "change_pct": 1.0, "prev_close": 108.9, "volume": 500,
                 "source": "data_broker.market_quote"}},
        cache, "2026-11-07 10:41:00 ET", dry_run=False)

    assert n == 1
    merged = json.loads(cache.read_text(encoding="utf-8"))["ABC"]
    assert merged["price"] == 110.0
    assert merged["source"] == "data_broker.market_quote"
    assert merged["analyst"] == "Strong Buy", "a field the source did not send must not be erased"


def test_cli_accepts_the_dry_run_flag_without_touching_the_state_root(tmp_path):
    """The flag has to reach main() through ``if __name__ == "__main__"``, which no import can exercise."""
    state = _state_dir(tmp_path)          # deliberately no holdings.json: the guard exits before any provider call
    env = {"TRADEAI_PERSISTENT_STATE_ROOT": str(tmp_path), "PATH": "/usr/bin:/bin"}
    proc = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "portfolio_repricer.py"), "--dry-run"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, env=env, timeout=120,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "holdings.json not found" in proc.stdout
    assert not _receipt(tmp_path).exists(), "the dry-run missing-file path must not write a receipt"
