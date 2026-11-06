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

try:  # repo root on sys.path
    from scripts.lib.agent_claim_board import (
        ClaimBoard, ClaimError, canonical_pattern, patterns_overlap, _segment_regex as claim_segment_regex)
except ImportError:  # scripts/ on sys.path
    from lib.agent_claim_board import (  # type: ignore[no-redef]
        ClaimBoard, ClaimError, canonical_pattern, patterns_overlap, _segment_regex as claim_segment_regex)

REPO = "PatsKiller/tardeai"
TRUSTED_REPO = Path(pwd.getpwuid(os.getuid()).pw_dir) / "trade-ai-v12-rebuild/trade-ai-v12-rebuild"
STATE = Path(pwd.getpwuid(os.getuid()).pw_dir) / "trade-ai-releases/persistent-state/data/coordination"
SCHEMA = "PrMergeDelegationApproval@v1"
EVIDENCE_SCHEMA = "PrMergeReviewEvidence@v1"
MAX_BYTES = 2 * 1024 * 1024
SHA = re.compile(r"[0-9a-f]{40}")
HASH = re.compile(r"[0-9a-f]{64}")
SESSION = re.compile(r"[A-Za-z0-9_./:-]{3,160}")
# The refused path classes live in one module so the Ready-to-merge projection cannot claim readiness
# the evaluator refuses (merge_path_classes.py). Re-exported here for every existing caller.
try:  # package import (scripts.lib.pr_merge_delegation)
    from .merge_path_classes import (
        DECISION_PATHS,
        DECISION_REFUSAL,
        DELEGATION_CONTROL_PATHS,
        OPERATOR_ONLY,
        OPERATOR_ONLY_REFUSAL,
        RESERVED,
        hits,
        path_refusal,
    )
except ImportError:  # scripts/ on sys.path, module loaded by file path (the merge tests do this)
    from lib.merge_path_classes import (  # type: ignore[no-redef]
        DECISION_PATHS,
        DECISION_REFUSAL,
        DELEGATION_CONTROL_PATHS,
        OPERATOR_ONLY,
        OPERATOR_ONLY_REFUSAL,
        RESERVED,
        hits,
        path_refusal,
    )

ENGINEERING_HELD_PATHS = {
    "hooks_guard": (
        ".cursor/hooks/*", ".githooks/*", "scripts/hooks/*", "scripts/githooks/*",
        ".cursor/hooks.json", ".cursor/settings*.json", ".claude/settings*.json", ".codex/config.toml",
        "bin/guard", "bin/agent-push", "install-guardrails.sh", "scripts/install_ai_work_policy.sh",
        "scripts/install_git_hooks.sh", "scripts/install-git-hygiene.sh", "scripts/git_hygiene_guard.sh",
        "scripts/agent_claim_precommit.sh", "scripts/guard_*", "scripts/lib/guard*",
        "scripts/lib/tradeai_push_budget.py", "scripts/lib/hands_off_policy.py",
        "scripts/agent_session_start.py", "scripts/lib/agent_session_receipt.py", "scripts/agent_claim.py",
        "scripts/lib/agent_claim_board.py", "config/agent_clients.yaml",
    ),
    "merge_deploy_control": (
        ".mergify.yml", ".github/workflows/*", "config/ci_gates/*", "config/merge_hold_paths.json",
        "scripts/lib/release_*.py", "scripts/lib/merge_hold_paths.py",
        "config/shared_infra_paths.json", "scripts/check_shared_infra_pr.py",
        "config/pr_merge_digest.json", "scripts/lib/pr_merge*.py", "scripts/pr_merge*.py",
        "scripts/lib/pr_all_checks_green.py", "scripts/request_pr_merge_approve.py",
        "scripts/notify_pr_merge_ready.py", "scripts/agent_merge_pr.sh", "scripts/lib/mergify_queue_monitor.py",
        "scripts/lib/work_pipeline_tier2.py", "scripts/lib/deploy_console_actions.py",
        "scripts/lib/operator_approval*.py", "scripts/admin_write_guard.py", "scripts/telegram_callback_handler.py",
        "scripts/api_v2.py", "scripts/lib/deploy_on_main.py", "scripts/deploy_on_main_poll.py",
        "scripts/*promote*.sh", "config/lane_registry.json",
        "tests/test_guard_standing_policy_20261102.py", "tests/test_pr_merge_delegation_20261102.py",
        "tests/test_pr_all_checks_standing_20261102.py",
    ),
}
# New classes require explicit engineering classification in the trusted source
# registry. A mutable class declaration cannot relax the immutable excluded paths.
DELEGATED_HELD_CLASSES = frozenset({"hooks_guard", "merge_deploy_control"})
NONDELEGATED_HELD_CLASSES = frozenset({"broker_order", "broker", "order", "secrets", "credentials",
                                     "agents_policy", "policy", "branch_protection", "mbi_behavior"})
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


