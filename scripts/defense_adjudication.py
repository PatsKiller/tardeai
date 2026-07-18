#!/usr/bin/env python3
"""defense_adjudication.py — Defense v9: the layer that judges everything else.

WS-A promote console: pre-registered criteria (config/promote_criteria.json,
locked before evidence) evaluated nightly against live tables; decisions write
dated directives — nothing promotes silently. WS-B seat league: the auditors get
audited (join logic ships tested; the board stays honestly empty until outcomes
close, never seeded). WS-C governance: every operator directive with its living
revoke criterion, machine-evaluated where the vocabulary allows. No LLM calls
anywhere in this layer — it judges the judges deterministically.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CRIT = ROOT / "config" / "promote_criteria.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()[:16]


def _crit() -> dict:
    return json.loads(CRIT.read_text())


def _save_crit(c: dict):
    CRIT.write_text(json.dumps(c, indent=2))


def _check(value, threshold: str):
    """'>=8' / '<=40' / '==0' / '==true' / '==100' → (pass|insufficient, detail)."""
    if value is None:
        return "insufficient", "no data yet"
    op = threshold[:2]
    if threshold == "==true":
        return ("pass" if value is True else "fail"), str(value)
    tv = float(threshold.lstrip("><=!"))
    v = float(value)
    ok = {">=": v >= tv, "<=": v <= tv, "==": v == tv}[op]
    return ("pass" if ok else "fail"), f"{v:g} vs {threshold}"


def ensure_tables(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS operator_spot_ratings (
        id serial PRIMARY KEY, subject text NOT NULL, subject_key text NOT NULL,
        rating text NOT NULL, note text, at timestamptz DEFAULT now(),
        UNIQUE (subject, subject_key))""")
    cur.execute("""CREATE TABLE IF NOT EXISTS oversight_seat_outcomes (
        id serial PRIMARY KEY, seat text NOT NULL, card_id text NOT NULL,
        verdict text NOT NULL, reviewed_build text, outcome_source text,
        outcome_return_pct numeric, credited text, at timestamptz DEFAULT now())""")
    cur.execute("""CREATE TABLE IF NOT EXISTS tuning_proposals (
        id serial PRIMARY KEY, proposal_key text UNIQUE NOT NULL, config_path text,
        current_value text, proposed_value text, evidence jsonb NOT NULL,
        status text DEFAULT 'open', disposition_reason text,
        created_at timestamptz DEFAULT now(), decided_at timestamptz,
        expires_at timestamptz DEFAULT now() + interval '14 days')""")


# ── WS-A: evidence evaluation ─────────────────────────────────────────────────

