#!/usr/bin/env python3
"""End-to-end smoke for two-way watchlist curation (forward + reverse KPIs).

Does NOT trade. Stages one synthetic CIO S5 feedback row, drains via lib (or
reports undrained), and prints loop health. Safe to re-run.

  .venv/bin/python scripts/ops/two_way_curation_smoke.py
  .venv/bin/python scripts/ops/two_way_curation_smoke.py --drain
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
os.chdir(ROOT)


def _load_env() -> None:
    env_file = Path(os.environ.get("TRADEAI_ENV_FILE", f"/run/user/{os.getuid()}/tradeai/env"))
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        if not k or not k.replace("_", "").isalnum() or k[0].isdigit():
            continue
        if not (k[0].isalpha() or k[0] == "_"):
            continue
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        os.environ.setdefault(k, v)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--drain", action="store_true", help="also run drain_curation_sources (dry eval if no --apply)")
    ap.add_argument("--apply-drain", action="store_true", help="drain with real promote_directive_lead")
    ap.add_argument("--stage-only", action="store_true",
                    help="with --apply-drain, force auto=False (hit record only; avoids watchlist lock)")
    args = ap.parse_args()
    _load_env()

    from lib.two_way_curation import (
        cio_situation_to_feedback,
        emit_all,
        undrained_staging,
        audit,
    )

    # Synthetic S5 so forward pipe has something even when detector is quiet
    fake_plan = {
        "situation_type": "S5_CASH_DEPLOYMENT",
        "symbols": ["SCHD", "VTI"],
        "seed_symbols": ["SCHD", "VTI", "XLU"],
        "rationale": "two_way_curation_smoke synthetic S5 cash deployment",
    }
    feedback = cio_situation_to_feedback(fake_plan)
    emit_res = emit_all("cio", feedback)
    undrained = undrained_staging("cio")
    audit("cio", "smoke", {"emit": emit_res, "undrained": len(undrained)})

    out = {
        "emit": emit_res,
        "feedback_n": len(feedback),
        "undrained_cio": len(undrained),
        "sample": [
            {"id": r.get("id"), "symbol": r.get("symbol"), "thesis": (r.get("thesis") or "")[:80]}
            for r in undrained[:5]
        ],
    }

    if args.drain or args.apply_drain:
        import psycopg2
        import psycopg2.extras

        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432"),
            dbname=os.getenv("DB_NAME", "trade_ai"),
            user=os.getenv("DB_USER", "trade_ai"),
            password=os.getenv("DB_PASSWORD"),
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
        cur = conn.cursor()
        dry = not args.apply_drain
        report: dict = {"detail": [], "promoted": 0, "staged": 0}

        def resolve_fn(d):
            spec = d.get("spec") or {}
            if d.get("kind") == "ticker" and spec.get("symbol"):
                return [str(spec["symbol"]).upper()]
            seeds = spec.get("seed_symbols") or []
            return [str(s).upper() for s in seeds[:5] if s]

        def evaluate(sym, did, reason, source, auto):
            if dry:
                return {"status": "DRY_RUN", "symbol": sym}
            try:
                import directive_promotion as dp
                # stage-only: record hit with honest surfaced_by without heavy enrich/upsert
                force_auto = False if args.stage_only else auto
                return dp.promote_directive_lead(sym, did, reason, source, auto=force_auto)
            except Exception as exc:
                return {"status": "ERROR", "error": str(exc)[:160], "symbol": sym}

        from lib.two_way_curation import drain_curation_sources
        drain_curation_sources(cur, dry, report, evaluate, resolve_fn, drain_limit=10)
        if not dry:
            conn.commit()
        else:
            conn.rollback()
        conn.close()
        out["drain"] = {
            "dry": dry,
            "curation_drained": report.get("curation_drained", 0),
            "promoted": report.get("promoted", 0),
            "staged": report.get("staged", 0),
            "detail_n": len(report.get("detail") or []),
            "detail_sample": (report.get("detail") or [])[:8],
        }

    # KPI snapshot
    try:
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=os.getenv("DB_PORT", "5432"),
            dbname=os.getenv("DB_NAME", "trade_ai"),
            user=os.getenv("DB_USER", "trade_ai"),
            password=os.getenv("DB_PASSWORD"),
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
        cur = conn.cursor()
        cur.execute("SELECT count(*) n FROM curation_loop_audit")
        audit_n = cur.fetchone()["n"]
        cur.execute(
            "SELECT count(*) n FROM watch_directives WHERE created_by IN ('cio','advisory','defense')"
        )
        desk_dir = cur.fetchone()["n"]
        cur.execute(
            "SELECT count(*) n FROM cio_directive_hits_staging WHERE NOT drained"
        )
        und = cur.fetchone()["n"]
        conn.close()
        out["kpis"] = {"audit_total": audit_n, "desk_directives": desk_dir, "cio_undrained": und}
    except Exception as exc:
        out["kpis_error"] = str(exc)[:160]

    print(json.dumps(out, indent=2, default=str))
    return 0 if emit_res.get("staged", 0) > 0 or emit_res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
