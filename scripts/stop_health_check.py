#!/usr/bin/env python3
"""Stop Health Check (Stage 2c) — the HEALTH-AGENT face of the stop lifecycle monitor.

Runs the stop_lifecycle_monitor scan, persists the snapshot, and escalates any alert-worthy stop condition
through the SAME surfaces the rest of the system uses:
  • SIEM      : save_alert_event(source_script='stop_health', ...) — visible in the security/alerts feed
                and consumable by Hermes (which reads alert_events per symbol).
  • Telegram  : central alert router (telegram_alert.send_telegram) — NEVER a direct bypass.
  • health log: system_health_events row so the system_health_agent watchdog sees this check ran.

Alert conditions (per the engine's health=alert): ORPHANED (a live stop with no matching holding —
on trigger it could short / reject), OVERSIZED (stop qty > shares held — a GTC stop does NOT auto-resize
when you trim), FILLED/TRIGGERED (the stop fired — the position may be flat now), and NEAR-TRIGGER within
0.75% (about to fire). Dedup: one alert per account/order/symbol/condition per 2h via SIEM history.

Run on cron during market hours (read-only on the broker side):
  python3 scripts/stop_health_check.py [--quiet]
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

_COMPONENT = "stop_health"


def _send_telegram(msg: str, *, reply_markup: dict | None = None, link_preview_options: dict | None = None) -> str | None:
    """Send via the central router. Returns the provider message id, or None.

    None covers every case where no message reached Telegram — suppressed by the
    router, digested, or a transport error. An absent id is information (there is
    nothing for the operator to acknowledge), not a failure, and it is returned
    as None rather than guessed. The previous bare `True` told the caller nothing
    it did not already know.
    """
    try:
        from telegram_alert import send_telegram_with_id
        # Decision cards (2026-10-08) add buttons + preview; plain text sends exactly as before.
        extra = {k: v for k, v in (("reply_markup", reply_markup), ("link_preview_options", link_preview_options))
                 if v is not None}
        return send_telegram_with_id(msg, **extra).get("message_id")
    except Exception:
        return None


def _siem(symbol: str, severity: str, text: str, payload: dict) -> int | None:
    """Write the SIEM row. Returns its alert_events id so a send can stamp it."""
    try:
        from alert_event_writer import save_alert_event
        return save_alert_event(alert_type="strategic_alert", severity=severity, source_script=_COMPONENT,
                                symbol=symbol or "", raw_text=text, parsed_payload=payload)
    except Exception:
        return None


def _attach_telegram_id(alert_event_ids, telegram_message_id: str | None) -> None:
    """Link SIEM rows to the message that actually carried them.

    The phone gets ONE batched card for N conditions (B2, 2026-09-16), so all N
    rows legitimately share a single provider id — that batched card is what the
    operator would acknowledge. A missing id links nothing rather than inventing
    an association.
    """
    if not telegram_message_id:
        return
    try:
        from alert_event_writer import attach_telegram_message_id
        for aid in alert_event_ids:
            if aid:
                attach_telegram_message_id(aid, telegram_message_id)
    except Exception:
        pass


_HOLDINGS_BASIS = None


def _pl_if_fired(symbol: str, account: str, stop_price, qty) -> dict | None:
    """Realized P/L if the stop fills at stop_price: qty × (stop − avg_cost).

    avg_cost per share = cost_basis / shares from holdings.json. Returns the
    dollar P/L, the R-multiple-ish percent vs cost, and whether the basis is
    partial (so the number is flagged, not silently wrong). None when basis is
    unavailable — an unknown P/L is stated as unknown, never guessed."""
    global _HOLDINGS_BASIS
    try:
        if _HOLDINGS_BASIS is None:
            import json
            from pathlib import Path
            p = Path(__file__).resolve().parent.parent / "data" / "portfolios" / "state" / "holdings.json"
            d = json.loads(p.read_text()) if p.exists() else {}
            _HOLDINGS_BASIS = {}
            for r in (d.get("holdings") or []):
                key = (str(r.get("symbol", "")).upper(), str(r.get("account", "")))
                _HOLDINGS_BASIS[key] = r
        h = _HOLDINGS_BASIS.get((str(symbol).upper(), str(account)))
        if not h:
            return None
        shares = float(h.get("shares") or h.get("quantity") or 0)
        cost_basis = h.get("cost_basis")
        if not shares or cost_basis in (None, ""):
            return None
        avg_cost = float(cost_basis) / shares
        sold = float(qty) if qty else shares
        pl = round(sold * (float(stop_price) - avg_cost), 2)
        pct = round((float(stop_price) - avg_cost) / avg_cost * 100, 1) if avg_cost else None
        return {"pl": pl, "pct": pct, "avg_cost": round(avg_cost, 2),
                "partial_basis": bool(h.get("basis_partial"))}
    except Exception:
        return None


def _pl_line(pl: dict | None) -> str:
    """Human tail for a stop alert: ' · if fired: −$413 (−44% vs cost $179)'."""
    if not pl or pl.get("pl") is None:
        return " · P/L if fired: basis unavailable"
    sign = "+" if pl["pl"] >= 0 else "−"
    tail = f" · if fired: {sign}${abs(pl['pl']):,.0f}"
    if pl.get("pct") is not None:
        tail += f" ({'+' if pl['pct'] >= 0 else '−'}{abs(pl['pct'])}% vs cost ${pl['avg_cost']:g})"
    if pl.get("partial_basis"):
        tail += " [partial basis]"
    return tail


def _recently_alerted(symbol: str, condition: str, hours: int = 2) -> bool:
    """Dedup a stable stop incident; retain the portfolio guard's existing route."""
    try:
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        if condition.startswith("siem:v1:"):
            cur.execute("""SELECT 1 FROM alert_events
                           WHERE source_script=%s AND parsed_payload->>'condition_key'=%s
                             AND COALESCE(lifecycle_state,'active') <> 'resolved'
                             AND created_at > NOW() - (%s * INTERVAL '1 hour') LIMIT 1""",
                        (_COMPONENT, condition, hours))
        else:
            cur.execute("""SELECT 1 FROM alert_events
                           WHERE source_script=%s AND symbol=%s AND raw_text LIKE %s
                             AND created_at > NOW() - INTERVAL '%s hours' LIMIT 1""",
                        (_COMPONENT, symbol, f"%{condition}%", hours))
        return cur.fetchone() is not None
    except Exception:
        return False   # fail open ⇒ we alert (better a dup than a miss on a safety signal)


