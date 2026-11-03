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

Shard03: --dry-run reports active alert count without DB/provider writes; unknown flags exit 2.
Real CLI runs leave a LaneRunReceipt@v1, preserving ok_at on exception. Shadow admission remains
blocked by the exact live cron comment; no scheduler or sender authority changed.
"""
from __future__ import annotations

import json
import math
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
STORE = ROOT / "data" / "runtime" / "ask_alerts.json"
_IPO_KW = ["ipo", "goes public", "going public", "public offering", "files to go public", "direct listing",
           "s-1 filing", "begins trading", "debut", "stock market listing", "to list shares"]


class _EvalError(Exception):
    """An alert could not be evaluated or its firing could not be enqueued.

    The run receipt may only say ok when every active alert was actually evaluated and every hit was durably enqueued.
    Before this, a database or provider failure was swallowed and the run still reported success (jobs coverage audit,
    2026-11-03): a failed news query looked like "no news", and an alert whose event row was not written was marked
    triggered anyway, losing it permanently while the receipt said ok.
    """


def _now():
    return datetime.now(timezone.utc).isoformat()


def _load():
    try:
        return json.loads(STORE.read_text())
    except Exception:
        return {"alerts": []}


def _load_strict():
    """The store for an EVALUATION run: a missing store is empty, but a corrupt one is an error.

    ``_load`` stays lenient for the API's ``add_alert``/``list_alerts``; an evaluation that silently treated a corrupt
    store as empty and then saved it would erase every alert.
    """
    try:
        return json.loads(STORE.read_text())
    except FileNotFoundError:
        return {"alerts": []}
    except Exception as exc:
        raise _EvalError(f"alert store unreadable: {type(exc).__name__}") from exc


def _save(d):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(d, indent=2))


def add_alert(question: str, context: dict | None = None) -> dict:
    """Create an alert from an ask. Derives companies/symbols + kind from the question's context."""
    context = context or {}
    privates = [p["name"] for p in context.get("positions", []) if p.get("private")]
    pubs = [p["symbol"] for p in context.get("positions", []) if not p.get("private") and p.get("held")]
    # Parse a THOUSANDS-SEPARATED amount: "$1,000" used to match "000" and become a 0.0 target, which
    # the evaluator cannot handle (jobs coverage audit 2026-11-03). Only a positive finite price is a target.
    target = None
    m = re.search(r"\$\s*(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{1,6}(?:\.\d+)?)", question)
    if m:
        try:
            value = float(m.group(1).replace(",", ""))
        except ValueError:
            value = None
        if value is not None and math.isfinite(value) and value > 0:
            target = value
    kind = "ipo_watch" if privates else ("price" if (target is not None and pubs) else "ipo_watch" if not pubs else "news")
    d = _load()
    alert = {
        "id": f"ask_{abs(hash(question + _now())) % 10**8}",
        "question": question[:300], "kind": kind, "companies": privates, "symbols": pubs,
        "target_price": target if kind == "price" else None,
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
        cur.execute("""SELECT title, source_url AS url, published_at FROM news_articles
                       WHERE lower(title) LIKE %s AND published_at > NOW() - INTERVAL '3 days'
                       ORDER BY published_at DESC LIMIT 25""", (like,))
        rows = cur.fetchall()
        out = []
        for title, url, pub in rows:
            t = (title or "").lower()
            if any(k in t for k in keywords):
                out.append({"title": title, "url": url, "at": str(pub)})
        return out
    except Exception as exc:
        # A failed query is not "no news": it is an evaluation that did not happen.
        raise _EvalError(f"news query failed: {type(exc).__name__}") from exc


def _fire(alert, subject, evidence):
    try:
        from alert_event_writer import save_alert_event
        alert_id = save_alert_event(alert_type="strategic_alert", severity="urgent", source_script="ask_alerts.py",
                                    raw_text=f"[ask-alert] {subject}: {evidence.get('title','condition met')} — you "
                                             f"asked: \"{alert['question']}\". {evidence.get('url','')}",
                                    parsed_payload={"kind": "ask_alert", "alert_id": alert["id"], "subject": subject,
                                                    "evidence": evidence})
    except Exception as exc:
        raise _EvalError(f"alert event write failed: {type(exc).__name__}") from exc
    if alert_id is None:
        # save_alert_event swallows its own DB error and returns None; the alert must stay active, not be "triggered".
        raise _EvalError("alert event not saved")
    return True


def check_alerts() -> list:
    """Evaluate every active alert. Returns the alerts that fired.

    Every failure is collected and raised AFTER the store is saved, so the run receipt says failed (with the previous
    ok_at preserved) instead of claiming a success that did not happen, and an alert that already fired keeps its
    ``triggered`` state instead of being fired again on the next run. A genuine "nothing fired" is still a success.
    An active alert this evaluator cannot handle (an unknown kind, or a price alert without a numeric target) is an
    error, not a silent skip: the lane may only report ok when every active alert was actually evaluated.
    """
    d = _load_strict(); fired = []; errors = []
    alerts = d.get("alerts")
    if not isinstance(alerts, list):
        raise _EvalError("alert store has no alert list")
    try:
        for a in alerts:
            try:
                if not isinstance(a, dict):
                    raise _EvalError(f"record is not an object ({type(a).__name__})")
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
                    target = float(a["target_price"])  # a non-numeric target is a malformed record, not a skip
                    if not math.isfinite(target) or target <= 0:
                        raise _EvalError("target price is not a positive finite number")
                    try:
                        import yfinance as yf
                        px = float(yf.Ticker(a["symbols"][0]).fast_info["last_price"])
                    except Exception as exc:
                        raise _EvalError(f"price quote failed: {type(exc).__name__}") from exc
                    if px >= target and _fire(a, a["symbols"][0], {"title": f"price ${px:.2f} ≥ ${target}"}):
                        a["status"], a["triggered_at"] = "triggered", _now()
                        fired.append({"id": a["id"], "subject": a["symbols"][0], "price": px})
                else:
                    errors.append(f"{a.get('id')}:unsupported active alert (kind={a.get('kind')!r})")
            except _EvalError as exc:
                errors.append(f"{a.get('id') if isinstance(a, dict) else '?'}:{exc}")
            except Exception as exc:  # a malformed record must never lose state already written
                errors.append(f"{a.get('id') if isinstance(a, dict) else '?'}:record:{type(exc).__name__}")
    finally:
        # Persist whatever completed even if something unexpected escapes the loop: an alert whose event was
        # already enqueued must not be fired a second time because its status write was skipped.
        _save(d)
    if errors:
        raise _EvalError("; ".join(errors))
    return fired


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(allow_abbrev=False)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.dry_run:
        active = sum(r.get("status") == "active" for r in list_alerts())
        print(f"DRY-RUN ask-alerts: would {'check' if a.check else 'list'} {active} active alert(s); "
              "check news/prices, enqueue alert_events on a hit and save alert status with --check; "
              "no DB, provider request, store write or live receipt")
        return 0
    from lib.lane_last_receipt import now_iso, write_lane_receipt
    started = now_iso()
    try:
        result = {"fired": check_alerts()} if a.check else list_alerts()
        print(json.dumps(result, indent=2))
    except Exception as exc:
        write_lane_receipt("ask-alerts", ok=False, exit_code=1, started_at=started,
                           error=type(exc).__name__)
        raise
    write_lane_receipt("ask-alerts", ok=True, exit_code=0, started_at=started,
                       summary={"checked": a.check,
                                "fired": len(result["fired"]) if a.check else 0,
                                "listed": 0 if a.check else len(result)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
