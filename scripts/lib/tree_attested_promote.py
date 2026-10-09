"""Tree-attested promote: accept the PR run's full-suite evidence for an identical merge tree.

Operator-approved 2026-10-09 (design: docs/architecture/ci/cio-hardening-design-audit-20261009.md,
"Medium-term" item 4, "Stage 3: merge -> promote", and "Where each moved or removed check keeps
its guarantee", row "Exact-SHA evidence at promote").

Today the promote waits for the push-to-main ``cio-hardening`` run of the merge SHA: the same
tree the PR already tested, re-tested for ~950 s (median). With
``TRADEAI_TREE_ATTESTED_PROMOTE=1`` the preflight first tries to prove that the merge commit
``M`` deploys exactly the tree a successful full-suite PR run tested:

  (a) the aggregate full-suite check (``ci-gate`` of cio-full-suite-sharded.yml) is the latest
      ``github-actions`` check run of that name on the PR head SHA ``H`` and succeeded; its
      workflow run is the latest run/attempt of that workflow for ``H`` and succeeded; the run's
      attestation artifact names ``H`` and the tree it tested;
  (b) ``git rev-parse H^{tree} == git rev-parse M^{tree}`` == the attested tested tree;
  (c) ``.github/workflows`` and the shard runner files are identical between ``H`` and ``M``
      (implied by (b); asserted explicitly so a future relaxation of (b) cannot drop it);
  (d) every context branch protection requires on ``main`` succeeded on ``H``.

All four hold -> the preflight passes without waiting for the main run and writes a receipt
naming the PR, ``H``, the tree and the check-run ids. Anything else -- including any API or git
error -- returns ``ok: False`` with reasons, and the caller falls back to today's exact-SHA
push/main wait. The flag defaults OFF.

The push-to-main run still executes and is the asynchronous backstop:
``release_grant_preflight.py --backstop-check --sha M`` reads it and exits 3 when it went red
(alarm wiring into health tooling is a follow-up; it is not done here).

AUTHORITY: READ_ONLY_ADVISORY. Reads GitHub run metadata and local git objects only; prints no
credential and never copies CLI stderr.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

SCHEMA = "TreeAttestedPromote@v1"
ATTESTATION_SCHEMA = "CiGateAttestation@v1"
FLAG_ENV = "TRADEAI_TREE_ATTESTED_PROMOTE"
AGGREGATE_CHECK = "ci-gate"
SHARDED_WORKFLOW = ".github/workflows/cio-full-suite-sharded.yml"
ATTESTATION_ARTIFACT = "ci-gate-attestation"
ATTESTATION_FILE = "ci_gate_attestation.json"
CHECK_APP = "github-actions"
BASE_BRANCH = "main"

#: Paths whose git object must be identical between the PR head and the merge commit.
WATCHED_PATHS = (
    ".github/workflows",
    "scripts/run_cio_hardening_ci.py",
    "scripts/lib/ci_shards.py",
    "config/ci_shard_duration_hints.json",
)

_SHA_RE = re.compile(r"[0-9a-f]{40}")


class Unavailable(Exception):
    """GitHub or git could not answer. Never a pass."""


class AttestIO(Protocol):
    def gh_pages(self, endpoint: str) -> list: ...

    def git(self, *args: str) -> str: ...

    def download_attestation(self, repo: str, run_id: int) -> dict | None: ...


def flag_enabled(env: dict | None = None) -> bool:
    return str((env if env is not None else os.environ).get(FLAG_ENV, "")).strip() == "1"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _items(pages: list, key: str | None) -> list:
    out: list = []
    for page in pages:
        if key is None:
            if not isinstance(page, list):
                raise Unavailable("invalid_response")
            out.extend(page)
        else:
            if not isinstance(page, dict) or not isinstance(page.get(key), list):
                raise Unavailable("invalid_response")
            out.extend(page[key])
    return out


def required_contexts(io: AttestIO, repo: str) -> list[str]:
    pages = io.gh_pages(f"repos/{repo}/branches/{BASE_BRANCH}/protection/required_status_checks")
    if not pages or not isinstance(pages[0], dict):
        raise Unavailable("protection_unreadable")
    body = pages[0]
    names = set(body.get("contexts") or [])
    names |= {c.get("context") for c in body.get("checks") or [] if c.get("context")}
    return sorted(names)


def source_pr(io: AttestIO, repo: str, merge_sha: str) -> dict:
    pulls = _items(io.gh_pages(f"repos/{repo}/commits/{merge_sha}/pulls?per_page=100"), None)
    hits = [
        p
        for p in pulls
        if p.get("merge_commit_sha") == merge_sha
        and p.get("merged_at")
        and (p.get("base") or {}).get("ref") == BASE_BRANCH
    ]
    if len(hits) != 1:
        raise LookupError("pr_not_found" if not hits else "pr_ambiguous")
    return hits[0]


def latest_check(runs: list[dict], name: str) -> dict | None:
    mine = [c for c in runs if c.get("name") == name and (c.get("app") or {}).get("slug") == CHECK_APP]
    return max(mine, key=lambda c: int(c.get("id") or 0)) if mine else None


def _run_order(run: dict) -> tuple[int, int, int]:
    return (int(run.get("run_number") or 0), int(run.get("id") or 0), int(run.get("run_attempt") or 1))


def attest(merge_sha: str, *, repo: str, io: AttestIO) -> dict:
    """Evaluate (a)-(d). Returns evidence with ``ok`` and ``reasons``; never raises."""
    ev: dict = {
        "schema": SCHEMA,
        "mode": "tree_attested",
        "candidate_sha": merge_sha,
        "repository": repo,
        "ok": False,
        "reasons": [],
        "checked_at": _now(),
    }
    reasons: list[str] = ev["reasons"]
    if not _SHA_RE.fullmatch(merge_sha or ""):
        reasons.append("candidate_sha_must_be_full")
        return ev
    try:
        pr = source_pr(io, repo, merge_sha)
        head = str((pr.get("head") or {}).get("sha") or "")
        ev["pr"] = pr.get("number")
        ev["head_sha"] = head
        if not _SHA_RE.fullmatch(head):
            reasons.append("head_sha_invalid")
            return ev

        # (b) tree equality, and the merge commit's relation to the head (recorded, not required).
        merge_tree = io.git("rev-parse", f"{merge_sha}^{{tree}}")
        head_tree = io.git("rev-parse", f"{head}^{{tree}}")
        ev["tree"] = merge_tree
        ev["head_tree"] = head_tree
        if merge_tree != head_tree:
            reasons.append("tree_differs")
        try:
            ev["merge_second_parent"] = io.git("rev-parse", f"{merge_sha}^2")
        except Unavailable:
            ev["merge_second_parent"] = None

        # (c) workflow + runner files identical, asserted explicitly.
        watched = {}
        for path in WATCHED_PATHS:
            try:
                m_obj = io.git("rev-parse", f"{merge_sha}:{path}")
                h_obj = io.git("rev-parse", f"{head}:{path}")
            except Unavailable:
                reasons.append(f"watched_path_unreadable:{path}")
                continue
            watched[path] = m_obj
            if m_obj != h_obj:
                reasons.append(f"watched_path_differs:{path}")
        ev["watched_objects"] = watched

        # (a) + (d) check runs on the PR head.
        contexts = required_contexts(io, repo)
        ev["required_contexts"] = contexts
        runs = _items(io.gh_pages(f"repos/{repo}/commits/{head}/check-runs?per_page=100"), "check_runs")
        check_ids: dict[str, int] = {}
        for name in sorted(set(contexts) | {AGGREGATE_CHECK}):
            c = latest_check(runs, name)
            if c is None:
                reasons.append(f"check_missing:{name}")
                continue
            check_ids[name] = int(c.get("id") or 0)
            if c.get("head_sha") not in (None, head):
                reasons.append(f"check_head_mismatch:{name}")
            if c.get("status") != "completed" or c.get("conclusion") != "success":
                reasons.append(f"check_not_successful:{name}")
        ev["check_run_ids"] = check_ids

        # (a) the aggregate check belongs to the sharded workflow's latest run for H.
        gate = latest_check(runs, AGGREGATE_CHECK)
        if gate is not None:
            suite_id = (gate.get("check_suite") or {}).get("id")
            wf_runs = _items(io.gh_pages(f"repos/{repo}/actions/runs?head_sha={head}&per_page=100"), "workflow_runs")
            sharded = [
                r
                for r in wf_runs
                if str(r.get("path") or "").split("@", 1)[0] == SHARDED_WORKFLOW and r.get("head_sha") == head
            ]
            run = next((r for r in sharded if r.get("check_suite_id") == suite_id), None)
            if run is None:
                reasons.append("aggregate_run_not_found")
            else:
                ev["workflow_run_id"] = int(run["id"])
                ev["workflow_run_attempt"] = int(run.get("run_attempt") or 1)
                if run.get("status") != "completed" or run.get("conclusion") != "success":
                    reasons.append("aggregate_run_not_successful")
                if max(sharded, key=_run_order) is not run:
                    reasons.append("aggregate_run_superseded")
                att = io.download_attestation(repo, int(run["id"]))
                ev["attestation"] = att
                if not isinstance(att, dict) or att.get("schema") != ATTESTATION_SCHEMA:
                    reasons.append("attestation_missing")
                else:
                    if att.get("head_sha") != head:
                        reasons.append("attestation_head_mismatch")
                    if att.get("tested_tree") != merge_tree:
                        reasons.append("attestation_tree_mismatch")
                    if att.get("ok") is not True:
                        reasons.append("attestation_not_ok")
    except LookupError as exc:
        reasons.append(str(exc))
    except Unavailable as exc:
        reasons.append("unavailable:" + str(exc)[:80])
    except (KeyError, TypeError, ValueError) as exc:
        reasons.append("unavailable:" + type(exc).__name__)
    ev["ok"] = not reasons
    return ev


def build_attestation(git, *, ok: bool, run_id: str | None, run_attempt: str | None, summary: dict) -> dict:
    """Written by the ``ci-gate`` job (artifact ``ci-gate-attestation``) on the tested checkout."""
    return {
        "schema": ATTESTATION_SCHEMA,
        "head_sha": git("rev-parse", "HEAD"),
        "tested_tree": git("rev-parse", "HEAD^{tree}"),
        "watched_objects": {p: git("rev-parse", f"HEAD:{p}") for p in WATCHED_PATHS},
        "ok": bool(ok),
        "run_id": run_id,
        "run_attempt": run_attempt,
        "expected_files": summary.get("expected_files"),
        "ran_files": summary.get("ran_files"),
        "at": _now(),
    }


# ---------------------------------------------------------------------------
# Real IO: gh + git subprocesses (the tests use a fake)
# ---------------------------------------------------------------------------


class SubprocessIO:
    def __init__(self, root: Path, runner=None):
        self.root = Path(root)
        self.run = runner or subprocess.run

    def gh_pages(self, endpoint: str) -> list:
        try:
            proc = self.run(["gh", "api", "--paginate", endpoint], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.SubprocessError) as exc:
            raise Unavailable(type(exc).__name__) from None
        if proc.returncode != 0:
            raise Unavailable("gh_api_failed")  # stderr is never copied (may hold host diagnostics)
        decoder = json.JSONDecoder()
        remaining = (proc.stdout or "").strip()
        pages = []
        while remaining:
            try:
                page, end = decoder.raw_decode(remaining)
            except ValueError:
                raise Unavailable("invalid_response") from None
            pages.append(page)
            remaining = remaining[end:].lstrip()
        if not pages:
            raise Unavailable("empty_response")
        return pages

    def git(self, *args: str) -> str:
        try:
            proc = self.run(["git", "-C", str(self.root), *args], capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as exc:
            raise Unavailable(type(exc).__name__) from None
        out = (proc.stdout or "").strip()
        if proc.returncode != 0 or not out:
            raise Unavailable("git_failed")
        return out

    def download_attestation(self, repo: str, run_id: int) -> dict | None:
        with tempfile.TemporaryDirectory(prefix="ci-gate-attest-") as tmp:
            try:
                proc = self.run(
                    ["gh", "run", "download", str(int(run_id)), "-R", repo, "-n", ATTESTATION_ARTIFACT, "-D", tmp],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
            except (OSError, subprocess.SubprocessError):
                return None
            path = Path(tmp) / ATTESTATION_FILE
            if proc.returncode != 0 or not path.is_file():
                return None
            try:
                body = json.loads(path.read_text(encoding="utf-8"))
            except ValueError:
                return None
            return body if isinstance(body, dict) else None


def repository_from_remote(io: AttestIO) -> str:
    remote = io.git("remote", "get-url", "origin")
    m = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([\w.-]+/[\w.-]+?)(?:\.git)?", remote)
    if not m:
        raise Unavailable("unsupported_repository")
    return m.group(1)


def collect(merge_sha: str, *, root: Path, io: AttestIO | None = None) -> dict:
    io = io or SubprocessIO(root)
    try:
        repo = repository_from_remote(io)
    except Unavailable as exc:
        return {
            "schema": SCHEMA,
            "mode": "tree_attested",
            "candidate_sha": merge_sha,
            "ok": False,
            "reasons": ["unavailable:" + str(exc)],
            "checked_at": _now(),
        }
    return attest(merge_sha, repo=repo, io=io)


def backstop_status(push_evidence: dict) -> tuple[str, int]:
    """Classify the push/main evidence for a tree-attested release: green 0, pending 2, red 3."""
    if push_evidence.get("ok"):
        return "green", 0
    if any(str(e).startswith("checks_unavailable") for e in push_evidence.get("errors") or []):
        return "unavailable", 2
    finished_bad = [
        c
        for c in push_evidence.get("checks") or []
        if c.get("status") == "completed" and c.get("conclusion") != "success"
    ]
    return ("red", 3) if finished_bad else ("pending", 2)
