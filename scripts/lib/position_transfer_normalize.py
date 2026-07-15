"""Transfer-aware position normalization for rollovers and Roth ladder conversions.

Builds on cost_basis_transfer detection: when shares move Fidelity→Schwab or
Traditional IRA→Roth, we:

  1. Classify transfer type
  2. Persist transfer_history rows (DB + holdings provenance fields)
  3. Auto-normalize destination lots (source account, basis carry-forward,
     performance_adjusted flag) so YTD / multi-period returns stay continuous
  4. Audit every automatic normalization
  5. Surface stop-impact flags and operator notifications

Holdings SSOT remains holdings.json. DB tables are the durable audit trail.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from typing import Any

log = logging.getLogger("position_transfer_normalize")

PROJECT_ROOT = Path(
    os.environ.get("TRADE_AI_ROOT")
    or Path(__file__).resolve().parents[2]
)
HOLDINGS_PATH = PROJECT_ROOT / "data" / "portfolios" / "state" / "holdings.json"
EVENTS_PATH = PROJECT_ROOT / "data" / "portfolios" / "state" / "cost_basis_transfer_events.json"

# Account family helpers for transfer classification
FIDELITY_ACCTS = frozenset({
    "fidelity_401k", "fidelity_rollover_ira", "fidelity_401k_brokerage",
    "fidelity_roth", "fidelity_traditional_ira",
})
SCHWAB_ACCTS = frozenset({
    "schwab_rollover_ira", "schwab_roth", "schwab_roth_ira", "schwab_taxable",
    "schwab_traditional_ira",
})
TRADITIONAL_IRA = frozenset({
    "schwab_rollover_ira", "schwab_traditional_ira", "fidelity_rollover_ira",
    "fidelity_401k", "fidelity_traditional_ira",
})
ROTH_IRA = frozenset({
    "schwab_roth", "schwab_roth_ira", "fidelity_roth",
})

TRANSFER_TYPES = (
    "fidelity_to_schwab",
    "traditional_to_roth",
    "external_rollover",
    "internal_transfer",
    "other",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _norm_acct(a: str) -> str:
    return (a or "").strip().lower()


def _norm_sym(s: str) -> str:
    return (s or "").strip().upper()


def classify_transfer_type(from_account: str, to_account: str) -> str:
    """Map account pair → transfer_type for UI notes + performance handling."""
    fa, ta = _norm_acct(from_account), _norm_acct(to_account)
    if fa in FIDELITY_ACCTS and ta in SCHWAB_ACCTS:
        return "fidelity_to_schwab"
    if fa in TRADITIONAL_IRA and ta in ROTH_IRA:
        return "traditional_to_roth"
    if fa.startswith("external") or "external" in fa:
        return "external_rollover"
    if fa.split("_")[0] == ta.split("_")[0]:
        return "internal_transfer"
    if fa and ta and fa != ta:
        return "external_rollover"
    return "other"


def transfer_display_note(transfer_type: str, from_account: str = "", to_account: str = "") -> str:
    """Human-readable label for YTD table / position UI."""
    if transfer_type == "fidelity_to_schwab":
        return "includes Fidelity rollover"
    if transfer_type == "traditional_to_roth":
        return "Roth conversion – performance carried forward"
    if transfer_type == "external_rollover":
        return "includes external rollover"
    if transfer_type == "internal_transfer":
        return "ex-transfers"
    return "position normalized after transfer"


def ensure_tables(cur=None) -> None:
    """Idempotent DDL (also in migrations/2026_07_23_position_transfer_history.sql)."""
    own = cur is None
    conn = None
    if own:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS position_transfer_history (
            id SERIAL PRIMARY KEY,
            event_id TEXT NOT NULL UNIQUE,
            symbol TEXT NOT NULL,
            from_account TEXT NOT NULL,
            to_account TEXT NOT NULL,
            shares_moved NUMERIC NOT NULL,
            cost_basis_total NUMERIC,
            per_share_basis NUMERIC,
            basis_source TEXT,
            transfer_type TEXT NOT NULL DEFAULT 'internal_transfer',
            confidence TEXT NOT NULL DEFAULT 'medium',
            status TEXT NOT NULL DEFAULT 'detected',
            share_match_pct NUMERIC,
            performance_adjusted BOOLEAN NOT NULL DEFAULT TRUE,
            detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            normalized_at TIMESTAMPTZ,
            sync_source TEXT,
            notes TEXT,
            meta_json JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""")
    cur.execute("""
        CREATE INDEX IF NOT EXISTS ix_pos_xfer_hist_symbol
            ON position_transfer_history (symbol, detected_at DESC)""")
    cur.execute("""
        CREATE INDEX IF NOT EXISTS ix_pos_xfer_hist_to_acct
            ON position_transfer_history (to_account, symbol)""")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS position_normalization_log (
            id SERIAL PRIMARY KEY,
            event_id TEXT,
            symbol TEXT NOT NULL,
            from_account TEXT,
            to_account TEXT NOT NULL,
            shares_moved NUMERIC,
            action TEXT NOT NULL,
            previous_state JSONB,
            new_state JSONB,
            stop_impact_json JSONB,
            performance_note TEXT,
            actor TEXT NOT NULL DEFAULT 'system',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )""")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS position_transfer_notifications (
            id SERIAL PRIMARY KEY,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'info',
            active BOOLEAN NOT NULL DEFAULT TRUE,
            related_event_ids TEXT[] DEFAULT '{}',
            meta_json JSONB DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            expires_at TIMESTAMPTZ,
            dismissed_at TIMESTAMPTZ
        )""")
    if own and conn is not None:
        conn.commit()


