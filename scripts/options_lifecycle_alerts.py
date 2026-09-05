#!/usr/bin/env python3
"""options_lifecycle_alerts.py — Phases 4+5: assignment/expiry engine + alert lifecycle.

Phase 4 — assignment_review(): DTE escalation windows, near-the-money and ITM
shorts, early-assignment (extrinsic floor + ex-div vs extrinsic using Schwab
fundamentals' next_div_date; dividend AMOUNT is estimated from yield and is
labeled an estimate), covered-share verification against live holdings, CSP
cash requirement, expiry-day do-not-expire-unreviewed. Unknown data yields an
explicit 'unknown' finding — never a silent pass.

Phase 5 — persistent alert lifecycle (options_lifecycle_alerts table):
NEW → ACKNOWLEDGED / SNOOZED → ESCALATED (unacked urgent, policy cadence,
bounded count) → SUPERSEDED / RESOLVED. Dedupe on
(strategy_position_id, recommendation, policy_version, urgency, dte_window,
giveback_bucket). Telegram only for red/amber and only through the router's
should_send_telegram gate. Digest is a pure text builder for the cron.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from options_lifecycle_model import ensure_tables
from options_lifecycle_engine import policy

HOLDINGS = ROOT / "data" / "portfolios" / "state" / "holdings.json"


def ensure_alert_tables(cur, conn):
    cur.execute("""CREATE TABLE IF NOT EXISTS options_lifecycle_alerts (
        alert_id serial PRIMARY KEY,
        strategy_position_id int NOT NULL,
        decision_id int,
        dedupe_key text NOT NULL,
        state text NOT NULL DEFAULT 'NEW',
        urgency text NOT NULL,
        title text NOT NULL,
        body text NOT NULL,
        findings jsonb NOT NULL DEFAULT '[]',
        channels_sent jsonb NOT NULL DEFAULT '[]',
        escalation_count int NOT NULL DEFAULT 0,
        created_at timestamptz DEFAULT now(),
        acknowledged_at timestamptz,
        snoozed_until timestamptz,
        escalated_at timestamptz,
        resolved_at timestamptz)""")
    cur.execute("""CREATE INDEX IF NOT EXISTS ix_ola_open
                   ON options_lifecycle_alerts (strategy_position_id)
                   WHERE state NOT IN ('RESOLVED','SUPERSEDED')""")
    # v1.2 P1: delivery-evidence columns in the committed builder (were workstation-only)
    for ddl in (
        "ALTER TABLE options_lifecycle_alerts ADD COLUMN IF NOT EXISTS attempted_at timestamptz",
        "ALTER TABLE options_lifecycle_alerts ADD COLUMN IF NOT EXISTS delivered_at timestamptz",
        "ALTER TABLE options_lifecycle_alerts ADD COLUMN IF NOT EXISTS message_id text",
        "ALTER TABLE options_lifecycle_alerts ADD COLUMN IF NOT EXISTS failure_reason text",
        "ALTER TABLE options_lifecycle_alerts ADD COLUMN IF NOT EXISTS retry_count int NOT NULL DEFAULT 0",
    ):
        cur.execute(ddl)
    conn.commit()


# ── Phase 4: assignment / exercise / expiration review ───────────────────────

def dte_window(dte: int | None, pol: dict) -> int | None:
    """Smallest configured escalation window the position has entered."""
    if dte is None:
        return None
    for w in sorted(pol["assignment"]["escalation_dte_windows"]):
        if dte <= w:
            return w
    return None


def _fundamentals(underlying: str) -> dict:
    try:
        import schwab_transport as st
        f = st.get_fundamentals([underlying])
        if f.get("status") == "ok" and f.get("fundamentals"):
            return f["fundamentals"][0] or {}
    except Exception:
        pass
    return {}


def _held_shares_live(account_key: str, symbol: str) -> float | None:
    try:
        h = json.loads(HOLDINGS.read_text())
        alias = {"schwab_roth_ira": "schwab_roth"}
        acct = alias.get(account_key, account_key)
        return sum(float(r.get("shares") or 0) for r in h.get("holdings", [])
                   if (r.get("symbol") or "").upper() == symbol.upper()
                   and (r.get("account") or "") in (acct, account_key) and not r.get("is_cash"))
    except Exception:
        return None


def assignment_review(s: dict, eco: dict, pol: dict) -> list[dict]:
    """[{code, urgency, line}] — every finding is a full sentence; unknowns are
    findings too (fail closed, never silent)."""
    a = pol["assignment"]
    out = []
    dte = eco.get("dte_nearest")
    legs = [l for l in s["legs"] if l["status"] == "open"]
    shorts = [l for l in legs if l["side"] == "short"]
    und_px = eco.get("underlying_price")

    w = dte_window(dte, pol)
    if w is not None:
        urg = "red" if w <= 1 else ("amber" if w <= 7 else "green")
        out.append({"code": f"dte_window_{w}", "urgency": urg,
                    "line": f"{dte} DTE — inside the {w}-day escalation window; management cadence tightens."})
    if dte == 0:
        if a["do_not_expire_unreviewed"]:
            out.append({"code": "expiry_day", "urgency": "red",
                        "line": "EXPIRATION DAY. Nothing expires unreviewed: confirm intent for every leg "
                                "(close, let expire OTM, or accept exercise/assignment). OCC auto-exercises "
                                "$0.01 ITM."})
    if shorts and und_px:
        for l in shorts:
            k = float(l["strike"])
            itm = (und_px > k) if l["option_type"] == "call" else (und_px < k)
            dist = abs(und_px - k) / und_px * 100
            if itm:
                out.append({"code": f"itm_short_{l['occ_symbol']}", "urgency": "red",
                            "line": f"Short {l['option_type']} {l['occ_symbol'].strip()} is ITM "
                                    f"(spot ${und_px:.2f} vs strike ${k:g}) — assignment is live risk, "
                                    "rising as extrinsic decays."})
            elif dist <= a["near_money_pct"]:
                out.append({"code": f"near_money_{l['occ_symbol']}", "urgency": "amber",
                            "line": f"Short strike ${k:g} only {dist:.1f}% from spot — inside the "
                                    f"{a['near_money_pct']}% near-money band; pin risk if this holds into expiry."})
        ext = eco.get("extrinsic_value")
        if ext is not None and any((und_px > float(l["strike"])) if l["option_type"] == "call"
                                   else (und_px < float(l["strike"])) for l in shorts):
            if abs(ext) < a["early_assignment_extrinsic_floor_dollars"]:
                out.append({"code": "early_assignment_extrinsic", "urgency": "red",
                            "line": f"Extrinsic value ≈ ${abs(ext):.0f} — below the "
                                    f"${a['early_assignment_extrinsic_floor_dollars']} floor with an ITM short. "
                                    "Early assignment becomes rational for the counterparty."})
        short_calls = [l for l in shorts if l["option_type"] == "call"]
        if short_calls:
            f = _fundamentals(s["underlying"])
            nd = f.get("next_div_date")
            if nd:
                try:
                    ex_days = (date.fromisoformat(str(nd)[:10]) - date.today()).days
                except Exception:
                    ex_days = None
                if ex_days is not None and 0 <= ex_days <= (dte or 0):
                    div_est = None
                    if f.get("div_yield") and und_px:
                        div_est = round(float(f["div_yield"]) / 100 * und_px / 4, 2)
                    ext = eco.get("extrinsic_value")
                    cmp_line = ""
                    if div_est is not None and ext is not None:
                        per_sh_ext = abs(ext) / (sum(float(l["contracts"]) for l in short_calls) * 100)
                        cmp_line = (f" Est. dividend ${div_est}/sh (yield-derived ESTIMATE) vs extrinsic "
                                    f"${per_sh_ext:.2f}/sh — " +
                                    ("dividend EXCEEDS extrinsic: early assignment before ex-div is likely "
                                     "for ITM calls." if div_est > per_sh_ext else
                                     "extrinsic still exceeds the dividend."))
                    out.append({"code": "exdiv_window", "urgency": "red" if "EXCEEDS" in cmp_line else "amber",
                                "line": f"Ex-dividend {nd} falls inside this option's life ({ex_days}d away)."
                                        + cmp_line})
            else:
                out.append({"code": "exdiv_unknown", "urgency": "green",
                            "line": "Ex-dividend date UNKNOWN (no fundamentals) — dividend-driven early "
                                    "assignment cannot be assessed. Treat as unreviewed, not as safe."})
    # covered-share verification
    if s["strategy_type"] in ("covered_call", "collar"):
        need = sum(float(l["contracts"]) * int(l["multiplier"]) for l in shorts if l["option_type"] == "call")
        held = _held_shares_live(s["account_key"], s["underlying"])
        if held is None:
            out.append({"code": "cover_unknown", "urgency": "amber",
                        "line": "Cannot verify covering shares (holdings unavailable) — fail closed: treat "
                                "as under-covered until verified."})
        elif held < need:
            out.append({"code": "under_covered", "urgency": "red",
                        "line": f"UNDER-COVERED: short calls need {need:.0f} sh, holdings show {held:.0f}. "
                                "An assignment would create a naked short share position."})
    if s["strategy_type"] == "cash_secured_put":
        cash_need = sum(float(l["strike"]) * float(l["contracts"]) * int(l["multiplier"])
                        for l in shorts if l["option_type"] == "put")
        out.append({"code": "csp_cash_note", "urgency": "green",
                    "line": f"Assignment would require ${cash_need:,.0f} cash — verify collateral remains "
                            "unencumbered in this account."})
    return out


# ── Phase 5: alert lifecycle ─────────────────────────────────────────────────

def _giveback_bucket(eco: dict, pol: dict) -> int:
    gb, mfe = eco.get("giveback"), eco.get("mfe")
    step = pol["alerts"]["giveback_notify_step_pct"]
    if gb is None or not mfe or float(mfe) <= 0:
        return -1
    return int((gb / float(mfe) * 100) // step)


def _dedupe_key(spid: int, d: dict, eco: dict, pol: dict) -> str:
    return "|".join([str(spid), d["recommendation"], pol["policy_version"], d["urgency"],
                     str(dte_window(eco.get("dte_nearest"), pol)), str(_giveback_bucket(eco, pol))])


URGENCY_RANK = {"green": 0, "amber": 1, "red": 2}


def _telegram_ev(text: str) -> dict:
    """Send via telegram_alert.send_telegram chokepoint. Evidence: {ok, message_id, error}."""
    try:
        from telegram_alert import send_telegram
        ok = bool(send_telegram(text))
        try:
            from lib.comms import CommunicationEvent, publish_communication
            publish_communication(CommunicationEvent(
                direction="OUTBOUND", event_type="alert", message_class="ops",
                producer="options_lifecycle_alerts", subject_key="ops:options_lifecycle",
                retention_class="operational", severity="warning",
                sanitized_body=text[:500], short_summary=text[:120],
            ))
        except Exception:
            # ALARM-DELIVERY-DECLARED: shadow ledger best-effort; never blocks operator alert
            pass
        return {"ok": ok, "message_id": None, "error": None if ok else "send_telegram_failed"}
    except Exception as e:
        return {"ok": False, "message_id": None, "error": str(e)[:80]}


def _telegram(text: str) -> bool:
    return _telegram_ev(text)["ok"]


def _identity_header(s: dict, d: dict, eco: dict, decision_id) -> str:
    """v1.1 P8: every alert names the exact contract, strategy, and decision."""
    legs = [l for l in s["legs"] if l["status"] == "open"]
    strikes = "/".join(f"{float(l['strike']):g}{'C' if l['option_type'] == 'call' else 'P'}" for l in legs)
    exps = "/".join(sorted({str(l["expiration"])[:10] for l in legs}))
    n = "+".join(f"{float(l['contracts']):g}" for l in legs)
    return (f"{s['account_key']} · pos #{s['strategy_position_id']} · {s['underlying']} "
            f"{s['strategy_type'].replace('_', ' ')} · {strikes} exp {exps} · {n} contract(s) · "
            f"{d['recommendation']} · snapshot {datetime.now(timezone.utc).strftime('%m-%d %H:%MZ')}"
            + (f" · decision #{decision_id}" if decision_id else ""))


def process_alerts(cur, conn, s: dict, eco: dict, d: dict, decision_id: int | None,
                   pol: dict, notify: bool = True, findings: list | None = None) -> dict | None:
    """One strategy's post-decision alert pass. v1.1: `d` is the REDUCED primary
    (one recommendation per snapshot — its urgency is authoritative); findings
    ride INSIDE the same message as supporting context, never as independent
    contradictory primaries. Delivery evidence recorded on the alert row."""
    findings = assignment_review(s, eco, pol) if findings is None else findings
    urgency = d["urgency"]
    key = _dedupe_key(s["strategy_position_id"], d, eco, pol)
    spid = s["strategy_position_id"]
    cur.execute("""SELECT alert_id, dedupe_key, urgency, state FROM options_lifecycle_alerts
                   WHERE strategy_position_id=%s AND state NOT IN ('RESOLVED','SUPERSEDED')
                   ORDER BY alert_id DESC LIMIT 1""", (spid,))
    live = cur.fetchone()
    if live and live[1] == key and URGENCY_RANK[urgency] <= URGENCY_RANK[live[2]]:
        return None  # duplicate state — no re-alert
    header = _identity_header(s, d, eco, decision_id)
    title = f"{s['underlying']} {s['strategy_type'].replace('_', ' ')} — {d['recommendation']}"
    body = header + "\n" + d["rationale"] + (
        "".join("\n• " + x.get("line", "") for x in (d.get("subordinate") or []) if x.get("line")) or
        "".join("\n• " + f["line"] for f in findings))
    if live:
        cur.execute("""UPDATE options_lifecycle_alerts SET state='SUPERSEDED', resolved_at=now()
                       WHERE alert_id=%s""", (live[0],))
    cur.execute("""INSERT INTO options_lifecycle_alerts
        (strategy_position_id, decision_id, dedupe_key, urgency, title, body, findings)
        VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING alert_id""",
        (spid, decision_id, key, urgency, title, body, json.dumps(findings)))
    aid = cur.fetchone()[0]
    sent = []
    if notify and urgency in pol["alerts"]["telegram_urgencies"]:
        mark = {"red": "🔴", "amber": "🟠"}.get(urgency, "")
        cur.execute("UPDATE options_lifecycle_alerts SET attempted_at=now() WHERE alert_id=%s", (aid,))
        ev = _telegram_ev(f"{mark} OPTIONS LIFECYCLE\n{header}\n{d['rationale'][:400]}")
        if ev["ok"]:
            sent.append("telegram")
            cur.execute("""UPDATE options_lifecycle_alerts SET delivered_at=now(), message_id=%s
                           WHERE alert_id=%s""", (ev["message_id"], aid))
        else:
            cur.execute("""UPDATE options_lifecycle_alerts SET failure_reason=%s,
                           retry_count=retry_count+1 WHERE alert_id=%s""", (ev["error"], aid))
    cur.execute("UPDATE options_lifecycle_alerts SET channels_sent=%s WHERE alert_id=%s",
                (json.dumps(sent), aid))
    conn.commit()
    return {"alert_id": aid, "urgency": urgency, "title": title, "sent": sent}


def resolve_alerts_for(cur, conn, spid: int, reason: str = "position closed"):
    cur.execute("""UPDATE options_lifecycle_alerts SET state='RESOLVED', resolved_at=now()
                   WHERE strategy_position_id=%s AND state NOT IN ('RESOLVED','SUPERSEDED')""", (spid,))
    conn.commit()


def escalate_unacked(cur, conn, pol: dict, notify: bool = True) -> list[int]:
    """Urgent (red) alerts unacknowledged past the policy window escalate —
    bounded count, re-notified, state ESCALATED."""
    a = pol["alerts"]
    cur.execute("""SELECT alert_id, title, escalation_count FROM options_lifecycle_alerts
                   WHERE urgency='red' AND state IN ('NEW','ESCALATED')
                     AND acknowledged_at IS NULL
                     AND (snoozed_until IS NULL OR snoozed_until < now())
                     AND escalation_count < %s
                     AND COALESCE(escalated_at, created_at) < now() - make_interval(hours => %s)""",
                (a["urgent_unacked_max_escalations"], a["urgent_unacked_escalate_hours"]))
    escalated = []
    for aid, title, cnt in cur.fetchall():
        cur.execute("""UPDATE options_lifecycle_alerts SET state='ESCALATED', escalated_at=now(),
                       escalation_count=escalation_count+1 WHERE alert_id=%s""", (aid,))
        if notify:
            _telegram(f"⛔ ESCALATION #{cnt + 1} — unacknowledged urgent options alert: {title}. "
                      "Acknowledge or act; this desk does not let urgent risks age silently.")
        escalated.append(aid)
    conn.commit()
    return escalated


def ack_alert(cur, conn, alert_id: int, snooze_hours: float | None = None) -> dict:
    if snooze_hours:
        cur.execute("""UPDATE options_lifecycle_alerts SET state='SNOOZED', acknowledged_at=now(),
                       snoozed_until=now() + make_interval(hours => %s) WHERE alert_id=%s""",
                    (snooze_hours, alert_id))
    else:
        cur.execute("""UPDATE options_lifecycle_alerts SET state='ACKNOWLEDGED', acknowledged_at=now()
                       WHERE alert_id=%s""", (alert_id,))
    conn.commit()
    return {"ok": True, "alert_id": alert_id, "state": "SNOOZED" if snooze_hours else "ACKNOWLEDGED"}


def open_alerts(cur) -> list[dict]:
    cur.execute("""SELECT alert_id, strategy_position_id, urgency, state, title, body,
                          escalation_count, created_at, snoozed_until
                   FROM options_lifecycle_alerts
                   WHERE state NOT IN ('RESOLVED','SUPERSEDED')
                   ORDER BY CASE urgency WHEN 'red' THEN 0 WHEN 'amber' THEN 1 ELSE 2 END, alert_id DESC""")
    cols = ["alert_id", "strategy_position_id", "urgency", "state", "title", "body",
            "escalation_count", "created_at", "snoozed_until"]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def daily_digest(cur) -> str:
    """Pure text for the optional daily digest cron. Honest about emptiness."""
    alerts = open_alerts(cur)
    cur.execute("""SELECT count(*) FROM options_strategy_positions WHERE status IN ('open','closing')""")
    n_open = cur.fetchone()[0]
    if n_open == 0:
        return "OPTIONS LIFECYCLE DIGEST — no open option strategies. Desk armed, book empty."
    lines = [f"OPTIONS LIFECYCLE DIGEST — {n_open} open strateg{'y' if n_open == 1 else 'ies'}, "
             f"{len(alerts)} live alert(s)"]
    for a in alerts[:10]:
        lines.append(f"[{a['urgency'].upper()}/{a['state']}] {a['title']}")
    return "\n".join(lines)


if __name__ == "__main__":
    from db_adapter import _get_conn
    conn = _get_conn(); cur = conn.cursor()
    ensure_tables(cur, conn)
    ensure_alert_tables(cur, conn)
    print("alert tables ensured")
    print(daily_digest(cur))
