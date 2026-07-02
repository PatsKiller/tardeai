#!/usr/bin/env python3
"""hermes_tradeai_handshake.py — Enqueue T1 research for Trade AI GO symbols (audit 2026-07-02)."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _load_go_symbols() -> list[str]:
    """GO tickers from latest trade-ai API snapshot or run_summary."""
    import urllib.request
    try:
        with urllib.request.urlopen("http://127.0.0.1:7777/api/v2/trade-ai", timeout=12) as r:
            payload = json.load(r)
            data = payload.get("data", payload)
        syms = []
        for t in data.get("scored_tickers") or data.get("tickers") or []:
            if (t.get("decision") or "").upper() == "GO" and not t.get("disqualified"):
                syms.append(str(t.get("symbol", "")).upper())
        return [s for s in syms if s and len(s) <= 5]
    except Exception:
        pass
    # fallback: reports run_summary
    today = datetime.now().strftime("%Y-%m-%d")
    for p in sorted((PROJECT_ROOT / "reports").glob(f"{today}/*/run_summary.json"), reverse=True)[:3]:
        try:
            d = json.loads(p.read_text())
            return [str(t.get("symbol", "")).upper() for t in d.get("go_tickers", [])
                    if t.get("symbol")]
        except Exception:
            continue
    return []


def run(apply: bool = False) -> dict:
    from db_adapter import _get_conn
    go = _load_go_symbols()
    conn = _get_conn()
    cur = conn.cursor()
    enqueued = 0
    for sym in go[:30]:
        cur.execute(
            """SELECT 1 FROM watchlist_agent_jobs
               WHERE symbol=%s AND status IN ('queued','processing')
                 AND created_at > NOW() - INTERVAL '6 hours' LIMIT 1""",
            (sym,),
        )
        if cur.fetchone():
            continue
        if apply:
            import uuid
            job_id = f"tradeai-go-{sym}-{datetime.now(timezone.utc).strftime('%Y%m%d%H')}"
            cur.execute(
                """INSERT INTO watchlist_agent_jobs
                   (id, symbol, requested_agent, request_type, note, status, priority, submitted_from, payload)
                   VALUES (%s, %s, 'maria', 'research', %s, 'queued', 0, 'tradeai_handshake', %s::jsonb)
                   ON CONFLICT (id) DO NOTHING""",
                (job_id, sym, f"Trade AI GO handshake {sym}",
                 json.dumps({"source": "tradeai_go", "trigger_source": "go_candidate"})),
            )
            enqueued += cur.rowcount
    if apply:
        conn.commit()
    out = {
        "ok": True,
        "apply": apply,
        "go_symbols": go,
        "enqueued": enqueued,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    print(json.dumps(out, indent=2))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    run(apply=args.apply)


if __name__ == "__main__":
    main()