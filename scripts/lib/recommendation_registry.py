"""Recommendation registry — a stable, deterministic rec_id for every recommendation the operator sees.

Learning loop PR1 (operator 2026-10-21: "Stable recommendation IDs, trade linkage, and R-multiple attribution provide
the highest long-term value"). Design: docs/ops/LEARNING_LOOP_PR1_2026-10-21.md. Store: recommendation_registry
(migrations/2026_10_21_learning_loop_pr1.sql). This module is the store's ONLY writer (``upsert_recs`` /
``bump_seen``); everything else here is pure.

Sources and their natural keys (the rec_id is ``rec_`` + sha256(source | natural key)[:20], so it never depends on
when or how often it is computed):

  cio_opportunity       symbol + entry zone + plan stop + plan target + the run_id that FIRST published that plan.
                        Version lines that keep the same plan (a rank-band or conviction change) keep the same rec_id;
                        a moved level, or a plan that disappears and comes back, gets a new one.
  paper_trade_proposal  paper_trade_proposals.id
  scalp_alert           trade_ai_scans.id (decision GO) and scalp_scan_results.id (decision GO, alerted)
  entry_alert           alert_events.alert_uid, for alert types in ENTRY_ALERT_TYPES

MBI_BEHAVIOR = 0: the plan levels are stored for attribution only (plan_stop / plan_target, never "stop"); nothing here
sizes, orders, stops or weights anything, and nothing here touches a broker.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

REGISTRY_WRITER = "scripts/lib/recommendation_registry.py"
SOURCES = ("cio_opportunity", "paper_trade_proposal", "scalp_alert", "entry_alert")

# How long a recommendation stays "active" after it was issued (or last re-confirmed, for opportunities).
TTL = {
    "cio_opportunity": timedelta(days=14),     # re-confirmed every curator run while the plan is current
    "paper_trade_proposal": timedelta(days=5),  # used only when the proposal row carries no expiry
    "scalp_alert": timedelta(days=1),           # a scalp GO is an intraday call
    "entry_alert": timedelta(days=3),
}
# alert_events types that carry an entry intent. alert_events had NONE of these in the 90 days to 2026-10-21 (the
# scalp GO alerts the operator sees live in trade_ai_scans / scalp_scan_results); the list is kept so an entry alert
# written there later is registered without a code change.
ENTRY_ALERT_TYPES = ("entry_alert", "entry_signal", "scalp_ignition", "scalp_entry")
KILL_SWITCH_ENV = "TRADEAI_REC_REGISTRY_WRITE"   # "0" → writers do nothing

COLUMNS = (
    "rec_id", "source", "source_table", "source_id", "symbol", "direction", "entry_low", "entry_high",
    "plan_stop", "plan_target", "created_at", "expires_at", "last_seen_at", "superseded_at", "conviction_at_issue",
    "conviction_scale", "first_seen_run_id", "stance", "source_status", "payload", "registry_writer",
)


# ── pure helpers ──────────────────────────────────────────────────────────────────────────────────────────────────
def rec_id_for(source: str, natural_key: str) -> str:
    if source not in SOURCES:
        raise ValueError(f"unknown recommendation source {source!r}")
    return "rec_" + hashlib.sha256(f"{source}|{natural_key}".encode("utf-8")).hexdigest()[:20]


def _f(v: Any) -> Optional[float]:
    try:
        if v is None or v == "":
            return None
        x = float(v)
        return x if x == x and x not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None


def _lvl(v: Any) -> str:
    """Canonical text for a price level inside a natural key (4 dp, so 90.8 == 90.80 == 90.8000)."""
    x = _f(v)
    return "-" if x is None else f"{x:.4f}"


def _ts(v: Any) -> Optional[datetime]:
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def direction_of(side: Any) -> str:
    s = str(side or "long").strip().lower()
    return "short" if s in ("short", "sell", "sell_short", "sellshort", "bearish") else "long"


def writes_enabled() -> bool:
    return os.environ.get(KILL_SWITCH_ENV, "1").strip() != "0"


# ── CIO opportunities ─────────────────────────────────────────────────────────────────────────────────────────────
def opportunity_plan(assessment: dict[str, Any]) -> Optional[dict[str, float]]:
    """The published plan of an OpportunityAssessment@v1 (entry zone, invalidation, primary target), or None when it
    has no complete plan. A one-sided zone collapses to the entry reference."""
    rr = (assessment or {}).get("risk_reward") or {}
    zone = rr.get("entry_zone") or []
    lo = _f(zone[0]) if len(zone) >= 1 else None
    hi = _f(zone[1]) if len(zone) >= 2 else lo
    ref = _f(rr.get("entry_ref"))
    if lo is None and ref is not None:
        lo = hi = ref
    stop = _f(rr.get("invalidation_level"))
    target = _f(rr.get("primary_target"))
    if target is None:
        prim = [t for t in rr.get("targets") or [] if isinstance(t, dict) and t.get("primary")]
        target = _f((prim or [{}])[0].get("px"))
    if lo is None or hi is None or stop is None or target is None:
        return None
    if lo > hi:
        lo, hi = hi, lo
    return {"entry_low": lo, "entry_high": hi, "plan_stop": stop, "plan_target": target}


def plan_key(symbol: str, plan: dict[str, float]) -> str:
    return "|".join((symbol.upper(), _lvl(plan["entry_low"]), _lvl(plan["entry_high"]),
                     _lvl(plan["plan_stop"]), _lvl(plan["plan_target"])))


def opportunity_rec_id(symbol: str, plan: dict[str, float], first_seen_run_id: str) -> str:
    return rec_id_for("cio_opportunity", f"{plan_key(symbol, plan)}|{first_seen_run_id}")


class OpportunityLineage:
    """Folds OpportunityAssessmentVersion@v1 lines (in file order) into recommendation rows.

    A symbol's plan lineage continues while consecutive versions publish the same plan; the rec keeps the run_id of
    the first version of that run of identical plans. A version with a different plan (or none) supersedes it."""

    def __init__(self, ttl: timedelta = TTL["cio_opportunity"]):
        self.ttl = ttl
        self.recs: dict[str, dict[str, Any]] = {}
        self.current: dict[str, str] = {}          # symbol → rec_id of the plan currently published (head)

    def feed(self, line: dict[str, Any]) -> Optional[str]:
        sym = str(line.get("symbol") or "").upper()
        if not sym:
            return None
        a = line.get("assessment") or {}
        at = _ts(line.get("written_at")) or _ts(a.get("as_of"))
        if at is None:
            return None
        run_id = str((line.get("provenance") or {}).get("run_id") or f"v{line.get('version')}@{at.isoformat()}")
        plan = opportunity_plan(a)
        prev_id = self.current.get(sym)
        prev = self.recs.get(prev_id) if prev_id else None
        if plan is not None and prev is not None and prev["_plan_key"] == plan_key(sym, plan):
            prev["last_seen_at"] = max(prev["last_seen_at"], at)
            prev["expires_at"] = prev["last_seen_at"] + self.ttl
            prev["stance"] = a.get("stance") or prev.get("stance")
            return prev_id
        if prev is not None and prev.get("superseded_at") is None:
            prev["superseded_at"] = at
            prev["expires_at"] = max(prev["created_at"], min(prev["expires_at"], at))
        if plan is None:
            self.current.pop(sym, None)
            return None
        rid = opportunity_rec_id(sym, plan, run_id)
        self.recs[rid] = {
            "rec_id": rid, "source": "cio_opportunity", "source_table": "data/cio/cio_opportunity_assessments.jsonl",
            "source_id": f"{plan_key(sym, plan)}|{run_id}", "symbol": sym, "direction": "long", **plan,
            "created_at": at, "expires_at": at + self.ttl, "last_seen_at": at, "superseded_at": None,
            "conviction_at_issue": _f(a.get("conviction")), "conviction_scale": "cio_conviction_0_100",
            "first_seen_run_id": run_id, "stance": a.get("stance"), "source_status": None,
            "payload": {"version": line.get("version"), "rank": a.get("rank"), "type": a.get("type"),
                        "rr": (a.get("risk_reward") or {}).get("rr"),
                        "entry_ref": (a.get("risk_reward") or {}).get("entry_ref")},
            "registry_writer": REGISTRY_WRITER, "_plan_key": plan_key(sym, plan),
        }
        self.current[sym] = rid
        return rid

    def confirm_current(self, symbols: Iterable[str], at: datetime) -> list[str]:
        """Re-confirm the current plan of each symbol still in the latest projection (extends its TTL)."""
        out = []
        for s in symbols:
            rid = self.current.get(str(s).upper())
            if rid:
                r = self.recs[rid]
                r["last_seen_at"] = max(r["last_seen_at"], at)
                r["expires_at"] = r["last_seen_at"] + self.ttl
                out.append(rid)
        return out

    def rows(self, since: Optional[datetime] = None) -> list[dict[str, Any]]:
        """Recs active at or after ``since`` (all when None), without private keys."""
        out = []
        for r in self.recs.values():
            if since is not None and r["expires_at"] < since:
                continue
            out.append({k: v for k, v in r.items() if not k.startswith("_")})
        return out

    @classmethod
    def from_jsonl(cls, path: Path, ttl: timedelta = TTL["cio_opportunity"]) -> "OpportunityLineage":
        lin = cls(ttl=ttl)
        p = Path(path)
        if not p.exists():
            return lin
        with p.open(encoding="utf-8") as fh:
            for raw in fh:
                try:
                    lin.feed(json.loads(raw))
                except (ValueError, TypeError):
                    continue
        return lin


# ── DB-backed sources (pure row → rec mappers) ───────────────────────────────────────────────────────────────────
def proposal_rec(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    pid, sym = row.get("id"), str(row.get("symbol") or "").upper()
    created = _ts(row.get("recommendation_created_at")) or _ts(row.get("created_at"))
    if pid is None or not sym or created is None:
        return None
    entry = _f(row.get("final_entry")) if _f(row.get("final_entry")) is not None else _f(row.get("proposed_entry"))
    stop = _f(row.get("final_stop")) if _f(row.get("final_stop")) is not None else _f(row.get("proposed_stop"))
    tgt = _f(row.get("final_target1")) if _f(row.get("final_target1")) is not None else _f(row.get("proposed_target1"))
    exp = _ts(row.get("max_expires_at")) or _ts(row.get("expires_at")) or (created + TTL["paper_trade_proposal"])
    conv = next((_f(row.get(k)) for k in ("confidence_score", "signal_score", "research_score")
                 if _f(row.get(k)) is not None), None)
    return {
        "rec_id": rec_id_for("paper_trade_proposal", str(pid)), "source": "paper_trade_proposal",
        "source_table": "paper_trade_proposals", "source_id": str(pid), "symbol": sym,
        "direction": direction_of(row.get("side")), "entry_low": entry, "entry_high": entry,
        "plan_stop": stop, "plan_target": tgt, "created_at": created, "expires_at": max(exp, created),
        "last_seen_at": None, "superseded_at": None, "conviction_at_issue": conv,
        "conviction_scale": "proposal_score", "first_seen_run_id": None, "stance": row.get("cio_view"),
        "source_status": row.get("status"),
        "payload": {"proposed_by": row.get("proposed_by"), "origin": row.get("origin"),
                    "strategy_id": row.get("strategy_id")},
        "registry_writer": REGISTRY_WRITER,
    }


def scalp_rec(row: dict[str, Any], table: str) -> Optional[dict[str, Any]]:
    rid, sym = row.get("id"), str(row.get("symbol") or "").upper()
    at = _ts(row.get("scanned_at"))
    px = _f(row.get("price"))
    if rid is None or not sym or at is None or px is None:
        return None
    sid = f"{table}:{rid}"
    return {
        "rec_id": rec_id_for("scalp_alert", sid), "source": "scalp_alert", "source_table": table, "source_id": sid,
        "symbol": sym, "direction": "long", "entry_low": px, "entry_high": px, "plan_stop": None,
        "plan_target": None, "created_at": at, "expires_at": at + TTL["scalp_alert"], "last_seen_at": None,
        "superseded_at": None, "conviction_at_issue": _f(row.get("score")), "conviction_scale": "scalp_score",
        "first_seen_run_id": str(row.get("run_id")) if row.get("run_id") is not None else None,
        "stance": row.get("decision"), "source_status": row.get("grade"),
        "payload": {"source": row.get("source"), "run_type": row.get("run_type")}, "registry_writer": REGISTRY_WRITER,
    }


def alert_rec(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    uid, sym = row.get("alert_uid"), str(row.get("symbol") or "").upper()
    at = _ts(row.get("created_at"))
    pp = row.get("parsed_payload") or {}
    if isinstance(pp, str):
        try:
            pp = json.loads(pp)
        except ValueError:
            pp = {}
    px = _f(row.get("price")) if _f(row.get("price")) is not None else _f(pp.get("entry") or pp.get("entry_price"))
    if not uid or not sym or at is None or px is None or row.get("alert_type") not in ENTRY_ALERT_TYPES:
        return None
    lo = _f(pp.get("entry_low")) if _f(pp.get("entry_low")) is not None else px
    hi = _f(pp.get("entry_high")) if _f(pp.get("entry_high")) is not None else px
    stop = _f(row.get("stop_price")) if _f(row.get("stop_price")) is not None else _f(pp.get("plan_stop"))
    return {
        "rec_id": rec_id_for("entry_alert", str(uid)), "source": "entry_alert", "source_table": "alert_events",
        "source_id": str(uid), "symbol": sym, "direction": direction_of(pp.get("direction") or pp.get("side")),
        "entry_low": min(lo, hi), "entry_high": max(lo, hi), "plan_stop": stop,
        "plan_target": _f(pp.get("target") or pp.get("plan_target")), "created_at": at,
        "expires_at": at + TTL["entry_alert"], "last_seen_at": None, "superseded_at": None,
        "conviction_at_issue": _f(row.get("confidence")), "conviction_scale": "alert_confidence",
        "first_seen_run_id": None, "stance": row.get("decision"), "source_status": row.get("lifecycle_state"),
        "payload": {"alert_type": row.get("alert_type"), "source_script": row.get("source_script")},
        "registry_writer": REGISTRY_WRITER,
    }


# ── the writer (SAVEPOINT-guarded; never raises into the caller's transaction) ───────────────────────────────────
def _row_tuple(r: dict[str, Any]) -> tuple:
    vals = []
    for c in COLUMNS:
        v = r.get(c)
        if c == "payload":
            v = json.dumps(v or {}, default=str, sort_keys=True)
        vals.append(v)
    return tuple(vals)


UPSERT_SQL = (
    "INSERT INTO recommendation_registry (" + ", ".join(COLUMNS) + ") VALUES %s "
    "ON CONFLICT (rec_id) DO UPDATE SET "
    "expires_at = GREATEST(recommendation_registry.expires_at, EXCLUDED.expires_at), "
    "last_seen_at = GREATEST(recommendation_registry.last_seen_at, EXCLUDED.last_seen_at), "
    "superseded_at = COALESCE(recommendation_registry.superseded_at, EXCLUDED.superseded_at), "
    "stance = COALESCE(EXCLUDED.stance, recommendation_registry.stance), "
    "source_status = COALESCE(EXCLUDED.source_status, recommendation_registry.source_status), "
    "updated_at = now() "
    # a re-confirmation rewrites the row at most every 12 h (the curator runs every 30 min)
    "WHERE EXCLUDED.expires_at > recommendation_registry.expires_at + interval '12 hours' "
    "OR (recommendation_registry.superseded_at IS NULL AND EXCLUDED.superseded_at IS NOT NULL) "
    "OR recommendation_registry.source_status IS DISTINCT FROM COALESCE(EXCLUDED.source_status, "
    "recommendation_registry.source_status)"
)
# conviction_at_issue, created_at, levels and the natural key are written once, at issue, and never updated.
# A superseded opportunity's expiry is pulled in to the supersede time (it can only shrink there, never grow).
SUPERSEDE_SQL = ("UPDATE recommendation_registry SET expires_at = GREATEST(created_at, LEAST(expires_at, %s)), "
                 "updated_at = now() WHERE rec_id = %s AND superseded_at IS NOT NULL AND expires_at > %s")


def upsert_recs(cur, recs: list[dict[str, Any]], page_size: int = 500) -> dict[str, Any]:
    """Upsert recs inside a SAVEPOINT. Returns {status, written}; on any error (table absent before the migration)
    rolls back to the savepoint and returns status 'skipped' — the caller's transaction is untouched."""
    if not writes_enabled():
        return {"status": "disabled", "written": 0, "kill_switch": KILL_SWITCH_ENV}
    if not recs:
        return {"status": "ok", "written": 0}
    from psycopg2.extras import execute_values

    cur.execute("SAVEPOINT rec_registry_upsert")
    try:
        written = 0
        for i in range(0, len(recs), page_size):
            chunk = recs[i:i + page_size]
            execute_values(cur, UPSERT_SQL, [_row_tuple(r) for r in chunk], page_size=page_size)
            written += max(cur.rowcount, 0)
        for r in recs:
            if r.get("superseded_at") is not None:
                cur.execute(SUPERSEDE_SQL, (r["superseded_at"], r["rec_id"], r["superseded_at"]))
        cur.execute("RELEASE SAVEPOINT rec_registry_upsert")
        return {"status": "ok", "written": written, "offered": len(recs)}
    except Exception as e:  # noqa: BLE001 — the registry must never break the recommendation's own write
        cur.execute("ROLLBACK TO SAVEPOINT rec_registry_upsert")
        cur.execute("RELEASE SAVEPOINT rec_registry_upsert")
        return {"status": "skipped", "written": 0, "error": f"{type(e).__name__}: {str(e)[:200]}"}