def overlaps(path, claimed):
    return path == claimed or path.startswith(claimed.rstrip("/") + "/") or claimed.startswith(path + "/") or hits(path, [claimed])


def engineering_classes_ok(classes, metadata):
    if not isinstance(metadata, dict):
        return False
    for class_id in classes:
        if class_id in NONDELEGATED_HELD_CLASSES:
            return False
        if class_id not in DELEGATED_HELD_CLASSES:
            row = metadata.get(class_id)
            if not isinstance(row, dict) or row.get("delegation_kind") != "engineering":
                return False
    return True


def collect_held_classes(paths, config, helper):
    """Resolve actual registry classes; never infer engineering from an unknown ID."""
    if not isinstance(config, dict) or config.get("schema") != "MergeHoldPaths@v1":
        raise Refused("held_classification_unavailable")
    rows = config.get("classes")
    if not isinstance(rows, list) or not rows:
        raise Refused("held_classification_unavailable")
    by_id = {}
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]
                or row["id"] in by_id or not isinstance(row.get("globs"), list) or not row["globs"]
                or any(not isinstance(glob, str) or not glob for glob in row["globs"])):
            raise Refused("held_classification_unavailable")
        if row["id"] in DELEGATED_HELD_CLASSES and "delegation_kind" in row and row["delegation_kind"] != "engineering":
            raise Refused("held_classification_unavailable")
        by_id[row["id"]] = row
    matched = helper.held_classes(paths, config)
    if not isinstance(matched, dict) or any(class_id not in by_id for class_id in matched):
        raise Refused("held_classification_unavailable")
    classes = sorted(set(matched) | {class_id for class_id, patterns in ENGINEERING_HELD_PATHS.items()
                                   if any(hits(path, patterns) for path in paths)})
    metadata = {class_id: {"delegation_kind": by_id.get(class_id, {}).get("delegation_kind")}
                for class_id in classes if class_id not in DELEGATED_HELD_CLASSES}
    if not engineering_classes_ok(classes, metadata):
        raise Refused("held_class_not_delegated")
    return classes, metadata


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


RELEASED_CLAIM_STATUSES = frozenset({"done", "abandoned"})


def takeover_links(doc):
    """``(target_id, kind)`` for one claim's ``takeover_of``.

    An UNTAGGED record is the historical meaning: a link written before provenance existed DID declare succession, and
    every record the board wrote before tonight relies on that. Only a record the board explicitly tags ``overlap`` —
    the mechanical "we share a file" link it now writes — is read as shared ancestry rather than succession.
    """
    pairs = []
    for item, target in zip(doc.get("takeover_of") or [], takeover_targets(doc)):
        kind = item.get("kind") if isinstance(item, dict) else None
        pairs.append((target, "overlap" if kind == "overlap" else "containment"))
    return pairs


