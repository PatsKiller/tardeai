"""positions_store phase-3 reader batch #1 — the Watch held flag reads positions_current (operator 2026-10-22).

Operator reply, verbatim, to "Use the broker-synced store for 'held' on Watch: Watch becomes positions batch #1 …
Recommend: yes": "I take your recommendations on above." (AGENTS.md §7A: the positions store has no reader until the
operator approves each phase-3 reader batch; §17: that approval is the operator's.)

1. The switch is ON in config for surface "watch" only; a Watch caller reads the store by default.
2. A caller with no surface (advice digest, opportunity) never reads the store.
3. Stale, empty or unreadable store -> holdings.json with an explicit fallback_reason, never silently.
4. The registry row lists the approved reader with a complete operator approval.
5. check_data_source_authority.py passes with the reader registered, and fails an unregistered reader.

Fakes only: no database, no network, no broker, no production state.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import check_data_source_authority as gate  # noqa: E402
from lib.data_broker import watch_decision as wd  # noqa: E402
from lib.data_broker import watch_domains as wdom  # noqa: E402

SAT = datetime(2026, 10, 24, 15, 0, tzinfo=timezone.utc)      # market closed -> 72 h positions_sync contract
AUTH = json.loads((ROOT / "config" / "data_source_authority.json").read_text(encoding="utf-8"))
READER_FILE = "scripts/lib/data_broker/watch_domains.py"


def _row():
    return next(d for d in AUTH["domains"] if d["domain"] == "positions_store")


def _holdings(tmp_path):
    p = tmp_path / "holdings.json"
    p.write_text(json.dumps({"updated_at": SAT.isoformat(),
                             "holdings": [{"symbol": "RTX", "shares": 10, "market_value": 1900.0}]}))
    return p


def _store(finished_at=None, *, rows=True, boom=False):
    calls = []

    def q(sql, params=None, fetch="all"):
        calls.append(sql)
        if boom:
            raise RuntimeError("db down")
        if not rows:
            return []
        return [{"symbol": "NVDA", "qty": 5, "is_cash": False, "as_of": finished_at, "finished_at": finished_at}]
    return q, calls


# ── 1 ── on by default, for Watch ─────────────────────────────────────────────

def test_config_turns_the_reader_on_for_watch_only():
    held = wd.load_config()["held"]
    assert held["positions_store_reader"] is True
    # 2026-10-22: operator "approve all" item G added "home" as reader batch #3
    # (tests/test_positions_reader_batch3_home_20261022.py); "watch" stays first, nothing else is admitted.
    assert held["positions_store_reader_surfaces"] == ["watch", "home"]
    assert wdom.WATCH_SURFACE == "watch"


def test_watch_reads_positions_current_by_default(tmp_path):
    q, calls = _store(SAT - timedelta(hours=2))
    h = wdom.held_positions(db_query=q, holdings_path=_holdings(tmp_path), registry={}, now=SAT,
                            surface=wdom.WATCH_SURFACE)          # cfg from config/watch_decision_standards.yaml
    assert calls and "FROM positions_current" in calls[0]
    assert h["source"] == "positions_store.positions_current" and h["symbols"] == {"NVDA"}
    assert h["positions_store_reader"] is True and h["fallback_reason"] is None and h["stale"] is False


# ── 2 ── only the approved surface ────────────────────────────────────────────

def test_a_caller_without_a_surface_never_reads_the_store(tmp_path):
    q, calls = _store(SAT - timedelta(hours=2))
    h = wdom.held_positions(db_query=q, holdings_path=_holdings(tmp_path), registry={}, now=SAT)
    assert calls == [] and h["source"] == "holdings_accounts.holdings_json" and h["positions_store_reader"] is False
    h = wdom.held_positions(db_query=q, holdings_path=_holdings(tmp_path), registry={}, now=SAT,
                            surface="advice_digest")
    assert calls == [] and h["positions_store_reader"] is False


def test_missing_surface_list_fails_closed():
    assert wdom.store_reader_on({"positions_store_reader": True}, "watch") is False
    assert wdom.store_reader_on({"positions_store_reader": False, "positions_store_reader_surfaces": ["watch"]},
                                "watch") is False


def test_watch_layers_pass_the_watch_surface_and_others_do_not():
    for f in ("scripts/lib/data_broker/watch_intelligence.py", "scripts/lib/watchlist_intelligence.py",
              "scripts/lib/rockville/live_projection.py"):
        assert "WATCH_SURFACE" in (ROOT / f).read_text(), f
    for f in ("scripts/lib/advice_digest.py", "scripts/send_advice_digest.py", "scripts/lib/data_broker/opportunity.py"):
        assert "WATCH_SURFACE" not in (ROOT / f).read_text(), f      # not in batch #1


# ── 3 ── freshness guard: explicit fallback, never silent ────────────────────

def test_stale_store_falls_back_with_a_verdict(tmp_path):
    q, _ = _store(SAT - timedelta(hours=100))
    h = wdom.held_positions(db_query=q, holdings_path=_holdings(tmp_path), registry={}, now=SAT, surface="watch")
    assert h["source"] == "holdings_accounts.holdings_json" and h["symbols"] == {"RTX"}
    assert h["fallback_reason"] == "positions_store_stale"


def test_unreadable_store_falls_back_with_a_verdict(tmp_path):
    q, calls = _store(boom=True)
    h = wdom.held_positions(db_query=q, holdings_path=_holdings(tmp_path), registry={}, now=SAT, surface="watch")
    assert calls and h["source"] == "holdings_accounts.holdings_json"
    assert h["fallback_reason"] == "positions_store_error:RuntimeError"


def test_empty_store_falls_back_with_a_verdict(tmp_path):
    q, _ = _store(rows=False)
    h = wdom.held_positions(db_query=q, holdings_path=_holdings(tmp_path), registry={}, now=SAT, surface="watch")
    assert h["fallback_reason"] == "positions_store_empty" and h["source"] == "holdings_accounts.holdings_json"


def test_nothing_readable_is_unavailable_and_stale_with_the_reason(tmp_path):
    q, _ = _store(boom=True)
    h = wdom.held_positions(db_query=q, holdings_path=tmp_path / "missing.json", registry={}, now=SAT,
                            surface="watch")
    assert h["source"] == "unavailable" and h["stale"] is True and h["symbols"] == set()
    assert h["fallback_reason"] == "positions_store_error:RuntimeError"


def test_payload_carries_the_verdict(tmp_path):
    q, _ = _store(SAT - timedelta(hours=100))
    h = wdom.held_positions(db_query=q, holdings_path=_holdings(tmp_path), registry={}, now=SAT, surface="watch")
    pub = wdom.held_detail_public(h)
    assert pub["fallback_reason"] == "positions_store_stale" and pub["surface"] == "watch" and pub["count"] == 1


# ── 4 ── the registry records the grant ──────────────────────────────────────

def test_registry_lists_the_approved_reader_batch():
    row = _row()
    # Later batches append rows (batch #2, 2026-10-22); batch #1 stays exactly one reader.
    (r,) = [x for x in row["approved_readers"] if x["batch"] == 1]
    assert r["batch"] == 1 and r["reader"] == f"{READER_FILE}::held_positions"
    assert r["files"] == [READER_FILE] and r["tables"] == ["positions_current"] and r["surfaces"] == ["watch"]
    a = r["approval"]
    assert a["approved_by"] == "operator" and a["approved_on"] == "2026-10-22"
    assert "I take your recommendations on above." in a["reference"] and "batch #1" in a["scope"]
    assert set(row["reader_gate"]["tables"]) >= {"positions_current", "position_lots", "realized_lots"}


# ── 5 ── the gate passes with the reader registered, and fails without it ────

def test_gate_passes_with_the_reader_registered():
    assert gate.check_readers(AUTH, gate._files()) == []
    assert gate.check_approvals(AUTH) == []


def test_gate_fails_an_unregistered_reader():
    auth = json.loads(json.dumps(AUTH))
    row = next(d for d in auth["domains"] if d["domain"] == "positions_store")
    row["approved_readers"] = []
    found = gate.check_readers(auth, [gate.PROJECT_ROOT / READER_FILE])
    assert [f["check"] for f in found] == ["UNAPPROVED_READER"] and found[0]["file"] == READER_FILE


def test_gate_fails_an_incomplete_grant():
    auth = json.loads(json.dumps(AUTH))
    row = next(d for d in auth["domains"] if d["domain"] == "positions_store")
    del row["approved_readers"][0]["approval"]["reference"]
    found = gate.check_readers(auth, [])
    assert found and found[0]["check"] == "READER_GRANT_INVALID" and "approval.reference" in found[0]["missing"]
