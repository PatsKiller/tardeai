#!/usr/bin/env python3
"""lesson_queue_cycle.py — the missing writer for the LQ-20261107-1884 promotion chain.

Before this lane the chain had a module and no writer: ``lesson_promotion.enqueue`` ran
exactly once (2026-09-28, manual), ``lesson_queue_hygiene --apply`` archived all 633 rows
once (2026-10-04, manual), and nothing scheduled either. ``lesson_promotions.jsonl`` was
frozen at PROMOTED 0; ``learning_promotion_decisions`` has never held a row.

One cycle, all of it append-only:

1. **link** — bind each lesson to the settled outcomes of its plan
   (``lesson_outcome_linkage``; provenance only, never evidence).
2. **enqueue** — queue P2-eligible lessons (>= 3 independent quality-checked outcomes),
   coalescing statement-hash duplicates so a rebuild cannot multiply the operator queue.
3. **digest** — the weekly ranked view of the queue (``lesson_promotion.weekly_digest``).
4. **package** — create ONE ApprovalPackage@v1 for the top QUEUED lessons, unless an
   un-decided lesson package is already open. This is the operator surface; the lane never
   approves its own items.
5. **consume** — for every item the OPERATOR approved in the approval ledger, transition
   the lesson with ``lesson_promotion.decide(..., by="operator:<who>")`` and record the
   decision in Postgres ``learning_promotion_decisions`` (``decision = promote_lesson``).
6. **receipt** — ``data/runtime/lesson-queue-cycle_last.json`` (json_key ok_at), the lane's
   output signal.

Promotion cannot be automatic. The only two routes to PROMOTED are (a) an operator
APPROVE on a package this lane created, and (b) an explicit ``--promote`` run carrying the
operator's own authorization in ``--by operator:...`` (the §17 act, recorded verbatim in
the row and in the DB decision payload). Nothing in this file promotes on its own.

    python3 scripts/lesson_queue_cycle.py                    # dry run
    python3 scripts/lesson_queue_cycle.py --apply            # one scheduled cycle
    python3 scripts/lesson_queue_cycle.py --promote top --by operator:name:typed \\
        --authorization "operator 2026-11-11 09:45 ET" --apply

AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0. No broker, no order, no live flag.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

SCHEMA = "LessonPromotionCycle@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
CAMPAIGN = "lesson-promotion"
WAVE = "P2"
MAX_PACKAGE_ITEMS = 10
RECEIPT_NAME = "lesson-queue-cycle_last.json"


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _lp():
    import lesson_promotion as lp  # type: ignore
    return lp


def _lol():
    import lesson_outcome_linkage as lol  # type: ignore
    return lol


def _loq():
    import lesson_outcome_quality as loq  # type: ignore
    return loq


def _ap():
    import approval_package as ap  # type: ignore
    return ap


def state_root(root: Path | None) -> Path:
    if root is not None:
        return Path(root)
    try:
        import canonical_store_registry as csr  # type: ignore
        return Path(csr.production_state_root())
    except Exception:  # noqa: BLE001
        return Path.home() / "trade-ai-releases" / "persistent-state"


def receipt_path(root: Path | None) -> Path:
    return state_root(root) / "data" / "runtime" / RECEIPT_NAME


def _env(root: Path | None) -> dict[str, str]:
    """Environment for this cycle. An explicit ``--root`` WINS over inherited state-root variables.

    Before this, ``setdefault`` honoured an ambient ``TRADEAI_STATE_ROOT`` (a test's hermetic
    empty root, or a staging root) and the approval package landed outside the requested root.
    """
    env = dict(os.environ)
    if root is not None:
        root = Path(root)
        env["TRADEAI_STATE_ROOT"] = str(root)
        env["TRADEAI_CIO_DIR"] = str(root / "data" / "cio")
        env["TRADEAI_GOVERNANCE_DIR"] = str(root / "data" / "governance")
    return env


# ── DB decision record ─────────────────────────────────────────────────────

def _conn_factory() -> Any:
    """The production connection the governance tables are written through."""
    try:
        import session13_db  # type: ignore
    except ImportError:
        from scripts import session13_db  # type: ignore
    return session13_db.get_conn()


def decision_exists(conn: Any, procedure_id: str) -> bool:
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM learning_promotion_decisions "
        "WHERE decision = %s AND decision_payload->>'procedure_id' = %s LIMIT 1",
        ["promote_lesson", procedure_id],
    )
    row = cur.fetchone()
    return bool(row)


def record_decision(conn: Any, *, procedure_id: str, decided_by: str, rationale: str,
                    payload: dict[str, Any]) -> str | None:
    """One learning_promotion_decisions row. Idempotent per procedure_id."""
    import learning_governance as lg  # type: ignore
    if decision_exists(conn, procedure_id):
        return None
    return lg.record_promotion_decision(
        conn,
        decision="promote_lesson",
        decided_by=decided_by,
        rationale=rationale,
        payload={"kind": "lesson_promotion", "procedure_id": procedure_id, **payload},
    )


# ── approval packages ──────────────────────────────────────────────────────

def _package_items(lp, queue_state: dict[str, dict], limit: int, price_on, daily_vol,
                   root: Path | None = None, env: dict | None = None) -> list[dict]:
    outcomes = lp.outcome_index(root, env)
    ranked = []
    for pid, row in queue_state.items():
        if row.get("status") != "QUEUED":
            continue
        v = lp.queue_verdict(row, outcomes, price_on=price_on, daily_vol=daily_vol)
        if not v.get("eligible"):
            continue
        ranked.append((v.get("independent", 0), pid, row))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    items = []
    for independent, pid, row in ranked[:limit]:
        items.append({
            "item_id": pid,
            "category": "OPERATOR",
            "title": f"PROMOTE {pid} [{row.get('source')}]: {str(row.get('statement') or '')[:160]}",
            "why": f"04 §5 procedural memory; P2 gate passed with {independent} independent quality-checked outcomes",
            "rule": "§17 operator ratifies; auto-promotion is blocked",
            "rollback": f"lesson_promotion_cli.py decide {pid} RETIRED --by operator:<name>",
            "scopes_needed": [],
            "reversible": True,
        })
    return items


def _open_lesson_package(led: Any) -> dict | None:
    seen = set()
    for row in led.rows():
        pid = row.get("package_id")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        pkg = led.package(pid)
        if pkg and pkg.get("campaign") == CAMPAIGN and pkg.get("state") in ("DRAFT", "SUBMITTED", "PARTIAL"):
            return pkg
    return None


def ensure_package(root: Path | None, env: dict, *, apply: bool, limit: int, price_on, daily_vol) -> dict:
    lp, ap = _lp(), _ap()
    led = ap.Ledger(ap.ledger_path(root, env))
    open_pkg = _open_lesson_package(led)
    if open_pkg:
        return {"created": False, "reason": "open_package", "package_id": open_pkg["package_id"],
                "state": open_pkg.get("state")}
    items = _package_items(lp, lp.state(root, env), limit, price_on, daily_vol, root, env)
    if not items:
        return {"created": False, "reason": "nothing_eligible", "items": 0}
    pkg = ap.new_package(CAMPAIGN, WAVE,
                         "Lessons that passed the operator-approved P2 gate and await an operator decision. "
                         "Approving an item promotes that lesson into advisory procedural memory; it never "
                         "becomes a behaviour field (MBI_BEHAVIOR = 0).",
                         items)
    if apply:
        led.append({"event": "PACKAGE_CREATED", "package_id": pkg["package_id"], "package": pkg})
    return {"created": bool(apply), "package_id": pkg["package_id"], "items": len(items),
            "state": pkg["state"], "dry_run": not apply}


def consume_approved(root: Path | None, env: dict, *, apply: bool, conn_factory: Callable[[], Any] | None = None) -> dict:
    """Promote every item the operator approved on a lesson-promotion package."""
    lp, ap = _lp(), _ap()
    led = ap.Ledger(ap.ledger_path(root, env))
    results: list[dict] = []
    errors: list[str] = []
    seen = set()
    queue_state = lp.state(root, env)
    for row in led.rows():
        pid = row.get("package_id")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        pkg = led.package(pid)
        if not pkg or pkg.get("campaign") != CAMPAIGN:
            continue
        for item in pkg.get("items") or []:
            if item.get("state") != "APPROVED":
                continue
            proc = str(item.get("item_id") or "")
            cur = queue_state.get(proc)
            if not cur:
                results.append({"procedure_id": proc, "result": "not_on_queue"})
                continue
            if cur.get("status") == "PROMOTED":
                results.append({"procedure_id": proc, "result": "already_promoted"})
                continue
            decided_by = "operator:" + str((item.get("decided_by") or {}).get("who") or "unknown") + ":package"
            if not apply:
                results.append({"procedure_id": proc, "result": "would_promote", "package_id": pid})
                continue
            try:
                lp.decide(proc, "PROMOTED", by=decided_by,
                          reason=f"operator APPROVED {pid} item {item.get('item_no')}", root=root, env=env)
                dec_id = None
                if conn_factory is not None:
                    conn = conn_factory()
                    try:
                        dec_id = record_decision(conn, procedure_id=proc, decided_by=decided_by,
                                                 rationale=f"operator APPROVED {pid} item {item.get('item_no')}",
                                                 payload={"package_id": pid, "item_no": item.get("item_no"),
                                                          "source": cur.get("source"), "statement": cur.get("statement"),
                                                          "supporting_outcome_ids": (cur.get("evidence") or {}).get("supporting_outcome_ids")})
                    finally:
                        try:
                            conn.close()
                        except Exception:  # noqa: BLE001
                            pass
                led.append({"event": "NOTE", "package_id": pid, "item_no": item.get("item_no"),
                            "note": f"EXECUTED procedure_id={proc} decision_id={dec_id or 'existing'}",
                            "decided_by": decided_by})
                results.append({"procedure_id": proc, "result": "promoted", "package_id": pid, "decision_id": dec_id})
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{proc}: {type(exc).__name__}: {exc}")
                results.append({"procedure_id": proc, "result": "error", "error": str(exc)[:200]})
    return {"promoted": sum(1 for r in results if r["result"] == "promoted"),
            "would_promote": sum(1 for r in results if r["result"] == "would_promote"),
            "results": results, "errors": errors}


# ── the two operator-authorized acts ───────────────────────────────────────

def promote_one(root: Path | None, env: dict, *, procedure_id: str, by: str, reason: str,
                authorization: str, apply: bool, price_on, daily_vol,
                conn_factory: Callable[[], Any] | None = None) -> dict:
    """Promote ONE lesson under the operator's explicit instruction (the §17 act)."""
    lp = _lp()
    if not str(by).startswith("operator:"):
        raise PermissionError("--by must be operator:<name>:<via>; a peer or an agent is never the operator")
    cur_state = lp.state(root, env)
    pid = procedure_id
    if procedure_id == "top":
        candidates = _package_items(lp, cur_state, 1, price_on, daily_vol, root, env)
        if not candidates:
            raise RuntimeError("no QUEUED lesson passes the P2 gate; nothing to promote")
        pid = candidates[0]["item_id"]
    row = cur_state.get(pid)
    if row is None:
        raise KeyError(f"{pid} is not on the promotion queue")
    if row.get("status") == "PROMOTED":
        return {"procedure_id": pid, "result": "already_promoted", "status": "PROMOTED"}
    if not apply:
        return {"procedure_id": pid, "result": "would_promote", "status": row.get("status"),
                "statement": row.get("statement"), "authorization": authorization}
    dec_id = None
    if conn_factory is not None:
        conn = conn_factory()
        try:
            dec_id = record_decision(conn, procedure_id=pid, decided_by=by,
                                     rationale=f"{reason} | authorization: {authorization}",
                                     payload={"authorization": authorization, "reason": reason,
                                              "source": row.get("source"), "statement": row.get("statement"),
                                              "supporting_outcome_ids": (row.get("evidence") or {}).get("supporting_outcome_ids")})
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
    row = lp.decide(pid, "PROMOTED", by=by, reason=f"{reason} | authorization: {authorization}", root=root, env=env)
    return {"procedure_id": pid, "result": "promoted", "status": "PROMOTED", "decision_id": dec_id,
            "decided_by": by, "authorization": authorization}


