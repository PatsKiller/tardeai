"""Release Train v2 open-PR census: every open PR in exactly one timestamped bucket (Phase 1, 2026-10-21).

Source: the PR-hygiene lane receipt ``<state root>/data/runtime/pr-hygiene-audit_last.json`` (LaneRunReceipt whose
``summary`` is ``PrHygieneAudit@v1``, written by ``scripts/pr_hygiene_audit.py``). Each row of ``summary.prs[]``
carries number, head, base, draft, holds, conflict and required_checks.status. This module only reads the receipt.

Enhanced design section 4: "Account for every open PR in mutually exclusive timestamped census buckets, including
unqueued, held and internal train PRs. Incomplete pagination or a changing snapshot is marked incomplete, not
reported as an exact total."

* A PR lands in the FIRST bucket of ``PRECEDENCE`` whose condition it meets, so the buckets are mutually exclusive by
  construction.
* The invariant is ``open_prs == sum(bucket counts)``. The census is COMPLETE only when the invariant holds, every row
  has a number, no number repeats, the row count equals ``open_prs``, the open count is below the lister's page cap,
  and the run that wrote the receipt succeeded. Otherwise it is INCOMPLETE and says why.
* No receipt, or an unreadable one, is UNAVAILABLE: ``value`` None, never an empty census or zero PRs.

Consumer: ``scripts/lib/release_train_view.py`` (summary ``census`` field and the ``/queue`` census).
AUTHORITY: READ_ONLY_ADVISORY. MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

LANE_ID = "pr-hygiene-audit"
SUMMARY_SCHEMA = "PrHygieneAudit@v1"
PAGE_CAP = 500            # pr_hygiene_audit.list_open_prs: gh pr list --limit 500
STALE_AFTER_HOURS = 36.0  # matches needs_action's pr_hygiene staleness rule

PRECEDENCE = ("train_internal", "queued", "draft", "held", "stacked", "conflicting", "mergeability_unknown",
              "checks_failing", "checks_pending", "checks_unknown", "unqueued_clean")


def bucket_of(pr: Mapping[str, Any], queued: Optional[set] = None) -> str:
    """The one bucket for one ``summary.prs[]`` row. Pure."""
    rc = pr.get("required_checks") if isinstance(pr.get("required_checks"), Mapping) else {}
    status = str((rc or {}).get("status") or "UNKNOWN").upper()
    if str(pr.get("head") or "").startswith("train/"):
        return "train_internal"
    if queued is not None and pr.get("number") in queued:
        return "queued"
    if pr.get("draft"):
        return "draft"
    if pr.get("holds"):
        return "held"
    if (pr.get("base") or "main") != "main":
        return "stacked"
    if pr.get("conflict") is True:
        return "conflicting"
    if pr.get("conflict") is None:
        return "mergeability_unknown"
    if status == "FAIL":
        return "checks_failing"
    if status == "PENDING":
        return "checks_pending"
    if status != "PASS":
        return "checks_unknown"
    return "unqueued_clean"


def build_census(summary: Mapping[str, Any], *, receipt_status: str = "ok", queued: Optional[Iterable[int]] = None,
                 page_cap: int = PAGE_CAP) -> dict[str, Any]:
    """Bucket a PrHygieneAudit@v1 summary. ``queued`` is the set of PR numbers in ``release_queue`` (None when the
    store is unreadable: then the ``queued`` bucket stays empty and ``queue_membership`` says UNAVAILABLE)."""
    as_of = summary.get("as_of")
    rows = summary.get("prs") if isinstance(summary.get("prs"), list) else []
    open_prs = summary.get("open_prs")
    qset = set(queued) if queued is not None else None
    buckets: dict[str, list[int]] = {b: [] for b in PRECEDENCE}
    reasons: list[str] = []
    seen: set = set()
    for pr in rows:
        if not isinstance(pr, Mapping) or not isinstance(pr.get("number"), int):
            if "row_without_number" not in reasons:
                reasons.append("row_without_number")
            continue
        n = pr["number"]
        if n in seen:
            if "duplicate_pr_rows" not in reasons:
                reasons.append("duplicate_pr_rows")
            continue
        seen.add(n)
        buckets[bucket_of(pr, qset)].append(n)
    total = sum(len(v) for v in buckets.values())
    if not isinstance(open_prs, int):
        reasons.append("open_prs_missing")
    else:
        if open_prs != total:
            reasons.append("invariant_mismatch")
        if len(rows) != open_prs:
            reasons.append("row_count_mismatch")
        if open_prs >= page_cap:
            reasons.append("possible_truncation")
    if str(receipt_status).lower() != "ok":
        reasons.append("last_run_failed")
    if summary.get("schema") != SUMMARY_SCHEMA:
        reasons.append("unexpected_summary_schema")
    holds = isinstance(open_prs, int) and open_prs == total
    return {
        "status": "COMPLETE" if not reasons else "INCOMPLETE",
        "open_prs": open_prs if isinstance(open_prs, int) else None,
        "bucket_total": total,
        "invariant": "open_prs == sum(buckets)",
        "invariant_holds": holds,
        "incomplete_reasons": reasons,
        "precedence": list(PRECEDENCE),
        "buckets": [{"name": b, "count": len(buckets[b]), "prs": sorted(buckets[b]), "as_of": as_of}
                    for b in PRECEDENCE],
        "queue_membership": "OK" if qset is not None else "UNAVAILABLE",
    }


def _parse(ts: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else None


def default_receipt_path() -> Path:
    try:
        from lib.lane_last_receipt import receipt_path
    except ImportError:  # pragma: no cover - repo root on sys.path instead of scripts/
        from scripts.lib.lane_last_receipt import receipt_path  # type: ignore[no-redef]
    return receipt_path(LANE_ID)


def load_census(path: Optional[Path] = None, *, queued: Optional[Iterable[int]] = None,
                now: Optional[datetime] = None, stale_after_hours: float = STALE_AFTER_HOURS,
                page_cap: int = PAGE_CAP) -> dict[str, Any]:
    """The census as a ``Field`` envelope (docs/ops/RELEASE_TRAIN_API.md section 2). Never raises."""
    now = now or datetime.now(timezone.utc)
    src = f"receipt:{LANE_ID}"
    try:
        p = Path(path) if path is not None else default_receipt_path()
    except Exception as exc:  # noqa: BLE001
        return {"value": None, "as_of": None, "freshness": "UNAVAILABLE", "source": src,
                "reason": f"error:{type(exc).__name__}"}
    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"value": None, "as_of": None, "freshness": "UNAVAILABLE", "source": src, "reason": "no_receipt"}
    except OSError:
        return {"value": None, "as_of": None, "freshness": "UNAVAILABLE", "source": src,
                "reason": "receipt_unreadable"}
    try:
        doc = json.loads(raw)
    except ValueError:
        doc = None
    if not isinstance(doc, Mapping):
        return {"value": None, "as_of": None, "freshness": "UNAVAILABLE", "source": src,
                "reason": "receipt_unreadable"}
    summary = doc.get("summary")
    if not isinstance(summary, Mapping) or "prs" not in summary:
        reason = "last_run_failed" if str(doc.get("status")) != "ok" else "receipt_has_no_census"
        return {"value": None, "as_of": doc.get("ok_at"), "freshness": "UNAVAILABLE", "source": src,
                "reason": reason}
    census = build_census(summary, receipt_status=str(doc.get("status") or ""), queued=queued, page_cap=page_cap)
    census["receipt"] = {"path": str(p), "lane_id": LANE_ID, "status": doc.get("status"),
                         "finished_at": doc.get("finished_at"), "summary_schema": summary.get("schema"),
                         "queue_membership": census.pop("queue_membership")}
    as_of = summary.get("as_of")
    ts = _parse(as_of)
    if ts is None:
        return {"value": census, "as_of": None, "freshness": "STALE", "source": src, "reason": "receipt_without_as_of"}
    age_h = (now - ts).total_seconds() / 3600.0
    if age_h > stale_after_hours:
        return {"value": census, "as_of": ts.isoformat(), "freshness": "STALE", "source": src,
                "reason": f"census older than {stale_after_hours:g} h ({age_h:.1f} h)"}
    return {"value": census, "as_of": ts.isoformat(), "freshness": "OK", "source": src,
            "reason": None if census["status"] == "COMPLETE" else "incomplete:" + ",".join(
                census["incomplete_reasons"])}
