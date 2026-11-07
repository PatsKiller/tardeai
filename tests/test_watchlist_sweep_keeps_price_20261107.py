"""ANCHOR: WATCHLIST_SWEEP_KEEPS_PRICE_20261107 — LQ-20261107-56: a failed price lookup never overwrites a known price with NULL."""
from __future__ import annotations

import sys
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import watchlist_enrichment_sweep as W  # noqa: E402


class _Cur:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))


def _write(price, chg=None):
    cur = _Cur()
    W._write_row(cur, "CXMT", rsi=55.0, trend="neutral", score=60, advisory="RSI 55 · band mid", price=price, chg=chg,
                 floatm=10.0, rvol=1.2, score_kind="technical")
    return cur.calls[0]


def test_failed_lookup_keeps_the_last_good_price_and_marks_the_row_stale():
    sql, params = _write(None)
    assert "price=COALESCE(%s, price)" in sql                       # NULL in -> the stored price stays
    assert "change_pct=CASE WHEN %s::numeric IS NULL THEN change_pct ELSE %s END" in sql
    assert params[4] is None and params[5] is None                  # price and its change% are both "not known"
    assert params[3].endswith(W.STALE_PRICE_NOTE) and "price stale" in params[3]
    assert "last_enriched_at=NOW()" in sql                          # rotation continues: a never-priced symbol cannot hog the queue


def test_fresh_price_replaces_price_and_change_and_is_not_marked_stale():
    sql, params = _write(391.16, 1.5)
    assert params[4] == 391.16 and params[5] == 391.16 and params[6] == 1.5
    assert "stale" not in params[3]


def test_no_unconditional_price_assignment_remains_in_the_sweep():
    src = (ROOT / "scripts" / "watchlist_enrichment_sweep.py").read_text(encoding="utf-8")
    assert "price=%s," not in src.replace("price=COALESCE(%s, price),", "")
    assert src.count("UPDATE watchlist_items SET") == 1             # one writer, so the guarantee holds everywhere


# ── LQ-20261107-273: the kept price carries its OWN as_of; a failed lookup is its own fact ──────────────────

def _write_capture(price, chg=None, source=None):
    cur = _Cur()
    W._write_row(cur, "CXMT", rsi=55.0, trend="neutral", score=60, advisory="RSI 55 · band mid", price=price, chg=chg,
                 floatm=10.0, rvol=1.2, score_kind="technical", price_source=source, capture=True)
    return cur.calls[0]


def test_a_taken_price_stamps_its_own_observation_time_and_clears_the_failure():
    """The price's timestamp must move only when a price was actually taken. last_enriched_at moves on every
    attempt, including a failed one, and the card used to read it as the price's age."""
    sql, params = _write_capture(391.16, 1.5, source="market_quotes")
    assert "price_observed_at=CASE WHEN %s::numeric IS NULL THEN price_observed_at ELSE NOW() END" in sql
    assert "price_observed_source=CASE WHEN %s::numeric IS NULL THEN price_observed_source ELSE %s END" in sql
    assert "price_lookup_failed_at=CASE WHEN %s::numeric IS NULL THEN NOW() ELSE NULL END" in sql
    # the capture fragment sits with the other price facts, before first_seen_price
    assert sql.index("price_lookup_failed_at") < sql.index("first_seen_price")
    assert params[9] == 391.16                     # price: the observation CASE takes the price that was taken
    assert params[10] == 391.16                    # price: the source CASE keys off the same value
    assert params[11] == "market_quotes"           # the rung that supplied it
    assert params[12] == 391.16                    # price: a success clears price_lookup_failed_at


def test_a_failed_lookup_records_the_failure_and_leaves_the_kept_price_s_time_alone():
    sql, params = _write_capture(None)
    assert "price=COALESCE(%s, price)" in sql                       # LQ-56 still holds with capture on
    assert params[3].endswith(W.STALE_PRICE_NOTE)
    assert params[9] is None                       # NULL -> price_observed_at unchanged: the KEPT price's time
    assert params[10] is None and params[11] is None  # NULL -> source unchanged, nothing claimed about the rung
    assert params[12] is None                      # NULL -> price_lookup_failed_at = NOW(): the failure is recorded
    assert "last_enriched_at=NOW()" in sql


class _ColCur:
    def __init__(self, cols=None, raises=None):
        self.cols, self.raises, self.sql = cols, raises, None

    def execute(self, sql, params=None):
        self.sql = sql
        if self.raises:
            raise self.raises

    def fetchall(self):
        return [(c,) for c in (self.cols or [])]


def _capture_available(cols=None, raises=None):
    W._PRICE_CAPTURE_SUPPORT = None                # the module asks once per process; ask again per test
    try:
        return W.price_capture_available(_ColCur(cols=cols, raises=raises))
    finally:
        W._PRICE_CAPTURE_SUPPORT = None


def test_price_capture_support_is_exactly_when_all_three_columns_exist():
    assert _capture_available(list(W.PRICE_CAPTURE_COLUMNS)) is True
    assert _capture_available([]) is False
    assert _capture_available(["price_observed_at", "price_observed_source"]) is False   # partial apply is not enough


def test_an_unreadable_column_check_keeps_the_lane_on_the_old_row_shape():
    """Fail closed on the NEW columns: a lane that cannot confirm the migration must still enrich."""
    assert _capture_available(raises=RuntimeError("permission denied")) is False


def test_capture_stays_off_on_a_dry_run():
    """A dry run must issue no write and must not reach for columns it will not use."""
    src = (ROOT / "scripts" / "watchlist_enrichment_sweep.py").read_text(encoding="utf-8")
    assert "capture = price_capture_available(cur) if not dry else False" in src


# ── the card half of LQ-273 is proved by a render test, which pytest cannot collect ────────────────────────

RENDER = ROOT / "apps/command-center-v3/src/lib/watchlistPriceMark.view.test.mjs"


def test_the_card_render_test_runs_in_the_job_that_has_the_packages():
    """The proof is a render of the real card, so it needs `typescript` and `react-dom` — the frontend build
    chain, not the Python shard. It runs because discovery finds it; this guard fails if it stops being found
    or becomes dormant (the FQ-076 pattern)."""
    assert RENDER.is_file(), f"the render test is missing: {RENDER}"
    app = ROOT / "apps/command-center-v3"
    pkg = json.loads((app / "package.json").read_text(encoding="utf-8"))
    assert "scripts/run-tests.mjs" in pkg["scripts"]["build"], (
        "the frontend build chain no longer runs the discovered test set — the card has lost its proof")
    assert re.search(r"\.test\.(ts|mjs|js|tsx|jsx)$", RENDER.name), (
        f"{RENDER.name} does not match the runner's discovery pattern, so it would never run")
    rel = str(RENDER.relative_to(app))
    dormant = json.loads((app / "scripts/tests.dormant.json").read_text(encoding="utf-8")).get("files") or {}
    assert rel not in dormant, f"the render test is dormant ({rel}); discovery will not run it"


def test_the_gate_names_the_file_that_carries_the_anchor():
    gate = ROOT / "config/ci_gates/watchlist_sweep_keeps_price_20261107.json"
    doc = json.loads(gate.read_text(encoding="utf-8"))
    assert doc["name"] == gate.stem, "the gate name must equal its file stem"
    assert doc["files"] == ["tests/test_watchlist_sweep_keeps_price_20261107.py"], doc["files"]
    assert "WATCHLIST_SWEEP_KEEPS_PRICE_20261107" in " ".join(doc.get("comment") or [])