def _stop_condition_key(payload: dict) -> str | None:
    """Only complete structured stop identities may acquire a recovery key."""
    from lib.siem_incident_identity import incident_key
    for field in ("account", "order_id", "symbol", "condition"):
        value = payload.get(field)
        if not ((isinstance(value, str) and value.strip()) or type(value) is int):
            return None
    return incident_key({"source_script": _COMPONENT, "alert_type": "strategic_alert",
                         "parsed_payload": payload})


def _recovery_time(value):
    from datetime import datetime
    try:
        value = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return value if value.tzinfo is not None and value.utcoffset() is not None else None
    except (TypeError, ValueError):
        return None


def _recovery_number(value):
    import math
    try:
        number = float(value) if value is not None and not isinstance(value, bool) else None
        return number if number is not None and math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _recovery_payload(value):
    import json
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return value if isinstance(value, dict) else {}


def _stop_observation_key(stop: dict) -> str:
    """Opaque fingerprint linking this scan's exact facts to its persisted row."""
    import hashlib
    import json
    flags = stop.get("flags")
    if isinstance(flags, str):
        flags = json.loads(flags)
    facts = {field: stop.get(field) for field in
             ("account", "order_id", "symbol", "status", "lifecycle", "health", "coverage")}
    facts.update(qty=_recovery_number(stop.get("qty")), held_qty=_recovery_number(stop.get("held_qty")),
                 flags=sorted(flags) if isinstance(flags, list) else None)
    return hashlib.sha256(json.dumps(facts, sort_keys=True, default=str).encode()).hexdigest()