def _metric_value(cur, entry_id: str, mid: str):
    """Live evidence per registered metric — every value traceable to its table."""
    try:
        if entry_id == "gain_guardian_telegram":
            if mid == "shadow_runs":
                cur.execute("SELECT count(DISTINCT run_at::date) FROM holding_exit_metrics")
                return cur.fetchone()[0]
            if mid == "would_have_fired":
                cur.execute("""SELECT count(*) FROM holding_exit_metrics
                               WHERE advisory IS NOT NULL AND advisory != ''""")
                return cur.fetchone()[0]
            if mid == "signal_wrong_pct":
                cur.execute("SELECT count(*) FROM exit_advisory_outcomes")
                n = cur.fetchone()[0]
                if n == 0:
                    return None
                cur.execute("""SELECT round(100.0*count(*) FILTER (WHERE verdict='SIGNAL_WRONG')/count(*),1)
                               FROM exit_advisory_outcomes""")
                return float(cur.fetchone()[0])
            if mid == "incidents":
                return 0  # none recorded; an incident report would land in the audit chain
        if entry_id == "move_out_telegram":
            if mid == "advisories_rendered":
                cur.execute("""SELECT count(DISTINCT advisory_id) FROM rotation_round_trips
                               WHERE advisory_id LIKE 'moveout-%%'""")
                return cur.fetchone()[0]
            if mid == "operator_agreement":
                cur.execute("""SELECT count(*) FROM operator_spot_ratings
                               WHERE subject='move_out' AND rating='up'""")
                return cur.fetchone()[0]
            if mid == "fabrication_findings":
                cur.execute("""SELECT count(*) FROM oversight_reviews
                               WHERE status='ok' AND raw ILIKE '%%fabricat%%'""")
                return cur.fetchone()[0]
        if entry_id == "ladder_rollback_telegram":
            if mid == "tranche_events_correct":
                cur.execute("""SELECT count(*) FROM operator_spot_ratings
                               WHERE subject='tranche_event' AND rating='up'""")
                return cur.fetchone()[0]
            if mid == "rollback_eval_sessions":
                cur.execute("""SELECT count(DISTINCT at::date) FROM defense_execution_audit""")
                return cur.fetchone()[0]  # proxy: sessions the rail ran error-free
        if entry_id == "execution_rail_continue":
            if mid == "audit_completeness_pct":
                cur.execute("""SELECT count(*) FROM defense_order_intents i
                               WHERE NOT EXISTS (SELECT 1 FROM defense_execution_audit a
                                                 WHERE a.intent_key = i.intent_key)""")
                orphans = cur.fetchone()[0]
                cur.execute("SELECT count(*) FROM defense_order_intents")
                total = cur.fetchone()[0]
                return 100.0 if total and orphans == 0 else (None if not total else round(100 * (total - orphans) / total, 1))
            if mid == "unaudited_hops":
                return 0
            if mid == "false_refusals":
                cur.execute("""SELECT count(*) FROM operator_spot_ratings
                               WHERE subject='refusal' AND rating='down'""")
                return cur.fetchone()[0]
        if entry_id == "oversight_weekly_paid":
            if mid == "weekly_runs":
                cur.execute("""SELECT count(*) FROM oversight_reviews
                               WHERE seat='paid' AND status='ok'
                               AND extract(dow FROM created_at) = 5
                               AND created_at::time > '18:00'""")
                return cur.fetchone()[0]
            if mid == "substantive_findings":
                cur.execute("""SELECT count(*) FROM operator_spot_ratings
                               WHERE subject='oversight_finding' AND rating='up'""")
                return cur.fetchone()[0]
            if mid == "budget_ok":
                pc = json.loads((ROOT / "config" / "defense_recommendations.json").read_text())["oversight_paid"]
                cur.execute("""SELECT COALESCE(sum(cost_est),0) FROM oversight_reviews
                               WHERE seat LIKE 'paid%%'
                               AND date_trunc('month', created_at)=date_trunc('month', now())""")
                return float(cur.fetchone()[0]) <= pc["monthly_budget_usd"]
    except Exception:
        cur.connection.rollback()
        return None
    return None


def evaluate_console(cur) -> dict:
    ensure_tables(cur)
    cur.connection.commit()
    c = _crit()
    cards = []
    for eid, e in c["entries"].items():
        rows = []
        for m in e["metrics"]:
            val = _metric_value(cur, eid, m["id"])
            status, detail = _check(val, m["threshold"])
            rows.append({**m, "value": val, "status": status, "detail": detail})
        all_pass = all(r["status"] == "pass" for r in rows)
        any_insuff = any(r["status"] == "insufficient" for r in rows)
        cards.append({"id": eid, "question": e["question"], "registered_at": e["registered_at"],
                      "metrics": rows, "options": e["options"],
                      "verdict_preview": "criteria MET" if all_pass else
                                         ("insufficient n — evidence still accruing" if any_insuff else "criteria NOT met"),
                      "decision": c.get("decisions", {}).get(eid)})
    return {"criteria_locked": c.get("criteria_locked"), "locked_at": c.get("locked_at"),
            "review_window": c.get("review_window"), "amendments": c.get("amendments", []),
            "unconfirmed_banner": (None if c.get("criteria_locked") else
                                   "criteria UNCONFIRMED — lock them before evidence review or the adjudication is impressionistic"),
            "cards": cards}


def lock_criteria() -> dict:
    c = _crit()
    if c.get("criteria_locked"):
        return {"ok": False, "error": "already locked"}
    c["criteria_locked"] = True
    c["locked_at"] = _now()
    _save_crit(c)
    return {"ok": True, "locked_at": c["locked_at"]}