def _stop_impact_for(account: str, symbol: str, new_shares: float | None) -> dict | None:
    """Best-effort stop coverage preview after share/account change."""
    try:
        from share_reconciliation import impact_preview
        return impact_preview(account, symbol, new_shares=new_shares)
    except Exception as e:
        return {"ok": False, "error": str(e)[:120]}


def persist_transfer_event(ev: dict[str, Any], *, auto_normalize: bool = True) -> dict[str, Any]:
    """Upsert one transfer into position_transfer_history; optionally mark auto_normalized."""
    ensure_tables()
    from db_adapter import _get_conn
    conn = _get_conn()
    cur = conn.cursor()

    event_id = str(ev.get("id") or "")
    if not event_id:
        return {"ok": False, "error": "missing event id"}

    from_acct = _norm_acct(ev.get("from_account") or "")
    to_acct = _norm_acct(ev.get("to_account") or "")
    xfer_type = ev.get("transfer_type") or classify_transfer_type(from_acct, to_acct)
    note = ev.get("notes") or transfer_display_note(xfer_type, from_acct, to_acct)
    status = str(ev.get("status") or "detected")
    if auto_normalize and status in ("auto_applied", "auto_tagged", "detected", "auto_normalized"):
        if ev.get("confidence") == "high" or status == "auto_applied":
            status = "auto_normalized"
    conf = str(ev.get("confidence") or "medium")
    ps = ev.get("per_share_basis")
    total_basis = ev.get("total_basis")
    if total_basis is None and ps is not None and ev.get("shares"):
        try:
            total_basis = round(float(ps) * float(ev["shares"]), 2)
        except (TypeError, ValueError):
            total_basis = None
    normalized_at = _now() if status == "auto_normalized" else None
    meta = {
        "basis_source": ev.get("basis_source"),
        "sync_source": ev.get("sync_source"),
        "original_status": ev.get("status"),
    }

    cur.execute("""
        INSERT INTO position_transfer_history (
            event_id, symbol, from_account, to_account, shares_moved,
            cost_basis_total, per_share_basis, basis_source, transfer_type,
            confidence, status, share_match_pct, performance_adjusted,
            detected_at, normalized_at, sync_source, notes, meta_json, updated_at
        ) VALUES (
            %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,
            COALESCE(%s::timestamptz, NOW()), %s, %s, %s, %s::jsonb, NOW()
        )
        ON CONFLICT (event_id) DO UPDATE SET
            shares_moved = EXCLUDED.shares_moved,
            cost_basis_total = COALESCE(EXCLUDED.cost_basis_total, position_transfer_history.cost_basis_total),
            per_share_basis = COALESCE(EXCLUDED.per_share_basis, position_transfer_history.per_share_basis),
            basis_source = COALESCE(EXCLUDED.basis_source, position_transfer_history.basis_source),
            transfer_type = EXCLUDED.transfer_type,
            confidence = EXCLUDED.confidence,
            status = CASE
                WHEN position_transfer_history.status IN ('confirmed','dismissed')
                    THEN position_transfer_history.status
                ELSE EXCLUDED.status
            END,
            share_match_pct = EXCLUDED.share_match_pct,
            normalized_at = COALESCE(EXCLUDED.normalized_at, position_transfer_history.normalized_at),
            sync_source = COALESCE(EXCLUDED.sync_source, position_transfer_history.sync_source),
            notes = COALESCE(EXCLUDED.notes, position_transfer_history.notes),
            meta_json = position_transfer_history.meta_json || EXCLUDED.meta_json,
            updated_at = NOW()
        RETURNING id, status
    """, (
        event_id,
        _norm_sym(ev.get("symbol") or ""),
        from_acct,
        to_acct,
        float(ev.get("shares") or 0),
        total_basis,
        float(ps) if ps is not None else None,
        ev.get("basis_source"),
        xfer_type,
        conf,
        status,
        float(ev["share_match_pct"]) if ev.get("share_match_pct") is not None else None,
        ev.get("detected_at"),
        normalized_at,
        ev.get("sync_source"),
        note,
        json.dumps(meta),
    ))
    row = cur.fetchone()
    conn.commit()
    return {
        "ok": True,
        "id": int(row[0]) if row else None,
        "status": row[1] if row else status,
        "event_id": event_id,
        "transfer_type": xfer_type,
        "display_note": note,
    }


