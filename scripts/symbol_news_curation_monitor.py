#!/usr/bin/env python3
"""Monitor + auto-fix: evidence-needing symbols stuck in `pending` curation (2026-09-27).

Operator: "wire a process that monitors and fixes this when it happens; we need SLAs".
Every run:
  1. priority set = open symbol-thesis priority requests, then current options-desk
     symbols, then the acquisition worker's debt-ordered queue (held names first);
  2. SLA report before: an evidence-needing symbol with NO approved news in the window
     while its news has waited in `pending` longer than sla_hours_priority is a breach;
  3. fix: curate each priority symbol's pending news (symbol_news_curation rules);
  4. fix: re-run symbol-thesis acquisition for up to acquire_per_run open requests
     (bounded LLM calls; the governed global cap still binds);
  5. SLA report after, written to data/runtime/symbol_news_curation_sla.json; a breach
     that survives the fix raises one alert_events row per hour (system_health).
Dry run by default; --apply writes.

    python3 scripts/symbol_news_curation_monitor.py            # dry run
    python3 scripts/symbol_news_curation_monitor.py --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))


def _load_env() -> None:
    f = ROOT / ".env"
    if not f.is_file():
        return
    for raw in f.read_text(errors="ignore").splitlines():
        s = raw.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def priority_symbols(limit: int) -> list[str]:
    from lib.symbol_thesis_priority import open_requests
    out: list[str] = list(open_requests(ROOT))
    try:
        props = json.loads((ROOT / "data/portfolios/state/options_proposals.json").read_text()).get("proposals") or []
        out += [str(p.get("symbol") or "").upper() for p in props]
    except Exception:  # noqa: BLE001
        pass
    try:
        from run_symbol_thesis_acquisition import build_debt_ordered_queue
        out += [str(r.get("symbol") or "").upper() for r in build_debt_ordered_queue(root=ROOT, limit=limit)]
    except Exception:  # noqa: BLE001
        pass
    seen, uniq = set(), []
    for s in out:
        if s and s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq[:limit]


def _alert(cur, report: dict) -> None:
    uid = f"symbol_news_curation_sla_{datetime.now(timezone.utc).strftime('%Y%m%d%H')}"
    names = ", ".join(b["symbol"] for b in report["breaches"][:8])
    cur.execute(
        """INSERT INTO alert_events (alert_uid, alert_type, symbol, severity, source_script, raw_text, created_at)
           VALUES (%s,'system_health',NULL,'warning','symbol_news_curation_monitor',%s,NOW())
           ON CONFLICT (alert_uid) DO NOTHING""",
        (uid, f"Curation SLA breached after auto-fix: {report['breach_count']} symbol(s) still have no approved "
              f"news past {report['sla_hours_priority']}h ({names}). Platform backlog: "
              f"{report['platform_pending_30d']} pending in 30d."))


def fundamentals_sla(conn, symbols: list[str], *, apply: bool) -> dict:
    import psycopg2.extras
    from lib import fundamentals_feed as ff
    from sec_fundamentals_ingest import is_fund
    fs = ff.settings()
    latest: dict[str, str] = {}
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""SELECT symbol, max(period_end) AS q FROM sec_xbrl
                       WHERE metric_name='revenue' AND symbol = ANY(%s) GROUP BY symbol""", (list(symbols),))
        for r in cur.fetchall() or []:
            latest[r["symbol"]] = str(r["q"])
        operating = [s for s in symbols if not is_fund(cur, s)]
    breaches = []
    for sym in operating:
        state = ff.freshness({"latest_quarter_end": latest.get(sym)}, fs)
        if state != "FRESH":
            breaches.append({"symbol": sym, "state": state, "latest_quarter_end": latest.get(sym)})
    fixed = []
    if apply and breaches:
        import contextlib
        import io
        from sec_fundamentals_ingest import main as ingest
        todo = [b["symbol"] for b in breaches][: int(fs.get("fix_per_run", 20))]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ingest(["--symbols", ",".join(todo), "--apply"])
        try:
            fixed = [(r["symbol"], r["status"], r.get("inserted", 0)) for r in json.loads(buf.getvalue())["results"]]
        except Exception:  # noqa: BLE001
            fixed = [(t, "UNKNOWN", 0) for t in todo]
    return {"operating_symbols": len(operating), "breaches_before_fix": len(breaches),
            "breaches": breaches[:30], "fixed": fixed}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Symbol-news curation SLA monitor + auto-fix")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "data" / "runtime" / "symbol_news_curation_sla.json"))
    a = ap.parse_args(argv)
    _load_env()
    import psycopg2
    import psycopg2.extras
    from lib import symbol_news_curation as snc
    s = snc.settings()
    pri = priority_symbols(int(s["max_symbols_per_run"]))
    conn = psycopg2.connect(host=os.getenv("DB_HOST"), port=os.getenv("DB_PORT"), dbname=os.getenv("DB_NAME"),
                            user=os.getenv("DB_USER"), password=os.getenv("DB_PASSWORD"))
    result: dict = {"mode": "apply" if a.apply else "dry_run", "priority_symbols": pri}
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            before = snc.sla_report(cur, pri, s)
            curated = [snc.curate_symbol(cur, sym, s, apply=a.apply) for sym in pri]
            if a.apply:
                conn.commit()
            result["curated"] = [c for c in curated if c["selected"]]
        acquired = []
        if a.apply:
            from lib.symbol_thesis_priority import open_requests
            todo = open_requests(ROOT)[: int(s["acquire_per_run"])]
            if todo:
                from run_symbol_thesis_acquisition import run as acquire
                batch = acquire(root=ROOT, symbols=todo, limit=len(todo), max_llm=int(s["acquire_max_llm"]),
                                apply=True)
                acquired = [{"symbol": r.get("symbol"), "status": r.get("status"), "gate": r.get("gate")}
                            for r in batch.get("results") or []]
        result["acquired"] = acquired
        # Fundamentals SLA (fundamentals plan F4, 2026-09-27): an operating company in the
        # priority set whose reported quarter is missing or older than
        # fundamentals_feed.stale_days_after_quarter is a breach; fix = ingest it now.
        result["fundamentals"] = fundamentals_sla(conn, pri, apply=a.apply)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            after = snc.sla_report(cur, pri, s)
            if a.apply and after["breach_count"]:
                _alert(cur, after)
                conn.commit()
        result["sla_before"] = {k: before[k] for k in ("breach_count", "platform_pending_30d")}
        result["sla"] = after
    finally:
        conn.close()
    if a.apply:
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("mode", "sla_before")} | {
        "curated_symbols": [(c["symbol"], c["selected"], c["approved"]) for c in result.get("curated", [])],
        "acquired": result.get("acquired"), "breaches_after": result["sla"]["breach_count"],
        "fundamentals": {k: result.get("fundamentals", {}).get(k) for k in ("operating_symbols", "breaches_before_fix")},
        "platform_pending_30d": result["sla"]["platform_pending_30d"]}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
