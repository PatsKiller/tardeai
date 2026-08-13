#!/usr/bin/env python3
"""Prove multi-desk two-way curation: emit from latest advisory/defense + drain staging.

1. Emit advisory feedback from data/runtime/advisory_desk_latest.json (actionable verdicts)
2. Emit defense feedback from data/runtime/defense_recommendations_latest.json
3. Drain cio/advisory/defense staging via promote (default stage-only)

Does NOT trade. Fail-soft per source.

  .venv/bin/python scripts/ops/emit_and_drain_desk_curation.py            # preview
  .venv/bin/python scripts/ops/emit_and_drain_desk_curation.py --apply
  .venv/bin/python scripts/ops/emit_and_drain_desk_curation.py --apply --promote
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

RUNTIME = ROOT / "data" / "runtime"


def _load_env() -> None:
    for env_file in (
        Path(os.environ.get("TRADEAI_ENV_FILE", f"/run/user/{os.getuid()}/tradeai/env")),
        ROOT / ".env",
    ):
        if not env_file.is_file():
            continue
        for line in env_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line or line.lstrip().startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if not k or not (k[0].isalpha() or k[0] == "_") or not all(
                c.isalnum() or c == "_" for c in k
            ):
                continue
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                v = v[1:-1]
            os.environ.setdefault(k, v)


def _advisory_feedback_list() -> tuple[list, dict]:
    from lib.two_way_curation import advisory_verdict_to_feedback

    path = RUNTIME / "advisory_desk_latest.json"
    if not path.is_file():
        return [], {"error": "missing advisory_desk_latest.json"}
    raw = json.loads(path.read_text())
    data = raw.get("data") if isinstance(raw.get("data"), dict) else raw
    rows = data.get("rows") or []
    if isinstance(rows, dict):
        rows = list(rows.values())

    by_hash: dict = {}
    op_path = RUNTIME / "advisory_opinions_latest.json"
    if op_path.is_file():
        orows = json.loads(op_path.read_text()).get("rows") or {}
        if isinstance(orows, dict):
            by_hash = orows

    feedback = []
    skipped = {"non_actionable": 0, "no_symbol": 0, "gated": 0}
    for row in rows:
        if not isinstance(row, dict):
            continue
        h = str(row.get("advisory_row_hash") or "")
        opinion = by_hash.get(h) if h else None
        verdict = str(
            (opinion or {}).get("verdict") or row.get("verdict") or ""
        ).upper()
        sym = str(row.get("symbol") or "").upper().strip()
        if not sym:
            skipped["no_symbol"] += 1
            continue
        if verdict not in ("ADD", "TRIM", "EXIT", "RE_ENTER"):
            skipped["non_actionable"] += 1
            continue
        eb = row.get("evidence_bundle") or {}
        if not isinstance(eb, dict):
            eb = {}
        evidence_count = int(
            eb.get("evidence_count")
            or len(eb.get("evidence_items") or [])
            or len((opinion or {}).get("evidence_cited") or [])
            or 0
        )
        conviction = (opinion or {}).get("conviction")
        if conviction is None:
            try:
                conviction = float(row.get("confidence") or 0) * 100
            except (TypeError, ValueError):
                conviction = None
        fb = advisory_verdict_to_feedback(
            verdict,
            sym,
            row_class=str(row.get("row_class") or "holding"),
            conviction=conviction,
            rationale=str(
                (opinion or {}).get("rationale") or row.get("rationale") or ""
            )[:300],
            evidence_count=evidence_count,
        )
        if not fb:
            skipped["gated"] += 1
            continue
        feedback.append(fb)
    return feedback, skipped


def _defense_feedback_list() -> tuple[list, dict]:
    from lib.two_way_curation import defense_card_to_feedback

    path = RUNTIME / "defense_recommendations_latest.json"
    if not path.is_file():
        return [], {"error": "missing defense_recommendations_latest.json"}
    raw = json.loads(path.read_text())
    groups = raw.get("groups") or {}
    feedback = []
    for g in ("get_into", "income", "short_side"):
        for card in groups.get(g) or []:
            c = dict(card)
            c.setdefault("group", g)
            if not c.get("symbol"):
                inst = (c.get("instruments") or [{}])[0]
                c["symbol"] = (
                    inst.get("symbol") if isinstance(inst, dict) else None
                ) or ""
            if not c.get("sector") and not c.get("note"):
                c["note"] = str(c.get("title") or c.get("entry_logic") or "")[:200]
            fb = defense_card_to_feedback(c)
            if fb:
                feedback.append(fb)
    meta = {"empty_reasons": raw.get("empty_reasons"), "groups": {
        g: len(groups.get(g) or []) for g in ("get_into", "income", "short_side", "protect")
    }}
    return feedback, meta


def _emit_advisory() -> dict:
    from lib.two_way_curation import emit_all

    feedback, skipped = _advisory_feedback_list()
    if not feedback:
        return {
            "ok": True,
            "source": "advisory",
            "staged": 0,
            "feedback_n": 0,
            "skipped": skipped,
        }
    res = emit_all("advisory", feedback)
    res["feedback_n"] = len(feedback)
    res["skipped"] = skipped
    return res


def _emit_defense() -> dict:
    from lib.two_way_curation import emit_all

    feedback, meta = _defense_feedback_list()
    if not feedback:
        return {
            "ok": True,
            "source": "defense",
            "staged": 0,
            "feedback_n": 0,
            **meta,
        }
    res = emit_all("defense", feedback)
    res["feedback_n"] = len(feedback)
    res.update(meta)
    return res


def _drain_all(*, apply: bool, stage_only: bool, limit: int) -> dict:
    import psycopg2
    import psycopg2.extras
    import directive_promotion as dp
    from lib.two_way_curation import drain_curation_sources

    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "trade_ai"),
        user=os.getenv("DB_USER", "trade_ai"),
        password=os.getenv("DB_PASSWORD"),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )
    cur = conn.cursor()
    cur.execute("SET lock_timeout = '3s'")
    report: dict = {"detail": [], "promoted": 0, "staged": 0}
    dry = not apply

    def resolve_fn(d):
        spec = d.get("spec") or {}
        if d.get("kind") == "ticker" and spec.get("symbol"):
            return [str(spec["symbol"]).upper()]
        seeds = list(spec.get("seed_symbols") or [])
        if spec.get("symbol"):
            seeds.insert(0, spec["symbol"])
        return [str(s).upper() for s in seeds if s][:8]

    def evaluate(sym, did, reason, source, auto):
        if dry:
            return {"status": "DRY_RUN", "symbol": sym}
        try:
            force_auto = False if stage_only else auto
            return dp.promote_directive_lead(
                sym, did, reason, source, conn=conn, auto=force_auto
            )
        except Exception as exc:
            return {"status": "ERROR", "error": str(exc)[:160], "symbol": sym}

    drain_curation_sources(
        cur, dry, report, evaluate, resolve_fn, drain_limit=limit, auto_apply=None
    )
    if apply:
        conn.commit()
    else:
        conn.rollback()
    conn.close()
    return {
        "dry": dry,
        "stage_only": stage_only,
        "curation_drained": report.get("curation_drained", 0),
        "promoted": report.get("promoted", 0),
        "staged_hits": report.get("staged", 0),
        "detail_n": len(report.get("detail") or []),
        "detail_sample": (report.get("detail") or [])[:12],
        "errors": sum(
            1 for d in (report.get("detail") or []) if d.get("status") == "ERROR"
        ),
    }


def _kpis() -> dict:
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
    out: dict = {}
    for src, tbl in (
        ("cio", "cio_directive_hits_staging"),
        ("advisory", "advisory_directive_hits_staging"),
        ("defense", "defense_directive_hits_staging"),
    ):
        cur.execute(
            f"SELECT count(*) total, count(*) FILTER (WHERE NOT drained) undrained FROM {tbl}"
        )
        r = cur.fetchone()
        out[src] = {"total": r["total"], "undrained": r["undrained"]}
    cur.execute(
        """SELECT surfaced_by, count(*) n FROM watch_directive_hits
           WHERE surfaced_by IN ('cio','advisory','defense')
             AND surfaced_at > now() - interval '24 hours'
           GROUP BY 1"""
    )
    out["hits_24h"] = {r["surfaced_by"]: r["n"] for r in cur.fetchall()}
    cur.execute(
        """SELECT count(*) n FROM watch_directive_hits
           WHERE promotion_status='STAGED_FOR_REVIEW'
             AND surfaced_by IN ('cio','advisory','defense')
             AND surfaced_at > now() - interval '7 days'"""
    )
    out["suggestions_7d"] = cur.fetchone()["n"]
    conn.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--promote", action="store_true")
    ap.add_argument("--emit-only", action="store_true")
    ap.add_argument("--drain-only", action="store_true")
    ap.add_argument("--limit", type=int, default=50)
    args = ap.parse_args()
    _load_env()

    out: dict = {"apply": args.apply}

    if not args.drain_only:
        if args.apply:
            out["advisory_emit"] = _emit_advisory()
            out["defense_emit"] = _emit_defense()
        else:
            afb, askip = _advisory_feedback_list()
            dfb, dmeta = _defense_feedback_list()
            out["preview"] = {
                "advisory_candidates": len(afb),
                "defense_candidates": len(dfb),
                "advisory_skipped": askip,
                "defense_meta": dmeta,
                "advisory_sample": [
                    {"symbol": f.get("spec", {}).get("symbol"), "verdict": f.get("verdict")}
                    for f in afb[:8]
                ],
                "defense_sample": [
                    {"symbol": f.get("spec", {}).get("symbol"), "label": f.get("directive_label")}
                    for f in dfb[:8]
                ],
            }

    if not args.emit_only:
        out["drain"] = _drain_all(
            apply=args.apply, stage_only=not args.promote, limit=args.limit
        )
    out["kpis"] = _kpis()
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
