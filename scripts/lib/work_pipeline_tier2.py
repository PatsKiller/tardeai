"""Work pipeline Tier 2: the risky operator acts, each a passkey assertion + typed phrase through the host applier.

Operator 2026-10-23, on the Work pipeline mockup: "nothing is actionable on there", then approved both action tiers
("both"). Tier 1 (``work_pipeline_commands``) writes only the coordination store. Tier 2 acts are Ops -> Controls
change kinds (``ops_controls_core.KINDS``, prefix ``pipeline.``), so they inherit that surface whole: the operator's
tailnet identity only (agents and the service token are refused, §27.2), CSRF, a request per act, a WebAuthn
assertion with user verification bound to that request plus the typed phrase the server shows (§27.3), the HMAC-signed
approval, the one host applier (``tradeai-ops-applier.service``) that executes it, and the durable audit. The sudo
window (#1970) is not merged, so every act needs its own fresh assertion.

Kinds (each gated by ``config/ops_controls.json`` ``work_pipeline.<flag>``; a kind whose flag is false is refused
``FEATURE_OFF`` before any request is created):

=========================== ====================== ======= ==========================================================
kind                        flag                   default effect (applier)
=========================== ====================== ======= ==========================================================
pipeline.approve_design     approve_design_enabled ON      append DesignApproval@v1 (the operator's words, time,
                                                           request, assertion) to <claims_dir>/designs/approvals.jsonl;
                                                           the Work board / pipeline read it at once; the next agent
                                                           commit sets ``status: APPROVED`` in docs/designs/<id>.md
pipeline.contract_reviewed  contract_reviewed_     ON      append ContractReview@v1 to <claims_dir>/contracts/
                            enabled                        reviews.jsonl for a DRAFT lane in config/n8n_health_
                                                           contracts.json; the next agent commit sets it REVIEWED
pipeline.approve_item       approve_item_enabled   OFF     APPROVE items of an approval package (approval_package
                                                           ledger, decided_by = the operator + passkey). OFF: an
                                                           APPROVED package lets the poller mint guard grants, and
                                                           issuing grants is never on the board until ratified
pipeline.merge_pr           merge_pr_enabled       OFF     the applier, with the operator's gh, re-reads the PR, refuses
                                                           unless the head SHA matches and every required check of the
                                                           base is exactly ``success``, then ``gh pr merge --merge
                                                           --match-head-commit``. OFF until an AGENTS clause allows a
                                                           merge from Command Center
pipeline.release_now        release_now_enabled    OFF     refused without an active ``release-write`` guard grant;
                                                           then scripts/cio_phase2_exact_main_deploy.sh prepare and
                                                           promote for the expected origin/main SHA. OFF until an
                                                           AGENTS clause allows a release from Command Center
=========================== ====================== ======= ==========================================================

Why a ledger, not a repo write, for approvals: Command Center and the applier never hold git push credentials, and
a commit to main from the applier would bypass review and the push policy (AI_WORK_POLICY.md). The ledger record is
immediate, append-only and carries the assertion; the design file catches up in the next reviewed commit, and until
it does the registry shows the approval with ``file_pending: true``.

``plan`` never calls GitHub or a deploy script (it runs in the Command Center process for the preview); ``apply``
runs only in the host applier. AUTHORITY: OPERATOR_ONLY. MBI_BEHAVIOR = 0: nothing here touches a broker.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Mapping, Optional

DESIGN_LEDGER_REL = "designs/approvals.jsonl"
CONTRACT_LEDGER_REL = "contracts/reviews.jsonl"
DESIGN_SCHEMA = "DesignApproval@v1"
CONTRACT_SCHEMA = "ContractReview@v1"
CONTRACTS_REL = "config/n8n_health_contracts.json"
DEPLOY_SCRIPT_REL = "scripts/cio_phase2_exact_main_deploy.sh"
FLAGS = {
    "pipeline.approve_design": ("approve_design_enabled", True),
    "pipeline.contract_reviewed": ("contract_reviewed_enabled", True),
    "pipeline.approve_item": ("approve_item_enabled", False),
    "pipeline.merge_pr": ("merge_pr_enabled", False),
    "pipeline.release_now": ("release_now_enabled", False),
}
LABELS = {
    "pipeline.approve_design": "Work pipeline: approve a design, phase or packet",
    "pipeline.contract_reviewed": "Work pipeline: mark a DRAFT n8n health contract reviewed",
    "pipeline.approve_item": "Work pipeline: approve approval-package items",
    "pipeline.merge_pr": "Work pipeline: merge a PR (required checks exactly success)",
    "pipeline.release_now": "Work pipeline: release now (exact-main prepare + promote)",
}
POLICY_NOTE = {
    "pipeline.approve_item": "OFF until ratified: an APPROVED package lets the poller mint guard grants, and issuing "
    "grants is never on the Work pipeline (operator 2026-10-23).",
    "pipeline.merge_pr": "OFF until an AGENTS.md clause allows a merge from Command Center through the host applier "
    "(§27.2 names the applier's scope).",
    "pipeline.release_now": "OFF until an AGENTS.md clause allows a release from Command Center through the host "
    "applier under the operator's release-write grant.",
}
DESIGN_ID_RE = re.compile(r"^(DSN-[0-9]{8}-[a-z0-9]+(?:-[a-z0-9]+)*(?:-P[0-9]{1,3})?|[a-z0-9][a-z0-9-]{2,79})$")
LANE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,80}$")
PKG_RE = re.compile(r"^pkg-[a-z0-9-]{4,80}$")
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
OK_CONCLUSION = "success"


def _err(code: str, detail: str = "", status: int = 409):
    from scripts.lib.ops_controls_core import OpsError

    return OpsError(code, detail, status)


def flags(cfg: Mapping[str, Any]) -> dict[str, bool]:
    wp = cfg.get("work_pipeline") or {}
    return {kind: bool(wp.get(flag, default)) for kind, (flag, default) in FLAGS.items()}


def kinds_view(cfg: Mapping[str, Any]) -> list[dict[str, Any]]:
    f = flags(cfg)
    return [{"kind": k, "label": LABELS[k], "enabled": f[k], "policy_note": POLICY_NOTE.get(k)} for k in FLAGS]


def claims_dir(cfg: Mapping[str, Any]) -> Path:
    raw = (cfg.get("work_pipeline") or {}).get("claims_dir")
    if raw:
        return Path(os.path.expanduser(str(raw)))
    from scripts.lib import agent_claim_board as B

    return B.default_claims_dir()


def _words(p: Mapping[str, Any]) -> str:
    w = " ".join(str(p.get("words") or "").split())
    if len(w) < 4 or len(w) > 1000 or any(ord(c) < 32 for c in w):
        raise _err("PARAMS_INVALID", "words: the operator's own words, 4-1000 printable characters", 400)
    return w


def read_ledger(path: Path, limit_bytes: int = 2 * 1024 * 1024) -> list[dict[str, Any]]:
    """Rows of an append-only JSONL ledger (bounded tail). Never raises."""
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - limit_bytes))
            text = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return []
    out = []
    for ln in text.splitlines():
        try:
            row = json.loads(ln)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def design_approvals(cd: Path) -> dict[str, dict[str, Any]]:
    """id -> the latest DesignApproval@v1 row."""
    return {str(r.get("id")): r for r in read_ledger(Path(cd) / DESIGN_LEDGER_REL) if r.get("schema") == DESIGN_SCHEMA}


def contract_reviews(cd: Path) -> dict[str, dict[str, Any]]:
    return {
        str(r.get("lane_id")): r
        for r in read_ledger(Path(cd) / CONTRACT_LEDGER_REL)
        if r.get("schema") == CONTRACT_SCHEMA
    }


def draft_contract_lanes(code_root: Path) -> list[str]:
    try:
        doc = json.loads((Path(code_root) / CONTRACTS_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    c = doc.get("contracts", doc) if isinstance(doc, dict) else {}
    items = c.items() if isinstance(c, dict) else [(x.get("lane_id"), x) for x in c if isinstance(x, dict)]
    return sorted(str(k) for k, v in items if isinstance(v, dict) and str(v.get("status")) == "DRAFT")


def _append(path: Path, row: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, (json.dumps(dict(row), sort_keys=True, default=str) + "\n").encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


def phrase(kind: str, params: Mapping[str, Any], today: str) -> str:
    target = {
        "pipeline.approve_design": lambda: params.get("design_id"),
        "pipeline.contract_reviewed": lambda: params.get("lane_id"),
        "pipeline.approve_item": lambda: params.get("package_id"),
        "pipeline.merge_pr": lambda: f"#{params.get('pr')}",
        "pipeline.release_now": lambda: str(params.get("sha") or "")[:9],
    }[kind]()
    verb = {
        "pipeline.approve_design": "APPROVE DESIGN",
        "pipeline.contract_reviewed": "CONTRACT REVIEWED",
        "pipeline.approve_item": "APPROVE PACKAGE",
        "pipeline.merge_pr": "MERGE PR",
        "pipeline.release_now": "RELEASE",
    }[kind]
    return f"{verb} {target} {today}"


# --------------------------------------------------------------------------------------------- plan (read-only)


def plan(kind: str, params: Mapping[str, Any], hosts: Any, store: Any, *, request_id: str, actor: str = ""):
    """Validate and preview. Read-only; no GitHub, no deploy script (this runs in Command Center for the preview)."""
    from scripts.lib.ops_controls_core import Plan, canonical, sha256_text

    if not flags(hosts.cfg).get(kind):
        raise _err(
            "FEATURE_OFF", f"{kind} is off (config/ops_controls.json work_pipeline). {POLICY_NOTE.get(kind, '')}"
        )
    p = dict(params)
    cd = claims_dir(hosts.cfg)
    if kind == "pipeline.approve_design":
        did = str(p.get("design_id") or "")
        if not DESIGN_ID_RE.fullmatch(did):
            raise _err("PARAMS_INVALID", "design_id: DSN-<date>-<slug>[-P<n>] or a packet slug", 400)
        words = _words(p)
        root = Path(hosts.code_root)
        base = did.rsplit("-P", 1)[0] if re.search(r"-P[0-9]{1,3}$", did) and did.startswith("DSN-") else did
        path = root / "docs" / "designs" / f"{base}.md"
        packet = root / "docs" / "ops" / "packets" / did / "README.md"
        if not (path.is_file() or packet.is_file()):
            raise _err("NOT_FOUND", f"no docs/designs/{base}.md and no docs/ops/packets/{did}/README.md", 404)
        prior = design_approvals(cd).get(did)
        if prior:
            raise _err("NO_CHANGE", f"{did} was approved {prior.get('at')} ({prior.get('actor')})")
        file_rel = str((path if path.is_file() else packet).relative_to(root))
        return Plan(
            kind, {"design_id": did, "words": words}, f"record the operator's approval of {did}", "awaiting operator",
            "APPROVED", sha256_text(canonical({"id": did, "prior": None})),
            diff=[f"+ {did}: APPROVED — “{words}”", f"  ledger {cd / DESIGN_LEDGER_REL}", f"  file {file_rel}: next agent commit"],
            warnings=["recorded in the coordination ledger now; the design file changes in the next reviewed commit"],
            undo=None, undo_reason="an approval is a record; supersede it with a new decision (HELD) in the design file",
            payload={"ledger": str(cd / DESIGN_LEDGER_REL), "file": file_rel},
        )  # fmt: skip
    if kind == "pipeline.contract_reviewed":
        lane = str(p.get("lane_id") or "")
        if not LANE_RE.fullmatch(lane):
            raise _err("PARAMS_INVALID", "lane_id invalid", 400)
        words = _words(p)
        if lane not in draft_contract_lanes(Path(hosts.code_root)):
            raise _err("NOT_DRAFT", f"{lane} has no DRAFT contract in {CONTRACTS_REL}")
        prior = contract_reviews(cd).get(lane)
        if prior:
            raise _err("NO_CHANGE", f"{lane} was marked reviewed {prior.get('at')}")
        return Plan(
            kind, {"lane_id": lane, "words": words}, f"record that the operator reviewed the {lane} health contract",
            "DRAFT", "REVIEWED", sha256_text(canonical({"lane": lane, "prior": None})),
            diff=[f"+ {lane}: REVIEWED — “{words}”", f"  file {CONTRACTS_REL}: next agent commit (§23.19)"],
            undo=None, undo_reason="a review is a record; a later contract change goes back to DRAFT by PR",
            payload={"ledger": str(cd / CONTRACT_LEDGER_REL)},
        )  # fmt: skip
    if kind == "pipeline.approve_item":
        pid = str(p.get("package_id") or "")
        if not PKG_RE.fullmatch(pid):
            raise _err("PARAMS_INVALID", "package_id invalid", 400)
        items = p.get("items", "all")
        if items != "all" and not (isinstance(items, list) and items and all(isinstance(i, int) for i in items)):
            raise _err("PARAMS_INVALID", "items: 'all' or a list of item numbers", 400)
        from scripts.lib import approval_package as AP

        pkg = AP.Ledger(AP.ledger_path()).package(pid)
        if pkg is None:
            raise _err("NOT_FOUND", f"package {pid}", 404)
        if pkg.get("state") not in ("SUBMITTED", "PARTIAL"):
            raise _err("NO_CHANGE", f"package {pid} is {pkg.get('state')}")
        return Plan(
            kind, {"package_id": pid, "items": items}, f"APPROVE {pid} {items if items != 'all' else 'all'}",
            pkg.get("state"), "APPROVED", sha256_text(canonical({"pkg": pid, "state": pkg.get("state")})),
            diff=[f"+ {pid} items {items}: APPROVED (passkey)"],
            warnings=["the poller may mint the guard grants this package binds"],
            undo=None, undo_reason="approval decisions are append-only; DENY later items instead",
        )  # fmt: skip
    if kind == "pipeline.merge_pr":
        try:
            pr = int(p.get("pr"))
        except (TypeError, ValueError):
            raise _err("PARAMS_INVALID", "pr must be a number", 400) from None
        sha = str(p.get("head_sha") or "")
        if not SHA40_RE.fullmatch(sha):
            raise _err("PARAMS_INVALID", "head_sha must be the 40-hex head commit shown on the card", 400)
        return Plan(
            kind, {"pr": pr, "head_sha": sha}, f"merge PR #{pr} at {sha[:9]} if every required check is exactly success",
            sha, "merged", sha256_text(canonical({"pr": pr, "sha": sha})),
            diff=[f"gh pr merge {pr} --merge --match-head-commit {sha}"],
            warnings=["the host applier re-reads the PR and its required checks with the operator's gh first"],
            undo=None, undo_reason="a merge is undone by a revert PR",
        )  # fmt: skip
    if kind == "pipeline.release_now":
        sha = str(p.get("sha") or "")
        if not SHA40_RE.fullmatch(sha):
            raise _err("PARAMS_INVALID", "sha must be the 40-hex origin/main commit to release", 400)
        return Plan(
            kind, {"sha": sha}, f"release origin/main {sha[:9]} (prepare + promote) under the release-write grant",
            None, sha, sha256_text(canonical({"release": sha})),
            diff=[f"bash {DEPLOY_SCRIPT_REL} prepare", f"bash {DEPLOY_SCRIPT_REL} promote"],
            warnings=["refused without an active release-write guard grant", "restarts portfolio-server"],
            undo=None, undo_reason=f"bash {DEPLOY_SCRIPT_REL} rollback",
        )  # fmt: skip
    raise _err("KIND_NOT_SUPPORTED", kind)


# --------------------------------------------------------------------------------------------- apply (applier only)


def _gh_json(hosts: Any, path: str) -> Any:
    rc, out, err = hosts.runner(["gh", "api", "--method", "GET", path], None)
    if rc != 0:
        raise _err("GITHUB_UNAVAILABLE", (err or f"rc {rc}").strip()[:200], 503)
    try:
        return json.loads(out or "null")
    except ValueError:
        raise _err("GITHUB_UNAVAILABLE", "unparseable gh output", 503) from None


def merge_preconditions(hosts: Any, repo: str, pr: int, sha: str) -> dict[str, Any]:
    """Re-read the PR and its base's required checks; refuse unless all are exactly success at ``sha``."""
    doc = _gh_json(hosts, f"repos/{repo}/pulls/{pr}")
    if not isinstance(doc, dict) or doc.get("state") != "open" or doc.get("merged"):
        raise _err("PR_NOT_OPEN", f"#{pr} is not open")
    if (doc.get("head") or {}).get("sha") != sha:
        raise _err("STATE_CHANGED", f"#{pr} head moved to {str((doc.get('head') or {}).get('sha'))[:9]}; preview again")
    base = (doc.get("base") or {}).get("ref") or "main"
    prot = _gh_json(hosts, f"repos/{repo}/branches/{base}/protection/required_status_checks")
    req = sorted(
        {*(str(c) for c in (prot or {}).get("contexts") or []),
         *(str(c.get("context")) for c in (prot or {}).get("checks") or [] if isinstance(c, dict))}
    )  # fmt: skip
    if not req:
        raise _err("NO_REQUIRED_CHECKS", f"base {base} has no required checks; merge at the host terminal")
    runs = (_gh_json(hosts, f"repos/{repo}/commits/{sha}/check-runs?per_page=100") or {}).get("check_runs") or []
    latest: dict[str, dict] = {}
    for r in runs:
        n = str(r.get("name") or "")
        if n and (n not in latest or str(r.get("started_at") or "") >= str(latest[n].get("started_at") or "")):
            latest[n] = r
    bad = [n for n in req if (latest.get(n) or {}).get("conclusion") != OK_CONCLUSION]
    if bad:
        raise _err("CHECKS_NOT_SUCCESS", "not exactly success: " + ", ".join(bad)[:300])
    return {"base": base, "required": req}


