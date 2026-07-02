#!/usr/bin/env python3
"""entry_desk_ops.py — Entry Desk (Path A) promote, copy-ack audit, automation, technical grades."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
AUDIT_LOG = PROJECT_ROOT / "data" / "runtime" / "entry_desk_copy_audit.jsonl"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()[:19]


def promote_to_broker_queue(body: dict) -> dict:
    """Create or refresh a broker-queue proposal from Entry Desk row fields."""
    b = body or {}
    sym = str(b.get("symbol") or "").strip().upper()
    account = str(b.get("account") or os.environ.get("ENTRY_DESK_DEFAULT_ACCOUNT") or "").strip()
    if not account or account.upper() == "ANY":
        return {"ok": False, "error": "account required on row (or set ENTRY_DESK_DEFAULT_ACCOUNT)"}
    shares = int(b.get("shares") or 10)
    entry = float(b.get("entry") or 0)
    stop = float(b.get("stop") or 0)
    target = float(b.get("target") or 0)
    strategy_id = str(b.get("strategy_id") or "momentum_scalp").strip()
    source_kind = str(b.get("source") or "WATCHLIST").upper()

    if not sym:
        return {"ok": False, "error": "symbol required"}
    if not (entry > 0 and stop > 0 and target > 0 and entry > stop and target > entry):
        return {"ok": False, "error": "valid entry > stop and target > entry required"}

    import paper_trade_logger as ptl
    res = ptl.create_manual_proposal(
        sym, shares, entry, stop, target,
        account=account, strategy_id=strategy_id, origin="entry_desk",
    )
    if not res.get("success"):
        return {"ok": False, "error": res.get("error") or res.get("message") or "promote failed", "data": res}

    pid = int(res.get("proposal_id") or res.get("id") or 0)
    diligence = None
    if pid:
        try:
            import broker_promote_oversight as bpo
            diligence = bpo.advance_broker_diligence(pid)
        except Exception as e:
            diligence = {"ok": False, "error": str(e)[:120]}

    return {
        "ok": True,
        "proposal_id": pid,
        "symbol": sym,
        "account": account,
        "source": source_kind,
        "message": f"{sym} queued as proposal #{pid} — open Proposals for Stage 2b + Auto route (2FA)",
        "diligence": diligence,
        "proposals_url": f"/v3/trading?tab=Proposals&symbol={sym}",
    }


def ack_ticket_copy(body: dict) -> dict:
    """Operator 2FA-style ack for manual ToS ticket copy — audit only, no broker write."""
    b = body or {}
    sym = str(b.get("symbol") or "").strip().upper()
    confirm = str(b.get("confirm_ticker") or "").strip().upper()
    kind = str(b.get("kind") or "setup").strip().lower()
    setup_line = str(b.get("setup_line") or "")[:500]
    actor = str(b.get("operator") or "operator")[:60]

    if not sym:
        return {"ok": False, "error": "symbol required"}
    if confirm != sym:
        return {"ok": False, "error": f"type ticker {sym} to confirm copy (web 2FA)"}

    ack_id = str(uuid.uuid4())
    row = {
        "ack_id": ack_id,
        "symbol": sym,
        "kind": kind,
        "setup_line": setup_line,
        "operator": actor,
        "channel": "web_ticker",
        "at": _utc(),
    }
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except Exception:
        pass

    try:
        import trade_modify as tm
        tm.audit_decision(
            "entry_desk_copy_ack",
            actor=actor,
            channel="web",
            after=row,
            reason=f"Entry Desk {kind} copy acknowledged — manual ToS, no API submit",
        )
    except Exception:
        pass

    return {"ok": True, "ack_id": ack_id, "symbol": sym, "kind": kind, "message": "Copy acknowledged — proceed in Thinkorswim"}


def get_entry_desk_automation() -> dict:
    """Automation metadata for Entry Desk — proposals cron + watchlist agents + recon."""
    import broker_desk_automation as bda
    base = bda.get_desk_automation_state()
    jobs = list(base.get("jobs") or [])

    wl_last = None
    wl_detail = None
    try:
        from db_adapter import _get_conn
        conn = _get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT MAX(updated_at) FROM watchlist_agent_jobs WHERE status IN ('completed','failed')"
        )
        r = cur.fetchone()
        if r and r[0]:
            wl_last = str(r[0])[:19]
        cur.execute(
            "SELECT status, COUNT(*) FROM watchlist_agent_jobs GROUP BY status"
        )
        parts = [f"{row[0]} {row[1]}" for row in (cur.fetchall() or [])]
        if parts:
            wl_detail = " · ".join(parts)
    except Exception:
        pass

    recon_last = None
    recon_detail = None
    try:
        from db_adapter import _get_conn
        cur = _get_conn().cursor()
        cur.execute(
            """SELECT id, orders_seen, matched, mismatched, status, started_at
               FROM schwab_shadow_recon_runs ORDER BY id DESC LIMIT 1"""
        )
        r = cur.fetchone()
        if r:
            recon_last = str(r[5] or "")[:19]
            recon_detail = f"#{r[0]} · orders {r[1]} · matched {r[2]} · mism {r[3]} · {r[4]}"
    except Exception:
        try:
            p = PROJECT_ROOT / "data" / "runtime" / "shadow_recon_last.json"
            if p.exists():
                blob = json.loads(p.read_text(encoding="utf-8"))
                recon_last = str(blob.get("at") or "")[:19]
                recon_detail = blob.get("summary")
        except Exception:
            pass

    jobs.append({
        "id": "watchlist_agents",
        "label": "Watchlist agents",
        "schedule": "Cron */5 off-hours · health_agent remediation",
        "manual": "Watchlist tab re-run",
        "last_at": wl_last,
        "last_detail": wl_detail,
        "automated": True,
    })
    jobs.append({
        "id": "shadow_recon",
        "label": "Schwab shadow recon",
        "schedule": "Manual reconcile + read-only activity poll",
        "manual": "Entry Desk refresh",
        "last_at": recon_last,
        "last_detail": recon_detail,
        "automated": False,
    })

    base["jobs"] = jobs
    base["desk"] = "entry_desk"
    return base


def technical_grades_batch(symbols: list[str], *, live_prices: dict | None = None) -> dict:
    """Finviz-based technical grades for visible Entry Desk symbols (no proposal required)."""
    import proposal_enrichment_bridge as peb
    from datetime import datetime, timezone

    syms = []
    seen = set()
    for s in symbols or []:
        u = str(s or "").strip().upper()
        if u and u not in seen:
            seen.add(u)
            syms.append(u)
    syms = syms[:40]
    graded_at = datetime.now(timezone.utc).isoformat()[:19]
    out: dict[str, dict] = {}

    for sym in syms:
        try:
            lp = None
            if live_prices and sym in live_prices:
                lp = float(live_prices[sym])
            snap = peb.snapshot_from_enrichment(sym, live_price=lp)
            grade = snap.get("technical_grade") or "TECH_INCOMPLETE"
            score = int(snap.get("technical_score") or 0)
            concerns = snap.get("technical_concerns") or []
            tech = peb.enrichment_technicals(sym, live_price=lp)
            assess = peb.build_technical_assessment(
                tech, grade, score, concerns, graded_at=graded_at,
                data_sources=[snap.get("enrichment_source") or "finviz"],
            )
            out[sym] = {
                "technical_grade": grade,
                "technical_score": score,
                "verdict": assess.get("verdict"),
                "action": assess.get("action"),
                "narrative_snip": (assess.get("narrative") or "")[:160],
                "graded_at": graded_at,
            }
        except Exception as e:
            out[sym] = {"technical_grade": "TECH_INCOMPLETE", "error": str(e)[:80]}

    return {"ok": True, "grades": out, "count": len(out), "generated_at": graded_at}