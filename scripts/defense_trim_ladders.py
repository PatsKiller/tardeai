#!/usr/bin/env python3
"""defense_trim_ladders.py — Defense v5: dynamic trims (DT), exit ladders (EL),
rotation plan (RP).

DT: compute_trim_plan() replaces the static "25–50%" band with a deterministic
composite whose ARITHMETIC RENDERS ON THE CARD — base from factor severity, GG
state modifier, concentration overage, stop context. Absent inputs are listed,
never silently defaulted. Sell tickets are per-account share/proceeds ESTIMATES
(as-of labeled, whole shares, IRA-first ordering with the taxable-harvest variant
shown, never auto-chosen).

EL: every trim advisory arms a ladder — T1 actionable now, T2 (T3 when urgent)
with machine-evaluable triggers frozen at creation: sector-state persistence,
price level (hosted on the 20-min watch_alerts evaluator), GG escalation,
factor-count increase. Symmetric: triggers confirm → tranche FIRES; sector
recovers / GG normalizes → tranche DISARMS visibly.

RP: confirmed partial trims open re-entry watches for the trimmed slice by
inserting tranche-slice rows into rotation_round_trips (Phase-0 decision: reuse
the RT machinery — its conditions/wash/outcome logic applies verbatim; a
`tranche_of` column keys the slice to its ladder).

Advisory-only; SHADOW discipline; nothing here places orders.
"""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config" / "defense_recommendations.json").read_text())
TC = CFG["trim_composite"]
LC = CFG["ladder"]


# ── DT1: the composite ─────────────────────────────────────────────────────────

def gg_latest(cur) -> dict:
    """Latest Gain Guardian state per (symbol, account)."""
    cur.execute("""SELECT DISTINCT ON (symbol, account) symbol, account, advisory,
                          severity, extension_state, giveback_state
                   FROM holding_exit_metrics ORDER BY symbol, account, run_at DESC""")
    return {(r[0], r[1]): {"advisory": r[2], "severity": r[3],
                           "extension_state": r[4], "giveback_state": r[5]}
            for r in cur.fetchall()}


def stop_context(cur, symbol: str, account: str) -> dict | None:
    """Active protective stop for the position, if any (stop_lifecycle)."""
    try:
        cur.execute("""SELECT stop_price, proximity_pct FROM stop_lifecycle
                       WHERE symbol=%s AND account=%s AND status IN ('open','active','WORKING')
                       ORDER BY id DESC LIMIT 1""", (symbol, account))
        r = cur.fetchone()
        return {"stop_price": float(r[0]), "proximity_pct": float(r[1] or 0)} if r else None
    except Exception:
        cur.connection.rollback()
        return None