def apply(kind: str, plan_: Any, hosts: Any, store: Any, *, request_id: str, actor: str) -> dict[str, Any]:
    res: dict[str, Any] = {"kind": kind, "summary": plan_.summary, "undo": None, "undo_reason": plan_.undo_reason}
    now = hosts.clock().isoformat(timespec="seconds")
    if kind in ("pipeline.approve_design", "pipeline.contract_reviewed"):
        ledger = Path(plan_.payload["ledger"])
        row = {
            "schema": DESIGN_SCHEMA if kind == "pipeline.approve_design" else CONTRACT_SCHEMA,
            **({"id": plan_.params["design_id"], "status": "APPROVED", "file": plan_.payload.get("file")}
               if kind == "pipeline.approve_design" else {"lane_id": plan_.params["lane_id"], "status": "REVIEWED"}),
            "words": plan_.params["words"],
            "actor": actor,
            "at": now,
            "request_id": request_id,
            "factor": "passkey+phrase (ops-controls request)",
        }  # fmt: skip
        _append(ledger, row)
        key = "id" if kind == "pipeline.approve_design" else "lane_id"
        got = [r for r in read_ledger(ledger) if r.get("request_id") == request_id and r.get(key) == row[key]]
        res["verify"] = {"ledger": str(ledger), "read_back_matches": bool(got)}
        res["backup_ref"] = None
        res["outcome"] = "APPLIED" if got else "FAILED"
        return res
    if kind == "pipeline.approve_item":
        from scripts.lib import approval_package as AP

        led = AP.Ledger(AP.ledger_path())
        reply = {
            "verb": "APPROVE",
            "package_id": plan_.params["package_id"],
            "items": plan_.params["items"],
            "reason": None,
        }
        pkg = AP.apply_reply(
            led, reply, decided_by={"actor": actor, "factor": "passkey+phrase", "request_id": request_id}
        )
        ok, n, why = led.verify_chain()
        res["verify"] = {"package_state": pkg.get("state"), "chain_ok": ok, "rows": n, "why": why}
        res["outcome"] = "APPLIED" if ok else "FAILED"
        return res
    if kind == "pipeline.merge_pr":
        from scripts.lib import agent_claim_lifecycle as LC

        repo = LC.default_repo(Path(hosts.code_root))
        pr, sha = plan_.params["pr"], plan_.params["head_sha"]
        pre = merge_preconditions(hosts, repo, pr, sha)
        rc, out, err = hosts.runner(
            ["gh", "pr", "merge", str(pr), "--repo", repo, "--merge", "--match-head-commit", sha], None
        )
        doc = _gh_json(hosts, f"repos/{repo}/pulls/{pr}")
        merged = bool(isinstance(doc, dict) and doc.get("merged"))
        res["verify"] = {"merge_rc": rc, "merged": merged, "merge_sha": (doc or {}).get("merge_commit_sha"), **pre,
                         "output": (out or err or "")[-300:]}  # fmt: skip
        res["outcome"] = "APPLIED" if rc == 0 and merged else "FAILED"
        return res
    if kind == "pipeline.release_now":
        gid = hosts.guard_id("release-write")
        if not gid:
            raise _err(
                "NO_RELEASE_GRANT",
                "no active release-write guard grant: issue one first (bin/guard grant release-write)",
            )
        from scripts.lib import ops_controls_core as C

        script = str(Path(hosts.code_root) / DEPLOY_SCRIPT_REL)
        steps = []
        for mode in ("prepare", "promote"):
            argv = ["bash", script, mode]
            # the host default runner caps at 60 s; a prepare builds the frontend and takes minutes
            rc, out, err = C._run(argv, None, timeout=1800) if hosts.runner is C._run else hosts.runner(argv, None)
            steps.append({"mode": mode, "rc": rc, "tail": (out or err or "")[-400:]})
            if rc != 0:
                break
        ok = len(steps) == 2 and all(s["rc"] == 0 for s in steps)
        res["verify"] = {"release_write_grant8": gid[:8], "steps": steps}
        res["undo_reason"] = f"bash {DEPLOY_SCRIPT_REL} rollback"
        res["outcome"] = "APPLIED" if ok else "FAILED"
        return res
    raise _err("KIND_NOT_SUPPORTED", kind)