def takeover_targets(doc):
    """Claim ids named by one claim's ``takeover_of``; a malformed link is the chain refusal."""
    raw = doc.get("takeover_of") or []
    if not isinstance(raw, list):
        raise Refused("claim_takeover_chain_invalid")
    targets = []
    for item in raw:
        target = item.get("claim_id") if isinstance(item, dict) else item
        if not isinstance(target, str) or not target or target in targets:
            raise Refused("claim_takeover_chain_invalid")
        targets.append(target)
    return targets


def claim_is_live(view, board):
    """A raw-active claim whose heartbeat is inside the board's stale window.

    A takeover link never makes a fresh claim stale: a hand-forged ``takeover_of`` naming a
    live claim leaves that claim live and blocking. Supersession is therefore evidence plus
    the predecessor no longer being live, never the board's link-induced staleness alone.
    """
    if view.doc.get("status") != "active":
        return False
    age = view.heartbeat_age_s
    return age is not None and age <= board.stale_after.total_seconds()


ARCHIVE_SCHEMA = "AgentClaimArchive@v1"
#: The archive also carries operator overrides; they are not claims and never resolve a takeover target.
ARCHIVE_NONCLAIM_SCHEMAS = frozenset({"AgentClaimOverride@v1"})
#: FQ-136 / D39 (operator 2026-11-05). A takeover target that is in neither the live views nor the canonical archive is
#: still a hard refusal — EXCEPT when the target's own claim id dates it before this cutoff, i.e. 2026-10-26 exclusive.
#: The archive has no coverage for 2026-10-23..2026-10-25 (70 distinct targets, measured 2026-11-05), so those documents
#: are gone rather than lost; a missing target dated on or after the cutoff may still exist and is still refused.
#: Deliberately a narrow, dated exception: it does not relax cycles, malformed links, live-claimant overlap, archive
#: validation, review counts, claims, holds or checks, and it never resolves a target to a claim — the target stays
#: unknown and unverified, which is why the release is logged rather than silent.
UNKNOWN_TAKEOVER_CUTOFF = datetime(2026, 10, 26, tzinfo=timezone.utc)
#: ``YYYYMMDDThhmmssZ-<vendor>-<hex>`` is the only claim-id shape this repository writes. Anything else is not datable
#: and therefore cannot earn the exception.
CLAIM_ID_STAMP = re.compile(r"^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z-")


def claim_id_datetime(claim_id: str) -> datetime | None:
    """The UTC instant encoded in a claim id, or ``None`` when the id is not in the canonical dated form."""
    match = CLAIM_ID_STAMP.match(claim_id)
    if match is None:
        return None
    try:
        year, month, day, hour, minute, second = (int(part) for part in match.groups())
        return datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
    except ValueError:
        return None


def takeover_target_unknown_is_acceptable(target: str) -> bool:
    """True when a target nobody can account for predates the archive's coverage (FQ-136).

    Only a datable target strictly before ``UNKNOWN_TAKEOVER_CUTOFF`` qualifies. An undatable id, or one dated on/after
    the cutoff, is not acceptable and the caller keeps refusing it.
    """
    stamp = claim_id_datetime(target)
    return stamp is not None and stamp < UNKNOWN_TAKEOVER_CUTOFF
#: What ``ClaimBoard.compact()`` can actually write, paired with the raw status it archives. ``live`` is deliberately
#: absent: compaction must never remove a live holder, so a record that says so is inconsistent or forged. Anything
#: outside these pairs — a missing, unknown or impossible ``state_at_archive``, or a mismatched status — refuses.
ARCHIVE_STATE_PAIRS = frozenset({("stale", "active"), ("done", "done"), ("abandoned", "abandoned")})
#: One archive record. ``claims_history.jsonl`` is append-only and grows without a total bound, so the file itself is
#: streamed and never size-capped; a single line larger than this is a malformed record and refuses.
MAX_ARCHIVE_RECORD_BYTES = 1_048_576