def _read_stop_recovery_rows(alert_ids: list[int]) -> list[dict]:
    """Read exact saved identities and promoted position evidence; never scan brokers."""
    from db_adapter import _get_conn
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT a.id AS alert_id, a.created_at, a.lifecycle_state,
                       a.symbol, a.parsed_payload,
                       sl.account AS stop_account, sl.symbol AS stop_symbol,
                       sl.order_id AS stop_order_id, sl.status AS stop_status,
                       sl.lifecycle AS stop_lifecycle, sl.health AS stop_health,
                       sl.flags AS stop_flags, sl.coverage AS stop_coverage,
                       sl.qty AS stop_qty, sl.held_qty AS stop_held_qty,
                       sl.snapshot_at AS stop_snapshot_at,
                       pc.qty AS position_qty, pc.as_of AS position_as_of,
                       pc.source AS position_source, pc.sync_run_id,
                       psr.status AS sync_status, psr.promoted AS sync_promoted,
                       psr.finished_at AS sync_finished_at,
                       (a.parsed_payload->>'account') = ANY(psr.accounts_ok) AS account_sync_ok
                FROM alert_events a
                LEFT JOIN stop_lifecycle sl
                  ON sl.account = a.parsed_payload->>'account'
                 AND sl.order_id = a.parsed_payload->>'order_id'
                 AND sl.symbol = a.parsed_payload->>'symbol'
                LEFT JOIN positions_current pc
                  ON pc.account_key = a.parsed_payload->>'account'
                 AND pc.symbol = a.parsed_payload->>'symbol'
                LEFT JOIN positions_sync_runs psr ON psr.run_id = pc.sync_run_id
                WHERE a.id = ANY(%s) AND a.source_script=%s
                ORDER BY a.id""", (alert_ids, _COMPONENT))
            columns = [description[0] for description in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]
    finally:
        # End this read transaction without closing db_adapter's shared connection.
        conn.rollback()


def _recovery_reason(row: dict, *, now, sync_cfg: dict, filled_alert_hours: float,
                     minimum_snapshot_at=None) -> tuple[str | None, str]:
    """Positive recovery proof for one exact order; absence is never recovery."""
    import json
    import math
    from positions_sync import freshness
    payload = _recovery_payload(row.get("parsed_payload"))
    if not _stop_condition_key(payload):
        return None, "incomplete_identity"
    if row.get("lifecycle_state") != "active":
        return None, "not_active"
    for field in ("account", "symbol", "order_id"):
        if str(row.get("stop_" + field) or "") != str(payload[field]):
            return None, "missing_exact_stop_observation"
    if row.get("symbol") != payload["symbol"]:
        return None, "conflicting_alert_symbol"
    created = _recovery_time(row.get("created_at"))
    observed = _recovery_time(row.get("stop_snapshot_at"))
    if not created or not observed or not created < observed <= now:
        return None, "observation_not_newer"
    if minimum_snapshot_at is not None and observed < minimum_snapshot_at:
        return None, "scan_not_persisted"
    if freshness(observed, sync_cfg, now)["stale"]:
        return None, "stale_stop_observation"
    flags = row.get("stop_flags")
    if isinstance(flags, str):
        try:
            flags = json.loads(flags)
        except (TypeError, ValueError):
            flags = None
    if not isinstance(flags, list) or not all(isinstance(flag, str) for flag in flags):
        return None, "missing_condition_observation"
    if row.get("stop_health") != "ok":
        return None, "stop_still_unhealthy"
    condition = payload["condition"]
    if condition not in {"ORPHANED", "OVERSIZED", "TRIGGERED", "NEAR_TRIGGER"}:
        return None, "unsupported_condition"
    status, lifecycle, coverage = (row.get("stop_" + field) for field in ("status", "lifecycle", "coverage"))
    if status in {"canceled", "cancelled", "rejected", "expired", "replaced"}:
        if lifecycle == "cancelled" and coverage == "closed" and not flags:
            return "terminal_stop_observed", ""
        return None, "conflicting_terminal_observation"
    if status == "filled":
        # The monitor already applies its existing fill-age policy. The older
        # alert itself must also predate that window when closeTime is not saved.
        if (lifecycle == "filled" and coverage == "closed" and flags == ["filled_stale"]
                and (observed - created).total_seconds() > filled_alert_hours * 3600):
            return "filled_alert_window_elapsed", ""
        return None, "fill_not_proven_stale"
    if condition not in {"ORPHANED", "OVERSIZED"}:
        return None, "fresh_price_or_terminal_evidence_required"
    if status not in {"working", "open", "new", "accepted"} or lifecycle != "working" or coverage != "full" or flags:
        return None, "incomplete_working_observation"
    qty = _recovery_number(row.get("stop_qty"))
    held = _recovery_number(row.get("stop_held_qty"))
    position = _recovery_number(row.get("position_qty"))
    if any(value is None or value <= 0 for value in (qty, held, position)):
        return None, "missing_positive_position"
    if row.get("sync_status") != "complete" or row.get("sync_promoted") is not True or row.get("account_sync_ok") is not True:
        return None, "position_sync_incomplete"
    position_at = _recovery_time(row.get("position_as_of"))
    finished = _recovery_time(row.get("sync_finished_at"))
    if (not position_at or not finished or not row.get("sync_run_id") or not row.get("position_source")
            or not created < position_at <= finished <= observed):
        return None, "position_observation_not_coherent"
    if freshness(position_at, sync_cfg, now)["stale"] or freshness(finished, sync_cfg, now)["stale"]:
        return None, "stale_position_observation"
    tolerance = _recovery_number(sync_cfg.get("qty_tolerance"))
    if tolerance is None or tolerance < 0 or abs(held - position) > tolerance or qty > math.ceil(position):
        return None, "position_quantity_conflict"
    return "fresh_exact_position_confirms_coverage", ""


def plan_stop_recovery(alert_ids: list[int], *, max_ids: int, minimum_snapshot_at=None) -> dict:
    """Read-only, capped recovery plan for explicit IDs, including legacy rows.

    It only reads existing stores. Calling this function can never reach an
    alert writer, monitor scan, broker reader, notification or model.
    """
    from datetime import datetime, timezone
    from positions_sync import load_sync_config
    from stop_lifecycle_monitor import _FILLED_ALERT_HOURS
    if type(max_ids) is not int or not 0 < max_ids <= 200:
        raise ValueError("max_ids must be between 1 and the writer's 200-ID cap")
    if (not isinstance(alert_ids, list) or len(alert_ids) > max_ids
            or any(type(value) is not int or value <= 0 for value in alert_ids)
            or len(set(alert_ids)) != len(alert_ids)):
        raise ValueError("recovery requires distinct positive explicit alert IDs within the cap")
    minimum = _recovery_time(minimum_snapshot_at) if minimum_snapshot_at is not None else None
    if minimum_snapshot_at is not None and minimum is None:
        raise ValueError("minimum_snapshot_at must be timezone-aware")
    now = datetime.now(timezone.utc)
    result = {"ok": True, "dry_run": True, "requested_ids": list(alert_ids), "max_ids": max_ids,
              "minimum_snapshot_at": minimum.isoformat() if minimum else None,
              "candidates": [], "blocked": [], "planned_at": now.isoformat()}
    rows = _read_stop_recovery_rows(alert_ids) if alert_ids else []
    grouped = {}
    for row in rows:
        grouped.setdefault(row["alert_id"], []).append(row)
    cfg = load_sync_config()
    for alert_id in alert_ids:
        matches = grouped.get(alert_id, [])
        if len(matches) != 1:
            result["blocked"].append({"alert_id": alert_id, "reason": "missing_or_conflicting_observations"})
            continue
        row = matches[0]
        reason, blocked = _recovery_reason(row, now=now, sync_cfg=cfg, filled_alert_hours=_FILLED_ALERT_HOURS,
                                            minimum_snapshot_at=minimum)
        if not reason:
            result["blocked"].append({"alert_id": alert_id, "reason": blocked})
            continue
        payload = _recovery_payload(row["parsed_payload"])
        result["candidates"].append({"alert_id": alert_id, "condition_key": _stop_condition_key(payload),
                                     "condition": payload["condition"], "reason": reason,
                                     "observation_key": _stop_observation_key({
                                         field: row.get("stop_" + field) for field in
                                         ("account", "order_id", "symbol", "status", "lifecycle", "health",
                                          "coverage", "flags", "qty", "held_qty")}),
                                     "observed_at": _recovery_time(row["stop_snapshot_at"]).isoformat()})
    return result


def apply_stop_recovery(plan: dict, *, max_ids: int, resolved_by: str) -> dict:
    """Revalidate a reviewed plan, then resolve only its still-proven exact IDs.

    This is the separately authorized apply boundary. A dry run never calls it.
    Neither a supplied plan nor elapsed time substitutes for fresh revalidation.
    """
    if not isinstance(plan, dict) or plan.get("ok") is not True or plan.get("dry_run") is not True:
        raise ValueError("a successful dry-run recovery plan is required")
    if not isinstance(resolved_by, str) or not resolved_by.strip():
        raise ValueError("recovery attribution is required")
    reviewed = {candidate["alert_id"]: candidate for candidate in plan["candidates"]}
    if len(reviewed) != len(plan["candidates"]) or not set(reviewed).issubset(plan["requested_ids"]):
        raise ValueError("invalid candidate IDs")
    refreshed = plan_stop_recovery(list(reviewed), max_ids=max_ids,
                                  minimum_snapshot_at=plan.get("minimum_snapshot_at"))
    result = {"ok": True, "dry_run": False, "resolved_ids": [], "blocked": list(refreshed["blocked"])}
    from alert_event_writer import resolve_alert_event_ids
    for candidate in refreshed["candidates"]:
        prior = reviewed[candidate["alert_id"]]
        prior_observation = _recovery_time(prior.get("observed_at"))
        if (candidate["condition_key"] != prior.get("condition_key") or prior_observation is None
                or candidate["observation_key"] != prior.get("observation_key")
                or _recovery_time(candidate["observed_at"]) < prior_observation):
            result["blocked"].append({"alert_id": candidate["alert_id"], "reason": "reviewed_evidence_changed"})
            continue
        try:
            changed = resolve_alert_event_ids([candidate["alert_id"]], source_script=_COMPONENT,
                         resolved_by=resolved_by, observed_before_or_at=_recovery_time(candidate["observed_at"]))
            result["resolved_ids"].extend(changed)
        except Exception as exc:
            result.update(ok=False, error=f"recovery_write_failed:{type(exc).__name__}")
            break
    return result


def _recover_current_scan(scan: dict, started_at) -> dict:
    """Automatically recover keyed incidents only after this scan persisted evidence."""
    stops = scan.get("stops")
    generated = _recovery_time(scan.get("generated_at"))
    if (not isinstance(stops, list) or not stops or generated is None or generated < started_at
            or scan.get("ok") is False or scan.get("errors")
            or (scan.get("summary") or {}).get("total") != len(stops)):
        return {"ok": False, "resolved_ids": [], "reason": "incomplete_scan"}
    try:
        observations = {}
        for stop in stops:
            identity = _stop_condition_key({**stop, "condition": "OBSERVATION_IDENTITY"})
            if identity:
                observations.setdefault(identity, []).append(stop)
        fingerprints = {_stop_observation_key(matches[0]) for matches in observations.values()
                        if len(matches) == 1 and matches[0].get("health") == "ok"}
        if not fingerprints:
            return {"ok": True, "resolved_ids": [], "reason": "no_complete_healthy_stop_observation"}
        from db_adapter import _get_conn
        conn = _get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""SELECT id FROM alert_events WHERE source_script=%s AND lifecycle_state='active'
                               AND parsed_payload->>'condition_key' IS NOT NULL ORDER BY id LIMIT 201""", (_COMPONENT,))
                ids = [row[0] for row in cur.fetchall()]
        finally:
            conn.rollback()
        if not ids:
            return {"ok": True, "resolved_ids": []}
        plan = plan_stop_recovery(ids, max_ids=200, minimum_snapshot_at=started_at)
        matching = []
        for candidate in plan["candidates"]:
            if candidate["observation_key"] in fingerprints:
                matching.append(candidate)
            else:
                plan["blocked"].append({"alert_id": candidate["alert_id"], "reason": "scan_observation_conflict"})
        plan["candidates"] = matching
        result = apply_stop_recovery(plan, max_ids=200, resolved_by="auto:stop_health_verified_observation")
        result["blocked"] = plan["blocked"] + result["blocked"]
        return result
    except Exception as exc:
        return {"ok": False, "resolved_ids": [], "reason": f"recovery_unverified:{type(exc).__name__}"}