def compute_trim_plan(factors: list, severity_urgent: bool, gg: dict | None,
                      eff_sector_pct: float | None, stop: dict | None) -> dict:
    """Deterministic trim fraction with rendered arithmetic + absent-input list."""
    arith, absent = [], []
    n = len(factors)
    base = TC["urgent_pct"] if severity_urgent else \
        TC["base_by_factor_count"].get(str(min(n, 4)), TC["base_by_factor_count"]["2"])
    frac = base
    arith.append(f"{n} factors ({base})" + (" · urgent" if severity_urgent else ""))

    if gg:
        gb = (gg.get("giveback_state") or "").upper()
        ext = (gg.get("extension_state") or "").upper()
        if "BREACH" in gb:
            frac += TC["gg_giveback_breach_pp"]
            arith.append(f"giveback-breach (+{TC['gg_giveback_breach_pp']})")
        elif "WATCH" in gb:
            frac += TC["gg_giveback_watch_pp"]
            arith.append(f"giveback-watch (+{TC['gg_giveback_watch_pp']})")
        if ext in ("EXTENDED", "CLIMAX") and frac < TC["gg_extended_floor_pct"]:
            frac = TC["gg_extended_floor_pct"]
            arith.append(f"GG {ext.lower()} floor ({TC['gg_extended_floor_pct']}) — fraction not persisted, floor from state")
    else:
        absent.append("GG: no row — not applied")

    if eff_sector_pct is not None:
        over = eff_sector_pct - TC["concentration_target_pct"]
        if over > 0:
            add = min(TC["concentration_cap_pp"], round(over))
            frac += add
            arith.append(f"concentration {eff_sector_pct:.1f}% vs {TC['concentration_target_pct']}% target (+{add})")
    else:
        absent.append("effective sector weight: n/a — not applied")

    if stop is None:
        gg_protects = bool(gg and ((gg.get("advisory") or "").strip()
                                   or (gg.get("giveback_state") or "").strip()
                                   or (gg.get("extension_state") or "NORMAL").upper() != "NORMAL"))
        if not gg_protects:
            frac += TC["no_protection_pp"]
            arith.append(f"no stop, no GG protection (+{TC['no_protection_pp']})")
    elif 0 < abs(stop.get("proximity_pct", 99)) <= 8:
        frac += TC["tight_stop_pp"]
        arith.append(f"tight stop {stop['proximity_pct']:+.1f}% ({TC['tight_stop_pp']})")

    lo, hi = TC["bounds_pct"]
    bounded = max(lo, min(hi, frac))
    if bounded != frac:
        arith.append(f"bounded {lo}–{hi}")
    step = TC["round_to"]
    final = int(round(bounded / step) * step)
    return {"fraction_pct": final,
            "rationale": f"trim {final}% — " + " + ".join(arith) +
                         (" · absent: " + "; ".join(absent) if absent else " · bounds ok"),
            "arithmetic": arith, "absent_inputs": absent}


# ── DT2: sell tickets ──────────────────────────────────────────────────────────

def sell_ticket(symbol: str, acct_rows: list, fraction_pct: int, as_of_label: str,
                sector: str | None, sector_dollars: float | None,
                total_book: float, lookthrough_weight: float = 1.0) -> dict:
    """Per-account sell options, IRA-first; taxable slice renders as the labeled
    harvest variant (wash chip) — both shown, operator picks. Estimates only."""
    ira_first = sorted(acct_rows, key=lambda r: (r["account"] == "schwab_taxable", -r["value"]))
    options = []
    for r in ira_first:
        if r["shares"] <= 0 or r["price"] <= 0:
            continue
        whole = r["shares"] == int(r["shares"])
        sh = math.floor(r["shares"] * fraction_pct / 100) if whole else round(r["shares"] * fraction_pct / 100, 3)
        if not sh:
            continue
        proceeds = sh * r["price"]
        after = r["value"] - proceeds
        opt = {"account": r["account"],
               "account_label": CFG["account_labels"].get(r["account"], r["account"]),
               "shares": sh, "price": r["price"], "price_as_of": as_of_label,
               "proceeds_est": round(proceeds), "position_after": round(after),
               "kind": "taxable_harvest" if r["account"] == "schwab_taxable" else "ira_first",
               "line": (f"Sell ≈ {sh} sh @ ~${r['price']:.2f} ≈ ${proceeds/1000:.1f}K "
                        f"({fraction_pct}% of {CFG['account_labels'].get(r['account'], r['account'])}) "
                        f"→ position after ${after/1000:.1f}K")}
        if opt["kind"] == "taxable_harvest":
            opt["line"] += " · TAXABLE-HARVEST option — wash-sale window applies; basis n/a until Cost Basis export; verify with tax context (Alex)"
        # resulting effective sector exposure (the lookthrough math pays off here)
        if sector and sector_dollars and total_book:
            sold_sector = proceeds * lookthrough_weight
            after_pct = (sector_dollars - sold_sector) / total_book * 100
            opt["sector_after"] = {"sector": sector,
                                   "before_pct": round(sector_dollars / total_book * 100, 1),
                                   "after_pct": round(after_pct, 1)}
            opt["line"] += f" · {sector} effective {opt['sector_after']['before_pct']}% → {opt['sector_after']['after_pct']}%"
        options.append(opt)
    return {"ordering": "IRA-first (no tax event) — taxable variant labeled, never auto-chosen",
            "options": options}


