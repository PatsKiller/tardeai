#!/usr/bin/env python3
"""Scalp GO alerts from the screener, on Trade-AI's scalp criteria. Dry run by default.

WHY
---
Operator, 2026-09-14: "look at my goal signals for my momentum scalps. For months have been broke and
not showing." Measured: trade_ai_scans held GO decisions every week (3 on 09-14, 5 on 09-09), but the
screener's GO list only rode inside the "Trade AI v12.1d" digest the router files to the archive, and
the social scanner's own GO alerts stopped on 2026-07-13. Operator decision: a GO alert must match
Trade-AI's scalp criteria (price, float, RVOL, gap, volume, score, verified catalyst) -- the route tag
is not required -- and social scalps are included.

WHAT
----
Reads today's GO rows from trade_ai_scans, keeps those that pass scalp_go_criteria.evaluate, sends ONE
alert per symbol per session (ledger), and explains what failed for the rest in the receipt. Without
--send nothing is sent. Every alert names the criteria it met and carries the READ_ONLY_ADVISORY tail.

AUTHORITY: READ_ONLY_ADVISORY. An alert is a notification; nothing here sizes, orders or stops.
MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.scalp_go_criteria import GoVerdict, evaluate, load_criteria  # noqa: E402

LEDGER = PROJECT_ROOT / "data" / "runtime" / "screener_go_alerts_sent.json"
RECEIPT = PROJECT_ROOT / "data" / "runtime" / "screener_go_alerts_last_run.json"
AUTHORITY = "READ_ONLY_ADVISORY"
NO_CONSUMER_REASON = "scheduled alert lane; Telegram is its consumer, the receipt its output"

COLUMNS = ("symbol", "run_label", "scanned_at", "score", "grade", "decision", "rvol", "price", "change_pct",
           "gap_pct", "float_m", "volume", "catalyst", "catalyst_verified", "disqualified", "source", "sector")


def pick_alerts(rows: Iterable[dict[str, Any]], *, sent: set[str], session: str,
                criteria: Optional[dict] = None,
                judge: Callable[[dict, Optional[dict]], GoVerdict] = evaluate) -> dict[str, list]:
    """Pure. Newest row per symbol; alert when it qualifies and was not alerted this session."""
    newest: dict[str, dict] = {}
    for r in rows:
        sym = str(r.get("symbol") or "").upper()
        if not sym:
            continue
        if sym not in newest or str(r.get("scanned_at") or "") > str(newest[sym].get("scanned_at") or ""):
            newest[sym] = r
    alert, withheld, already = [], [], []
    for sym, r in sorted(newest.items()):
        v = judge(r, criteria)
        if not v.qualifies:
            withheld.append({"symbol": sym, "failed": v.failed, "missing": v.missing})
        elif f"{session}:{sym}" in sent:
            already.append(sym)
        else:
            alert.append({"row": r, "tier": v.tier, "passed": v.passed})
    return {"alert": alert, "withheld": withheld, "already_sent": already}


def format_alert(item: dict) -> str:
    r = item["row"]
    sym = str(r.get("symbol")).upper()
    tier = "🔥 A+" if item["tier"] == "A+" else "✅ GO"
    def num(v, fmt):
        try:
            return fmt.format(float(v))
        except (TypeError, ValueError):
            return "?"
    src = "social + screener" if "social" in str(r.get("source") or "").lower() else "screener"
    lines = [
        f"{tier} {sym} — momentum scalp setup ({src})",
        f"Price {num(r.get('price'), '${:.2f}')} · gap {num(r.get('gap_pct') if r.get('gap_pct') is not None else r.get('change_pct'), '{:+.1f}%')}"
        f" · RVOL {num(r.get('rvol'), '{:.1f}x')} · float {num(r.get('float_m'), '{:.1f}M')}"
        f" · volume {num(r.get('volume'), '{:,.0f}')}",
        f"Score {num(r.get('score'), '{:.0f}')} · catalyst: {str(r.get('catalyst') or 'verified')[:120]}",
        "Meets Trade-AI scalp criteria: " + ", ".join(item["passed"]),
        ("HELD — in book" if item.get("held") is True else "NOT HELD" if item.get("held") is False else ""),
        f"Scan {str(r.get('run_label') or '')} · {str(r.get('scanned_at') or '')[:16]}",
        "Advisory only — no order, size or stop is placed from this alert.",
        AUTHORITY,
    ]
    lines = [l for l in lines if l]  # drop the empty held line when not determined
    return "\n".join(lines)


def rich_alert(item: dict) -> Optional[dict]:
    """The Bot API rendering: bold linked ticker, one line of numbers, chart preview, CC/Finviz/Yahoo buttons.

    Operator 2026-09-14: "no emphasis in links on everything that can go back to the command center or to
    the source". None when the layout cannot be built; the caller then sends format_alert's text.
    """
    if os.environ.get("TELEGRAM_RICH_ALERTS", "1").strip().lower() in ("0", "false", "off", "no"):
        return None
    try:
        from lib.telegram_rich import go_alert  # noqa: PLC0415

        return go_alert(item["row"], tier=item["tier"], passed=item["passed"],
                        held=item.get("held")).render()
    except Exception as exc:  # noqa: BLE001 -- formatting must never cost the alert
        print(f"rich GO layout unavailable ({type(exc).__name__}: {exc}); sending plain text", file=sys.stderr)
        return None


def _cio_go_gate(symbol: str, text: str,
                 db_query: Optional[Callable[..., list[dict]]] = None) -> dict[str, Any]:
    """Consult ``cio_decisions`` before a GO would-send. Fail closed when missing."""
    try:
        from lib.cio_telegram_stance_gate import check_investment_send  # noqa: PLC0415
    except ImportError:
        from scripts.lib.cio_telegram_stance_gate import check_investment_send  # type: ignore
    verdict = check_investment_send(
        symbol=symbol,
        message_text=text,
        asserted_stance="bullish",
        db_query=db_query,
        source="screener_go_alerts",
    )
    return verdict.as_dict()


def _send_go(send_telegram: Callable[..., Any], item: dict,
             db_query: Optional[Callable[..., list[dict]]] = None) -> tuple[bool, Optional[str]]:
    # bypass_router: the legacy router classified "momentum scalp setup" as
    # job_telemetry -> DIGEST and send_telegram returned True for the digested
    # message, so ARMP (A+) and ELMT were recorded as sent at 12:15 on
    # 2026-09-14 and never reached the operator.
    rich = rich_alert(item)
    text = rich["text"] if rich else format_alert(item)
    sym = str(item["row"].get("symbol") or "").upper()
    gate = _cio_go_gate(sym, text, db_query=db_query)
    if not gate.get("allow", False):
        return False, str(gate.get("held_reason") or "cio_stance_conflict")
    if str(gate.get("annotation_text") or "").strip():
        try:
            from lib.cio_telegram_stance_gate import StanceGateVerdict, apply_stance_rewrite  # noqa: PLC0415
        except ImportError:
            from scripts.lib.cio_telegram_stance_gate import StanceGateVerdict, apply_stance_rewrite  # type: ignore
        text = apply_stance_rewrite(text, sym, StanceGateVerdict(**gate))
    extra = ({"reply_markup": rich["reply_markup"], "link_preview_options": rich["link_preview_options"]}
             if rich else {})
    ok = bool(send_telegram(text, bypass_router=True, message_class="operator_alert", **extra))
    return ok, None


def _load_ledger(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _db_rows(session: date) -> list[dict]:
    import psycopg2  # noqa: PLC0415

    def setting(k, d=""):
        v = os.getenv(k, "")
        if v:
            return v
        try:
            for line in (PROJECT_ROOT / ".env").read_text(encoding="utf-8").splitlines():
                if line.startswith(f"{k}="):
                    return line.split("=", 1)[1].strip().strip("'\"")
        except OSError:
            pass
        return d
    conn = psycopg2.connect(host=setting("DB_HOST", "localhost"), dbname=setting("DB_NAME", "trade_ai"),
                            user=setting("DB_USER", "trade_ai"), password=setting("DB_PASSWORD"),
                            options="-c default_transaction_read_only=on", connect_timeout=5)
    try:
        cur = conn.cursor()
        cur.execute(f"SELECT {', '.join(COLUMNS)} FROM trade_ai_scans WHERE run_date = %s AND decision = 'GO'",
                    (session,))
        return [dict(zip(COLUMNS, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="send the alerts (default: dry run)")
    ap.add_argument("--session", help="YYYY-MM-DD (default: today)")
    args = ap.parse_args()
    session = date.fromisoformat(args.session) if args.session else date.today()
    try:
        rows = _db_rows(session)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: could not read trade_ai_scans: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    ledger = _load_ledger(LEDGER)
    plan = pick_alerts(rows, sent=set(ledger), session=session.isoformat(), criteria=load_criteria())
    # B3: held/not-held triage label from the authoritative holdings universe.
    try:
        from lib.holdings_universe import held_equity_tickers  # noqa: PLC0415
        held_set = set(held_equity_tickers())
    except Exception:  # noqa: BLE001 -- a failed holdings read must not cost the alert
        held_set = set()
    for item in plan["alert"]:
        item["held"] = str(item["row"]["symbol"]).upper() in held_set
    sent_now: list[str] = []
    cio_held: list[dict[str, str]] = []
    try:
        from lib.comms_editor import default_db_query as _cio_db  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        _cio_db = None
    if args.send:
        from telegram_alert import send_telegram  # noqa: PLC0415

        for item in plan["alert"]:
            sym = str(item["row"]["symbol"]).upper()
            # bypass_router: the legacy router classified "momentum scalp setup" as
            # job_telemetry -> DIGEST and send_telegram returned True for the digested
            # message, so ARMP (A+) and ELMT were recorded as sent at 12:15 on
            # 2026-09-14 and never reached the operator -- the same silence that hid
            # GO signals for months. The operator asked for these in real time; the
            # Communications Editor still formats every message at the transport.
            # 2026-09-18: also join cio_decisions before would-send (fail closed).
            ok, held_reason = _send_go(send_telegram, item, db_query=_cio_db)
            if ok:
                ledger[f"{session.isoformat()}:{sym}"] = datetime.now(timezone.utc).isoformat()
                sent_now.append(sym)
            elif held_reason:
                cio_held.append({"symbol": sym, "held_reason": held_reason})
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        LEDGER.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    else:
        # Dry-run still consults CIO so the receipt shows what would be held.
        for item in plan["alert"]:
            sym = str(item["row"]["symbol"]).upper()
            text = format_alert(item)
            gate = _cio_go_gate(sym, text, db_query=_cio_db)
            if not gate.get("allow", False):
                cio_held.append({"symbol": sym, "held_reason": str(gate.get("held_reason") or "cio_stance_conflict")})
    report = {"schema": "ScreenerGoAlerts@v1", "ran_at": datetime.now(timezone.utc).isoformat(),
              "session": session.isoformat(), "mode": "send" if args.send else "dry_run",
              "go_rows": len(rows), "qualifying": [a["row"]["symbol"] for a in plan["alert"]],
              "sent": sent_now, "already_sent": plan["already_sent"], "withheld": plan["withheld"],
              "cio_held": cio_held, "authority": AUTHORITY}
    print(json.dumps({k: report[k] for k in ("session", "mode", "go_rows", "qualifying", "sent",
                                              "already_sent", "cio_held")}))
    for w in plan["withheld"][:10]:
        print(f"  withheld {w['symbol']}: failed={w['failed']} missing={w['missing']}")
    for c in cio_held[:10]:
        print(f"  cio_held {c['symbol']}: {c['held_reason']}")
    if not args.send:
        for item in plan["alert"][:3]:
            print("---- would send ----\n" + format_alert(item))
    else:
        RECEIPT.parent.mkdir(parents=True, exist_ok=True)
        RECEIPT.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