def _hermes_finding(symbol: str, condition: str, line: str, payload: dict) -> None:
    """Write the stop-health condition into Hermes' research stream so Hermes 'monitors' it — it surfaces
    on the Open Trades card's Hermes section and in the Hermes hub, same as any research finding."""
    conn = None
    try:
        import json
        from db_adapter import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        # research_type='stop_health' is the identity; thesis_type/status must satisfy the table's CHECKs
        # (thesis_type ∈ bullish/bearish/neutral/mixed → 'neutral'; status ∈ staged/.. → 'staged').
        # One write module per store (SoT Phase 9): SQL lives in lib.writers.hermes_research_writer.
        from lib.writers.hermes_research_writer import write_research_rows
        write_research_rows(cur, [{
            "source": "hermes", "hermes_agent_name": "StopHealthMonitor", "research_type": "stop_health",
            "symbol": symbol, "topic": f"Stop health: {condition}", "summary": f"{condition} — {line}",
            "thesis": line, "thesis_type": "neutral", "evidence_json": json.dumps(payload),
            "confidence_score": 0.95, "model_used": "stop_lifecycle_monitor", "status": "staged",
            "category_lifecycle": "stop",
        }], producer="StopHealthMonitor")
        conn.commit()
    except Exception:
        if conn is not None:
            try:
                conn.rollback()   # never leave the shared connection in an aborted txn
            except Exception:
                pass