def archived_claims(board) -> dict[str, dict[str, object]]:
    """Canonical archive records by ``claim_id``, validated; ``{}`` when the archive does not exist.

    ``ClaimBoard.compact()`` appends an ``AgentClaimArchive@v1`` wrapper around the original ``AgentClaim@v1`` and
    removes the live file. A predecessor that is gone from the views is durable history only when the archive carries
    a well-formed record whose nested claim names that same ``claim_id`` — absence alone never resolves a target, and
    a malformed/unknown record refuses the whole ledger. Only the ``(state_at_archive, status)`` pairs ``compact()``
    can write are accepted, so a record archived while the claim was still ``live`` — or one with an unknown or
    impossible state — refuses. The file is read strictly line by line and is never size-capped as a whole: an
    append-only archive must keep resolving as it grows, so only a single oversized record is refused.
    Read-only: the archive is never written.
    """
    path = getattr(board, "history", None)
    if path is None:
        return {}
    out: dict[str, dict[str, object]] = {}
    try:
        handle = Path(path).open("rb")
    except FileNotFoundError:
        return {}
    except OSError:
        raise Refused("claim_takeover_chain_invalid") from None
    with handle:
        while True:
            try:
                raw = handle.readline(MAX_ARCHIVE_RECORD_BYTES + 1)
            except OSError:
                raise Refused("claim_takeover_chain_invalid") from None
            if not raw:
                break
            if len(raw) > MAX_ARCHIVE_RECORD_BYTES or not raw.endswith(b"\n"):
                raise Refused("claim_takeover_chain_invalid")  # one record larger than any compaction writes
            if not raw.strip():
                continue
            try:
                line = raw.decode("utf-8")
                rec = json.loads(line)
            except (UnicodeDecodeError, ValueError):
                raise Refused("claim_takeover_chain_invalid") from None
            if not isinstance(rec, dict):
                raise Refused("claim_takeover_chain_invalid")
            schema = rec.get("schema")
            if schema in ARCHIVE_NONCLAIM_SCHEMAS:
                continue
            claim = rec.get("claim")
            if (schema != ARCHIVE_SCHEMA or not isinstance(claim, dict) or claim.get("schema") != "AgentClaim@v1"
                    or not isinstance(claim.get("claim_id"), str) or not claim["claim_id"]):
                raise Refused("claim_takeover_chain_invalid")
            state, status = rec.get("state_at_archive"), claim.get("status")
            if (state, status) not in ARCHIVE_STATE_PAIRS:
                raise Refused("claim_takeover_chain_invalid")
            out[claim["claim_id"]] = {"status": status, "state_at_archive": state}
    return out


def claim_shared_paths(config):
    """Exact shared-additive scopes from Host's main-SHA blob, never an env override."""
    if not isinstance(config, dict) or config.get("schema") != "AgentClaimSharedPaths@v1":
        return frozenset()
    rows = config.get("paths")
    if not isinstance(rows, list):
        return frozenset()
    shared = set()
    for row in rows:
        try:
            path = canonical_pattern(row["path"])
        except (ClaimError, KeyError, TypeError, ValueError):
            continue
        if not any(char in path for char in "*?["):
            shared.add(path)
    return frozenset(shared)