# ── EL: ladders ────────────────────────────────────────────────────────────────

def ensure_ladder_tables(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS rotation_ladders (
        id serial PRIMARY KEY, advisory_id text UNIQUE NOT NULL, symbol text NOT NULL,
        account text NOT NULL, status text NOT NULL DEFAULT 'open',
        t1_fraction int, t1_status text DEFAULT 'advised',
        tranches jsonb NOT NULL DEFAULT '[]',
        factor_count_at_creation int, created_at timestamptz DEFAULT now(),
        closed_at timestamptz, close_reason text)""")
    cur.execute("""ALTER TABLE rotation_round_trips
                   ADD COLUMN IF NOT EXISTS tranche_of int""")


def swing_low(cur, symbol: str, days: int) -> float | None:
    cur.execute("""SELECT min(close_price) FROM ticker_prices
                   WHERE symbol=%s AND price_date > CURRENT_DATE - %s""", (symbol, days))
    r = cur.fetchone()
    return round(float(r[0]), 2) if r and r[0] else None


def arm_ladder(cur, card: dict, plan: dict, sector: str | None, state: str | None,
               factor_count: int, urgent: bool) -> dict | None:
    """Create the ladder for a trim advisory (idempotent per advisory_id).
    Triggers frozen at creation — machine-evaluable vocabulary ONLY."""
    sym, acct = card["instruments"][0]["symbol"], card["accounts"][0]
    cur.execute("SELECT id, tranches FROM rotation_ladders WHERE advisory_id=%s", (card["id"],))
    if cur.fetchone():
        return None
    low = swing_low(cur, sym, LC["price_trigger_lookback_days"])
    triggers = []
    if sector and state:
        triggers.append({"type": "sector_persist", "sector": sector, "state": state,
                         "sessions": LC["sector_persist_sessions"],
                         "label": f"{sector} still {state} after {LC['sector_persist_sessions']} more sessions"})
    if low:
        triggers.append({"type": "price_below", "symbol": sym, "level": low,
                         "label": f"close < ${low} ({LC['price_trigger_lookback_days']}d swing low)"})
    triggers.append({"type": "gg_escalation", "symbol": sym, "account": acct,
                     "label": "GG escalates to GIVEBACK-BREACH or CLIMAX"})
    triggers.append({"type": "factor_increase", "baseline": factor_count,
                     "label": f"factor count rises above {factor_count}"})
    tranches = [{"tranche": "T2", "add_fraction_pct": LC["t2_add_pp"], "status": "armed",
                 "triggers": triggers}]
    if urgent and LC["t3_only_when_urgent"]:
        tranches.append({"tranche": "T3", "add_fraction_pct": LC["t3_add_pp"], "status": "armed",
                         "triggers": [{"type": "gg_escalation", "symbol": sym, "account": acct,
                                       "label": "GG CLIMAX / giveback-breach after T2"}]})
    cur.execute("""INSERT INTO rotation_ladders (advisory_id, symbol, account, t1_fraction,
                   tranches, factor_count_at_creation)
                   VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
                (card["id"], sym, acct, plan["fraction_pct"], json.dumps(tranches), factor_count))
    lid = cur.fetchone()[0]
    # price trigger hosted on the 20-min watch_alerts evaluator (reuse — no new loop)
    if low:
        cur.execute("""SELECT 1 FROM watch_alerts WHERE symbol=%s AND condition_type='price_cross_below'
                       AND threshold=%s AND created_by='defense_ladder' AND active LIMIT 1""", (sym, low))
        if not cur.fetchone():
            cur.execute("""INSERT INTO watch_alerts (symbol, condition_type, threshold, recurring,
                           active, created_by, note)
                           VALUES (%s,'price_cross_below',%s,false,true,'defense_ladder',%s)""",
                        (sym, low, f"ladder#{lid} T2 price trigger"))
    return {"ladder_id": lid, "tranches": tranches}


