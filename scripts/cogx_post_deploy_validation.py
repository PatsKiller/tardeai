#!/usr/bin/env python3
"""cogx_post_deploy_validation.py — stage 6 of the approval workflow (11 §2): PostDeployValidation@v1.

Read-only checks that the served release carries the Wave 1 code, that every Wave 1 lane's output
signal has been observed, that the heartbeat/breach/conformance artifacts exist under the state root,
and (when a DSN is reachable) that the intelligence schema holds the projection. Prints the verdict and,
with --write, stores it under the governance dir. Exit 0 = VALIDATED, 1 = NOT_VALIDATED (with the
failing checks named). Never mutates anything.

NO_CONSUMER_REASON: a stage-6 gate; its PostDeployValidation@v1 rows are read by the operator and the
package artifact (docs/ops/COGX_WAVE1_APPROVAL_PACKAGE_2026-09-27.md); a bus consumer is Wave 2.
Authority: READ_ONLY_ADVISORY.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ / "scripts" / "lib"))
sys.path.insert(0, str(PROJ / "scripts"))

NO_CONSUMER_REASON = (
    "stage-6 validation gate (11 §2); PostDeployValidation@v1 rows are read by the operator and copied into "
    "the package artifact; a Command Center panel is Wave 2"
)

WAVE1_FILES = ["scripts/lib/intelligence_client.py", "scripts/gir_projector.py", "scripts/supervisor_breach_detector.py",
               "scripts/report_platform_conformance.py", "scripts/approval_package_reminder.py", "scripts/lib/approval_package.py",
               "config/systemd/user/tradeai-gir-projector.timer", "config/systemd/user/tradeai-supervisor-breach-detector.timer"]
WAVE1_LANES = ["platform-conformance-audit", "supervisor-breach-detector", "gir-projector", "approval-package-reminder"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--package-id", default="pkg-20260927-cogx-w1-d9e1")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--current", default=str(Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT"))
    ap.add_argument("--registry", help="lane registry to validate against (default: the served release's)")
    a = ap.parse_args()
    from approval_package import governance_dir  # type: ignore
    import lane_registry  # type: ignore
    now = _dt.datetime.now(_dt.timezone.utc)
    cur = Path(a.current)
    checks: list[dict] = []

    def add(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    pin = os.path.realpath(cur) if cur.exists() else None
    add("served_pin", bool(pin), {"pin": Path(pin).name if pin else None})
    missing = [f for f in WAVE1_FILES if not (cur / f).exists()]
    add("wave1_files_in_current", not missing, {"missing": missing})
    reg_p = Path(a.registry) if a.registry else cur / "config" / "lane_registry.json"
    reg = lane_registry.load_registry(reg_p) if reg_p.exists() else lane_registry.load_registry()
    lanes = {l["lane_id"]: l for l in reg.get("lanes", [])}
    for lid in WAVE1_LANES:
        lane = lanes.get(lid)
        if not lane:
            add(f"lane_declared:{lid}", False, {}); continue
        obs = lane_registry.observe_signal(lane.get("output_signal") or {})
        last = obs.get("last_output_at")
        add(f"lane_output_signal:{lid}", bool(last), {"state": lane.get("state"), "last_output_at": str(last) if last else None})
    gov = governance_dir()
    st_runtime = gov.parent / "runtime"
    for name, p in (("conformance_report", gov / "platform_conformance_latest.json"), ("breach_latest", st_runtime / "supervisor_breach_detector_latest.json"),
                    ("sla_seed", st_runtime / "supervisor_sla_seed.json")):
        add(name, p.exists(), {"path": str(p), "age_h": round((now.timestamp() - p.stat().st_mtime) / 3600, 2) if p.exists() else None})
    hb_dir = st_runtime / "heartbeats"
    hbs = list(hb_dir.glob("*.json")) if hb_dir.exists() else []
    add("heartbeat_files", len(hbs) > 0, {"count": len(hbs), "lanes": sorted(p.stem for p in hbs)[:20]})
    # intelligence schema (read-only, tenant set)
    try:
        import db_adapter  # type: ignore
        conn = db_adapter._get_conn()
        with conn.cursor() as c:
            c.execute("SET app.tenant_id = 'tradeai:tenant:primary'")
            c.execute("SELECT (SELECT count(*) FROM intelligence.gir_entity), (SELECT count(*) FROM intelligence.gir_edge), (SELECT count(*) FROM intelligence.sla), (SELECT count(*) FROM intelligence.heartbeat)")
            e, ed, s, h = c.fetchone()
        conn.rollback()
        add("intelligence_schema_rows", e > 0 and s > 0, {"gir_entity": e, "gir_edge": ed, "sla": s, "heartbeat": h})
    except Exception as exc:  # noqa: BLE001
        add("intelligence_schema_rows", False, {"error": f"{type(exc).__name__}: {exc}"[:120]})
    failed = [c["check"] for c in checks if not c["ok"]]
    verdict = {"schema": "PostDeployValidation@v1", "package_id": a.package_id, "as_of": now.isoformat(),
               "verdict": "VALIDATED" if not failed else "NOT_VALIDATED", "failed": failed, "checks": checks, "authority": "READ_ONLY_ADVISORY"}
    print(json.dumps(verdict, indent=1, default=str))
    if a.write:
        out = gov / "approvals" / a.package_id / f"post_deploy_validation_{now.strftime('%Y%m%dT%H%M%SZ')}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(verdict, indent=1, default=str) + "\n", encoding="utf-8"); print(f"wrote {out}")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