# ── one cycle ──────────────────────────────────────────────────────────────

_UNSET = object()


def run_cycle(root: Path | None = None, *, apply: bool = False, package_limit: int = MAX_PACKAGE_ITEMS,
              conn_factory: Callable[[], Any] | None = None,
              price_on: Any = _UNSET, daily_vol: Any = _UNSET) -> dict:
    env = _env(root)
    lp, lol, loq = _lp(), _lol(), _loq()
    started = _now_iso()
    if price_on is _UNSET and daily_vol is _UNSET:
        price_on, daily_vol = loq.default_lookups()
    result: dict[str, Any] = {
        "schema": SCHEMA, "authority": AUTHORITY, "financial_action": False,
        "memory_behavior_influence": 0, "applied": bool(apply), "started_at": started,
        "price_checks": "LIVE" if price_on else "UNAVAILABLE (quality checks fail closed)",
        "root": str(state_root(root)), "errors": [],
    }
    try:
        result["links"] = lol.apply(root, env, apply=apply)
        result["enqueue"] = lp.enqueue(root, env, apply=apply, price_on=price_on, daily_vol=daily_vol)
        digest = lp.weekly_digest(root, env, price_on=price_on, daily_vol=daily_vol)
        result["digest"] = {"eligible_total": digest.get("eligible_total"),
                            "status_counts": digest.get("status_counts")}
        result["package"] = ensure_package(root, env, apply=apply, limit=package_limit,
                                           price_on=price_on, daily_vol=daily_vol)
        if apply:
            result["consume"] = consume_approved(root, env, apply=True, conn_factory=conn_factory)
        else:
            result["consume"] = consume_approved(root, env, apply=False)
        st = lp.state(root, env)
        cons = result.get("consume") or {}
        result["errors"].extend(cons.get("errors") or [])
        result["state"] = {
            "queued": sum(1 for r in st.values() if r.get("status") == "QUEUED"),
            "promoted": sum(1 for r in st.values() if r.get("status") == "PROMOTED"),
            "archived": sum(1 for r in st.values() if r.get("status") == "ARCHIVED"),
            "total": len(st),
        }
        result["ok"] = not result["errors"]
        result["ok_at"] = _now_iso()
    except Exception as exc:  # noqa: BLE001
        result["ok"] = False
        result["ok_at"] = _now_iso()
        result["errors"].append(f"{type(exc).__name__}: {exc}")
        result["traceback"] = traceback.format_exc()[-2000:]
    if apply:
        path = receipt_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=1, sort_keys=True, default=str)
            fh.write("\n")
        result["receipt_path"] = str(path)
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--dry-run", action="store_true",
                    help="explicit dry run (the allowlist's dry_run_arg; the default when --apply is absent)")
    ap.add_argument("--root", help="state root containing data/cio (default: production persistent-state)")
    ap.add_argument("--max-package-items", type=int, default=MAX_PACKAGE_ITEMS)
    ap.add_argument("--promote", help="procedure_id to promote, or 'top' for the strongest P2 lesson")
    ap.add_argument("--by", default="", help="operator:<name>:<via> — required with --promote")
    ap.add_argument("--reason", default="operator-directed single-lesson promotion")
    ap.add_argument("--authorization", default="", help="the operator instruction this act cites")
    ap.add_argument("--no-db", action="store_true", help="skip the learning_promotion_decisions write (tests)")
    a = ap.parse_args(argv)
    cf: Callable[[], Any] | None = None if a.no_db else _conn_factory
    if a.no_db:
        cf = None
    try:
        if a.promote:
            env = _env(Path(a.root) if a.root else None)
            price_on, daily_vol = _loq().default_lookups()
            out = promote_one(Path(a.root) if a.root else None, env, procedure_id=a.promote,
                              by=a.by, reason=a.reason, authorization=a.authorization,
                              apply=a.apply, price_on=price_on, daily_vol=daily_vol,
                              conn_factory=cf)
        else:
            out = run_cycle(Path(a.root) if a.root else None, apply=a.apply,
                            package_limit=a.max_package_items, conn_factory=cf)
    except (PermissionError, KeyError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__, "detail": str(exc)}))
        return 2
    print(json.dumps(out, indent=1, sort_keys=True, default=str))
    return 0 if out.get("ok", True) and not out.get("errors") else 1


if __name__ == "__main__":
    sys.exit(main())