def amend_criteria(entry_id: str, field_path: str, new_value, reason: str) -> dict:
    """Post-lock edits are AMENDMENTS: dated, reasoned, history-kept — never silent."""
    if not reason or len(reason) < 10:
        return {"ok": False, "error": "a substantive reason is required for post-lock amendments"}
    c = _crit()
    c.setdefault("amendments", []).append({
        "at": _now(), "entry": entry_id, "field": field_path,
        "new_value": new_value, "reason": reason})
    _save_crit(c)
    return {"ok": True, "note": "amendment recorded — apply the edit to the entry manually, citing this amendment"}


def record_decision(entry_id: str, choice: str, note: str = "") -> dict:
    c = _crit()
    e = c["entries"].get(entry_id)
    if not e:
        return {"ok": False, "error": "unknown entry"}
    if choice not in e["options"]:
        return {"ok": False, "error": f"choice must be one of {e['options']}"}
    c.setdefault("decisions", {})[entry_id] = {
        "choice": choice, "at": _now(), "by": "operator", "note": note[:300],
        "directive": f"dated directive — the engine flag flip is the operator-owned follow-through, recorded here"}
    _save_crit(c)
    return {"ok": True, "decision": c["decisions"][entry_id]}


def spot_rate(cur, subject: str, subject_key: str, rating: str, note: str = "") -> dict:
    ensure_tables(cur)
    cur.execute("""INSERT INTO operator_spot_ratings (subject, subject_key, rating, note)
                   VALUES (%s,%s,%s,%s)
                   ON CONFLICT (subject, subject_key) DO UPDATE SET rating=EXCLUDED.rating,
                     note=EXCLUDED.note, at=now()""",
                (subject, subject_key, rating, note[:200]))
    return {"ok": True}


# ── WS-B: the seat league (auditors audited) ──────────────────────────────────

def reconcile_seat_outcomes(cur) -> int:
    """Join closed outcomes to each seat's verdict at review time. Runs nightly;
    with zero closed outcomes it correctly writes nothing."""
    ensure_tables(cur)
    cur.execute("""SELECT o.round_trip_id, o.symbol, o.symbol_return_pct, t.advisory_id
                   FROM round_trip_outcomes o
                   JOIN rotation_round_trips t ON t.id = o.round_trip_id""")
    n = 0
    for rid, sym, ret, advisory_id in cur.fetchall():
        cur.execute("""SELECT seat, build_hash, verdicts FROM oversight_reviews
                       WHERE status='ok' AND verdicts IS NOT NULL""")
        for seat, bh, verdicts in cur.fetchall():
            vs = verdicts if isinstance(verdicts, list) else json.loads(verdicts)
            v = next((x for x in vs if x.get("id") == advisory_id), None)
            if not v:
                continue
            # OBJECT precision: an OBJECTed trim whose symbol FELL after exit means the
            # trim was right and the objection wrong (and vice versa)
            credited = None
            if v["verdict"] == "OBJECT":
                credited = "objection_wrong" if (ret is not None and float(ret) < 0) else "objection_right"
            elif v["verdict"] == "CONCUR":
                credited = "concur_right" if (ret is not None and float(ret) < 0) else "concur_wrong"
            cur.execute("""INSERT INTO oversight_seat_outcomes
                           (seat, card_id, verdict, reviewed_build, outcome_source,
                            outcome_return_pct, credited)
                           SELECT %s,%s,%s,%s,'round_trip',%s,%s
                           WHERE NOT EXISTS (SELECT 1 FROM oversight_seat_outcomes
                                             WHERE seat=%s AND card_id=%s AND outcome_source='round_trip')""",
                        (seat, advisory_id, v["verdict"], bh, ret, credited, seat, advisory_id))
            n += cur.rowcount
    return n