def _log_health_event(ok: bool, summary: dict) -> None:
    try:
        from db_adapter import _get_conn
        conn = _get_conn(); cur = conn.cursor()
        cur.execute("""CREATE TABLE IF NOT EXISTS system_health_events (
                         id SERIAL PRIMARY KEY, component TEXT, event_type TEXT, severity TEXT,
                         message TEXT, action_taken TEXT, success BOOLEAN, created_at TIMESTAMPTZ DEFAULT NOW())""")
        cur.execute("""INSERT INTO system_health_events (component, event_type, severity, message, success)
                       VALUES (%s,'STOP_HEALTH_SCAN',%s,%s,%s)""",
                    (_COMPONENT, "WARN" if not ok else "INFO",
                     f"{summary.get('total')} stops · health {summary.get('by_health')}", ok))
        conn.commit()
    except Exception:
        pass


def _portfolio_drawdown_guard() -> dict | None:
    """Portfolio-level drawdown guard (stop_policy.yaml portfolio_drawdown_guard).

    Advisory only — compares the newest daily_system_metrics portfolio_value to its
    peak over peak_window_days and alerts at alert_pct / critical_pct below peak.
    Never places or modifies an order. Fail-soft: any error returns None."""
    try:
        import holding_family as hf
        cfg = (hf._policy().get("portfolio_drawdown_guard") or {})
        if not cfg.get("enabled"):
            return None
        window = int(cfg.get("peak_window_days") or 90)
        alert_pct = float(cfg.get("alert_pct") or 10.0)
        critical_pct = float(cfg.get("critical_pct") or 12.0)
        dedup_h = int(cfg.get("dedup_hours") or 6)
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""SELECT metric_date, portfolio_value FROM daily_system_metrics
                       WHERE metric_date >= CURRENT_DATE - %s::int
                         AND portfolio_value IS NOT NULL AND portfolio_value > 0
                       ORDER BY metric_date""", (window,))
        rows = cur.fetchall()
        conn.rollback()
        if len(rows) < 2:
            return None
        peak_date, peak = max(rows, key=lambda r: float(r[1]))
        cur_date, cur_val = rows[-1]
        dd_pct = (float(peak) - float(cur_val)) / float(peak) * 100.0
        out = {"peak_usd": float(peak), "peak_date": str(peak_date),
               "current_usd": float(cur_val), "as_of": str(cur_date),
               "drawdown_pct": round(dd_pct, 2), "window_days": window,
               "alert_pct": alert_pct, "critical_pct": critical_pct}
        if dd_pct < alert_pct:
            return {**out, "level": "ok"}
        level = "critical" if dd_pct >= critical_pct else "warning"
        cond = "PORTFOLIO_DRAWDOWN_CRITICAL" if level == "critical" else "PORTFOLIO_DRAWDOWN"
        line = (f"portfolio ${float(cur_val):,.0f} is {dd_pct:.1f}% below its {window}d peak "
                f"${float(peak):,.0f} ({peak_date}) — review stops/exposure (advisory; no orders placed)")
        if not _recently_alerted("PORTFOLIO", cond, hours=dedup_h):
            payload = {"kind": "stop_health", "condition": cond, **out}
            alert_event_id = _siem("PORTFOLIO", "critical" if level == "critical" else "warning",
                                   f"[stop-health] {cond} · {line}", payload)
            # DB first, Telegram second — so the id exists only now.
            mid = _send_telegram(f"{'🚨' if level == 'critical' else '⚠️'} PORTFOLIO DRAWDOWN — {line}")
            _attach_telegram_id([alert_event_id], mid)
            _hermes_finding("PORTFOLIO", cond, line, payload)
        return {**out, "level": level, "condition": cond}
    except Exception as e:
        print(f"stop_health: drawdown guard skipped ({e})", file=sys.stderr)
        return None


def run(quiet: bool = False) -> dict:
    from datetime import datetime, timezone
    import stop_lifecycle_monitor as slm
    scan_started_at = datetime.now(timezone.utc)
    res = slm.scan(persist=True)
    summary, alerts = res["summary"], res["alerts"]
    fired = []
    batch: list[tuple[str, str, str, str, str]] = []  # (sev, cond, sym, acct, line)
    # Parallel to `batch`: the alert_events id each entry wrote, so the batched
    # card's provider id can be stamped onto every row it carried.
    batch_alert_event_ids: list = []
    for r in alerts:
        sym, acct = r["symbol"], r["account"]
        # the single most severe condition for the message
        # severity MUST be one of the alert_events constraint values: info|warning|urgent|critical
        # P/L that WOULD be realized if this stop fills — the number the operator
        # actually decides on (a near-trigger on a deep loser reads very
        # differently from one locking a gain).
        _pl = _pl_if_fired(sym, acct, r.get("stop_price"), r.get("qty") or r.get("held_qty"))
        if "orphaned" in r["flags"]:
            cond, sev, line = "ORPHANED", "urgent", f"stop with no matching {acct} holding (#{r['order_id']}) — on trigger it could short/reject. Cancel it."
        elif "oversized" in r["flags"]:
            cond, sev, line = "OVERSIZED", "urgent", f"stop covers {r['qty']} sh but you hold {r['held_qty']} — modify to {r['held_qty']} sh.{_pl_line(_pl)}"
        elif "filled" in r["flags"]:
            cond, sev, line = "TRIGGERED", "urgent", f"stop FILLED (#{r['order_id']}) — position may be flat; review.{_pl_line(_pl)}"
        else:
            cond, sev, line = "NEAR_TRIGGER", "warning", f"price within {r.get('proximity_pct')}% of stop ${r.get('stop_price')} — about to fire.{_pl_line(_pl)}"
        payload = {"kind": "stop_health", "condition": cond,
                   "pl_if_fired": (_pl or {}).get("pl"), "pl_if_fired_pct": (_pl or {}).get("pct"),
                   **{k: r.get(k) for k in
                   ("account", "symbol", "broker", "order_id", "order_type", "stop_price", "qty",
                    "held_qty", "current_price", "proximity_pct", "coverage", "lifecycle", "health")}}
        # Account/order identity prevents one account's alert suppressing another.
        condition_key = _stop_condition_key(payload)
        if condition_key:
            payload["condition_key"] = condition_key
        # Missing identity is never sufficient evidence to suppress a safety alert.
        if not condition_key or not _recently_alerted(sym, condition_key):
            batch_alert_event_ids.append(
                _siem(sym, sev, f"[stop-health] {cond} · {sym}@{acct} · {line}", payload))
            _hermes_finding(sym, cond, line, payload)   # enter Hermes' research stream (deduped via the same 2h window)
            batch.append((sev, cond, sym, acct, line))
            fired.append(f"{sym}:{cond}")
    # B2 (2026-09-16): collapse per-symbol repeats into ONE message. SIEM + Hermes stay per-symbol
    # (durable evidence, one row each); the phone gets a single batched card instead of one per symbol.
    if batch:
        card = None
        try:
            from lib import telegram_cards as _tc  # decision card (operator 2026-10-08); rollback: config/telegram_cards.yaml
            if _tc.enabled("stop_health"):
                card = _tc.stop_health_card([{"symbol": sym, "account": acct, "condition": cond, "severity": sev,
                                              "line": line} for sev, cond, sym, acct, line in batch])
        except Exception:  # noqa: BLE001 — never lose a stop alert over a layout problem
            card = None
        if card:
            mid = _send_telegram(card["text"], reply_markup=card.get("reply_markup"),
                                 link_preview_options=card.get("link_preview_options"))
        elif len(batch) == 1:
            sev, cond, sym, acct, line = batch[0]
            mid = _send_telegram(f"{'🚨' if sev == 'urgent' else '⚠️'} STOP HEALTH — {cond}: *{sym}* ({acct})\n{line}")
        else:
            n_urgent = sum(1 for b in batch if b[0] == "urgent")
            head = f"{'🚨' if n_urgent else '⚠️'} STOP HEALTH — {len(batch)} alert(s)"
            if n_urgent and n_urgent < len(batch):
                head += f" ({n_urgent} urgent)"
            lines = [f"{'🚨' if sev == 'urgent' else '⚠️'} {cond}: *{sym}* ({acct})\n{line}"
                     for sev, cond, sym, acct, line in batch]
            mid = _send_telegram(head + "\n\n" + "\n\n".join(lines))
        # One card carried every row in this run — link them all to it.
        _attach_telegram_id(batch_alert_event_ids, mid)
    dd = _portfolio_drawdown_guard()
    if dd and dd.get("level") in ("warning", "critical"):
        fired.append(f"PORTFOLIO:{dd['condition']}")
    summary["portfolio_drawdown"] = dd
    summary["incident_recovery"] = _recover_current_scan(res, scan_started_at)
    if not summary["incident_recovery"].get("ok"):
        print("stop_health: incident recovery unverified; alerts remain open", file=sys.stderr)
    _log_health_event(ok=(not alerts), summary=summary)
    if not quiet:
        print(f"stop_health: {summary['total']} stops · health {summary['by_health']} · "
              f"alerts {len(alerts)} · telegram fired {fired or 'none'} · "
              f"drawdown {dd.get('drawdown_pct') if dd else 'n/a'}%")
    return {"summary": summary, "alert_count": len(alerts), "telegram_fired": fired,
            "portfolio_drawdown": dd}


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(str(PROJECT_ROOT / ".env"))
    run(quiet="--quiet" in sys.argv)
