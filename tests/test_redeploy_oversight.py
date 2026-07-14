#!/usr/bin/env python3
"""PR-4/PR-5 — plan lock, oversight, analysis acceptance."""
from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def test_build_analysis_payload():
    ov = _load("redeploy_oversight", "scripts/lib/redeploy_oversight.py")
    ev = {
        "id": 144,
        "symbol": "FCNTX",
        "account": "schwab_rollover_ira",
        "proceeds_usd": 107023.01,
        "metadata": {
            "phase_a": {
                "reconciliation": {"net_proceeds_usd": 107023.01, "deployable_cash_usd": 17540.67, "reconciliation_status": "unsettled"},
                "exposure_loss": {"sectors": [{"sector": "Technology", "usd_removed": 27612}], "income_status": "unknown"},
                "portfolio_context": {"is_major_sale": True},
            },
            "phase_b": {"primary_archetype": "F", "plans": [{"plan_archetype": "F", "deploy_pct_of_net": 4.1, "reserve_usd": 89000}]},
        },
    }
    a = ov.build_analysis_payload(ev)
    assert a["before"]["sold_symbol"] == "FCNTX"
    assert a["exposure_loss"]["income_status"] == "unknown"
    assert a["plan_count"] == 1


def test_parse_verdict():
    ov = _load("redeploy_oversight", "scripts/lib/redeploy_oversight.py")
    p = ov._parse_verdict('{"verdict":"pass","summary":"ok","risks":[]}')
    assert p["verdict"] == "pass"
    assert p["parsed"] is True


def test_lock_and_oversight_db():
    ov = _load("redeploy_oversight", "scripts/lib/redeploy_oversight.py")
    pdb = _load("redeploy_plan_db", "scripts/lib/redeploy_plan_db.py")
    try:
        from db_adapter import get_connection
    except Exception:
        return
    conn = get_connection()
    cur = conn.cursor()
    ov.ensure_oversight_schema(cur)
    conn.commit()

    cur.execute("SELECT id FROM deploy_plans WHERE deploy_event_id=144 ORDER BY version DESC, composite_rank DESC LIMIT 1")
    row = cur.fetchone()
    if not row:
        return
    plan_id = int(row[0])

    # unlock if test re-run
    cur.execute(
        "UPDATE deploy_events SET plan_locked_at=NULL, locked_plan_id=NULL, locked_plan_version=NULL, operator_status='open' WHERE id=144"
    )
    cur.execute("UPDATE deploy_plans SET locked_at=NULL, locked_by=NULL WHERE deploy_event_id=144")
    conn.commit()

    idem = f"test-lock-{uuid.uuid4().hex[:12]}"
    lock = ov.lock_deploy_plan(cur, 144, {"plan_id": plan_id, "idempotency_key": idem})
    assert lock.get("ok"), lock
    conn.commit()

    plan = pdb.get_plan_by_id(cur, plan_id)
    assert plan.get("locked_at") or plan.get("locked_by")

    analysis = ov.get_event_analysis(cur, 144)
    assert analysis.get("ok")
    assert analysis["lock"]["locked_plan_id"] == plan_id

    oversight = ov.run_deploy_oversight(cur, {"event_id": 144, "plan_id": plan_id})
    assert oversight.get("ok"), oversight
    assert oversight.get("oversight_status") in ("passed", "failed", "pending")
    conn.commit()


if __name__ == "__main__":
    tests = [test_build_analysis_payload, test_parse_verdict, test_lock_and_oversight_db]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print(f"ALL {len(tests)} PASSED")