def validate_takeover_graph(views, board, shared_config=None):
    """Refuse a takeover graph that is ambiguous or unreadable.

    Chain-invalid: cycles, unknown targets, duplicate/malformed entries, and currently live claimants naming the
    same predecessor whose exclusive path scopes overlap (or cannot be read). Disjoint live siblings are valid:
    the board records inherited links mechanically. A released or non-live sibling is durable
    history, not ambiguity — and a predecessor that compaction removed from the views is durable history only when the
    canonical archive records it as released; a target nobody can account for still refuses.
    """
    by_id = {view.claim_id: view for view in views}
    edges = {}
    for view in views:
        targets = takeover_targets(view.doc)
        if targets:
            edges[view.claim_id] = targets
    archived: dict[str, dict[str, object]] | None = None
    unknown_takeover_targets: list[tuple[str, str]] = []
    for source, targets in edges.items():
        for target in targets:
            if target in by_id:
                continue
            if archived is None:
                archived = archived_claims(board)
            if target not in archived:
                # FQ-136 / D39: a target dated before the archive's coverage is UNKNOWN, not invalid. It is never
                # resolved to a claim — the edge stays unverifiable — so the release is recorded, attributably.
                if takeover_target_unknown_is_acceptable(target):
                    unknown_takeover_targets.append((source, target))
                    continue
                raise Refused("claim_takeover_chain_invalid")
    colour = {}

    def visit(node):
        colour[node] = "grey"
        for nxt in edges.get(node, ()):
            if colour.get(nxt) == "grey":
                raise Refused("claim_takeover_chain_invalid")
            if colour.get(nxt) is None:
                visit(nxt)
        colour[node] = "black"

    for node in edges:
        if colour.get(node) is None:
            visit(node)
    # FQ-136: released, but never silent. One line per unknown edge, on stderr so the CLI's JSON stdout stays parseable.
    for source, target in unknown_takeover_targets:
        print(
            f"pr_merge_delegation: warning: takeover target {target} (named by {source}) is in neither the live board "
            f"nor the archive and predates {UNKNOWN_TAKEOVER_CUTOFF.date().isoformat()}; treated as UNKNOWN, not invalid "
            "(FQ-136/D39)",
            file=sys.stderr,
        )
    live = {view.claim_id: claim_is_live(view, board) for view in views}
    claimants = {}
    for source in edges:
        if not live.get(source):
            continue
        # Only a link that DECLARES succession makes two live claims rivals for one predecessor. A mere shared file
        # (``overlap``) is history for the state resolver and never a claim of exclusive succession — the docstring's
        # own line, now enforced instead of assumed.
        for target, kind in takeover_links(by_id[source].doc):
            if kind in ("containment", "explicit"):
                claimants.setdefault(target, set()).add(source)
    # _claim_locked mechanically records EVERY overlapping stale predecessor.
    # Shared ancestry alone is not a declaration of exclusive succession.
    shared = claim_shared_paths(shared_config)
    scopes = {}
    for sources in claimants.values():
        if len(sources) < 2:
            continue
        ordered = sorted(sources)
        try:
            for source in ordered:
                if source in scopes:
                    continue
                raw = by_id[source].doc.get("paths")
                if not isinstance(raw, list) or not raw:
                    raise Refused("claim_takeover_chain_invalid")
                canonical = [canonical_pattern(path) for path in raw]
                for path in canonical:
                    for segment in path.split("/"):
                        claim_segment_regex(segment)  # validate before disjoint prefixes can short-circuit
                scopes[source] = [path for path in canonical if path not in shared]
            for index, left in enumerate(ordered):
                for right in ordered[index + 1:]:
                    if any(patterns_overlap(a, b) for a in scopes[left] for b in scopes[right]):
                        raise Refused("claim_takeover_chain_invalid")
        except (ClaimError, TypeError, ValueError, re.error):
            raise Refused("claim_takeover_chain_invalid") from None


def effective_claim_states(claims, board, shared_config=None):
    """Classify snapshot claims with the canonical ``ClaimBoard.views()`` resolver.

    released   : raw status in {done, abandoned}
    live       : raw active and heartbeat inside the board's stale window (a forged link
                 naming a live claim never defeats it)
    superseded : raw active, not live, named by a well-formed ``takeover_of`` entry from any
                 claim (a released successor's link is durable and keeps the predecessor
                 superseded rather than reverting it to ``unresolved``)
    unresolved : raw active, not live and not superseded (age alone never resolves)

    Without a board (synthetic snapshots) the historical raw-status reading is kept: raw
    ``active`` is treated as live, everything else as released.
    """
    if board is None:
        return {claim.get("claim_id"): ("live" if claim.get("status") == "active" else "released")
                for claim in claims}
    views, unreadable = board.views()
    if unreadable:
        raise Refused("claim_board_unavailable_or_truncated")
    validate_takeover_graph(views, board, shared_config)
    by_id = {view.claim_id: view for view in views}
    live = {view.claim_id: claim_is_live(view, board) for view in views}
    named = set()
    for view in views:
        named.update(takeover_targets(view.doc))
    states = {}
    for claim in claims:
        claim_id = claim.get("claim_id")
        view = by_id.get(claim_id)
        status = claim.get("status")
        if status in RELEASED_CLAIM_STATUSES:
            states[claim_id] = "released"
        elif view is None:
            states[claim_id] = "unresolved" if status == "active" else "released"
        elif live.get(claim_id):
            states[claim_id] = "live"
        elif status == "active" and claim_id in named:
            states[claim_id] = "superseded"
        else:
            states[claim_id] = "unresolved"
    return states


