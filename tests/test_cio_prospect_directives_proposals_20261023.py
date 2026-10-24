"""CIO prospect — watch directives and open proposals on the record (ANCHOR CIO_PROSPECT_DIRECTIVES_PROPOSALS_20261023).

Silo audit 2026-10-23 (docs/ops/CIO_MEMORY_SILO_AUDIT_2026-10-23.md, PR #1995) P2-2 / P2-3: no CIO consumer read
watch_directives (#23), and no code ever set the prospect stage ``proposed`` (#30).

Pins: an active ticker directive reaches the record as the protected watchlist way-in ``operator_directive``, read
through the watch_directives projection (watch_intelligence.active_ticker_directives) on the injected read-only
session; open proposals set stage ``proposed`` ONLY once the operator grants the registry row ``paper_proposals``
— until then the read is inert and the source says why (§26.6, §17). The builder writes nothing.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from scripts.lib import cio_instrument_record as ir  # noqa: E402
from scripts.lib import cio_prospect_builder as B  # noqa: E402
from scripts.lib import cio_prospect_watchlist_rules as W  # noqa: E402
from scripts.lib.data_broker import watch_intelligence as WI  # noqa: E402

NOW = datetime(2026, 10, 23, 14, 0, tzinfo=timezone.utc)
G, I = "5f0c6a3e-3333-5333-8333-000000000001", "5f0c6a3e-3333-5333-8333-0000000000a1"
G2, I2 = "5f0c6a3e-3333-5333-8333-000000000002", "5f0c6a3e-3333-5333-8333-0000000000a2"
IDS = {"DIRX": (G, I), "PROP": (G2, I2)}
GRANTED = {"domains": [{"domain": "paper_proposals", "approval": {"approved_by": "operator", "approved_on": "2026-10-23",
                                                                   "reference": "test", "scope": "test"}}]}


def _identity(sym):
    g, i = IDS[sym]
    return {"symbol": sym, "security_guid": g, "issuer_guid": i, "subject_guid": g, "identity_status": "CONFIRMED"}


def _db(sql, params=None):
    if "FROM watch_directives" in sql:
        return [{"symbol": "DIRX", "id": 41, "label": "operator: watch the FDA date", "rationale": None,
                 "trade_ai_enabled": True, "hermes_enabled": True,
                 "created_at": datetime(2026, 10, 20, 13, 0, tzinfo=timezone.utc),
                 "updated_at": datetime(2026, 10, 20, 13, 0, tzinfo=timezone.utc)}]
    if "FROM paper_trade_proposals" in sql:
        return [{"symbol": "PROP", "proposal_id": 9001, "status": "pending",
                 "created_at": datetime(2026, 10, 23, 13, 0, tzinfo=timezone.utc)}]
    return []


def _build(tmp: Path, **kw):
    (tmp / "data/cio").mkdir(parents=True, exist_ok=True)
    return B.build(tmp, db_query=_db, held_reader=lambda: {"symbols": set(), "source": "t", "as_of": None},
                   identity_resolver=_identity, now=NOW, **kw)


def _tree(root: Path) -> dict:
    return {str(p.relative_to(root)): (p.stat().st_mtime_ns, p.stat().st_size) for p in root.rglob("*") if p.is_file()}


def test_directive_is_a_protected_way_in_on_the_record(tmp_path):
    doc = _build(tmp_path, registry={"domains": []})
    assert doc["sources"]["directives"]["status"] == "ok"
    d = {r["symbol"]: r for r in doc["prospects"]}["DIRX"]       # a directive alone brings the security in
    assert d["watchlist"]["origin"] == "operator_directive" and d["watchlist"]["protected"] is True
    assert d["watchlist"]["reason"] == "watch directive #41: operator: watch the FDA date"
    ir.prospect_row(d)


def test_proposals_are_inert_until_the_row_is_granted(tmp_path):
    root = tmp_path
    doc = _build(root, registry={"domains": []})
    assert doc["sources"]["proposals"]["status"].startswith("not_read (registry row paper_proposals not granted")
    assert "PROP" not in {r["symbol"] for r in doc["prospects"]}
    assert all(r["stage"] != "proposed" for r in doc["prospects"])


def test_once_granted_an_open_proposal_sets_stage_proposed_with_its_evidence(tmp_path):
    doc = _build(tmp_path, registry=GRANTED)
    p = {r["symbol"]: r for r in doc["prospects"]}["PROP"]
    assert p["stage"] == "proposed"
    assert p["stage_evidence"]["source"] == "paper_trade_proposals" and p["stage_evidence"]["proposal_id"] == 9001
    ir.prospect_row(p)


def test_builder_still_writes_nothing(tmp_path):
    (tmp_path / "data/cio").mkdir(parents=True)
    before = _tree(tmp_path)
    _build(tmp_path, registry=GRANTED)
    assert _tree(tmp_path) == before


def test_projection_uses_the_injected_session_and_fails_soft():
    seen = []
    rows = WI.active_ticker_directives(db_query=lambda sql: seen.append(sql) or [{"symbol": "X", "created_at": 1}])
    assert rows and "FROM watch_directives" in seen[0]

    def boom(sql):
        raise RuntimeError("down")
    assert WI.active_ticker_directives(db_query=boom) == []


def test_rules_know_the_new_origin_and_it_is_protected():
    rules = W.load_rules()
    assert W.is_protected("operator_directive", rules)
    assert "operator_directive" in W.ORIGIN_ORDER


def test_gate_file_registers_this_test():
    gate = json.loads((ROOT / "config/ci_gates/cio_prospect_directives_proposals_20261023.json").read_text())
    assert "tests/test_cio_prospect_directives_proposals_20261023.py" in gate["files"]