def log_normalization(
    *,
    event_id: str | None,
    symbol: str,
    from_account: str | None,
    to_account: str,
    shares_moved: float | None,
    action: str,
    previous_state: dict | None = None,
    new_state: dict | None = None,
    stop_impact: dict | None = None,
    performance_note: str | None = None,
    actor: str = "system",
) -> int | None:
    ensure_tables()
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO position_normalization_log (
                event_id, symbol, from_account, to_account, shares_moved,
                action, previous_state, new_state, stop_impact_json,
                performance_note, actor
            ) VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s)
            RETURNING id
        """, (
            event_id,
            _norm_sym(symbol),
            _norm_acct(from_account or "") or None,
            _norm_acct(to_account),
            shares_moved,
            action,
            json.dumps(previous_state or {}),
            json.dumps(new_state or {}),
            json.dumps(stop_impact or {}),
            performance_note,
            actor,
        ))
        rid = cur.fetchone()[0]
        conn.commit()
        return int(rid)
    except Exception as e:
        log.warning("normalization log failed: %s", e)
        return None


def annotate_holding_row(h: dict[str, Any], ev: dict[str, Any]) -> dict[str, Any]:
    """Stamp provenance + transfer history onto a destination holdings row (in place)."""
    from_acct = _norm_acct(ev.get("from_account") or "")
    to_acct = _norm_acct(ev.get("to_account") or h.get("account") or "")
    xfer_type = ev.get("transfer_type") or classify_transfer_type(from_acct, to_acct)
    note = transfer_display_note(xfer_type, from_acct, to_acct)

    # Preserve earliest original source across multi-hop (Fidelity → Schwab → Roth)
    if not h.get("original_source_account"):
        h["original_source_account"] = from_acct or "external_rollover"
    h["current_account"] = to_acct or _norm_acct(h.get("account") or "")

    entry = {
        "date": (ev.get("detected_at") or _now_iso())[:10],
        "from_account": from_acct,
        "to_account": to_acct,
        "shares_moved": ev.get("shares"),
        "cost_basis_if_known": ev.get("total_basis"),
        "per_share_basis": ev.get("per_share_basis"),
        "basis_source": ev.get("basis_source"),
        "transfer_type": xfer_type,
        "event_id": ev.get("id"),
        "status": ev.get("status"),
        "confidence": ev.get("confidence"),
        "display_note": note,
    }
    hist = list(h.get("transfer_history") or [])
    # de-dupe by event_id
    if not any(x.get("event_id") == entry["event_id"] for x in hist if isinstance(x, dict)):
        hist.append(entry)
    h["transfer_history"] = hist[-20:]  # cap growth

    h["transfer_history_tag"] = {
        "event_id": ev.get("id"),
        "from_account": from_acct,
        "to_account": to_acct,
        "shares": ev.get("shares"),
        "per_share_basis": ev.get("per_share_basis"),
        "basis_source": ev.get("basis_source"),
        "confidence": ev.get("confidence"),
        "status": ev.get("status"),
        "detected_at": ev.get("detected_at"),
        "transfer_type": xfer_type,
        "display_note": note,
    }
    h["performance_adjusted"] = True
    h["adjusted_for_transfer"] = _now_iso()
    h["normalized_after_transfer"] = True
    h["normalization_status"] = "Position normalized after rollover/transfer"
    h["transfer_display_note"] = note

    # system/broker share fields: ensure both present
    try:
        sh = float(h.get("shares") or 0)
    except (TypeError, ValueError):
        sh = 0.0
    if h.get("system_shares") is None and sh:
        h["system_shares"] = sh
    if h.get("broker_actual_shares") is None and sh:
        h["broker_actual_shares"] = sh

    # basis carry-forward when high confidence
    if ev.get("status") in ("auto_applied", "auto_normalized", "auto_tagged") and ev.get("per_share_basis"):
        try:
            ps = float(ev["per_share_basis"])
            if sh > 0 and ps > 0:
                # Only fill if missing or partial transfer basis
                src = str(h.get("cost_basis_source") or "")
                if not h.get("cost_basis") or src in (
                    "partial_transfer_in", "unknown", "broker_api", ""
                ) or h.get("basis_partial"):
                    cb = round(sh * ps, 2)
                    h["cost_basis"] = cb
                    h["cost_basis_source"] = "auto_transfer_history"
                    h["basis_partial"] = False
                    h["avg_cost"] = round(ps, 6)
                    mv = h.get("market_value")
                    if mv is not None:
                        h["gain_loss"] = round(float(mv) - cb, 2)
                        h["gain_loss_pct"] = round((float(mv) - cb) / cb * 100, 4) if cb > 0 else None
        except (TypeError, ValueError):
            pass
    return h


def normalize_holdings_for_events(
    holdings_doc: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    actor: str = "system",
    persist_db: bool = True,
) -> dict[str, Any]:
    """Apply full normalization pipeline for a batch of transfer events."""
    if not events:
        return {
            "ok": True,
            "events": 0,
            "normalized": 0,
            "holdings_doc": holdings_doc,
            "transfer_events": [],
            "summary": "no transfers",
        }

    enriched: list[dict[str, Any]] = []
    normalized = 0
    stop_flags: list[dict] = []

    for raw in events:
        ev = dict(raw)
        fa = _norm_acct(ev.get("from_account") or "")
        ta = _norm_acct(ev.get("to_account") or "")
        ev["transfer_type"] = ev.get("transfer_type") or classify_transfer_type(fa, ta)
        ev["display_note"] = transfer_display_note(ev["transfer_type"], fa, ta)

        # Promote high-confidence auto_tagged → auto_normalized
        if ev.get("confidence") == "high" and ev.get("status") in (
            "auto_tagged", "auto_applied", "detected"
        ):
            ev["status"] = "auto_normalized"
        elif ev.get("status") == "auto_applied":
            ev["status"] = "auto_normalized"

        db_row = None
        if persist_db:
            try:
                db_row = persist_transfer_event(ev, auto_normalize=True)
            except Exception as e:
                log.warning("persist transfer failed %s: %s", ev.get("id"), e)
                db_row = {"ok": False, "error": str(e)[:120]}

        # Find destination row
        dest = None
        for h in holdings_doc.get("holdings") or []:
            if (_norm_acct(h.get("account") or "") == ta
                    and _norm_sym(h.get("symbol") or "") == _norm_sym(ev.get("symbol") or "")):
                dest = h
                break

        prev_state = None
        new_state = None
        stop_impact = None
        if dest is not None:
            prev_state = {
                "account": dest.get("account"),
                "shares": dest.get("shares"),
                "system_shares": dest.get("system_shares"),
                "cost_basis": dest.get("cost_basis"),
                "cost_basis_source": dest.get("cost_basis_source"),
                "original_source_account": dest.get("original_source_account"),
            }
            annotate_holding_row(dest, ev)
            new_state = {
                "account": dest.get("account"),
                "shares": dest.get("shares"),
                "system_shares": dest.get("system_shares"),
                "cost_basis": dest.get("cost_basis"),
                "cost_basis_source": dest.get("cost_basis_source"),
                "original_source_account": dest.get("original_source_account"),
                "current_account": dest.get("current_account"),
                "normalized_after_transfer": dest.get("normalized_after_transfer"),
                "transfer_display_note": dest.get("transfer_display_note"),
            }
            try:
                sh = float(dest.get("shares") or 0)
            except (TypeError, ValueError):
                sh = None
            stop_impact = _stop_impact_for(ta, _norm_sym(ev.get("symbol") or ""), sh)
            if stop_impact and stop_impact.get("warn_live_stop"):
                stop_flags.append({
                    "symbol": _norm_sym(ev.get("symbol") or ""),
                    "account": ta,
                    "impact": stop_impact,
                })
            normalized += 1

        if persist_db:
            log_normalization(
                event_id=ev.get("id"),
                symbol=ev.get("symbol") or "",
                from_account=fa,
                to_account=ta,
                shares_moved=float(ev["shares"]) if ev.get("shares") is not None else None,
                action="auto_normalize" if ev.get("status") == "auto_normalized" else "detected",
                previous_state=prev_state,
                new_state=new_state,
                stop_impact=stop_impact if isinstance(stop_impact, dict) else None,
                performance_note=ev.get("display_note"),
                actor=actor,
            )
            if stop_impact and stop_impact.get("warn_live_stop"):
                log_normalization(
                    event_id=ev.get("id"),
                    symbol=ev.get("symbol") or "",
                    from_account=fa,
                    to_account=ta,
                    shares_moved=float(ev["shares"]) if ev.get("shares") is not None else None,
                    action="stop_impact_flag",
                    stop_impact=stop_impact,
                    performance_note=(
                        "Live stop qty may not match held shares after transfer; "
                        "prefer replace-mode resize."
                    ),
                    actor=actor,
                )

        enriched.append({**ev, "db": db_row})

    # Active season / batch notification
    if persist_db and normalized:
        try:
            upsert_transfer_notification(
                kind=_notification_kind(enriched),
                title=_notification_title(enriched),
                body=_notification_body(enriched, stop_flags),
                severity="warning" if stop_flags else "info",
                related_event_ids=[e.get("id") for e in enriched if e.get("id")],
                meta={"stop_flags": len(stop_flags), "count": normalized},
            )
        except Exception as e:
            log.warning("transfer notification failed: %s", e)

    # Alert bus (non-fatal)
    try:
        from alert_event_writer import save_alert_event
        for e in enriched[:8]:
            save_alert_event(
                alert_type="strategic_alert",
                severity="info",
                source_script="position_transfer_normalize",
                symbol=_norm_sym(e.get("symbol") or ""),
                raw_text=(
                    f"[transfer-normalize] {e.get('symbol')} "
                    f"{e.get('from_account')} → {e.get('to_account')} "
                    f"({e.get('shares')} sh, {e.get('transfer_type')}, {e.get('status')}) "
                    f"— {e.get('display_note')}"
                ),
                parsed_payload={"kind": "position_transfer", **{k: e.get(k) for k in (
                    "id", "symbol", "from_account", "to_account", "shares",
                    "transfer_type", "status", "confidence", "display_note",
                )}},
            )
    except Exception:
        pass

    summary = (
        f"{len(enriched)} transfer(s): {normalized} position(s) normalized "
        f"({', '.join(sorted({e.get('transfer_type') or '?' for e in enriched}))})"
    )
    return {
        "ok": True,
        "events": len(enriched),
        "normalized": normalized,
        "stop_flags": stop_flags,
        "transfer_events": enriched,
        "holdings_doc": holdings_doc,
        "summary": summary,
    }


def _notification_kind(events: list[dict]) -> str:
    types = {e.get("transfer_type") for e in events}
    if "fidelity_to_schwab" in types:
        return "rollover_active"
    if "traditional_to_roth" in types:
        return "roth_ladder_season"
    return "normalization_batch"


def _notification_title(events: list[dict]) -> str:
    kinds = {_notification_kind(events)}
    if "rollover_active" in kinds:
        return "Fidelity → Schwab rollover: positions being normalized"
    if "roth_ladder_season" in kinds:
        return "Roth ladder conversion: performance carried forward"
    return "Positions normalized after internal transfer"


def _notification_body(events: list[dict], stop_flags: list) -> str:
    lines = [
        "Trade AI automatically linked transferred shares to existing holdings so "
        "YTD / multi-period performance stays continuous (ex-transfers at household level).",
        "",
        f"Normalized {len(events)} movement(s):",
    ]
    for e in events[:12]:
        lines.append(
            f"  • {e.get('symbol')}: {e.get('from_account')} → {e.get('to_account')} "
            f"({e.get('shares')} sh) — {e.get('display_note')}"
        )
    if stop_flags:
        lines.append("")
        lines.append(
            f"{len(stop_flags)} position(s) have live stops that may need replace-mode "
            "resize after the transfer. Review Stop Management (same 2FA flow)."
        )
    lines.append("")
    lines.append("No action required unless a stop is mis-sized or a candidate needs confirmation.")
    return "\n".join(lines)


def upsert_transfer_notification(
    *,
    kind: str,
    title: str,
    body: str,
    severity: str = "info",
    related_event_ids: list | None = None,
    meta: dict | None = None,
    ttl_days: int = 14,
) -> int | None:
    ensure_tables()
    from db_adapter import _get_conn
    conn = _get_conn()
    cur = conn.cursor()
    expires = _now() + timedelta(days=ttl_days)
    # Collapse duplicate active notifications of same kind within 24h
    cur.execute("""
        SELECT id FROM position_transfer_notifications
        WHERE kind=%s AND active=TRUE AND dismissed_at IS NULL
          AND created_at > NOW() - INTERVAL '24 hours'
        ORDER BY id DESC LIMIT 1
    """, (kind,))
    row = cur.fetchone()
    ids = [str(x) for x in (related_event_ids or []) if x]
    if row:
        cur.execute("""
            UPDATE position_transfer_notifications SET
                title=%s, body=%s, severity=%s,
                related_event_ids = (
                    SELECT ARRAY(SELECT DISTINCT unnest(
                        COALESCE(related_event_ids, '{}') || %s::text[]
                    ))
                ),
                meta_json = COALESCE(meta_json, '{}'::jsonb) || %s::jsonb,
                expires_at=%s
            WHERE id=%s
            RETURNING id
        """, (title, body, severity, ids, json.dumps(meta or {}), expires, row[0]))
        nid = cur.fetchone()[0]
    else:
        cur.execute("""
            INSERT INTO position_transfer_notifications
                (kind, title, body, severity, active, related_event_ids, meta_json, expires_at)
            VALUES (%s,%s,%s,%s,TRUE,%s,%s::jsonb,%s)
            RETURNING id
        """, (kind, title, body, severity, ids, json.dumps(meta or {}), expires))
        nid = cur.fetchone()[0]
    conn.commit()
    return int(nid)


def list_transfer_history(
    *,
    account: str | None = None,
    symbol: str | None = None,
    limit: int = 50,
) -> list[dict]:
    ensure_tables()
    from db_adapter import _get_conn
    cur = _get_conn().cursor()
    clauses = []
    params: list[Any] = []
    if account:
        clauses.append("(from_account=%s OR to_account=%s)")
        params.extend([_norm_acct(account), _norm_acct(account)])
    if symbol:
        clauses.append("symbol=%s")
        params.append(_norm_sym(symbol))
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(int(limit))
    cur.execute(f"""
        SELECT id, event_id, symbol, from_account, to_account, shares_moved,
               cost_basis_total, per_share_basis, basis_source, transfer_type,
               confidence, status, share_match_pct, performance_adjusted,
               detected_at, normalized_at, sync_source, notes, meta_json
        FROM position_transfer_history
        {where}
        ORDER BY detected_at DESC NULLS LAST, id DESC
        LIMIT %s
    """, params)
    cols = [d[0] for d in cur.description]
    out = []
    for r in cur.fetchall() or []:
        d = dict(zip(cols, r))
        for k in ("shares_moved", "cost_basis_total", "per_share_basis", "share_match_pct"):
            if d.get(k) is not None:
                d[k] = float(d[k])
        for k in ("detected_at", "normalized_at"):
            if d.get(k) is not None and hasattr(d[k], "isoformat"):
                d[k] = d[k].isoformat()
        d["display_note"] = d.get("notes") or transfer_display_note(
            d.get("transfer_type") or "other",
            d.get("from_account") or "",
            d.get("to_account") or "",
        )
        out.append(d)
    return out


def list_active_notifications(*, include_expired: bool = False) -> list[dict]:
    ensure_tables()
    from db_adapter import _get_conn
    cur = _get_conn().cursor()
    if include_expired:
        cur.execute("""
            SELECT id, kind, title, body, severity, active, related_event_ids,
                   meta_json, created_at, expires_at, dismissed_at
            FROM position_transfer_notifications
            WHERE dismissed_at IS NULL
            ORDER BY created_at DESC LIMIT 20
        """)
    else:
        cur.execute("""
            SELECT id, kind, title, body, severity, active, related_event_ids,
                   meta_json, created_at, expires_at, dismissed_at
            FROM position_transfer_notifications
            WHERE active=TRUE AND dismissed_at IS NULL
              AND (expires_at IS NULL OR expires_at > NOW())
            ORDER BY created_at DESC LIMIT 20
        """)
    cols = [d[0] for d in cur.description]
    out = []
    for r in cur.fetchall() or []:
        d = dict(zip(cols, r))
        for k in ("created_at", "expires_at", "dismissed_at"):
            if d.get(k) is not None and hasattr(d[k], "isoformat"):
                d[k] = d[k].isoformat()
        out.append(d)
    return out


def dismiss_notification(notif_id: int) -> dict:
    ensure_tables()
    from db_adapter import _get_conn
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute("""
        UPDATE position_transfer_notifications
        SET active=FALSE, dismissed_at=NOW()
        WHERE id=%s
        RETURNING id
    """, (int(notif_id),))
    row = cur.fetchone()
    conn.commit()
    return {"ok": bool(row), "id": int(notif_id)}


def process_and_normalize(
    prior_doc: dict[str, Any] | None,
    current_doc: dict[str, Any],
    *,
    sync_source: str = "holdings_sync",
    apply: bool = True,
) -> dict[str, Any]:
    """Full pipeline: cost_basis detect → normalize → DB audit → tagged holdings.

    Drop-in companion to cost_basis_transfer.process_holdings_change; prefer calling
    this from protected_holdings_write so both basis carry-forward and provenance run.
    """
    from lib.cost_basis_transfer import detect_transfers, apply_transfer_events

    events = detect_transfers(prior_doc, current_doc)
    if not events:
        return {
            "ok": True,
            "events": 0,
            "normalized": 0,
            "applied_overrides": 0,
            "candidates": 0,
            "summary": "no transfers detected",
            "holdings_doc": current_doc,
        }

    # Basis overrides (existing path)
    basis_result = apply_transfer_events(events, apply=apply, sync_source=sync_source)
    stamped = basis_result.get("transfer_events") or events
    for e in stamped:
        e["sync_source"] = sync_source
        e["transfer_type"] = classify_transfer_type(
            e.get("from_account") or "", e.get("to_account") or ""
        )

    if not apply:
        return {
            **basis_result,
            "ok": True,
            "normalized": 0,
            "transfer_events": stamped,
            "holdings_doc": current_doc,
        }

    norm = normalize_holdings_for_events(
        current_doc, stamped, actor="system", persist_db=True
    )
    return {
        "ok": True,
        "events": norm.get("events", 0),
        "normalized": norm.get("normalized", 0),
        "applied_overrides": basis_result.get("applied_overrides", 0),
        "candidates": basis_result.get("candidates", 0),
        "stop_flags": norm.get("stop_flags") or [],
        "transfer_events": norm.get("transfer_events") or stamped,
        "holdings_doc": norm.get("holdings_doc") or current_doc,
        "summary": (
            f"{norm.get('summary')}; basis overrides: "
            f"{basis_result.get('applied_overrides', 0)} applied, "
            f"{basis_result.get('candidates', 0)} need confirmation"
        ),
    }


def account_transfer_notes_ytd(state_dir: Path | None = None) -> dict[str, list[str]]:
    """Per-account display notes for YTD table from recent transfer history + JSON events."""
    notes: dict[str, set[str]] = {}

    def _add(acct: str, note: str) -> None:
        if not acct or not note:
            return
        notes.setdefault(_norm_acct(acct), set()).add(note)

    # DB
    try:
        for row in list_transfer_history(limit=100):
            tt = row.get("transfer_type") or "other"
            note = row.get("display_note") or transfer_display_note(tt)
            _add(row.get("to_account") or "", note)
            _add(row.get("from_account") or "", "ex-transfers")
            if tt == "fidelity_to_schwab":
                _add(row.get("to_account") or "", "includes Fidelity rollover")
            if tt == "traditional_to_roth":
                _add(row.get("to_account") or "", "Roth conversion – performance carried forward")
    except Exception:
        pass

    # JSON fallback
    try:
        if EVENTS_PATH.exists():
            doc = json.loads(EVENTS_PATH.read_text())
            for e in doc.get("transfer_events") or []:
                tt = e.get("transfer_type") or classify_transfer_type(
                    e.get("from_account") or "", e.get("to_account") or ""
                )
                note = transfer_display_note(tt)
                _add(e.get("to_account") or "", note)
                _add(e.get("from_account") or "", "ex-transfers")
    except Exception:
        pass

    # Seasonal Roth ladder hint (Jan–Apr typical)
    today = date.today()
    if today.month <= 4:
        for a in ROTH_IRA:
            _add(a, "Roth conversion – performance carried forward")
            # traditional source may also show ex-transfers
        for a in ("schwab_rollover_ira", "fidelity_rollover_ira"):
            _add(a, "ex-transfers")

    return {k: sorted(v) for k, v in notes.items()}