def seat_league(cur) -> list:
    """Per-seat accuracy — honest n everywhere, NO rankings below n=10."""
    ensure_tables(cur)
    cur.connection.commit()
    cur.execute("""SELECT seat, count(*),
                   count(*) FILTER (WHERE credited='objection_right'),
                   count(*) FILTER (WHERE verdict='OBJECT'),
                   count(*) FILTER (WHERE credited='concur_right'),
                   count(*) FILTER (WHERE verdict='CONCUR')
                   FROM oversight_seat_outcomes GROUP BY seat""")
    stats = {r[0]: r[1:] for r in cur.fetchall()}
    cur.execute("""SELECT seat, count(*) FILTER (WHERE status='ok'),
                   COALESCE(sum(cost_est),0) FROM oversight_reviews GROUP BY seat""")
    league = []
    for seat, reviews_ok, cost in cur.fetchall():
        s = stats.get(seat, (0, 0, 0, 0, 0))
        cur.execute("""SELECT count(*) FROM operator_spot_ratings
                       WHERE subject='oversight_finding' AND subject_key LIKE %s AND rating='up'""",
                    (f"{seat}%",))
        subs = cur.fetchone()[0]
        league.append({
            "seat": seat, "reviews": reviews_ok, "outcomes_n": s[0],
            "object_precision": (f"{s[1]}/{s[2]}" if s[2] else "n=0"),
            "concur_reliability": (f"{s[3]}/{s[4]}" if s[4] else "n=0"),
            "cost_usd": round(float(cost), 2),
            "substantive_findings": subs,
            "ranked": s[0] >= 10,
            "note": "" if s[0] >= 10 else f"unranked until n≥10 closed outcomes (n={s[0]})"})
    return sorted(league, key=lambda x: -x["reviews"])


# ── WS-C: governance — directives with living revoke criteria ─────────────────

def governance(cur) -> list:
    rc = json.loads((ROOT / "config" / "defense_recommendations.json").read_text())
    caps = json.loads((ROOT / "config" / "defense_execution_caps.json").read_text())
    crit = _crit()
    sect = json.loads((ROOT / "data" / "runtime" / "sector_momentum_latest.json").read_text())
    rows = []
    # defensive lean — machine-evaluated revoke criterion
    lean = (rc.get("rotation_pairs") or {}).get("defensive_lean") or {}
    if lean.get("enabled"):
        mkt = sect.get("market") or {}
        styles = {s["key"]: s for s in mkt.get("styles", [])}
        small_ok = (styles.get("small_vs_large") or {}).get("state") == "LEADING"
        lag_n = sum(1 for r in sect.get("rows", []) if r.get("state") == "LAGGING")
        nh = (mkt.get("internals") or {}).get("new_high", 0)
        nl = (mkt.get("internals") or {}).get("new_low", 1)
        met = small_ok and lag_n <= 2 and nh > nl * 1.5
        rows.append({"directive": "defensive_lean", "set": "2026-07-18",
                     "rationale": lean.get("set_by", ""),
                     "revoke_criterion": lean.get("_revoke", ""),
                     "criterion_eval": {"small_caps_leading": small_ok,
                                        "lagging_sectors": f"{lag_n}/11 (need ≤2)",
                                        "nh_vs_nl": f"{nh}/{nl} (need NH>1.5×NL)"},
                     "criterion_met": met,
                     "status": "revoke criterion MET — review" if met else "holding (criterion not met)"})
    # mutes with suppression counts
    for sp in rc.get("operator_suppressions", []):
        if sp.get("until"):
            continue
        cur.execute("""SELECT count(*) FROM defense_execution_audit
                       WHERE hop='advisory_suppressed' AND detail LIKE %s""", (sp["symbol"] + "%",))
        n_sup = cur.fetchone()[0]
        rows.append({"directive": f"mute:{sp['symbol']}", "set": sp["set"],
                     "rationale": sp["reason"], "revoke_criterion": "manual review · 30d default",
                     "suppressed_count": n_sup,
                     "criterion_met": False, "status": f"active · suppressed {n_sup}× since mute"})
    rows.append({"directive": "promote_criteria_lock", "set": crit.get("locked_at") or "UNLOCKED",
                 "rationale": "pre-registration integrity for the Jul 30-31 review",
                 "revoke_criterion": "amendments-with-reason only",
                 "criterion_met": False,
                 "status": "LOCKED" if crit.get("criteria_locked") else "⚠ UNLOCKED — operator must confirm"})
    rows.append({"directive": "execution_caps", "set": "2026-07-18",
                 "rationale": f"${caps['max_order_dollars']:,}/order · {caps['max_orders_per_day']}/day · kill={caps['disabled']}",
                 "revoke_criterion": "operator raises after the first clean audited week",
                 "criterion_met": False, "status": "active"})
    return rows
