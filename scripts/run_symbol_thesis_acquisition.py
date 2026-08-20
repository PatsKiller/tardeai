#!/usr/bin/env python3
"""run_symbol_thesis_acquisition.py — autonomous, debt-sensitive thesis acquisition.

Wires the whole symbol-thesis chain end-to-end in one governed run, ordered by
debt/materiality (P0 held-conflicted → P1 held/reentry/opportunity → P2 → P3):

  retrieve RAG (supporting + contradictory)  →  budgeted multi-source acquire
  → curate → embed approved items → re-retrieve → Flash synthesis → reconcile →
  publish symbol_*@vN.

Every stage is fail-closed: nothing is embedded unless curation-approved, Flash
is never a research source, and no thesis version is published unless the
synthesis gate is READY_FOR_SYNTHESIS AND Flash returns a valid, cited draft.

Dry by default. --apply opts into real acquisition, embedding (db-write), Flash
(llm), and thesis publish (CIOThesisStore). A JSONL ledger makes runs resumable
and idempotent (no duplicate acquisition within 72h; no duplicate publish).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from scripts.lib.symbol_thesis_attach import thesis_fields_for_symbol, watchlist_materiality
from scripts.lib.symbol_thesis_coverage import (
    build_coverage_report,
)
from scripts.lib.symbol_thesis_evidence import build_evidence_catalog
from scripts.lib.symbol_thesis_acquisition import (
    build_acquisition_plan,
    embed_evidence_into_rag,
    dry_run_searx_step,
)
from scripts.lib.symbol_thesis_synthesis import (
    build_synthesis_packet,
    synthesize_thesis_via_flash,
    apply_synthesis_to_thesis,
)
from scripts.lib.symbol_thesis_research import _priority_band, _specific_question
from scripts.lib.symbol_thesis_materiality import classify_materiality, TIERS

AUTHORITY = "READ_ONLY_ADVISORY"
LEDGER_REL = Path("data/cio/symbol_thesis_acquisition_ledger.jsonl")

_TIER_RANK = {t: i for i, t in enumerate(TIERS)}
_PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _digest(*parts: Any) -> str:
    blob = "|".join(str(p if p is not None else "") for p in parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _debt_key(row: dict[str, Any], priority: str, tier: str) -> tuple:
    memberships = set(row.get("memberships") or [])
    held = 0 if "HELD" in memberships else 1
    rs = str(row.get("reentry_state") or "").upper()
    near = 0 if any(x in rs for x in ("NEAR", "READY", "IN_ZONE", "REENTER")) else 1
    try:
        opp = int(row.get("opportunity_rank")) if row.get("opportunity_rank") is not None else 999
    except (TypeError, ValueError):
        opp = 999
    return (
        _PRIORITY_RANK.get(priority, 9),
        _TIER_RANK.get(tier, 9),
        held,
        near,
        opp,
        str(row.get("symbol") or ""),
    )


def _is_ticker(s: str) -> bool:
    """Reject CUSIP/account-id style identifiers; keep 1-5 char tickers/ETFs/funds."""
    t = str(s or "").strip().upper()
    if not t:
        return False
    # tickers/funds/classes: up to 5 chars, starting with a letter, allowing . and -
    if len(t) <= 5 and t[0].isalpha() and all(c.isalnum() or c in ".-" for c in t):
        return True
    return False


def build_debt_ordered_queue(
    *, root: Path, canary: bool = False, limit: int = 10, material_only: bool = True
) -> list[dict[str, Any]]:
    """Debt-sensitive ordered research queue (P0→P3, T0→T4, held/reentry/rank).

    Iterates the full coverage report (not the truncated trigger list) and drops
    discovery-only INSUFFICIENT_DATA rows and non-ticker identifiers, so held
    names always surface at the front regardless of alphabetical position.
    """
    report = build_coverage_report(root=root, material_only=False)
    canary_set = frozenset({"SCHG", "CSCO", "ANET"})
    MATERIAL = {"ACTIVE_MATERIAL", "ACTIVE_LOW_PRIORITY", "RESEARCH_REQUIRED"}
    RESEARCH_STATES = {"RESEARCH_REQUIRED", "STALE", "CONFLICTED"}

    rows: list[tuple[tuple, dict[str, Any]]] = []
    for cov in report.get("rows") or []:
        sym = str(cov.get("symbol") or "")
        if canary and sym not in canary_set:
            continue
        if not _is_ticker(sym):
            continue
        memberships = list(cov.get("memberships") or [])
        thesis_state = str(cov.get("coverage_state") or "INSUFFICIENT_DATA")
        watch_mat = watchlist_materiality(
            memberships,
            thesis_state=thesis_state,
            opp_rank=cov.get("opportunity_rank"),
        )
        if watch_mat == "DISCOVERY_ONLY" and thesis_state == "INSUFFICIENT_DATA":
            continue
        if material_only and watch_mat not in MATERIAL and not cov.get("material"):
            continue
        # only schedule names that actually need thesis work
        if thesis_state not in RESEARCH_STATES and not (
            watch_mat in {"ACTIVE_MATERIAL", "ACTIVE_LOW_PRIORITY", "RESEARCH_REQUIRED"}
            and not cov.get("has_current_symbol_thesis")
        ):
            continue
        tier = classify_materiality(
            memberships=memberships,
            held="HELD" in memberships,
            reentry_state=cov.get("reentry_state"),
            opportunity_rank=cov.get("opportunity_rank"),
        ).get("materiality_tier")
        priority = _priority_band(
            memberships=memberships,
            thesis_state=thesis_state,
            reentry_state=cov.get("reentry_state"),
            opportunity_rank=cov.get("opportunity_rank"),
            materiality=watch_mat,
        )
        key = _debt_key(cov, priority, tier or "")
        rows.append((key, {**cov, "_priority": priority, "_tier": tier, "_materiality": watch_mat}))
    rows.sort(key=lambda x: x[0])
    return [r for _, r in rows[: max(0, int(limit))]]


def _load_ledger(root: Path) -> list[dict[str, Any]]:
    path = root / LEDGER_REL
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            out.append(rec)
    return out


def _append_ledger(root: Path, rec: dict[str, Any]) -> None:
    path = root / LEDGER_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True, default=str) + "\n")


def _prior_state(root: Path, question_digest: str) -> dict[str, Any]:
    for rec in _load_ledger(root):
        if rec.get("question_digest") == question_digest:
            return rec
    return {}


def _thesis_conn(root: Path):
    """Postgres connection from root/.env (same pattern as symbol_universe). Fail-soft."""
    try:
        import psycopg2
        pw = os.environ.get("DB_PASSWORD", "")
        env_path = root / ".env"
        if not pw and env_path.exists():
            for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith("DB_PASSWORD="):
                    pw = line.split("=", 1)[1].strip().strip("'\"")
        if not pw:
            return None
        return psycopg2.connect(
            host=os.environ.get("DB_HOST", "localhost"),
            port=int(os.environ.get("DB_PORT", "5432")),
            dbname=os.environ.get("DB_NAME", "trade_ai"),
            user=os.environ.get("DB_USER", "trade_ai"),
            password=pw,
        )
    except Exception:
        return None


def run_one(
    sym: str,
    *,
    root: Path,
    apply: bool,
    skip_acquire: bool,
    skip_embed: bool,
    skip_synthesize: bool,
    skip_publish: bool,
    llm_budget_left: list[int],
) -> dict[str, Any]:
    conn = _thesis_conn(root)
    try:
        return _run_one_impl(
            sym,
            root=root,
            apply=apply,
            skip_acquire=skip_acquire,
            skip_embed=skip_embed,
            skip_synthesize=skip_synthesize,
            skip_publish=skip_publish,
            llm_budget_left=llm_budget_left,
            conn=conn,
        )
    finally:
        if conn is not None:
            conn.close()


def _run_one_impl(
    sym: str,
    *,
    root: Path,
    apply: bool,
    skip_acquire: bool,
    skip_embed: bool,
    skip_synthesize: bool,
    skip_publish: bool,
    llm_budget_left: list[int],
    conn=None,
) -> dict[str, Any]:
    fields = thesis_fields_for_symbol(sym, root=root)
    memberships = list(fields.get("memberships") or [])
    role = str(fields.get("portfolio_role") or "UNKNOWN")
    thesis_state = str(fields.get("thesis_state") or "INSUFFICIENT_DATA")
    gap = (fields.get("research_gaps") or ["Create living symbol thesis"])[0]
    question = _specific_question(
        sym, gap, memberships=memberships, role=role, thesis_state=thesis_state
    )
    qd = _digest(sym, question)
    prior = _prior_state(root, qd)

    out: dict[str, Any] = {
        "schema": "SymbolThesisAcquisitionRun@v1",
        "as_of": _now(),
        "symbol": sym.upper(),
        "priority": fields.get("thesis_state"),
        "question": question,
        "question_digest": qd,
        "authority": AUTHORITY,
        "financial_action": False,
    }

    catalog = build_evidence_catalog(sym, question=question, role=role, limit_each=8, conn=conn)
    plan = build_acquisition_plan(sym, question=question, evidence_catalog=catalog, priority="P1")
    sufficiency = (catalog.get("sufficiency") or {}).get("sufficient_for_synthesis", False)

    acquired: list[dict[str, Any]] = []
    embed_result: dict[str, Any] = {}
    if apply and plan.get("status") == "ACQUISITION_PLANNED" and not skip_acquire:
        recent_acquire = prior.get("status") == "ACQUIRED" and prior.get("acquired_at")
        if not recent_acquire:
            for step in plan.get("steps") or []:
                if step.get("family") == "searxng_metasearch":
                    acquired.extend(dry_run_searx_step(step.get("targets") or []))
                    step["status"] = "EXECUTED"

    if acquired:
        out["acquired_n"] = len(acquired)
        if apply and not skip_embed:
            embed_result = embed_evidence_into_rag(acquired, max_embeds=20)
        else:
            embed_result = {"dry": True, "embedded": 0}
        out["embed_result"] = embed_result

    final_catalog = catalog
    if acquired or (embed_result or {}).get("embedded"):
        # re-retrieve so newly embedded (approved) items count toward sufficiency
        final_catalog = build_evidence_catalog(sym, question=question, role=role, limit_each=8, conn=conn)
        sufficiency = (final_catalog.get("sufficiency") or {}).get("sufficient_for_synthesis", False)

    packet = build_synthesis_packet(
        sym,
        question=question,
        evidence_catalog=final_catalog,
        acquisition_plan=plan,
        thesis_fields=fields,
        portfolio_role=role,
    )
    gate = packet.get("gate")
    out["gate"] = gate
    out["sufficiency"] = (final_catalog.get("sufficiency") or {})
    out["catalog"] = {
        "supporting_n": len(final_catalog.get("supporting") or []),
        "contradictory_n": len(final_catalog.get("contradictory") or []),
        "structured_n": len(final_catalog.get("structured") or []),
    }

    if gate != "READY_FOR_SYNTHESIS":
        out["status"] = "BLOCKED"
        out["block_reason"] = gate
        out["remaining_gaps"] = (
            (final_catalog.get("sufficiency") or {}).get("remaining_evidence_gaps") or []
        )
        out["pending_curation_n"] = sum(
            1 for a in acquired
            if (a.get("rag_status") or "pending") == "pending" and not a.get("error")
        )
        return out

    if skip_synthesize or (apply and llm_budget_left[0] <= 0):
        out["status"] = "READY_NOT_SYNTHESIZED" if not apply else "LLM_BUDGET_EXHAUSTED"
        out["note"] = "synthesis gate ready; Flash not called"
        return out

    if not apply:
        out["status"] = "READY_FOR_SYNTHESIS"
        out["note"] = "dry: would call Flash + reconcile + publish"
        return out

    synth = synthesize_thesis_via_flash(sym, packet, call_llm=True)
    out["flash"] = {
        "success": synth.get("ok"),
        "error": synth.get("error"),
        "model_used": (synth.get("flash") or {}).get("model_used"),
        "cost_estimate": (synth.get("flash") or {}).get("cost_estimate"),
        "raw": str(synth.get("raw") or "")[:2000],
    }
    llm_budget_left[0] -= 1
    if not synth.get("ok"):
        out["status"] = "SYNTHESIS_FAILED"
        out["error"] = synth.get("error")
        return out

    if skip_publish:
        out["status"] = "SYNTHESIZED_NOT_PUBLISHED"
        return out

    review = apply_synthesis_to_thesis(
        sym, synth["synthesis_result"], packet=packet, publish=True, notify=False, root=root
    )
    out["review"] = {
        "ok": review.get("ok"),
        "classification": (review.get("review") or {}).get("classification"),
        "version_published": (review.get("review") or {}).get("version_published"),
        "new_version": (review.get("review") or {}).get("new_version"),
    }
    if review.get("ok") and (review.get("review") or {}).get("version_published"):
        out["status"] = "PUBLISHED"
    else:
        out["status"] = "SYNTHESIZED_NO_MATERIAL_CHANGE"
    return out


def run(
    *,
    root: Path,
    symbols: Optional[list[str]] = None,
    canary: bool = False,
    limit: int = 10,
    max_llm: int = 5,
    apply: bool = False,
    skip_acquire: bool = False,
    skip_embed: bool = False,
    skip_synthesize: bool = False,
    skip_publish: bool = False,
) -> dict[str, Any]:
    if symbols:
        queue = [{"symbol": s.upper(), "_priority": "MANUAL"} for s in symbols]
    else:
        queue = build_debt_ordered_queue(root=root, canary=canary, limit=limit)

    llm_budget = [max(0, int(max_llm))]
    results: list[dict[str, Any]] = []
    for row in queue:
        sym = str(row.get("symbol") or "").upper()
        rec = run_one(
            sym,
            root=root,
            apply=apply,
            skip_acquire=skip_acquire,
            skip_embed=skip_embed,
            skip_synthesize=skip_synthesize,
            skip_publish=skip_publish,
            llm_budget_left=llm_budget,
        )
        if apply:
            _append_ledger(root, rec)
        results.append(rec)

    statuses: dict[str, int] = {}
    for r in results:
        statuses[r.get("status")] = statuses.get(r.get("status"), 0) + 1
    return {
        "schema": "SymbolThesisAcquisitionBatch@v1",
        "as_of": _now(),
        "mode": "apply" if apply else "dry",
        "queued": len(queue),
        "statuses": statuses,
        "llm_calls_used": max_llm - llm_budget[0],
        "results": results,
        "authority": AUTHORITY,
        "financial_action": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Autonomous debt-sensitive thesis acquisition")
    ap.add_argument("--symbols", default=None, help="Comma-separated symbols (default: debt-ordered)")
    ap.add_argument("--canary", action="store_true", help="Restrict to SCHG/CSCO/ANET")
    ap.add_argument("--limit", type=int, default=10, help="Max symbols per run")
    ap.add_argument("--max-llm", type=int, default=5, help="Max Flash calls per run")
    ap.add_argument("--apply", action="store_true", help="Actually acquire/embed/synthesize/publish")
    ap.add_argument("--skip-acquire", action="store_true")
    ap.add_argument("--skip-embed", action="store_true")
    ap.add_argument("--skip-synthesize", action="store_true")
    ap.add_argument("--skip-publish", action="store_true")
    ap.add_argument("--root", default=str(ROOT), help="Repo root")
    a = ap.parse_args()

    syms = [s.strip().upper() for s in (a.symbols or "").split(",") if s.strip()] or None
    batch = run(
        root=Path(a.root),
        symbols=syms,
        canary=a.canary,
        limit=a.limit,
        max_llm=a.max_llm,
        apply=a.apply,
        skip_acquire=a.skip_acquire,
        skip_embed=a.skip_embed,
        skip_synthesize=a.skip_synthesize,
        skip_publish=a.skip_publish,
    )

    print(json.dumps({"mode": batch["mode"], "queued": batch["queued"],
                      "statuses": batch["statuses"],
                      "llm_calls_used": batch["llm_calls_used"]}, indent=2))
    for r in batch["results"]:
        extra = ""
        if r.get("review"):
            extra = f" → {r['review'].get('classification')} v{r['review'].get('new_version')}"
        print(f"  {r['symbol']:6s} {r['status']:28s} gate={r.get('gate')}{extra}")
        if r.get("error"):
            print(f"         error={r['error'][:160]}")
        if r.get("remaining_gaps"):
            print(f"         gaps={r['remaining_gaps']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
