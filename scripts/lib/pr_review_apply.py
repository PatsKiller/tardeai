"""pr_review_apply — the host applier for "Approve merge" in the Command Center review sheet (approvals-pr-review/v001).

HELD CLASS (merge_deploy_control, config/merge_hold_paths.json): it adds the ``operator-merge`` label, so it merges
only by the operator's own merge (AGENTS.md §25.10).

Runs inside the digest reconcile timer (scripts/lib/pr_merge_digest.reconcile, every 3 min). For each new
``DECIDED`` row in the operator decisions ledger with kind ``MERGE``, decision ``APPROVE`` and effect
``OPERATOR_MERGE_LABEL`` (the operator's authenticated tailnet decision, never an agent's), it checks that:
  - the PR is open and not a draft;
  - its current head equals the head the operator approved (the ledger row's ``head_sha``);
  - it is not held (config/merge_hold_paths.json paths or a hold label) — held PRs are the operator's own merge (D6);
  - the four required checks are green on that head;
then calls the same label function ``settle_approve_all`` uses and writes ``PrMergeHeadBinding@v1`` with
``source: "cc_review"`` and the ledger row hash. Any failed check writes an outcome row instead (the sheet shows it,
e.g. "head moved"). Each ledger row is applied at most once. Never merges, pushes or promotes. ``MBI_BEHAVIOR = 0``.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable, Optional

try:
    from scripts.lib import merge_hold_paths as mhp
    from scripts.lib import pr_merge_telegram as pmt
except ImportError:  # pragma: no cover — run from scripts/
    from lib import merge_hold_paths as mhp  # type: ignore
    from lib import pr_merge_telegram as pmt  # type: ignore

BINDING_SCHEMA = "PrMergeHeadBinding@v1"
SOURCE = "cc_review"


def outcomes_path() -> Path:
    return pmt.store_dir() / "cc_review_applied.jsonl"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _append(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def ledger_rows() -> list[dict[str, Any]]:
    from scripts.lib import operator_approvals as oa
    from scripts.lib.approval_package import governance_dir
    return oa.DecisionLedger(governance_dir() / "operator_decisions.jsonl", approved=lambda: False).rows()


def pending(rows: list[dict[str, Any]], done: set[str]) -> list[dict[str, Any]]:
    return [r for r in rows if r.get("event") == "DECIDED" and r.get("kind") == "MERGE" and r.get("decision") == "APPROVE"
            and r.get("effect") == "OPERATOR_MERGE_LABEL" and str(r.get("actor", "")).startswith("tailnet:")
            and r.get("hash_self") and r["hash_self"] not in done]


def bindings() -> dict[int, dict[str, Any]]:
    """Latest labelled cc_review head per PR, for pr_merge_digest.approved_bindings."""
    out: dict[int, dict[str, Any]] = {}
    for r in _read_jsonl(outcomes_path()):
        if r.get("outcome") == "labeled":
            out[int(r["pr"])] = {"head_sha": str(r.get("head_sha") or ""), "at": str(r.get("at") or ""),
                                 "source": f"{SOURCE}:{str(r.get('ledger_hash') or '')[:12]}"}
    return out


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _view(repo: str, pr: int) -> dict[str, Any]:
    import subprocess
    p = subprocess.run(["gh", "pr", "view", str(int(pr)), "--repo", repo, "--json",
                        "number,state,headRefOid,isDraft,labels,files,changedFiles,statusCheckRollup"],
                       capture_output=True, text=True, timeout=90, check=False)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout).strip()[:200])
    return json.loads(p.stdout or "{}")


def check(view: dict[str, Any], row: dict[str, Any], *, all_files: Callable[[int], list[str]] | None = None) -> Optional[str]:
    """None when the label may be added for this ledger row; else the reason shown in the sheet."""
    from scripts.lib import pr_review as R
    if str(view.get("state") or "").upper() != "OPEN":
        return "PR is not open"
    if view.get("isDraft"):
        return "PR is a draft"
    if str(view.get("headRefOid") or "") != str(row.get("head_sha") or ""):
        return "head moved"
    files = [str(f.get("path") if isinstance(f, dict) else f) for f in view.get("files") or []]
    if int(view.get("changedFiles") or len(files)) > len(files):
        files = all_files(int(row["pr"])) if all_files else []
        if not files:
            return "file list unverified"
    if mhp.held_classes(files) or (pmt.label_names(view) & mhp.hold_labels()):
        return "held: the operator's own merge"
    green, _ = R.check_states(view.get("statusCheckRollup"))
    if not green:
        return "required checks not green"
    return None


def run(*, repo: str = pmt.DEFAULT_REPO, apply: bool, rows: list[dict[str, Any]] | None = None,
        view: Callable[[str, int], dict[str, Any]] = _view, add_label: Callable[..., dict[str, Any]] | None = None,
        all_files: Callable[[int], list[str]] | None = None) -> list[dict[str, Any]]:
    add_label = add_label or pmt.add_operator_merge_label
    done = {str(r.get("ledger_hash")) for r in _read_jsonl(outcomes_path())}
    results = []
    for r in pending(rows if rows is not None else ledger_rows(), done):
        pr = int(r.get("pr") or str(r.get("item_id", "pr:0")).split(":", 1)[1])
        out = {"schema": BINDING_SCHEMA, "source": SOURCE, "pr": pr, "head_sha": r.get("head_sha"),
               "ledger_hash": r["hash_self"], "actor": r.get("actor"), "decided_at": r.get("at"), "at": _now_iso()}
        try:
            reason = check(view(repo, pr), {**r, "pr": pr}, all_files=all_files)
        except Exception as exc:  # noqa: BLE001 - a failed view is an outcome, retried next cycle (not recorded)
            results.append({**out, "outcome": "view_failed", "reason": str(exc)[:200]})
            continue
        if reason:
            out.update(outcome="refused", reason=reason)
        elif not apply:
            out.update(outcome="would_label")
        else:
            res = add_label(pr, repo=repo)
            out.update(outcome="labeled" if res.get("ok") else "label_failed", reason=None if res.get("ok") else str(res)[:200])
        if apply and out["outcome"] != "label_failed":
            _append(outcomes_path(), out)
        results.append(out)
    return results


# ── D1: "Approve all" leaves out PRs whose review is missing, says HOLD or has a BLOCKER ─────────────


def _state_root() -> Path:
    import os
    env = os.environ.get("TRADEAI_STATE_ROOT")
    if env:
        return Path(env)
    from scripts.lib.persistent_state_root import good_persistent_root
    return Path(good_persistent_root())


def review_gate_active() -> bool:
    """D1 and the "Review #N" buttons start when the reviewer can write (its pr_reviews store row is approved).

    Before that no review exists, and leaving every PR out of "Approve all" would stop the only working merge
    approval; the digest then behaves exactly as before.
    """
    from scripts.lib import pr_review as R
    return R.registry_store_approved()


def review_url(pr: int, head: str) -> Optional[str]:
    from scripts.lib import pr_review as R
    return R.review_url(pr, head)


def partition(ready: list[dict[str, Any]], *, store=None, rows: list[dict[str, Any]] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split the digest's ready PRs into (approve-all eligible, open-the-review). D1 plus the sheet's Hold / Ask-author."""
    from scripts.lib import pr_review as R
    store = store or R.Store(R.store_dir(_state_root()), approved=lambda: False)
    rows = ledger_rows() if rows is None else rows
    stopped = {(str(r.get("item_id")), str(r.get("head_sha") or r.get("source_sha"))): r.get("decision") for r in rows
               if r.get("event") == "DECIDED" and r.get("kind") == "MERGE" and r.get("decision") in ("HOLD", "REQUEST_CHANGES")}
    keep, out = [], []
    for it in ready:
        head = str(it.get("head_sha") or "")
        why = {"HOLD": "you held it in the review", "REQUEST_CHANGES": "you asked the author to change it"}.get(
            stopped.get((f"pr:{int(it['pr'])}", head)) or "")
        if not why:
            ok, why = R.approve_all_eligible(store.latest(int(it["pr"])), head)
            why = None if ok else why
        (out if why else keep).append({**it, "review_reason": why} if why else it)
    return keep, out