def evaluate_ladders(cur, sector_states: dict, factor_counts: dict, gg: dict) -> list:
    """Nightly: fire OR disarm armed tranches. Both paths mandatory. Returns render rows."""
    cur.execute("""SELECT id, advisory_id, symbol, account, status, t1_fraction, t1_status,
                          tranches, factor_count_at_creation, created_at
                   FROM rotation_ladders WHERE status='open' ORDER BY created_at DESC""")
    out = []
    now = datetime.now(timezone.utc)
    for lid, aid, sym, acct, status, t1f, t1s, tranches, fc0, created in cur.fetchall():
        tranches = tranches if isinstance(tranches, list) else json.loads(tranches)
        changed = False
        if isinstance(created, str):
            created = datetime.fromisoformat(created.replace(" ", "T").split(".")[0] + "+00:00")
        created = created if created.tzinfo else created.replace(tzinfo=timezone.utc)
        sessions_open = max(0, ((now - created).days * 5) // 7)
        for t in tranches:
            if t["status"] != "armed":
                continue
            fired_by, disarm = None, None
            for tr in t["triggers"]:
                if tr["type"] == "sector_persist":
                    cur_state = sector_states.get(tr["sector"])
                    if cur_state not in (tr["state"], None):
                        disarm = f"sector recovered — {tr['sector']} now {cur_state}"
                    elif cur_state == tr["state"] and sessions_open >= tr["sessions"]:
                        fired_by = tr["label"]
                elif tr["type"] == "price_below":
                    cur.execute("""SELECT last_fired_at FROM watch_alerts WHERE symbol=%s
                                   AND condition_type='price_cross_below' AND threshold=%s
                                   AND created_by='defense_ladder' AND last_fired_at IS NOT NULL
                                   LIMIT 1""", (tr["symbol"], tr["level"]))
                    if cur.fetchone():
                        fired_by = tr["label"]
                elif tr["type"] == "gg_escalation":
                    g = gg.get((sym, acct)) or {}
                    if "BREACH" in (g.get("giveback_state") or "").upper() or \
                            (g.get("extension_state") or "").upper() == "CLIMAX":
                        fired_by = tr["label"]
                elif tr["type"] == "factor_increase":
                    if factor_counts.get((sym, acct), 0) > tr["baseline"]:
                        fired_by = tr["label"]
                if fired_by:
                    break
            if fired_by:
                t["status"] = "fired"
                t["fired_at"] = now.isoformat()
                t["fired_by"] = fired_by
                changed = True
            elif disarm:
                t["status"] = "disarmed"
                t["disarmed_at"] = now.isoformat()
                t["disarmed_reason"] = disarm
                changed = True
        # ladder expires with its advisory's invalidation: sector recovered AND no armed/fired-pending
        if all(t["status"] in ("disarmed", "executed") for t in tranches):
            status = "closed"
            cur.execute("""UPDATE rotation_ladders SET status='closed', closed_at=now(),
                           close_reason='all tranches resolved' WHERE id=%s""", (lid,))
        if changed:
            cur.execute("UPDATE rotation_ladders SET tranches=%s WHERE id=%s",
                        (json.dumps(tranches), lid))
        out.append({"ladder_id": lid, "advisory_id": aid, "symbol": sym, "account": acct,
                    "t1_fraction": t1f, "t1_status": t1s, "tranches": tranches,
                    "status": status})
    return out


def confirm_tranche(cur, ladder_id: int, tranche: str, qty=None, price=None) -> bool:
    """One-tap tranche execution → RP1: the executed slice opens a re-entry watch
    (rotation_round_trips row keyed by tranche_of) with conditions frozen NOW."""
    cur.execute("SELECT symbol, account, tranches, t1_fraction FROM rotation_ladders WHERE id=%s",
                (ladder_id,))
    row = cur.fetchone()
    if not row:
        return False
    sym, acct, tranches, t1f = row
    tranches = tranches if isinstance(tranches, list) else json.loads(tranches)
    frac = t1f
    if tranche == "T1":
        cur.execute("UPDATE rotation_ladders SET t1_status='executed' WHERE id=%s", (ladder_id,))
    else:
        hit = next((t for t in tranches if t["tranche"] == tranche), None)
        if not hit or hit["status"] not in ("armed", "fired"):
            return False
        hit["status"] = "executed"
        hit["executed_at"] = datetime.now(timezone.utc).isoformat()
        frac = hit["add_fraction_pct"]
        cur.execute("UPDATE rotation_ladders SET tranches=%s WHERE id=%s",
                    (json.dumps(tranches), ladder_id))
    import rotation_round_trips as rt
    try:
        cur.execute("""SELECT 1 FROM operator_core_registry WHERE symbol=%s
                       AND (account IS NULL OR account=%s) LIMIT 1""", (sym, acct))
        slice_core = cur.fetchone() is not None
    except Exception:
        cur.connection.rollback()
        slice_core = False
    conds = rt.conditions_from_card(
        {"instruments": [{"symbol": sym}]}, None, None, is_core=slice_core)
    cur.execute("""INSERT INTO rotation_round_trips
                   (advisory_id, symbol, account, status, exit_detected_at, exit_source,
                    exit_qty, exit_price, exit_loss_known, re_entry_conditions, tranche_of)
                   VALUES (%s,%s,%s,'stepped_out',now(),'operator_confirm',%s,%s,false,%s,%s)
                   ON CONFLICT (advisory_id) DO NOTHING""",
                (f"tranche-{ladder_id}-{tranche}", sym, acct, qty, price,
                 json.dumps(conds), ladder_id))
    return True


# ── RP2: the panel rows ────────────────────────────────────────────────────────

def rotation_plan(cur, stances: list, ladders: list, round_trips: list) -> list:
    """One row per position with ANY active rotation state — the page's memory."""
    by_key = {}
    st_map = {(s["symbol"], s["account"]): s for s in stances}
    for lad in ladders:
        k = (lad["symbol"], lad["account"])
        by_key.setdefault(k, {"symbol": lad["symbol"], "account": lad["account"]})["ladder"] = lad
    for t in round_trips:
        k = (t["symbol"], t["account"])
        by_key.setdefault(k, {"symbol": t["symbol"], "account": t["account"]})\
            .setdefault("round_trips", []).append(t)
    rows = []
    for k, v in by_key.items():
        s = st_map.get(k) or {}
        lad = v.get("ladder")
        ladder_state = None
        if lad:
            t1 = f"T1 {lad['t1_fraction']}% {'✓ executed' if lad['t1_status'] == 'executed' else 'advised'}"
            armed = [t for t in lad["tranches"] if t["status"] == "armed"]
            fired = [t for t in lad["tranches"] if t["status"] == "fired"]
            disarmed = [t for t in lad["tranches"] if t["status"] == "disarmed"]
            bits = [t1]
            for t in fired:
                bits.append(f"{t['tranche']} TRIGGERED — {t.get('fired_by', '')}")
            for t in armed:
                bits.append(f"{t['tranche']} armed ({len(t['triggers'])} triggers)")
            for t in disarmed:
                bits.append(f"{t['tranche']} DISARMED — {t.get('disarmed_reason', '')}")
            ladder_state = " · ".join(bits)
        rows.append({"symbol": v["symbol"], "account": v["account"],
                     "account_label": CFG["account_labels"].get(v["account"], v["account"]),
                     "value": s.get("value"), "stance": s.get("stance"),
                     "ladder": ladder_state, "ladder_detail": lad,
                     "round_trips": v.get("round_trips", [])})
    rows.sort(key=lambda r: -(r.get("value") or 0))
    return rows