def register_opportunities_after_curation(conn, event_path: Path, current_symbols: Iterable[str],
                                          changed_symbols: Iterable[str], at: Optional[datetime] = None
                                          ) -> dict[str, Any]:
    """Curator hook (scripts/cio_opportunity_curator.py --apply, after the version lines are appended).

    Rebuilds the plan lineage from the append-only history (so the rec_id is the same one the backfill computes),
    re-confirms every plan still in the projection, and upserts the recs of the symbols that changed this run plus
    every re-confirmed one. Commits its own work; never raises."""
    if not writes_enabled():
        return {"status": "disabled", "kill_switch": KILL_SWITCH_ENV}
    try:
        at = at or datetime.now(timezone.utc)
        lin = OpportunityLineage.from_jsonl(event_path)
        confirmed = set(lin.confirm_current(current_symbols, at))
        changed = {str(s).upper() for s in changed_symbols}
        recs = [r for r in lin.rows() if r["rec_id"] in confirmed or r["symbol"] in changed]
        with conn.cursor() as cur:
            res = upsert_recs(cur, recs)
        conn.commit()
        return {**res, "lineage_recs": len(lin.recs), "confirmed": len(confirmed)}
    except Exception as e:  # noqa: BLE001
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        return {"status": "error", "error": f"{type(e).__name__}: {str(e)[:200]}"}
