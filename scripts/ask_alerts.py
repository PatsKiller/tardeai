#!/usr/bin/env python3
"""ask_alerts.py — persistent alerts created from the "Ask the agents" box.

When the operator asks something like "alert me when I can get SpaceX (SPCX)", we save a tracked alert.
The monitor (run on a schedule) checks each alert and fires to the SIEM/Telegram pipeline via
alert_event_writer.save_alert_event when the condition is met.

Kinds:
  • ipo_watch  — private name (SpaceX/OpenAI…). Fires when news mentions the company + an IPO/listing
                 keyword. (No automated price feed exists for a private company; news is the signal.)
  • price      — public ticker with a target price. Fires when current price crosses it.
Storage: data/runtime/ask_alerts.json (idempotent, append). NOT a hallucination source — the alert just
records the operator's intent; firing requires a real news/price hit.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STORE = ROOT / "data" / "runtime" / "ask_alerts.json"
_IPO_KW = ["ipo", "goes public", "going public", "public offering", "files to go public", "direct listing",
           "s-1 filing", "begins trading", "debut", "stock market listing", "to list shares"]


def _now():
    return datetime.now(timezone.utc).isoformat()


def _load():
    try:
        return json.loads(STORE.read_text())
    except Exception:
        return {"alerts": []}


def _save(d):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(d, indent=2))


def add_alert(question: str, context: dict | None = None) -> dict:
    """Create an alert from an ask. Derives companies/symbols + kind from the question's context."""
    context = context or {}
    privates = [p["name"] for p in context.get("positions", []) if p.get("private")]
    pubs = [p["symbol"] for p in context.get("positions", []) if not p.get("private") and p.get("held")]
    m = re.search(r"\$?\s*(\d{2,5}(?:\.\d+)?)", question)
    kind = "ipo_watch" if privates else ("price" if (m and pubs) else "ipo_watch" if not pubs else "news")
    d = _load()
    alert = {
        "id": f"ask_{abs(hash(question + _now())) % 10**8}",
        "question": question[:300], "kind": kind, "companies": privates, "symbols": pubs,
        "target_price": float(m.group(1)) if (kind == "price" and m) else None,
        "created_at": _now(), "status": "active", "triggered_at": None,
    }
    d["alerts"].append(alert)
    _save(d)
    return alert


def list_alerts():
    return _load().get("alerts", [])


def _news_hits(company: str, keywords):
    try:
        from alert_event_writer import _get_conn
        c = _get_conn(); cur = c.cursor()
        like = "%" + company.lower() + "%"
        cur.execute("""SELECT title, url, published_at FROM news_articles
                       WHERE lower(title) LIKE %s AND published_at > NOW() - INTERVAL '3 days'
                       ORDER BY published_at DESC LIMIT 25""", (like,))
        rows = cur.fetchall()
        out = []
        for title, url, pub in rows:
            t = (title or "").lower()
            if any(k in t for k in keywords):
                out.append({"title": title, "url": url, "at": str(pub)})
        return out
    except Exception:
        return []


def _fire(alert, subject, evidence):
    try:
        from alert_event_writer import save_alert_event
        save_alert_event(alert_type="strategic_alert", severity="urgent", source_script="ask_alerts.py",
                         raw_text=f"[ask-alert] {subject}: {evidence.get('title','condition met')} — you asked: "
                                  f"\"{alert['question']}\". {evidence.get('url','')}",
                         parsed_payload={"kind": "ask_alert", "alert_id": alert["id"], "subject": subject,
                                         "evidence": evidence})
        return True
    except Exception:
        return False


def check_alerts() -> list:
    d = _load(); fired = []
    for a in d.get("alerts", []):
        if a.get("status") != "active":
            continue
        if a["kind"] == "ipo_watch":
            for name in a.get("companies", []) or ["SpaceX"]:
                hits = _news_hits(name, _IPO_KW)
                if hits and _fire(a, name, hits[0]):
                    a["status"], a["triggered_at"] = "triggered", _now()
                    fired.append({"id": a["id"], "subject": name, "evidence": hits[0]})
                    break
        elif a["kind"] == "price" and a.get("target_price") and a.get("symbols"):
            try:
                # Data Broker (2026-07-31): route through the canonical quote waterfall
                # (Alpaca/Schwab/Polygon/Finnhub/FMP/yfinance/Finviz) instead of a raw
                # yfinance call, so this alert can't disagree with what the UI shows.
                # See config/data_registry.yaml:quote_last_price.
                from market_quote_provider import get_best_quote
                q = get_best_quote(a["symbols"][0]) or {}
                px = float(q["last_price"])
                if px >= a["target_price"] and _fire(a, a["symbols"][0], {"title": f"price ${px:.2f} ≥ ${a['target_price']}"}):
                    a["status"], a["triggered_at"] = "triggered", _now()
                    fired.append({"id": a["id"], "subject": a["symbols"][0], "price": px})
            except Exception:
                pass
    _save(d)
    return fired


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.check:
        print(json.dumps({"fired": check_alerts()}, indent=2))
    else:
        print(json.dumps(list_alerts(), indent=2))
