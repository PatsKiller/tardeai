#!/usr/bin/env python3
"""Independent PR reviewer (host timer tradeai-pr-review, every 5 min) — Design approvals-pr-review/v001.

  pr_independent_review.py [--apply] [--pr N] [--json]

Dry run (default): lists the open PRs, prints the would-review set with each one's §29 preflight (credit journal,
process cap, the combined $2/day review cap, the global provider cap) and the would-answer questions. It calls no
model, writes nothing and posts nothing.

--apply: refused with STORE_APPROVAL_PENDING until the operator-approved ``pr_reviews`` row is in
config/data_source_authority.json (D5). Then, per READY PR (not draft, four required checks green on the head,
10 min settled after the last push) without a review of its head: a data-quality gate, the independence check, one
governed review call (Sonnet 5.5 normal; Opus 5.5 + a free OAuth ChatGPT→Grok second read for held and shared-infra
PRs; never DeepSeek), the harness rules, PrReview@v1 written once per (PR, head), and the
``tradeai/independent-review`` commit status (D4) with the operator-provisioned status token only. Operator questions
(QUESTION rows in the operator decisions ledger) get one capped answer each. When the credit is unusable the PR is
marked "waiting for credit" with the next try; there is no paid fallback (D3).

Never merges, labels, approves, pushes, comments on GitHub or reads the operator's gh token for a write.
MBI_BEHAVIOR = 0.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from scripts.lib import pr_review as R  # noqa: E402

LIST_FIELDS = "number,title,url,headRefOid,baseRefName,isDraft,labels,statusCheckRollup,changedFiles,updatedAt,createdAt"
VIEW_FIELDS = "number,title,url,headRefOid,body,labels,files,changedFiles,commits,author"
MAX_REVIEWS_PER_CYCLE = 3


# ── side effects (each injectable) ───────────────────────────────────────────


def _gh(args: list[str], timeout: int = 90) -> str:
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:2])} failed: {(proc.stderr or proc.stdout).strip()[:200]}")
    return proc.stdout


def gh_list(repo: str) -> list[dict]:
    return json.loads(_gh(["pr", "list", "--repo", repo, "--base", "main", "--state", "open", "--limit", "100",
                           "--json", LIST_FIELDS]) or "[]")


def gh_view(repo: str, pr: int) -> dict:
    doc = json.loads(_gh(["pr", "view", str(int(pr)), "--repo", repo, "--json", VIEW_FIELDS]) or "{}")
    # gh pr --json has no base SHA; the REST pull carries it (the base branch tip the PR is compared with).
    doc["baseRefOid"] = _gh(["api", f"repos/{repo}/pulls/{int(pr)}", "--jq", ".base.sha"]).strip()
    if int(doc.get("changedFiles") or 0) > len(doc.get("files") or []):
        raw = _gh(["api", "--paginate", f"repos/{repo}/pulls/{int(pr)}/files?per_page=100",
                   "--jq", ".[] | {filename, additions, deletions, status}"])
        flat = [json.loads(line) for line in raw.splitlines() if line.strip()]
        doc["files"] = [{"path": f["filename"], "additions": f.get("additions", 0), "deletions": f.get("deletions", 0),
                         "status": f.get("status")} for f in flat]
    return doc


def gh_diff(repo: str, base: str, head: str) -> str:
    # Bound to the exact SHAs (three-dot: from the merge base), never "whatever the PR is now".
    return _gh(["api", "-H", "Accept: application/vnd.github.v3.diff", f"repos/{repo}/compare/{base}...{head}"], timeout=120)


def gh_head(repo: str, pr: int) -> str:
    return json.loads(_gh(["pr", "view", str(int(pr)), "--repo", repo, "--json", "headRefOid"]) or "{}").get("headRefOid", "")


def default_model(process_id: str, prompt: str, max_tokens: int, *, lanes: Optional[tuple] = None,
                  response_json: bool = True) -> tuple[str, dict]:
    """One governed call. Anthropic-only rows never leave the credit (an unusable credit raises); OAuth rows use the
    pinned free lanes. Returns (text, {provider, model, cost_usd})."""
    if lanes:
        from scripts.lib.governed_cloud_generation import generate_cloud
        text, lane = generate_cloud(prompt, process_id=process_id, task_summary="independent PR review (second read)",
                                    timeout=240, lanes=lanes, max_tokens=max_tokens, response_json=response_json)
        return text, {"provider": lane, "model": lane, "cost_usd": 0.0}
    from scripts.lib import anthropic_routing as promo
    from scripts.lib import llm_consumption as lc
    cfg = lc.get_process_config(process_id)
    if not promo.active(process_id, cfg):
        raise RuntimeError("ANTHROPIC_CREDIT_UNAVAILABLE: anthropic-only process; queue and retry")
    text, prov = lc.gate_and_generate(prompt, process_id=process_id, lane=(cfg.get("allowed_lanes") or ["grok"])[0],
                                      task_summary="independent PR review", timeout=240, max_tokens=max_tokens,
                                      response_json=response_json, return_provenance=True)
    return str(text), {"provider": str(prov.get("provider") or "anthropic"),
                       "model": prov.get("returned_model") or prov.get("requested_model_id"),
                       "cost_usd": float(prov.get("estimated_cost_usd") or 0.0)}


def default_post_status(repo: str, sha: str, payload: dict, token_env: str) -> dict:
    """D4. Only the operator-provisioned commit-status token in the unit's environment; never gh, never a key file."""
    token = os.environ.get(token_env)
    if not token:
        return {"posted": False, "reason": "STATUS_IDENTITY_NOT_PROVISIONED"}
    req = urllib.request.Request(f"https://api.github.com/repos/{repo}/statuses/{sha}", method="POST",
                                 data=json.dumps(payload).encode(),
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                          "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https origin
            return {"posted": resp.status == 201, "http": resp.status}
    except urllib.error.HTTPError as exc:
        return {"posted": False, "http": exc.code, "reason": "STATUS_POST_REFUSED"}
    except (urllib.error.URLError, OSError) as exc:
        return {"posted": False, "reason": type(exc).__name__}


def default_questions() -> list[dict]:
    from scripts.lib import operator_approvals as oa
    from scripts.lib.approval_package import governance_dir
    rows = oa.DecisionLedger(governance_dir() / "operator_decisions.jsonl", approved=lambda: False).rows()
    return [r for r in rows if r.get("event") == "QUESTION" and str(r.get("item_id", "")).startswith("pr:")]


@dataclass
class Deps:
    list_prs: Callable[[str], list[dict]]
    view_pr: Callable[[str, int], dict]
    diff: Callable[[str, str, str], str]
    head: Callable[[str, int], str]
    model: Callable[..., tuple[str, dict]]
    post_status: Callable[[str, str, dict, str], dict]
    questions: Callable[[], list[dict]]
    credit: Callable[[datetime], dict]
    agents_text: Callable[[], str]
    clock: Callable[[], datetime] = R.utc_now


def default_deps(state_root: Path) -> Deps:
    return Deps(list_prs=gh_list, view_pr=gh_view, diff=gh_diff, head=gh_head, model=default_model,
                post_status=default_post_status, questions=default_questions,
                credit=lambda now: R.credit_snapshot(state_root, now),
                agents_text=lambda: (ROOT / "AGENTS.md").read_text(encoding="utf-8"))


# ── one review ───────────────────────────────────────────────────────────────


def _labels(pr: dict) -> list[str]:
    return sorted(str(lb.get("name") if isinstance(lb, dict) else lb) for lb in pr.get("labels") or [])


def _files(view: dict) -> list[dict]:
    out = []
    for f in view.get("files") or []:
        path = str(f.get("path") or f.get("filename") or "")
        status = f.get("status") or ("added" if f.get("deletions") == 0 and f.get("additions") else "modified")
        out.append({"path": path, "additions": int(f.get("additions") or 0), "deletions": int(f.get("deletions") or 0),
                    "status": str(status).lower()})
    return out


def _last_push(view: dict) -> Optional[datetime]:
    times = [R.parse_iso(c.get("committedDate")) for c in view.get("commits") or []]
    times = [t for t in times if t]
    return max(times) if times else None


def candidate_state(pr: dict, now: datetime) -> Optional[str]:
    if pr.get("isDraft") or str(pr.get("baseRefName") or "main") != "main":
        return None
    green, _ = R.check_states(pr.get("statusCheckRollup"))
    return "ready" if green else None


def _call(deps: Deps, process_id: str, prompt: str, max_tokens: int, lanes=None, response_json=True) -> tuple[Optional[str], dict]:
    try:
        return deps.model(process_id, prompt, max_tokens, lanes=lanes, response_json=response_json)
    except Exception as exc:  # noqa: BLE001 - the caller turns a failure into a wait or CANNOT_REVIEW
        return None, {"error": str(exc)[:200]}


def review_one(*, repo: str, pr_row: dict, cfg: dict, store: R.Store, deps: Deps, apply: bool, out: dict) -> None:
    now = deps.clock()
    n = int(pr_row["number"])
    head = str(pr_row.get("headRefOid") or "")
    view = deps.view_pr(repo, n)
    files = _files(view)
    labels = _labels(view)
    held = R.held_classes([f["path"] for f in files], labels)
    shared = R.is_shared_infra(labels, view.get("title", ""))
    tier = "deep" if held or shared else "normal"
    last = _last_push(view)
    settle = timedelta(minutes=int(cfg.get("settle_minutes", 10)))
    if last and now - last < settle:
        row = {"pr": n, "head_sha": head, "state": "SETTLING", "reason": "10-minute settle after the last push",
               "next_try_at": R.iso(last + settle), "at": R.iso(now)}
        out["settling"].append(row)
        if apply:
            store.write_status(row)
        return
    credit = deps.credit(now)
    # The dry run adds each would-review's projected cost, so its list is what fits under today's limits (§29).
    pf = R.preflight(kind="review", tier=tier, pr=n, cfg=cfg, spend_rows=store.spend() + out["projected_spend"],
                     credit=credit, now=now)
    item = {"pr": n, "head_sha": head, "tier": tier, "held": held, "shared_infra": shared, "preflight": pf}
    if not pf["ok"]:
        row = {"pr": n, "head_sha": head, "state": "WAITING_FOR_CREDIT", "reason": pf["reason"],
               "next_try_at": pf["next_try_at"], "limits": pf["limits"], "at": R.iso(now)}
        out["waiting"].append(row)
        if apply:
            store.write_status(row)
        return
    if not apply:
        out["would_review"].append(item)
        out["projected_spend"].append({"at": R.iso(now), "kind": "review", "call": 1, "pr": n, "provider": "anthropic",
                                       "process_id": pf["process_id"],
                                       "cost_usd": float(cfg["budget"]["projected_cost_usd"][tier])})
        return
    run_id = now.strftime("%m%d-%H%M") + "-" + secrets.token_hex(3)
    reviewer = {"process_id": pf["process_id"], "provider": "anthropic", "model": cfg["models"][tier], "run_id": run_id,
                "id": R.reviewer_id(run_id), "fresh_context": True, "started_at": R.iso(now)}
    author = R.author_identity([f"{c.get('messageHeadline', '')}\n{c.get('messageBody', '')}" for c in view.get("commits") or []],
                               view.get("body") or "", (view.get("author") or {}).get("login", ""))
    indep = R.independence(author, reviewer)
    if not indep["ok"]:
        row = {"pr": n, "head_sha": head, "state": "CANNOT_REVIEW", "reason": "independence check failed: " + str(indep["reason"]),
               "at": R.iso(now)}
        out["refused"].append(row)
        store.write_status(row)
        return
    base = str(view.get("baseRefOid") or pr_row.get("baseRefOid") or "")
    diff_text = deps.diff(repo, base, head)
    hunks = R.split_hunks(diff_text)
    defect = R.data_quality_gate(files=files, changed_files=int(view.get("changedFiles") or len(files)), hunks=hunks,
                                 head_now=deps.head(repo, n), head=head, diff_text=diff_text)
    if not defect and len(hunks) > int(cfg.get("max_hunks", 400)):
        defect = "too large to review in one pass — split the PR"
    _, checks = R.check_states(pr_row.get("statusCheckRollup"))
    ui = any(f["path"].startswith("apps/command-center-v3/src") for f in files)
    policy = R.policy_excerpts(deps.agents_text(), cfg, shared_infra=shared or bool(held), ui=ui)
    ctx = {"pr": n, "title": view.get("title", ""), "base_sha": base, "head_sha": head, "body": view.get("body") or ""}
    model_out, cost, calls, provider_model = None, 0.0, 0, None
    if not defect:
        parts = R.chunk_hunks(hunks, int(cfg["input_budget_chars"][tier]), int(cfg.get("max_calls_per_review", 3)))
        if parts is None:
            defect = "too large to review in one pass — split the PR"
        else:
            outs = []
            for i, part in enumerate(parts, 1):
                prompt = R.build_prompt(pr=ctx, files=files, hunks=part, policy=policy, part=(i, len(parts)))
                parsed = None
                for attempt in range(2):  # one retry on a schema failure
                    calls += 1
                    text, prov = _call(deps, pf["process_id"], prompt, int(cfg["max_output_tokens"][tier]))
                    if text is not None and prov.get("provider") in cfg.get("forbidden_providers", []):
                        text = None  # never DeepSeek: discarded, not shown
                    store.add_spend({"at": R.iso(deps.clock()), "kind": "review", "call": calls, "pr": n, "head_sha": head,
                                     "process_id": pf["process_id"], "provider": prov.get("provider") or "anthropic",
                                     "cost_usd": float(prov.get("cost_usd") or 0.0), "run_id": run_id,
                                     "error": prov.get("error")})
                    cost += float(prov.get("cost_usd") or 0.0)
                    provider_model = prov.get("model") or provider_model
                    if text is None and "CREDIT" in str(prov.get("error", "")).upper():
                        row = {"pr": n, "head_sha": head, "state": "WAITING_FOR_CREDIT", "reason": str(prov["error"])[:160],
                               "next_try_at": R.iso(deps.clock() + timedelta(minutes=int(cfg.get("retry_after_minutes", 30)))),
                               "at": R.iso(deps.clock())}
                        out["waiting"].append(row)
                        store.write_status(row)
                        return
                    parsed = R.parse_model(text) if text else None
                    if parsed:
                        break
                if parsed is None:
                    outs = []
                    break
                outs.append(parsed)
            model_out = R.merge_parts(outs) if outs else None
    ruled = R.apply_rules(model_out, hunks=hunks, held=held, shared_infra=shared, gate_defect=defect,
                          unexplained_max=float(cfg.get("unexplained_hunk_max_ratio", 0.10)))
    second = None
    if (held or shared) and not defect:
        # D2: a free, different-provider second read for held and shared-infra PRs. It never sets the verdict.
        prompt = R.build_prompt(pr=ctx, files=files, hunks=hunks[:200], policy=policy)
        text, prov = _call(deps, cfg["processes"]["second_read"], prompt, 4000, lanes=tuple(cfg.get("second_read_lanes") or ("chatgpt", "grok")))
        parsed = R.parse_model(text) if text and prov.get("provider") not in cfg.get("forbidden_providers", []) else None
        srun = run_id + "-2"
        second = {"process_id": cfg["processes"]["second_read"], "provider": prov.get("provider"), "run_id": srun,
                  "id": R.reviewer_id(srun), "cost_usd": 0.0,
                  "verdict": parsed["verdict"] if parsed else None, "summary": parsed["summary"] if parsed else None,
                  "findings": [f for f in (parsed or {}).get("findings", []) if f["severity"] in ("BLOCKER", "MAJOR")][:10],
                  "error": None if parsed else (prov.get("error") or "no valid answer")}
    finished = deps.clock()
    reviewer.update(model=provider_model or reviewer["model"], finished_at=R.iso(finished),
                    duration_s=round((finished - now).total_seconds(), 1), cost_usd=round(cost, 4), calls=calls)
    rec = {"schema": R.SCHEMA, "pr": n, "title": view.get("title", ""), "url": view.get("url", ""), "base_ref": "main",
           "base_sha": base, "head_sha": head, "diff_sha256": hashlib.sha256(diff_text.encode()).hexdigest(),
           "files": files, "author": author, "reviewer": reviewer, "second_read": second, "independent": indep,
           "summary": ruled["summary"], "risk": ruled["risk"],
           "classes": {"held": held, "held_paths": R.held_paths([f["path"] for f in files]), "shared_infra": shared,
                       "labels": labels},
           "areas": R.build_areas(files, hunks, ruled["hunk_notes"], cfg),
           "evidence": R.evidence_from(view, files, checks), "findings": ruled["findings"],
           "dropped_findings": ruled["dropped_findings"], "unexplained_hunks": ruled["unexplained_hunks"],
           "hunk_count": len(hunks), "verdict": ruled["verdict"], "verdict_reason": ruled["verdict_reason"],
           "preflight": pf["limits"], "created_at": R.iso(finished)}
    rec["document_sha"] = R.document_sha(rec)
    store.write_review(rec)
    out["reviewed"].append({"pr": n, "head_sha": head, "verdict": rec["verdict"], "cost_usd": rec["reviewer"]["cost_usd"]})
    sc = cfg.get("commit_status") or {}
    if sc.get("enabled"):
        post = deps.post_status(repo, head, R.commit_status_payload(rec, cfg, R.review_url(n, head)), sc.get("token_env", ""))
        store.update_status_post(rec, {**post, "at": R.iso(deps.clock())})


def answer_questions(*, cfg: dict, store: R.Store, deps: Deps, apply: bool, out: dict) -> None:
    answered = {a.get("question_hash") for a in store.answers()}
    for q in deps.questions():
        if q.get("hash_self") in answered:
            continue
        n = int(str(q["item_id"]).split(":", 1)[1])
        rec = store.review(n, str(q.get("source_sha") or ""))
        now = deps.clock()
        pf = R.preflight(kind="question", tier="normal", pr=n, cfg=cfg, spend_rows=store.spend(), credit=deps.credit(now), now=now)
        item = {"pr": n, "question_hash": q.get("hash_self"), "preflight": pf}
        if rec is None:
            out["questions_waiting"].append({**item, "reason": "no review of that head"})
            continue
        if not pf["ok"]:
            out["questions_waiting"].append({**item, "reason": pf["reason"]})
            continue
        if not apply:
            out["would_answer"].append(item)
            continue
        context = {k: rec.get(k) for k in ("pr", "title", "head_sha", "summary", "risk", "classes", "findings", "verdict")}
        context["changes"] = [{"file": h["file"], "header": h["header"], "note": h.get("note")}
                              for a in rec.get("areas") or [] for f in a["files"] for h in f["hunks"]][:200]
        prompt = ("You are the independent reviewer of this pull request. Answer the operator's question in plain words, "
                  "in at most 6 sentences, using only the review and change list below. If the answer is not in them, "
                  "say so. Never say the PR may merge itself.\n\nReview:\n" + json.dumps(context, ensure_ascii=False)[:40000]
                  + "\n\nQuestion:\n" + str(q.get("question") or "")[: int(cfg.get("max_question_chars", 1000))])
        text, prov = _call(deps, cfg["processes"]["question"], prompt, int(cfg["max_output_tokens"]["question"]), response_json=False)
        if text is not None and prov.get("provider") in cfg.get("forbidden_providers", []):
            text = None
        store.add_spend({"at": R.iso(deps.clock()), "kind": "question", "call": 1, "pr": n, "head_sha": rec["head_sha"],
                         "process_id": cfg["processes"]["question"], "provider": prov.get("provider") or "anthropic",
                         "cost_usd": float(prov.get("cost_usd") or 0.0), "error": prov.get("error")})
        if text is None:
            out["questions_waiting"].append({**item, "reason": prov.get("error") or "no answer"})
            continue
        store.add_answer({"question_hash": q["hash_self"], "pr": n, "head_sha": rec["head_sha"], "question": q.get("question"),
                          "asked_at": q.get("at"), "answer": text.strip()[:3000], "cost_usd": float(prov.get("cost_usd") or 0.0),
                          "provider": prov.get("provider"), "model": prov.get("model"), "at": R.iso(deps.clock())})
        out["answered"].append({"pr": n, "question_hash": q["hash_self"]})


def cycle(*, repo: str, cfg: dict, store: R.Store, deps: Deps, apply: bool, only_pr: Optional[int] = None) -> dict:
    out: dict[str, Any] = {"apply": apply, "store_approved": store.approved(), "would_review": [], "reviewed": [],
                           "settling": [], "waiting": [], "refused": [], "already": [], "would_answer": [],
                           "answered": [], "questions_waiting": [], "errors": [], "projected_spend": []}
    if apply and not store.approved():
        out["refused_all"] = "STORE_APPROVAL_PENDING"
        return out
    prs = deps.list_prs(repo)
    now = deps.clock()
    snap = []
    for pr in prs:
        green, checks = R.check_states(pr.get("statusCheckRollup"))
        snap.append({"pr": int(pr["number"]), "title": str(pr.get("title") or "")[:200], "url": pr.get("url"),
                     "head_sha": pr.get("headRefOid"), "draft": bool(pr.get("isDraft")), "labels": _labels(pr),
                     "checks": checks, "checks_green": green, "created_at": pr.get("createdAt"), "updated_at": pr.get("updatedAt")})
    if apply:
        store.write_snapshot({"as_of": R.iso(now), "repo": repo, "prs": snap})
    done = 0
    # Newest first: the daily cap goes to work most likely to merge, not to an old backlog.
    for pr in sorted(prs, key=lambda p: int(p["number"]), reverse=True):
        n = int(pr["number"])
        if only_pr is not None and n != only_pr:
            continue
        if candidate_state(pr, now) is None:
            continue
        if store.review(n, str(pr.get("headRefOid") or "")):
            out["already"].append(n)
            continue
        if done >= MAX_REVIEWS_PER_CYCLE:
            break
        try:
            review_one(repo=repo, pr_row=pr, cfg=cfg, store=store, deps=deps, apply=apply, out=out)
        except Exception as exc:  # noqa: BLE001 - one PR's failure never stops the others; it is reported
            out["errors"].append({"pr": n, "error": f"{type(exc).__name__}: {str(exc)[:200]}"})
        done = len(out["reviewed"])
    try:
        answer_questions(cfg=cfg, store=store, deps=deps, apply=apply, out=out)
    except Exception as exc:  # noqa: BLE001
        out["errors"].append({"questions": f"{type(exc).__name__}: {str(exc)[:200]}"})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--pr", type=int)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    cfg = R.load_config()
    env_root = os.environ.get("TRADEAI_STATE_ROOT")
    if env_root:
        state_root = Path(env_root)
    else:
        from scripts.lib.persistent_state_root import good_persistent_root
        state_root = Path(good_persistent_root())
    store = R.Store(R.store_dir(state_root, cfg), approved=lambda: R.registry_store_approved(ROOT, cfg))
    started = time.monotonic()
    out = cycle(repo=cfg["repo"], cfg=cfg, store=store, deps=default_deps(state_root), apply=bool(a.apply and not a.dry_run),
                only_pr=a.pr)
    out["elapsed_s"] = round(time.monotonic() - started, 1)
    if a.json:
        print(json.dumps(out, indent=1, default=str))
    else:
        print(f"apply={out['apply']} store_approved={out['store_approved']} {out.get('refused_all', '')} "
              f"would_review={len(out['would_review'])} reviewed={len(out['reviewed'])} settling={len(out['settling'])} "
              f"waiting={len(out['waiting'])} refused={len(out['refused'])} already={len(out['already'])} "
              f"would_answer={len(out['would_answer'])} answered={len(out['answered'])} errors={len(out['errors'])}")
        for row in out["would_review"]:
            lim = row["preflight"]["limits"]
            print(f"  would review #{row['pr']} head {row['head_sha'][:9]} tier={row['tier']} process={row['preflight']['process_id']} "
                  f"credit={lim['credit'].get('status')} combined={lim['combined']['spent_today_usd']}/{lim['combined']['daily_cost_cap_usd']} "
                  f"headroom={lim['headroom_usd']}")
        for row in out["waiting"]:
            print(f"  waiting #{row['pr']}: {row['reason']} next={row.get('next_try_at')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
