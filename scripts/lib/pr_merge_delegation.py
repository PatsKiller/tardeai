"""Manual exact-head coordinator merge, inert until trusted main ratifies policy30.

No daemon, operator-label write, notification, deployment or broker import. Review
registration is a coordinator's manual identity/provenance check, NOT cryptographic
identity or operator approval. Raw artifacts are pinned and re-read. The GitHub
login shared by several coding agents is never an independent reviewer identity.

CLI defaults to a read-only plan: --pr N --actor-session SESSION [--apply].
Registration: coordinator/review-evidence/<PR>-<full-head>.json. Only --apply
can reach a writable lock/ledger or the exact-head squash merge subprocess.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import fnmatch
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import re
import stat
import subprocess
import sys
from zoneinfo import ZoneInfo

REPO = "PatsKiller/tardeai"
TRUSTED_REPO = Path("/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild")
STATE = Path(pwd.getpwuid(os.getuid()).pw_dir) / "trade-ai-releases/persistent-state/data/coordination"
SCHEMA = "PrMergeDelegationApproval@v1"
EVIDENCE_SCHEMA = "PrMergeReviewEvidence@v1"
MAX_BYTES = 2 * 1024 * 1024
SHA = re.compile(r"[0-9a-f]{40}")
HASH = re.compile(r"[0-9a-f]{64}")
SESSION = re.compile(r"[A-Za-z0-9_./:-]{3,160}")
RESERVED = ("AGENTS.md", "AI_WORK_POLICY.md", "CLAUDE.md", "GEMINI.md", ".goosehints",
            ".cursor/rules/*", ".github/copilot-instructions.md", "config/agent_standing_authority.json",
            ".cursor/hooks/guard_standing_policy.py", "scripts/lib/pr_merge_delegation.py",
            "config/merge_hold_paths.json", "scripts/lib/merge_hold_paths.py")
OPERATOR_ONLY = ("scripts/brokers/*", "scripts/active_trader/*", "scripts/moomoo/*", "scripts/schwab_*",
                 "scripts/lib/schwab_*", "scripts/broker_*", "scripts/lib/broker*", "scripts/*order_intent*",
                 "scripts/lib/*order_intent*", "scripts/*execution_guard*", "scripts/lib/*execution_guard*",
                 "scripts/alpaca_*stop*", "scripts/defense_execution.py", "apps/broker-admin/*",
                 "config/active_trader*", "config/secret_registry.yaml", ".env", ".env.*", "*/.env", "*/.env.*",
                 "config/*branch*protection*", ".github/settings*", "scripts/*branch*protection*",
                 "scripts/lib/trading_lock.py", "scripts/lib/trading_session_grant.py")
DECISION_PATHS = ("config/lane_registry.json", "config/data_source_authority.json", "config/n8n_relay_live*.json",
                  "config/n8n_live*.json", "config/*access_mode*", "config/*kill_switch*", "config/*risk_policy*")
IDENTITY_LIMIT = "Manual coordinator mapping of real agent sessions against claims/source; not cryptographic authentication."


class Refused(RuntimeError):
    """A fixed safe reason code; no stderr or raw artifact contents."""


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def text_id(value):
    return isinstance(value, str) and bool(SESSION.fullmatch(value))


def full_sha(value):
    return isinstance(value, str) and bool(SHA.fullmatch(value))


def safe_read(path, *, dir_fd=None):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=dir_fd)
        with os.fdopen(fd, "rb") as stream:
            st = os.fstat(stream.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or st.st_size > MAX_BYTES:
                raise Refused("evidence_path_unsafe")
            data = stream.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise Refused("evidence_oversized")
            return data
    except OSError as exc:
        raise Refused("evidence_unavailable") from exc


def json_read(path):
    try:
        value = json.loads(safe_read(path))
    except (ValueError, UnicodeError) as exc:
        raise Refused("evidence_json_invalid") from exc
    if not isinstance(value, dict):
        raise Refused("evidence_shape_invalid")
    return value


def path_ok(value):
    return isinstance(value, str) and value and not value.startswith("/") and "\\" not in value and all(
        p not in {"", ".", ".."} for p in value.split("/"))


def hits(path, patterns):
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def overlaps(path, claimed):
    return path == claimed or path.startswith(claimed.rstrip("/") + "/") or claimed.startswith(path + "/") or hits(path, [claimed])


def freeze(now):
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise Refused("clock_invalid")
    local = now.astimezone(ZoneInfo("America/New_York"))
    return local.weekday() < 5 and (9, 30) <= (local.hour, local.minute) < (16, 15)


def reviewer_artifact(raw):
    """Strict machine fields or one canonical full-SHA line; ambiguity fails closed."""
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        try:
            lines = re.findall(r"^Adversarial-review: MERGE reviewer=(\S+) head=([0-9a-f]{40})$", raw.decode(), re.M)
        except UnicodeError as exc:
            raise Refused("review_artifact_invalid") from exc
        if len(lines) != 1:
            raise Refused("review_artifact_ambiguous")
        return {"reviewer": lines[0][0], "head_sha": lines[0][1], "verdict": "MERGE"}
    if not isinstance(value, dict):
        raise Refused("review_artifact_invalid")
    heads = [value[k] for k in ("head_sha", "head", "source_commit") if k in value]
    reviewers = [value[k] for k in ("reviewer_session", "reviewer") if k in value]
    if not heads or any(not full_sha(head) for head in heads) or len(set(heads)) != 1:
        raise Refused("review_artifact_ambiguous")
    if not reviewers or any(not text_id(reviewer) for reviewer in reviewers) or len(set(reviewers)) != 1:
        raise Refused("review_artifact_ambiguous")
    return {"reviewer": reviewers[0], "head_sha": heads[0], "verdict": value.get("verdict")}


def evaluate(snapshot, *, now):
    """Pure decision over freshly collected, trusted-source evidence. No authority minting."""
    try:
        authority = snapshot.get("authority")
        if not isinstance(authority, dict) or authority.get("ok") is not True:
            raise Refused("standing_authority_not_active")
        provenance = authority.get("authority")
        if not isinstance(provenance, dict) or provenance.get("capability") != "coordinator_merge" or not full_sha(provenance.get("policy_sha")):
            raise Refused("standing_authority_provenance_invalid")
        requirements = provenance.get("requirements")
        if (not isinstance(requirements, dict) or type(requirements.get("ordinary_reviews")) is not int
                or requirements["ordinary_reviews"] < 1 or type(requirements.get("held_reviews")) is not int
                or requirements["held_reviews"] < 2):
            raise Refused("review_requirements_invalid")
        pr, role, evidence = snapshot["pr"], snapshot["coordinators"], snapshot["evidence"]
        actor = snapshot["actor_session"]
        if not text_id(actor) or not isinstance(role, dict):
            raise Refused("actor_identity_invalid")
        rows = role.get("coordinators")
        if role.get("schema") != "CoordinatorRegistry@v1" or not isinstance(rows, list):
            raise Refused("coordinator_registry_invalid")
        leads = [r for r in rows if isinstance(r, dict) and r.get("id") == role.get("lead")]
        if len(leads) != 1 or not text_id(role.get("lead")) or leads[0].get("role") != "lead":
            raise Refused("current_release_lead_missing")
        lead = leads[0]
        territories = lead.get("territories")
        if (not isinstance(territories, list) or any(not isinstance(value, str) for value in territories)
                or "release" not in territories or not isinstance(lead.get("vendor"), str) or not lead["vendor"]):
            raise Refused("current_release_lead_missing")
        claims = snapshot["claims"]
        actor_claims = [c for c in claims if c.get("session") == actor and c.get("status") == "active"
                        and c.get("vendor") == lead.get("vendor") and any(
                            isinstance(p, str) and p.endswith("coordination/coordinator/coordinators.json") for p in c.get("paths", []))]
        if len(actor_claims) != 1 or actor_claims[0].get("schema") != "AgentClaim@v1" or (lead.get("session") is not None and lead["session"] != actor):
            raise Refused("actor_not_registered_coordinator_holder")
        if freeze(now):
            raise Refused("market_operating_freeze_use_existing_urgent_route")
        head = pr.get("headRefOid")
        if not full_sha(head) or type(pr.get("number")) is not int or pr["number"] < 1:
            raise Refused("pr_identity_invalid")
        if pr.get("state") != "OPEN" or pr.get("baseRefName") != "main" or pr.get("isDraft") is not False:
            raise Refused("pr_not_ready_open_main")
        if pr.get("mergeable") != "MERGEABLE" or pr.get("mergeStateStatus") not in {"CLEAN", "HAS_HOOKS"}:
            raise Refused("pr_mergeability_not_proven")
        files = pr.get("files")
        if not isinstance(files, list) or not files or any(not path_ok(p) for p in files) or len(files) != len(set(files)) or pr.get("changedFiles") != len(files):
            raise Refused("changed_files_incomplete")
        prior_paths = pr.get("prior_paths", [])
        if not isinstance(prior_paths, list) or any(not path_ok(path) for path in prior_paths):
            raise Refused("prior_file_paths_incomplete")
        effective_files = sorted(set([*files, *prior_paths]))
        excluded = snapshot.get("excluded_globs")
        if not isinstance(excluded, list) or any(not isinstance(p, str) or not p for p in excluded):
            raise Refused("merge_exclusions_invalid")
        if any(hits(p, (*RESERVED, *OPERATOR_ONLY, *excluded)) for p in effective_files):
            raise Refused("operator_only_or_delegation_definition_path")
        if any(hits(p, DECISION_PATHS) for p in effective_files):
            raise Refused("applicable_section17_decision_required")
        if snapshot.get("checks", {}).get("ok") is not True:
            raise Refused("exact_head_checks_not_green")
        if snapshot.get("checks_head") != head:
            raise Refused("checks_head_mismatch")
        if evidence.get("schema") != EVIDENCE_SCHEMA or evidence.get("pr") != pr["number"] or evidence.get("head_sha") != head:
            raise Refused("registration_head_mismatch")
        if evidence.get("registered_by") != {"actor": lead["id"], "session": actor} or evidence.get("identity_provenance") != "manual_coordinator_claim_and_source_check":
            raise Refused("registration_identity_provenance_missing")
        commit_shas = pr.get("commit_shas")
        if not isinstance(commit_shas, list) or not commit_shas or any(not full_sha(v) for v in commit_shas) or evidence.get("source_commit_shas") != commit_shas:
            raise Refused("source_authorship_coverage_unproven")
        authors = evidence.get("authors")
        if not isinstance(authors, list) or not authors:
            raise Refused("authors_missing")
        author_sessions = set()
        for author in authors:
            if not isinstance(author, dict) or not text_id(author.get("actor")) or not text_id(author.get("session")):
                raise Refused("author_identity_invalid")
            found = [c for c in claims if c.get("claim_id") == author.get("claim_id") and c.get("session") == author["session"]]
            if len(found) != 1 or found[0].get("schema") != "AgentClaim@v1" or found[0].get("status") not in {"done", "released"} or found[0].get("head_sha") not in [head, *commit_shas]:
                raise Refused("author_holder_release_unproven")
            if not any(overlaps(p, cp) for p in effective_files for cp in found[0].get("paths", []) if isinstance(cp, str)):
                raise Refused("author_claim_does_not_cover_source")
            if author["session"] in author_sessions:
                raise Refused("author_identity_duplicate")
            author_sessions.add(author["session"])
        for claim in claims:
            if claim.get("status") == "active" and any(overlaps(p, cp) for p in effective_files for cp in claim.get("paths", []) if isinstance(cp, str)):
                raise Refused("current_source_holder_not_released")
        reviews = evidence.get("reviews")
        if not isinstance(reviews, list) or not reviews:
            raise Refused("independent_reviews_missing")
        reviewers, proof = set(), []
        for review in reviews:
            if not isinstance(review, dict) or not text_id(review.get("reviewer_session")):
                raise Refused("reviewer_identity_invalid")
            session = review["reviewer_session"]
            if session in author_sessions or session == actor or session in reviewers:
                raise Refused("reviewer_not_independent")
            if review.get("head_sha") != head or review.get("verdict") != "MERGE" or not isinstance(review.get("artifact_sha256"), str) or not HASH.fullmatch(review["artifact_sha256"]):
                raise Refused("review_not_exact_head_merge")
            raw = snapshot["review_artifacts"].get(review.get("artifact"))
            if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != review["artifact_sha256"]:
                raise Refused("review_artifact_hash_mismatch")
            parsed = reviewer_artifact(raw)
            if parsed != {"reviewer": session, "head_sha": head, "verdict": "MERGE"}:
                raise Refused("review_artifact_fields_mismatch")
            reviewers.add(session)
            proof.append({"reviewer_session": session, "artifact_sha256": review["artifact_sha256"]})
        held = snapshot.get("held")
        if type(held) is not bool:
            raise Refused("held_classification_unavailable")
        required = requirements["held_reviews"] if held else requirements["ordinary_reviews"]
        if len(reviewers) < required:
            raise Refused("independent_review_count_insufficient")
        bound = {"pr": pr["number"], "head_sha": head, "files": files, "prior_paths": prior_paths, "commit_shas": commit_shas,
                 "actor_session": actor, "coordinator": lead, "authority": authority["authority"],
                 "review_proof": proof, "registration_sha256": snapshot["registration_sha256"],
                 "held": held, "claims": [{k: c.get(k) for k in ("claim_id", "session", "status", "head_sha", "paths")} for c in claims]}
        return {"ok": True, "reason": "qualified", "head_sha": head, "pr": pr["number"], "actor": lead["id"],
                "actor_session": actor, "held": held, "required_reviews": required, "review_proof": proof,
                "authority": authority["authority"], "fingerprint": digest(bound), "identity_limit": IDENTITY_LIMIT,
                "would_merge": ["gh", "pr", "merge", str(pr["number"]), "--repo", REPO, "--squash", "--match-head-commit", head]}
    except (Refused, KeyError, TypeError, ValueError, AttributeError) as exc:
        return {"ok": False, "reason": str(exc) if isinstance(exc, Refused) else "critical_evidence_invalid", "would_merge": None}


class Host:
    """Fixed trusted host sources; injection exists only on the Python test API."""
    def __init__(self):
        self.repo, self.state = TRUSTED_REPO, STATE

    def command(self, args):
        try:
            cp = subprocess.run(args, cwd=self.repo, capture_output=True, text=True, timeout=60, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            raise Refused("read_transport_unavailable") from exc
        if cp.returncode:
            raise Refused("read_command_refused")
        return cp.stdout

    def gh(self, args):
        try:
            return json.loads(self.command(["gh", *args]))
        except ValueError as exc:
            raise Refused("github_metadata_invalid") from exc

    def git(self, *args):
        return self.command(["git", *args]).strip()

    def helper(self, path, sha):
        raw = self.git("show", f"{sha}:{path}").encode()
        location = self.repo / path
        if safe_read(location).strip() != raw.strip():
            raise Refused("trusted_helper_dirty_or_not_main")
        spec = importlib.util.spec_from_file_location("standing_merge_" + digest([sha, path]), location)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        prior = sys.dont_write_bytecode
        try:
            sys.dont_write_bytecode = True
            spec.loader.exec_module(module)
        finally:
            sys.dont_write_bytecode = prior
        return module

    def collect(self, pr_number, actor_session):
        sha = self.git("rev-parse", "refs/remotes/origin/main")
        if not full_sha(sha) or self.git("rev-parse", "HEAD") != sha or self.gh(["api", f"repos/{REPO}/commits/main"])["sha"] != sha:
            raise Refused("trusted_canonical_main_not_current")
        policy = self.git("show", f"{sha}:AGENTS.md")
        manifest = json.loads(self.git("show", f"{sha}:config/agent_standing_authority.json"))
        authority_helper = self.helper(".cursor/hooks/guard_standing_policy.py", sha)
        authority = authority_helper.authorize(policy, manifest, capability="coordinator_merge", policy_sha=sha,
                                               revoked=authority_helper.revoked_marker())
        if authority.get("ok") is not True:
            return {"authority": authority}
        fields = "number,state,isDraft,headRefOid,headRefName,baseRefName,mergeable,mergeStateStatus,files,changedFiles,statusCheckRollup,commits,author,reviews,labels"
        pr = self.gh(["pr", "view", str(pr_number), "--repo", REPO, "--json", fields])
        rest = self.gh(["api", f"repos/{REPO}/pulls/{pr_number}"])
        if not isinstance(rest, dict) or rest.get("head", {}).get("sha") != pr.get("headRefOid"):
            raise Refused("github_head_changed_during_collection")
        commits = pr.get("commits")
        if not isinstance(commits, list) or not commits or len(commits) != rest.get("commits") or len(commits) >= 250:
            raise Refused("source_commits_incomplete")
        pr["commit_shas"] = [r.get("oid") for r in commits if isinstance(r, dict)]
        if len(pr["commit_shas"]) != len(commits):
            raise Refused("source_commits_invalid")
        pr["files"] = [r.get("path") for r in pr.get("files", []) if isinstance(r, dict)]
        if rest.get("changed_files") != len(pr["files"]):
            raise Refused("github_changed_files_incomplete")
        file_rows = self.gh(["api", f"repos/{REPO}/pulls/{pr_number}/files?per_page=100", "--paginate", "--slurp", "--jq",
                             "[.[][] | {filename,previous_filename,status}]"])
        if (not isinstance(file_rows, list) or len(file_rows) != rest["changed_files"] or len(file_rows) >= 3000
                or any(not isinstance(row, dict) or not path_ok(row.get("filename")) for row in file_rows)
                or sorted(row["filename"] for row in file_rows) != sorted(pr["files"])):
            raise Refused("github_prior_paths_incomplete")
        pr["prior_paths"] = []
        for row in file_rows:
            prior = row.get("previous_filename")
            if row.get("status") == "renamed" and not path_ok(prior):
                raise Refused("github_rename_source_missing")
            if prior is not None:
                if not path_ok(prior):
                    raise Refused("github_prior_path_invalid")
                pr["prior_paths"].append(prior)
        checks = self.helper("scripts/lib/pr_all_checks_green.py", sha).evaluate_merge_rollup(pr.get("statusCheckRollup"))
        hold = self.helper("scripts/lib/merge_hold_paths.py", sha)
        hold_config = json.loads(self.git("show", f"{sha}:config/merge_hold_paths.json"))
        labels = pr.get("labels")
        if not isinstance(labels, list) or any(not isinstance(row, dict) or not isinstance(row.get("name"), str) for row in labels):
            raise Refused("pr_labels_incomplete")
        if any(row["name"].lower() in {"hold", "do-not-merge", "operator-hold"} for row in labels):
            raise Refused("explicit_hold_requires_existing_resolution")
        held = bool(hold.held_classes([*pr["files"], *pr["prior_paths"]], hold_config)
                    or {row["name"] for row in labels} & hold.hold_labels(hold_config))
        coordinator = self.state / "coordinator"
        registration = coordinator / "review-evidence" / f"{pr_number}-{pr.get('headRefOid')}.json"
        raw = safe_read(registration)
        evidence = json.loads(raw)
        if not isinstance(evidence, dict):
            raise Refused("registration_shape_invalid")
        artifacts = {}
        for review in evidence.get("reviews", []):
            if not isinstance(review, dict) or not path_ok(review.get("artifact")):
                raise Refused("review_artifact_path_invalid")
            location = coordinator / review["artifact"]
            if not location.resolve().is_relative_to(coordinator.resolve()) or location.is_symlink():
                raise Refused("review_artifact_path_unsafe")
            artifacts[review["artifact"]] = safe_read(location)
        claims = []
        paths = sorted((self.state / "claims").glob("*.json"))
        if not paths or len(paths) > 5000:
            raise Refused("claim_board_unavailable_or_truncated")
        for path in paths:
            claims.append(json_read(path))
        cap = manifest.get("capabilities", {}).get("coordinator_merge", {})
        return {"authority": authority, "pr": pr, "checks": checks, "checks_head": pr.get("headRefOid"),
                "coordinators": json_read(coordinator / "coordinators.json"), "claims": claims,
                "evidence": evidence, "review_artifacts": artifacts, "registration_sha256": hashlib.sha256(raw).hexdigest(),
                "excluded_globs": [*authority["authority"]["reserved_paths"], *cap["excluded_globs"]]
                    if isinstance(cap, dict) and isinstance(cap.get("excluded_globs"), list) else None, "held": held,
                "actor_session": actor_session}

    def ledger_path(self, pr):
        return self.state / "coordinator/merge-delegation" / f"{pr}.jsonl"

    @contextmanager
    def lock(self, pr):
        directory = self.ledger_path(pr).parent
        if directory.parent.resolve() != directory.parent:
            raise Refused("ledger_parent_aliased")
        directory.mkdir(mode=0o700, exist_ok=True)
        parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            fd = os.open(f"{pr}.lock", os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
            with os.fdopen(fd, "a+") as stream:
                st = os.fstat(stream.fileno())
                if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                    raise Refused("ledger_lock_unsafe")
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                self._ledger_parent = parent
                try:
                    yield
                finally:
                    self._ledger_parent = None
        finally:
            os.close(parent)

    def history(self, pr):
        path = self.ledger_path(pr)
        parent = getattr(self, "_ledger_parent", None)
        if parent is None:
            if not path.exists() and not path.is_symlink():
                return []
            raw = safe_read(path)
        else:
            try:
                os.stat(path.name, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                return []
            raw = safe_read(path.name, dir_fd=parent)
        try:
            rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
        except ValueError as exc:
            raise Refused("merge_ledger_invalid") from exc
        if any(not isinstance(row, dict) or row.get("schema") != SCHEMA for row in rows):
            raise Refused("merge_ledger_invalid")
        return rows

    def append(self, pr, event):
        path = self.ledger_path(pr)
        parent = getattr(self, "_ledger_parent", None)
        if parent is None:
            raise Refused("ledger_write_requires_lock")
        fd = os.open(path.name, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent)
        with os.fdopen(fd, "ab") as stream:
            st = os.fstat(stream.fileno())
            if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
                raise Refused("merge_ledger_unsafe")
            stream.write((json.dumps(event, sort_keys=True) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.fsync(parent)

    def merge(self, command):
        try:
            cp = subprocess.run(command, cwd=self.repo, capture_output=True, text=True, timeout=90, check=False)
            return cp.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def merged(self, pr, head):
        doc = self.gh(["pr", "view", str(pr), "--repo", REPO, "--json", "state,headRefOid,mergeCommit,mergedAt"])
        commit = doc.get("mergeCommit")
        sha = commit.get("oid") if isinstance(commit, dict) else None
        if doc.get("state") == "MERGED" and doc.get("headRefOid") == head and full_sha(sha) and doc.get("mergedAt"):
            return sha
        return None


def plan(pr, actor_session, *, adapter=None, now=None):
    adapter = adapter or Host()
    try:
        snapshot = adapter.collect(pr, actor_session)
        if snapshot.get("authority", {}).get("ok") is True and snapshot.get("pr", {}).get("number") != pr:
            raise Refused("requested_pr_identity_mismatch")
        return evaluate(snapshot, now=now or datetime.now(timezone.utc))
    except Refused as exc:
        return {"ok": False, "reason": str(exc), "would_merge": None}
    except (ValueError, TypeError, KeyError, AttributeError):
        return {"ok": False, "reason": "critical_evidence_unavailable", "would_merge": None}


def run(pr, actor_session, *, apply=False, adapter=None, clock=None):
    adapter, clock = adapter or Host(), clock or (lambda: datetime.now(timezone.utc))
    initial = plan(pr, actor_session, adapter=adapter, now=clock())
    initial["dry_run"] = not apply
    if not apply:
        initial["would_write"] = ["per-PR lock", "PrMergeDelegationApproval ledger before exact-head merge"] if initial["ok"] else []
        return initial
    if not initial["ok"]:
        if initial.get("reason") == "pr_not_ready_open_main":
            for prior in adapter.history(pr):
                head, merged = prior.get("head_sha"), prior.get("merge_sha")
                if prior.get("event") == "merged" and full_sha(head) and full_sha(merged) and adapter.merged(pr, head) == merged:
                    return {"ok": True, "reason": "already_merged", "merge_sha": merged, "dry_run": False}
        return initial
    # A read-only plan cannot reach lock, mkdir, append or merge.
    with adapter.lock(pr):
        history = adapter.history(pr)
        if history:
            head = history[0].get("head_sha")
            observed = adapter.merged(pr, head) if full_sha(head) else None
            recorded = [r.get("merge_sha") for r in history if r.get("event") == "merged"]
            if observed and observed in recorded:
                return {"ok": True, "reason": "already_merged", "merge_sha": observed, "dry_run": False}
            return {"ok": False, "reason": "previous_attempt_requires_reconciliation", "dry_run": False}
        final = plan(pr, actor_session, adapter=adapter, now=clock())
        if not final["ok"] or final.get("fingerprint") != initial.get("fingerprint"):
            return {"ok": False, "reason": "critical_evidence_changed", "dry_run": False}
        event = {"schema": SCHEMA, "event": "approved", "pr": pr, "head_sha": final["head_sha"],
                 "at": clock().astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                 "authority": final["authority"], "actor": final["actor"], "actor_session": actor_session,
                 "review_proof": final["review_proof"], "fingerprint": final["fingerprint"],
                 "identity_limit": IDENTITY_LIMIT, "source": "ratified_policy_coordinator_delegation"}
        adapter.append(pr, event)
        # Re-read AFTER durable approval, immediately before mutation. Head is
        # additionally bound by GitHub's --match-head-commit on the actual write.
        last = plan(pr, actor_session, adapter=adapter, now=clock())
        if not last["ok"] or last.get("fingerprint") != final.get("fingerprint"):
            adapter.append(pr, {**event, "event": "refused_changed"})
            return {"ok": False, "reason": "critical_evidence_changed", "dry_run": False}
        submitted = adapter.merge(final["would_merge"])
        try:
            merged = adapter.merged(pr, final["head_sha"])
        except (Refused, ValueError, TypeError, KeyError):
            merged = None
        if not submitted or not merged:
            adapter.append(pr, {**event, "event": "uncertain"})
            return {"ok": False, "reason": "merge_uncertain_do_not_retry", "dry_run": False}
        adapter.append(pr, {**event, "event": "merged", "merge_sha": merged})
        return {"ok": True, "reason": "merged_not_deployed", "head_sha": final["head_sha"], "merge_sha": merged, "dry_run": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", type=int, required=True)
    parser.add_argument("--actor-session", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.pr < 1 or not text_id(args.actor_session):
        parser.error("positive PR and registered actor session required")
    try:
        result = run(args.pr, args.actor_session, apply=args.apply)
    except (Refused, OSError, ValueError):
        result = {"ok": False, "reason": "merge_refused_or_receipt_failure", "dry_run": not args.apply}
    print(json.dumps(result, sort_keys=True))
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