def evaluate(snapshot, *, now, claim_board=None):
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
        # Effective state comes from the canonical board resolver, never raw status alone. The
        # board is read-only here: views() only reads claim files and lifecycle sidecars.
        board = claim_board if claim_board is not None else snapshot.get("claim_board")
        if board is None and snapshot.get("claim_board_dir"):
            board = ClaimBoard(snapshot["claim_board_dir"], now=lambda: now)
        states = effective_claim_states(claims, board, snapshot.get("claim_shared_paths_config"))
        actor_candidates = [c for c in claims if c.get("session") == actor
                            and c.get("vendor") == lead.get("vendor") and any(
                                isinstance(p, str) and p.endswith("coordination/coordinator/coordinators.json") for p in c.get("paths", []))]
        actor_claims = [c for c in actor_candidates if states.get(c.get("claim_id")) == "live"]
        if len(actor_claims) != 1 or actor_claims[0].get("schema") != "AgentClaim@v1" or (lead.get("session") is not None and lead["session"] != actor):
            if any(states.get(c.get("claim_id")) == "superseded" for c in actor_candidates):
                raise Refused("actor_holder_superseded")
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
        refusal = path_refusal(effective_files, operator_only_extra=excluded)
        if refusal is not None:
            raise Refused(refusal)
        if evidence.get("section17_review_completed") is not True:
            raise Refused("section17_review_unproven")
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
        authorship_hash = evidence.get("source_authorship_sha256")
        if (evidence.get("authors_and_coauthors_complete") is not True or not isinstance(authorship_hash, str)
                or not HASH.fullmatch(authorship_hash) or authorship_hash != snapshot.get("source_authorship_sha256")):
            raise Refused("source_authorship_manual_completeness_unproven")
        shared = snapshot.get("shared_infra")
        if not isinstance(shared, dict) or type(shared.get("required")) is not bool:
            raise Refused("shared_infra_classification_unavailable")
        if shared["required"] and (shared.get("ok") is not True or evidence.get("shared_infra_isolated_reviewed") is not True):
            raise Refused("shared_infra_evidence_unproven")
        if evidence.get("authority_rails_unchanged") is not True:
            raise Refused("reporting_workflow_no_weakening_attestation_missing")
        authors = evidence.get("authors")
        if not isinstance(authors, list) or not authors:
            raise Refused("authors_missing")
        author_sessions, covered_paths = set(), set()
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
            covered_paths.update(path for path in effective_files if any(overlaps(path, cp) for cp in found[0].get("paths", []) if isinstance(cp, str)))
        if covered_paths != set(effective_files):
            raise Refused("source_author_claim_coverage_incomplete")
        # Shared-additive custody is nonexclusive, from the same main-SHA config used by the graph.
        # This applies only AFTER actual authors have released and covered every effective source path.
        shared_paths = claim_shared_paths(snapshot.get("claim_shared_paths_config"))
        try:
            exclusive_files = [p for p in map(canonical_pattern, effective_files) if p not in shared_paths]
            for claim in claims:
                # A superseded predecessor no longer holds its files; released claims already freed them.
                if not exclusive_files or states.get(claim.get("claim_id")) not in {"live", "unresolved"}:
                    continue
                scopes = [canonical_pattern(cp) for cp in claim.get("paths", []) if isinstance(cp, str)]
                # Preserve the holder gate's existing exclusive overlap semantics (including fnmatch globs).
                if any(overlaps(p, cp) for p in exclusive_files for cp in scopes if cp not in shared_paths):
                    raise Refused("current_source_holder_not_released")
        except ClaimError:
            raise Refused("current_source_holder_not_released") from None
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
        held_classes = snapshot.get("held_classes")
        if (type(held) is not bool or not isinstance(held_classes, list)
                or any(not isinstance(value, str) for value in held_classes)
                or len(set(held_classes)) != len(held_classes) or held != bool(held_classes)):
            raise Refused("held_classification_unavailable")
        floor_classes = {class_id for class_id, patterns in ENGINEERING_HELD_PATHS.items()
                         if any(hits(path, patterns) for path in effective_files)}
        if not floor_classes.issubset(held_classes):
            raise Refused("held_classification_unavailable")
        if not engineering_classes_ok(held_classes, snapshot.get("held_class_metadata", {})):
            raise Refused("held_class_not_delegated")
        if held and (evidence.get("engineering_tests_completed") is not True
                     or evidence.get("engineering_docs_completed") is not True):
            raise Refused("held_engineering_completion_unproven")
        required = requirements["held_reviews"] if held else requirements["ordinary_reviews"]
        if len(reviewers) < required:
            raise Refused("independent_review_count_insufficient")
        bound = {"pr": pr["number"], "head_sha": head, "files": files, "prior_paths": prior_paths, "commit_shas": commit_shas,
                 "actor_session": actor, "coordinator": lead, "authority": authority["authority"],
                 "review_proof": proof, "registration_sha256": snapshot["registration_sha256"],
                 "source_authorship_sha256": snapshot["source_authorship_sha256"], "shared_infra": shared,
                 "held": held, "held_classes": held_classes,
                 "held_class_metadata": snapshot.get("held_class_metadata", {}), "claims": [{k: c.get(k) for k in ("claim_id", "session", "status", "head_sha", "paths")} for c in claims]}
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
            cp = subprocess.run(args, cwd=self.repo, capture_output=True, text=True, timeout=60, check=False)  # noqa: S603 -- internal fixed git/gh argv; no shell text
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

    def pr_file_rows(self, pr_number, expected):
        """Plain API GETs supported by the installed gh; bound to the known count."""
        if type(expected) is not int or not 1 <= expected <= 3000:
            raise Refused("github_changed_files_incomplete")
        rows, seen = [], set()
        for page in range(1, (expected + 99) // 100 + 1):
            chunk = self.gh(["api", f"repos/{REPO}/pulls/{pr_number}/files?per_page=100&page={page}"])
            wanted = min(100, expected - len(rows))
            if not isinstance(chunk, list) or len(chunk) != wanted:
                raise Refused("github_file_pages_incomplete")
            for row in chunk:
                if (not isinstance(row, dict) or not path_ok(row.get("filename"))
                        or row["filename"] in seen or not isinstance(row.get("status"), str)
                        or row["status"] not in {"added", "removed", "modified", "renamed", "copied", "changed", "unchanged"}):
                    raise Refused("github_prior_paths_incomplete")
                seen.add(row["filename"])
                # Patch contents are not eligibility evidence. Retain metadata
                # only, rather than all response bodies across as many as 30 pages.
                rows.append({key: row[key] for key in ("filename", "previous_filename", "status") if key in row})
        return rows

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
        policy_pr = authority["authority"]["ratification"]["pr"]
        comments = []
        for page in range(1, 11):
            chunk = self.gh(["api", f"repos/{REPO}/issues/{policy_pr}/comments?per_page=100&page={page}"])
            if not isinstance(chunk, list):
                raise Refused("policy_comment_evidence_invalid")
            comments.extend(chunk)
            if len(chunk) < 100:
                break
        else:
            raise Refused("policy_comment_evidence_truncated")
        authority = authority_helper.verify_ratification_evidence(authority["authority"], comments, expected_operator=REPO.split("/")[0])
        if authority.get("ok") is not True:
            return {"authority": authority}
        fields = "number,title,body,state,isDraft,headRefOid,headRefName,baseRefName,mergeable,mergeStateStatus,files,changedFiles,statusCheckRollup,commits,author,reviews,labels"
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
        file_rows = self.pr_file_rows(pr_number, rest.get("changed_files"))
        if sorted(row["filename"] for row in file_rows) != sorted(pr["files"]):
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
        label_names = {row["name"].lower() for row in labels}
        if label_names & {"hold", "do-not-merge", "operator-hold"}:
            raise Refused("explicit_hold_requires_existing_resolution")
        if label_names & {"broker", "broker_active_trader", "active-trader", "active_trader", "broker-active-trader"}:
            raise Refused("broker_label_operator_only")
        effective_files = [*pr["files"], *pr["prior_paths"]]
        held_classes, held_metadata = collect_held_classes(effective_files, hold_config, hold)
        if label_names & hold.hold_labels(hold_config) and not held_classes:
            raise Refused("held_label_class_unresolved")
        held = bool(held_classes)
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
        claim_board_dir = self.state / "claims"
        claim_shared_config = json.loads(self.git("show", f"{sha}:config/agent_claim_shared_paths.json"))
        shared_config = json.loads(self.git("show", f"{sha}:config/shared_infra_paths.json"))
        patterns = shared_config.get("paths")
        if not isinstance(patterns, list) or any(not isinstance(pattern, str) for pattern in patterns):
            raise Refused("shared_infra_patterns_invalid")
        assessment = self.helper("scripts/check_shared_infra_pr.py", sha).assess(
            [*pr["files"], *pr["prior_paths"]], str(pr.get("title") or ""), str(pr.get("body") or ""), patterns)
        shared_required = assessment.get("shared_infra") is True
        shared_ok = assessment.get("ok") is True
        if shared_required:
            check_helper = self.helper("scripts/lib/pr_all_checks_green.py", sha)
            required_shared = tuple(dict.fromkeys([*check_helper.MERGE_REQUIRED_CHECKS, "shared-infra-review"]))
            extra = check_helper.evaluate_merge_rollup(pr.get("statusCheckRollup"), required=required_shared)
            shared_ok = shared_ok and extra.get("ok") is True and bool({"shared-infra", "solo"} & label_names)
        shared = {"required": shared_required, "ok": shared_ok,
                  "metadata_sha256": digest({"title": pr.get("title"), "body": pr.get("body"), "labels": sorted(label_names)})}
        cap = manifest.get("capabilities", {}).get("coordinator_merge", {})
        return {"authority": authority, "pr": pr, "checks": checks, "checks_head": pr.get("headRefOid"),
                "coordinators": json_read(coordinator / "coordinators.json"), "claims": claims,
                "evidence": evidence, "review_artifacts": artifacts, "registration_sha256": hashlib.sha256(raw).hexdigest(),
                "excluded_globs": [*authority["authority"]["reserved_paths"], *cap["excluded_globs"]]
                    if isinstance(cap, dict) and isinstance(cap.get("excluded_globs"), list) else None,
                "held": held, "held_classes": held_classes, "held_class_metadata": held_metadata,
                "actor_session": actor_session, "shared_infra": shared,
                "claim_board_dir": str(claim_board_dir), "claim_shared_paths_config": claim_shared_config,
                "source_authorship_sha256": digest({"author": pr.get("author"), "commits": commits})}

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
            cp = subprocess.run(command, cwd=self.repo, capture_output=True, text=True, timeout=90, check=False)  # noqa: S603 -- validated fixed exact-head merge argv from evaluate()
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
