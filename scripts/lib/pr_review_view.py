"""Approvals → Merges read model (Design approvals-pr-review/v001). No GitHub call, no model call, no write.

``merge_items`` turns the reviewer's store (scripts/lib/pr_review.py) and its open-PR snapshot into one ``MERGE``
approval item per PR, id ``pr:<N>``, for the existing queue projection (scripts/lib/operator_approvals.py). The
item's ``document_sha`` is the review's ``document_sha`` when the review is of the PR's current head, so a new push
changes what the ledger binds and cancels any earlier approval of the old head. ``summary`` is the Merges strip.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from scripts.lib import operator_approvals as core
from scripts.lib import pr_review as R

#: The snapshot is rewritten every 5 minutes by the reviewer timer; older than this is a source gap.
SNAPSHOT_MAX_AGE = timedelta(minutes=30)
APPLIER_MODULE = "scripts/lib/pr_review_apply.py"


def _store(state_root: Path, cfg: Mapping[str, Any], root: Path) -> R.Store:
    return R.Store(R.store_dir(state_root, cfg), approved=lambda: R.registry_store_approved(root, cfg))


def refusal(rec: Optional[dict], head: str, state: str, checks_green: bool) -> Optional[str]:
    if rec is None or rec.get("head_sha") != head:
        return "REVIEW_STALE" if rec is not None else "REVIEW_REQUIRED"
    if state == "cannot":
        return "REVIEW_CANNOT_REVIEW"
    if not checks_green:
        return "CHECKS_NOT_GREEN"
    return None


def review_view(rec: Optional[dict], snap: Mapping[str, Any], status: Optional[dict]) -> dict:
    head = str(snap.get("head_sha") or "")
    state = R.row_state(rec, status, head)
    view: dict[str, Any] = {"pr": snap["pr"], "title": snap.get("title"), "url": snap.get("url"), "current_head": head,
                            "labels": snap.get("labels") or [], "checks": snap.get("checks") or {},
                            "checks_green": bool(snap.get("checks_green")), "pill": R.pill(state, rec),
                            "stale": bool(rec) and rec.get("head_sha") != head,
                            "queue": status if status and status.get("head_sha") == head else None,
                            "approve_all": dict(zip(("eligible", "reason"), R.approve_all_eligible(rec, head))),
                            "review": rec}
    return view


def merge_items(*, state_root: Path, root: Path, code_sha: str, cfg: Mapping[str, Any] | None = None,
                now: Optional[datetime] = None) -> dict:
    cfg = cfg or R.load_config()
    now = now or R.utc_now()
    store = _store(state_root, cfg, root)
    snap = store.snapshot()
    if snap is None:
        # No snapshot: the reviewer has not run (its store is not yet approved, D5). Nothing to list, not a failure;
        # the Merges strip says so (summary.store_approved).
        return {"rows": [], "gap": "PR review snapshot unavailable" if store.approved() else None}
    as_of = R.parse_iso(snap.get("as_of"))
    gap = None if as_of and now - as_of <= SNAPSHOT_MAX_AGE else "PR review snapshot is stale"
    rows = []
    for pr in snap.get("prs") or []:
        if pr.get("draft"):
            continue
        n, head = int(pr["pr"]), str(pr.get("head_sha") or "")
        rec, status = store.latest(n), store.status(n)
        if rec is None and status is None and not pr.get("checks_green"):
            continue  # never reached READY: not waiting on the operator
        view = review_view(rec, pr, status)
        fresh = rec is not None and rec.get("head_sha") == head
        findings = (rec or {}).get("findings") or []
        changes = [{"id": f"finding_{f['id']}", "section": f["severity"], "before": "", "after": f["title"],
                    "kind": "added", "plain": None, "reason": None} for f in findings] if fresh else []
        doc_sha = rec["document_sha"] if fresh else core.digest({"pr": n, "head_sha": head, "state": view["pill"]["state"]})
        doc = {"text": "", "base_text": "", "source_sha": head if core.SHA.fullmatch(head) else "0" * 40,
               "version": f"PR #{n} · head {head[:9]}", "document_sha": doc_sha, "changes": changes, "sections": [],
               "source_verified": True,
               "prechecks": {"sensitive_sections": [], "removed_blocks": 0, "weakens_rules": "NOT_ASSESSED",
                             "policy_tests": {"state": "UNKNOWN", "reason": "See the review's checks"}},
               "review": view}
        author = (rec or {}).get("author") or {}
        it = core.item(ident=f"pr:{n}", kind="MERGE", title=str(pr.get("title") or f"PR #{n}"),
                       proposed_by=" · ".join(x for x in (author.get("vendor"), author.get("session")) if x) or None,
                       created_at=pr.get("created_at"), doc=doc, source="pr_reviews", pr=n,
                       source_refs=[f"github_pr:{n}"])
        held = bool(((rec or {}).get("classes") or {}).get("held"))
        it["merge"] = {"head_sha": head, "held": held, "reviewed": fresh, "stale": view["stale"],
                       "state": view["pill"]["state"],
                       "refusal": refusal(rec, head, view["pill"]["state"], bool(pr.get("checks_green")))}
        it["pill"] = view["pill"]
        it["summary"] = (rec or {}).get("summary") if fresh else None
        it["head_sha"] = head
        it["checks_green"] = bool(pr.get("checks_green"))
        it["checks"] = pr.get("checks") or {}
        it["classes"] = (rec or {}).get("classes") or {"held": [], "shared_infra": "shared-infra" in (pr.get("labels") or [])}
        rows.append(it)
    return {"rows": rows, "gap": gap}


def summary(*, state_root: Path, root: Path, items: list[dict], cfg: Mapping[str, Any] | None = None,
            decisions_approved: Callable[[], bool] = lambda: False, now: Optional[datetime] = None) -> dict:
    cfg = cfg or R.load_config()
    now = now or R.utc_now()
    store = _store(state_root, cfg, root)
    spend = R.spend_today(store.spend(), now)
    snap = store.snapshot() or {}
    counts = {"ready": 0, "held": 0, "rereviewing": 0, "waiting_credit": 0, "cannot": 0, "hold": 0}
    key = {"ready": "ready", "notes": "ready", "held": "held", "stale": "rereviewing", "credit": "waiting_credit",
           "cannot": "cannot", "hold": "hold"}
    for it in items:
        counts[key[it["merge"]["state"]]] += 1
    digest = {"last_sent_at": None, "next_at": None}
    try:
        from scripts.lib import pr_merge_digest as pmd
        sent = [r for r in pmd.load_digests() if (r.get("delivery") or {}).get("accepted")]
        if sent:
            digest["last_sent_at"] = core.iso(datetime.fromtimestamp(float(sent[-1]["created_at"]), tz=timezone.utc))
        digest["next_at"] = pmd.next_digest_at(now)
    except Exception:  # noqa: BLE001 - the strip says "unknown" rather than inventing a time
        pass
    b = cfg.get("budget") or {}
    return {"store_approved": store.approved(), "decisions_store_approved": bool(decisions_approved()),
            "label_applier_live": (root / APPLIER_MODULE).is_file(),
            "snapshot_as_of": snap.get("as_of"), "counts": counts, "digest": digest,
            "spend": {"usd_today": round(spend["usd"], 2), "cap_usd": b.get("combined_daily_cost_cap_usd"),
                      "reviews_today": spend["reviews"], "max_reviews_per_day": b.get("max_reviews_per_day"),
                      "questions_today": spend["questions"]},
            "models": cfg.get("models"), "commit_status_context": (cfg.get("commit_status") or {}).get("context"),
            "as_of": core.iso(now)}


def thread(*, state_root: Path, root: Path, pr: int, ledger_rows: list[dict], cfg: Mapping[str, Any] | None = None) -> dict:
    """The sheet's Ask and decision history for one PR: QUESTION rows with the reviewer's answers, DECIDED rows."""
    cfg = cfg or R.load_config()
    answers = {a.get("question_hash"): a for a in _store(state_root, cfg, root).answers()}
    ident = f"pr:{int(pr)}"
    mine = [r for r in ledger_rows if r.get("item_id") == ident]
    questions = [{"at": r.get("at"), "question": r.get("question"), "head_sha": r.get("source_sha"),
                  "answer": (answers.get(r.get("hash_self")) or {}).get("answer"),
                  "answered_at": (answers.get(r.get("hash_self")) or {}).get("at"),
                  "cost_usd": (answers.get(r.get("hash_self")) or {}).get("cost_usd")}
                 for r in mine if r.get("event") == "QUESTION"]
    decisions = [{k: r.get(k) for k in ("at", "decision", "effect", "head_sha", "source_sha", "document_sha", "actor", "comment")}
                 for r in mine if r.get("event") == "DECIDED"]
    return {"questions": questions[-20:], "decisions": decisions[-20:]}
