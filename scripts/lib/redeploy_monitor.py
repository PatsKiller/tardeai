"""redeploy_monitor — Phase E: fill recording, restoration metrics, Hermes outcomes (advisory only)."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.redeploy_data_truth import POLICY_VERSION, _as_float, _load_json

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
STATE = PROJECT_ROOT / "data" / "portfolios" / "state"
MIGRATION_E = PROJECT_ROOT / "migrations" / "2026_07_17_redeploy_phase_e_monitoring.sql"
MIGRATION_INTEGRITY = PROJECT_ROOT / "migrations" / "2026_07_19_redeploy_data_integrity.sql"

GENERATOR_VERSION = "phase_e_1.1.0"

# P0 data-integrity guards (2026-07-13 fixture-pollution audit):
# fills are production evidence unless explicitly environment='test', and test
# fills are only accepted when REDEPLOY_ALLOW_TEST_FILLS=1 (never on the prod box).
_FIXTURE_MARKER = re.compile(r"\b(fixture|synthetic|dummy|fake|test)\b", re.IGNORECASE)


def _fixture_marker_in(body: dict[str, Any]) -> str | None:
    """Return the offending field name if any fixture marker appears in operator-supplied text."""
    for field in ("evidence_note", "recorded_by"):
        val = str(body.get(field) or "")
        if val and _FIXTURE_MARKER.search(val):
            return field
    idem = str(body.get("idempotency_key") or "")
    if idem and (idem.startswith("test-") or _FIXTURE_MARKER.search(idem)):
        return "idempotency_key"
    return None

# ETF → GICS sector (inverse of plan engine restore map)
_ETF_SECTOR = {
    "QQQ": "Technology",
    "XLC": "Communication Services",
    "XLF": "Financial Services",
    "XLY": "Consumer Cyclical",
    "XLV": "Healthcare",
    "XLI": "Industrials",
    "XLP": "Consumer Defensive",
    "XLE": "Energy",
    "XLB": "Basic Materials",
    "XLU": "Utilities",
    "XLRE": "Real Estate",
    "BND": "Fixed Income",
    "SCHD": "Dividend Equity",
    "JEPQ": "Technology",
    "JEPI": "Technology",
}

_THEME_SECTOR = {
    "ITA": "Defense / Aerospace",
    "XAR": "Defense / Aerospace",
    "PPA": "Defense / Aerospace",
}


def ensure_monitor_tables(cur) -> None:
    if MIGRATION_E.is_file():
        cur.execute(MIGRATION_E.read_text())
    if MIGRATION_INTEGRITY.is_file():
        cur.execute(MIGRATION_INTEGRITY.read_text())


def _idempotency_key(payload: dict[str, Any]) -> str:
    basis = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(basis.encode()).hexdigest()[:32]


def _sector_for_ticker(ticker: str) -> str | None:
    sym = ticker.upper()
    if sym in _ETF_SECTOR:
        return _ETF_SECTOR[sym]
    return _THEME_SECTOR.get(sym)


def list_fills(cur, event_id: int, *, plan_archetype: str | None = None) -> list[dict[str, Any]]:
    """Production fills only — test/quarantined rows never reach metrics, UI, or learning."""
    ensure_monitor_tables(cur)
    if plan_archetype:
        cur.execute(
            """SELECT id, deploy_event_id, deploy_plan_id, plan_version, plan_archetype,
                      leg_index, ticker, stage, filled_shares, filled_price, filled_dollars,
                      filled_at, account, evidence_source, evidence_note, recorded_by,
                      idempotency_key, environment, broker_confirmation_id
               FROM redeploy_stage_fills
               WHERE deploy_event_id=%s AND plan_archetype=%s AND environment='production'
               ORDER BY filled_at DESC, id DESC""",
            (event_id, plan_archetype.upper()[:1]),
        )
    else:
        cur.execute(
            """SELECT id, deploy_event_id, deploy_plan_id, plan_version, plan_archetype,
                      leg_index, ticker, stage, filled_shares, filled_price, filled_dollars,
                      filled_at, account, evidence_source, evidence_note, recorded_by,
                      idempotency_key, environment, broker_confirmation_id
               FROM redeploy_stage_fills
               WHERE deploy_event_id=%s AND environment='production'
               ORDER BY filled_at DESC, id DESC""",
            (event_id,),
        )
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def compute_restoration_metrics(
    event: dict[str, Any],
    fills: list[dict[str, Any]],
    *,
    plan_archetype: str | None = None,
) -> dict[str, Any]:
    """Sector restoration % vs exposure removed (Phase A)."""
    meta = event.get("metadata") or {}
    exposure = (meta.get("phase_a") or {}).get("exposure_loss") or {}
    sectors_removed = {
        str(s.get("sector")): _as_float(s.get("usd_removed"))
        for s in exposure.get("sectors") or []
        if s.get("sector")
    }
    if not sectors_removed:
        return {"sectors": [], "total_restored_usd": 0.0, "total_removed_usd": 0.0, "restoration_pct": 0.0}

    relevant = fills
    if plan_archetype:
        relevant = [f for f in fills if str(f.get("plan_archetype") or "").upper() == plan_archetype.upper()[:1]]

    restored_by_sector: dict[str, float] = {}
    total_restored = 0.0
    for f in relevant:
        sec = _sector_for_ticker(str(f.get("ticker") or ""))
        if not sec:
            continue
        # Map defense theme to closest exposure sector if no exact match
        usd = _as_float(f.get("filled_dollars"))
        restored_by_sector[sec] = restored_by_sector.get(sec, 0.0) + usd
        total_restored += usd

    total_removed = sum(sectors_removed.values())
    rows = []
    for sector, removed in sorted(sectors_removed.items(), key=lambda x: -x[1]):
        restored = restored_by_sector.get(sector, 0.0)
        # Defense ETFs may restore via theme — attribute to Industrials proxy if no Defense row
        if restored <= 0 and sector == "Industrials":
            restored = restored_by_sector.get("Defense / Aerospace", 0.0)
        pct = round(restored / removed * 100.0, 1) if removed > 0 else 0.0
        rows.append({
            "sector": sector,
            "usd_removed": round(removed, 2),
            "usd_restored": round(restored, 2),
            "restoration_pct": pct,
        })

    restoration_pct = round(total_restored / total_removed * 100.0, 1) if total_removed > 0 else 0.0
    return {
        "plan_archetype": plan_archetype,
        "sectors": rows[:12],
        "total_restored_usd": round(total_restored, 2),
        "total_removed_usd": round(total_removed, 2),
        "restoration_pct": restoration_pct,
        "income_status": exposure.get("income_status"),
    }


def build_fill_summary(fills: list[dict[str, Any]]) -> dict[str, Any]:
    by_ticker: dict[str, dict[str, Any]] = {}
    for f in fills:
        sym = str(f.get("ticker") or "").upper()
        row = by_ticker.setdefault(sym, {"ticker": sym, "stages_filled": [], "total_shares": 0, "total_dollars": 0.0})
        row["stages_filled"].append(int(f.get("stage") or 0))
        row["total_shares"] += int(f.get("filled_shares") or 0)
        row["total_dollars"] = round(row["total_dollars"] + _as_float(f.get("filled_dollars")), 2)
    return {
        "fill_count": len(fills),
        "tickers": list(by_ticker.values()),
        "total_dollars_deployed": round(sum(t["total_dollars"] for t in by_ticker.values()), 2),
    }


def _reeval_flags(event: dict[str, Any], fills: list[dict[str, Any]]) -> list[dict[str, str]]:
    flags: list[dict[str, str]] = []
    meta = event.get("metadata") or {}
    recon = (meta.get("phase_a") or {}).get("reconciliation") or {}
    status = recon.get("reconciliation_status") or event.get("reconciliation_status")
    if status == "holdings_stale":
        flags.append({
            "code": "REEVAL-000",
            "message": "Holdings snapshot predates sale — run Schwab sync; deployable uses net proceeds until verified",
        })
    elif status == "unsettled":
        flags.append({"code": "REEVAL-001", "message": "Cash in holdings below 50% of net — confirm settlement or sync broker"})
    if status == "partial":
        flags.append({"code": "REEVAL-002", "message": "Partial settlement — consider staged plan F tranche 2"})
    export_ready = (meta.get("phase_c") or {}).get("export_readiness") or {}
    if export_ready.get("export_allowed") is False:
        flags.append({"code": "REEVAL-003", "message": "Quotes stale — refresh technical_snapshot before next export"})
    if fills:
        flags.append({"code": "REEVAL-004", "message": f"{len(fills)} manual fill(s) recorded — restoration metrics updated"})
    net = _as_float(recon.get("net_proceeds_usd") or event.get("proceeds_usd"))
    deployable = _as_float(recon.get("deployable_cash_usd"))
    if net > 0 and deployable >= net * 0.95:
        flags.append({"code": "REEVAL-005", "message": "Settlement verified — plan may proceed to operator implementation review"})
    return flags


def emit_hermes_outcome(cur, fill: dict[str, Any], *, event: dict[str, Any]) -> int | None:
    """Record fill evidence on Hermes outcome ledger (manual evidence only)."""
    fill_id = int(fill["id"])
    sym = str(fill.get("ticker") or "").upper()
    stage = int(fill.get("stage") or 0)
    arch = fill.get("plan_archetype") or "?"
    sold = str(event.get("symbol") or "").upper()
    claim = (
        f"redeploy_fill:{sold}→{sym} stage{stage} plan{arch} "
        f"${_as_float(fill.get('filled_dollars')):.0f} manual"
    )
    try:
        cur.execute(
            """INSERT INTO hermes_outcome_ledger
               (subject_type, subject_id, symbol, emitted_at, claim, direction)
               VALUES ('redeploy_fill', %s, %s, %s, %s, 'long')
               ON CONFLICT (subject_type, subject_id) DO NOTHING
               RETURNING id""",
            (fill_id, sym, fill.get("filled_at") or datetime.now(timezone.utc), claim),
        )
        row = cur.fetchone()
        return int(row[0]) if row else None
    except Exception:
        return None


def append_outcome_bus(fill: dict[str, Any], event: dict[str, Any], *, apply: bool = True) -> None:
    """Lightweight bus append for governor feedback (best-effort)."""
    try:
        from lib.hermes_outcome_bus.bus import load_outcome_bus, write_outcome_bus
        bus = load_outcome_bus()
        sym = str(fill.get("ticker") or "").upper()
        by_sym = bus.setdefault("by_symbol", {})
        entry = by_sym.setdefault(sym, {"fills": [], "redeploy_events": []})
        entry.setdefault("redeploy_events", []).append({
            "event_id": event.get("id"),
            "sold_symbol": event.get("symbol"),
            "stage": fill.get("stage"),
            "filled_dollars": fill.get("filled_dollars"),
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        })
        bus.setdefault("feedback_to_governor", []).append({
            "source": "redeploy_monitor",
            "symbol": sym,
            "note": f"Manual redeploy fill stage {fill.get('stage')} for {event.get('symbol')} sale",
            "at": datetime.now(timezone.utc).isoformat(),
        })
        write_outcome_bus(bus, apply=apply)
    except Exception:
        pass


def record_stage_fill(cur, event_id: int, body: dict[str, Any]) -> dict[str, Any]:
    """POST record-fill — manual operator evidence only; idempotent."""
    ensure_monitor_tables(cur)
    required = ("ticker", "stage", "filled_shares", "filled_price", "account")
    missing = [k for k in required if not body.get(k)]
    if missing:
        return {"ok": False, "error": f"missing_fields:{','.join(missing)}"}

    stage = int(body["stage"])
    if stage not in (1, 2, 3):
        return {"ok": False, "error": "stage must be 1, 2, or 3"}

    shares = int(body["filled_shares"])
    price = _as_float(body["filled_price"])
    dollars = round(shares * price, 2)
    if shares <= 0 or price <= 0:
        return {"ok": False, "error": "invalid_shares_or_price"}

    environment = str(body.get("environment") or "production").strip().lower()
    if environment not in ("production", "test"):
        return {"ok": False, "error": "environment must be 'production' or 'test'"}
    if environment == "test" and os.environ.get("REDEPLOY_ALLOW_TEST_FILLS") != "1":
        return {
            "ok": False,
            "error": "test_fills_forbidden: environment='test' requires REDEPLOY_ALLOW_TEST_FILLS=1 "
                     "and must never run against the production database",
        }
    if environment == "production":
        offending = _fixture_marker_in(body)
        if offending:
            return {
                "ok": False,
                "error": f"fixture_marker_rejected: {offending} contains a test/fixture marker; "
                         "production fills must carry real operator evidence",
            }

    idem = str(body.get("idempotency_key") or "").strip()
    if not idem:
        idem = _idempotency_key({
            "event_id": event_id,
            "ticker": str(body["ticker"]).upper(),
            "stage": stage,
            "shares": shares,
            "price": price,
            "filled_at": str(body.get("filled_at") or "")[:19],
        })

    cur.execute(
        "SELECT id FROM redeploy_stage_fills WHERE idempotency_key=%s",
        (idem,),
    )
    existing = cur.fetchone()
    if existing:
        return {"ok": True, "duplicate": True, "fill_id": int(existing[0]), "idempotency_key": idem}

    cur.execute(
        "SELECT id, symbol, metadata FROM deploy_events WHERE id=%s",
        (event_id,),
    )
    ev_row = cur.fetchone()
    if not ev_row:
        return {"ok": False, "error": "event_not_found"}
    metadata = ev_row[2]
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}
    event = {"id": event_id, "symbol": ev_row[1], "metadata": metadata}

    plan_id = body.get("plan_id")
    plan_version = body.get("plan_version")
    archetype = str(body.get("plan_archetype") or body.get("archetype") or "F").upper()[:1]

    if plan_id:
        cur.execute(
            "SELECT id, version, plan_archetype FROM deploy_plans WHERE id=%s AND deploy_event_id=%s",
            (int(plan_id), event_id),
        )
        prow = cur.fetchone()
        if prow:
            plan_id, plan_version, archetype = int(prow[0]), int(prow[1]), str(prow[2])

    broker_confirmation_id = (str(body.get("broker_confirmation_id") or "").strip() or None)
    if environment == "production":
        # Content-level duplicate guard: identical production fills need a distinct
        # broker confirmation id to prove they are genuinely separate executions.
        cur.execute(
            """SELECT id FROM redeploy_stage_fills
               WHERE deploy_event_id=%s AND COALESCE(deploy_plan_id,0)=%s
                 AND COALESCE(plan_version,0)=%s AND ticker=%s AND stage=%s
                 AND filled_shares=%s AND filled_price=%s
                 AND COALESCE(broker_confirmation_id,'')=%s
                 AND environment='production'""",
            (
                event_id,
                int(plan_id) if plan_id else 0,
                int(plan_version) if plan_version else 0,
                str(body["ticker"]).upper(),
                stage,
                shares,
                price,
                broker_confirmation_id or "",
            ),
        )
        dup = cur.fetchone()
        if dup:
            return {
                "ok": False,
                "error": "duplicate_fill_content",
                "existing_fill_id": int(dup[0]),
                "hint": "identical fill already recorded — supply broker_confirmation_id "
                        "if this is a genuinely separate execution",
            }

    filled_at = body.get("filled_at")
    if filled_at:
        filled_at = str(filled_at)[:19]
    else:
        filled_at = datetime.now(timezone.utc)

    cur.execute(
        """INSERT INTO redeploy_stage_fills
           (deploy_event_id, deploy_plan_id, plan_version, plan_archetype, leg_index,
            ticker, stage, filled_shares, filled_price, filled_dollars, filled_at,
            account, evidence_source, evidence_note, idempotency_key, recorded_by,
            environment, broker_confirmation_id)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING id, deploy_event_id, ticker, stage, filled_shares, filled_price,
                     filled_dollars, filled_at, plan_archetype, idempotency_key, environment""",
        (
            event_id,
            int(plan_id) if plan_id else None,
            int(plan_version) if plan_version else None,
            archetype,
            body.get("leg_index"),
            str(body["ticker"]).upper(),
            stage,
            shares,
            price,
            dollars,
            filled_at,
            str(body["account"]),
            str(body.get("evidence_source") or "operator_manual"),
            (str(body.get("evidence_note") or "")[:500] or None),
            idem,
            str(body.get("recorded_by") or "operator")[:64],
            environment,
            broker_confirmation_id,
        ),
    )
    cols = [d[0] for d in cur.description]
    fill = dict(zip(cols, cur.fetchone()))

    cur.execute(
        """INSERT INTO redeploy_monitor_audit (deploy_event_id, action, idempotency_key, payload)
           VALUES (%s, 'record_fill', %s, %s::jsonb)
           ON CONFLICT (action, idempotency_key) DO NOTHING""",
        (event_id, idem, json.dumps(body, default=str)),
    )

    # Test fills never reach Hermes learning, the outcome bus, or event metadata.
    if environment != "production":
        return {
            "ok": True,
            "advisory_only": True,
            "manual_evidence_only": True,
            "environment": environment,
            "fill": fill,
            "idempotency_key": idem,
            "note": "test fill recorded in quarantine — excluded from restoration, learning, and outcome bus",
        }

    hermes_id = emit_hermes_outcome(cur, fill, event=event)
    append_outcome_bus(fill, event, apply=True)

    snapshot = persist_monitor_snapshot(
        cur, event_id, event=event, plan_archetype=archetype, hermes_ids=[hermes_id] if hermes_id else [],
    )

    meta = dict(metadata)
    meta.setdefault("phase_e", {})
    meta["phase_e"]["last_fill_at"] = str(fill.get("filled_at"))
    meta["phase_e"]["fill_count"] = (meta["phase_e"].get("fill_count") or 0) + 1
    meta["phase_e"]["restoration_pct"] = snapshot.get("restoration_metrics", {}).get("restoration_pct")
    cur.execute(
        "UPDATE deploy_events SET metadata=%s::jsonb, updated_at=NOW() WHERE id=%s",
        (json.dumps(meta), event_id),
    )

    return {
        "ok": True,
        "advisory_only": True,
        "manual_evidence_only": True,
        "fill": fill,
        "restoration_metrics": snapshot.get("restoration_metrics"),
        "fill_summary": snapshot.get("fill_summary"),
        "hermes_outcome_id": hermes_id,
        "idempotency_key": idem,
    }


def persist_monitor_snapshot(
    cur,
    event_id: int,
    *,
    event: dict[str, Any] | None = None,
    plan_archetype: str | None = None,
    hermes_ids: list[int] | None = None,
) -> dict[str, Any]:
    ensure_monitor_tables(cur)
    if event is None:
        cur.execute("SELECT metadata, proceeds_usd, cash_visible_usd, reconciliation_status FROM deploy_events WHERE id=%s", (event_id,))
        row = cur.fetchone()
        if not row:
            return {}
        meta = row[0]
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        event = {"id": event_id, "metadata": meta, "proceeds_usd": row[1], "cash_visible_usd": row[2]}

    arch = (plan_archetype or (event.get("metadata") or {}).get("phase_b", {}).get("primary_archetype") or "F").upper()[:1]
    fills = list_fills(cur, event_id, plan_archetype=arch)
    restoration = compute_restoration_metrics(event, fills, plan_archetype=arch)
    summary = build_fill_summary(fills)
    flags = _reeval_flags(event, fills)

    version = (event.get("metadata") or {}).get("phase_b_persisted_version")
    hermes_ids = [i for i in (hermes_ids or []) if i]

    cur.execute(
        """INSERT INTO redeploy_monitor_snapshots
           (deploy_event_id, plan_version, plan_archetype, restoration_metrics, fill_summary,
            reeval_flags, hermes_outcome_ids, generator_version, policy_version)
           VALUES (%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s,%s)
           RETURNING id, snapshot_at""",
        (
            event_id,
            version,
            arch,
            json.dumps(restoration),
            json.dumps(summary),
            json.dumps(flags),
            hermes_ids or [],
            GENERATOR_VERSION,
            POLICY_VERSION,
        ),
    )
    snap_id, snap_at = cur.fetchone()
    return {
        "snapshot_id": int(snap_id),
        "snapshot_at": str(snap_at),
        "plan_archetype": arch,
        "restoration_metrics": restoration,
        "fill_summary": summary,
        "reeval_flags": flags,
    }


def get_monitoring_state(cur, event_id: int) -> dict[str, Any]:
    ensure_monitor_tables(cur)
    cur.execute(
        "SELECT id, symbol, account, proceeds_usd, metadata, status FROM deploy_events WHERE id=%s",
        (event_id,),
    )
    row = cur.fetchone()
    if not row:
        return {"ok": False, "error": "event_not_found"}
    cols = [d[0] for d in cur.description]
    event = dict(zip(cols, row))
    meta = event.get("metadata") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}
    event["metadata"] = meta

    fills = list_fills(cur, event_id)
    primary = meta.get("phase_b", {}).get("primary_archetype") or "F"
    restoration = compute_restoration_metrics(event, fills, plan_archetype=primary)
    summary = build_fill_summary(fills)
    flags = _reeval_flags(event, fills)

    cur.execute(
        """SELECT id, snapshot_at, plan_archetype, restoration_metrics, fill_summary, reeval_flags
           FROM redeploy_monitor_snapshots
           WHERE deploy_event_id=%s ORDER BY snapshot_at DESC LIMIT 5""",
        (event_id,),
    )
    scols = [d[0] for d in cur.description]
    history = []
    for r in cur.fetchall():
        h = dict(zip(scols, r))
        for jf in ("restoration_metrics", "fill_summary", "reeval_flags"):
            if isinstance(h.get(jf), str):
                try:
                    h[jf] = json.loads(h[jf])
                except Exception:
                    pass
        history.append(h)

    return {
        "ok": True,
        "advisory_only": True,
        "event_id": event_id,
        "symbol": event.get("symbol"),
        "status": event.get("status"),
        "primary_plan_archetype": primary,
        "fills": fills,
        "restoration_metrics": restoration,
        "fill_summary": summary,
        "reeval_flags": flags,
        "phase_e": meta.get("phase_e") or {},
        "snapshot_history": history,
        "generator_version": GENERATOR_VERSION,
    }


def reeval_open_events(cur, *, limit: int = 100) -> dict[str, Any]:
    """Cron hook: refresh monitoring snapshots for open events with fills or unsettled proceeds."""
    ensure_monitor_tables(cur)
    cur.execute(
        """SELECT id FROM deploy_events WHERE status='open'
           ORDER BY sold_at DESC LIMIT %s""",
        (limit,),
    )
    results = []
    for (eid,) in cur.fetchall():
        state = get_monitoring_state(cur, eid)
        if state.get("error"):
            continue
        needs = bool(state.get("fills")) or any(
            f.get("code") in ("REEVAL-001", "REEVAL-002", "REEVAL-003", "REEVAL-005")
            for f in state.get("reeval_flags") or []
        )
        if needs:
            snap = persist_monitor_snapshot(cur, eid)
            results.append({"event_id": eid, "snapshot_id": snap.get("snapshot_id"), "restoration_pct": snap.get("restoration_metrics", {}).get("restoration_pct")})
    return {"ok": True, "evaluated": len(results), "results": results, "generator_version": GENERATOR_VERSION}