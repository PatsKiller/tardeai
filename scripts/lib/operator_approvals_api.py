"""Thin Approvals handlers. Agents may read; decisions require the real operator.

POST performs a handler-side origin/CSRF check even in report-only auth mode.
No submitted actor, document text, command, URL, grant or policy token is trusted.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from scripts.lib import operator_approvals as core

PREFIX = "/api/v2/governance"
ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Ctx:
    principal: Callable[[], str]
    listener: Callable[[], str | None]
    csrf: Callable[[str, str], tuple[bool, str]]
    allowed_logins: frozenset
    sources: dict[str, Callable[[], list[dict]]]
    ledger: core.DecisionLedger
    policy: Callable[[], dict]
    clock: Callable[[], datetime] = core.utc_now
    can_read: Callable[[], bool] = field(default=lambda: False)


def _git(root: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, timeout=5, check=True)
    return out.stdout.decode("utf-8")


def git_policy(root: Path = ROOT) -> dict:
    sha = _git(root, "rev-parse", "HEAD").strip()
    # Read from the commit, not a concurrently edited worktree file.
    return core.policy_projection(_git(root, "show", f"{sha}:AGENTS.md"), source_sha=sha)


def _default_sources(root: Path) -> dict:
    from scripts.lib.approval_board_projection import load_packages
    from scripts.lib import approval_package as packages_core

    def packages():
        rows = []
        path = packages_core.ledger_path()
        if not path.is_file() or not packages_core.Ledger(path).verify_chain()[0]:
            raise core.Refused("PACKAGE_LEDGER_UNAVAILABLE", 503)
        source_sha = _git(root, "rev-parse", "HEAD").strip()
        for pkg in load_packages():
            if pkg.get("state") not in ("SUBMITTED", "PARTIAL"):
                continue
            expires = pkg.get("expires_at")
            if expires and datetime.fromisoformat(expires.replace("Z", "+00:00")) <= core.utc_now():
                continue
            for proposal in pkg.get("items", []):
                if proposal.get("state") not in ("PENDING", "NEEDS_LOCAL", "DEFERRED"):
                    continue
                # Project only fields the operator is meant to read; never raw codes/tokens.
                public = {key: proposal.get(key) for key in ("title", "why", "rule", "rollback", "scopes_needed", "depends_on")}
                kind = "SPEND" if proposal.get("category") == "BUDGET" else "ACTIVATE"
                if "release-write" in (proposal.get("scopes_needed") or []):
                    kind = "RELEASE"
                doc = core.document(json.dumps(public, indent=2, ensure_ascii=False), source_sha=source_sha,
                                    version=str(pkg.get("package_id")))
                rows.append(core.item(ident=f"{pkg['package_id']}:{proposal['item_no']}", kind=kind,
                                      title=proposal["title"], proposed_by=pkg.get("created_by"),
                                      created_at=pkg.get("submitted_at") or pkg.get("created_at"), doc=doc,
                                      source="approval_packages", governed_href="/system/ops-controls"))
        return rows

    def guard_requests():
        from scripts.lib import guard_remote_approval as guard
        if not guard.requests_path().is_file():
            raise core.Refused("GUARD_REQUEST_SOURCE_UNAVAILABLE", 503)
        data = guard._load()
        if data.get("corrupt"):
            raise core.Refused("GUARD_REQUEST_SOURCE_CORRUPT", 503)
        code_sha, out = _git(root, "rev-parse", "HEAD").strip(), []
        for row in data["requests"]:
            if row.get("status") != "PENDING" or row.get("expires_at", 0) <= core.utc_now().timestamp():
                continue
            if row.get("scope_conflict"):
                raise core.Refused("GUARD_SCOPE_CONFLICT", 503)
            public = {k: row.get(k) for k in ("request_id", "scope", "seconds", "uses", "reason", "created_at", "expires_at")}
            kind = "RELEASE" if row.get("scope") == "release-write" else "ACTIVATE"
            out.append(core.item(ident="guard:" + guard.request_id_of(row), kind=kind,
                                 title=f"Grant request: {guard.request_scope(row)}", proposed_by=None,
                                 created_at=iso_timestamp(row.get("created_at")), source="guard_requests",
                                 doc=core.document(json.dumps(public, ensure_ascii=False, indent=2), source_sha=code_sha),
                                 governed_href="/system/ops-controls"))
        return out

    def designs():
        from scripts.lib.design_registry import DesignStore, designs_awaiting, ledger_approved_ids
        designs, errors = DesignStore(root).load()
        candidates = designs_awaiting(root, designs, ledger_approved_ids(None))
        code_sha, out = _git(root, "rev-parse", "HEAD").strip(), []
        deadline = time.monotonic() + 1.5
        incomplete = False
        for row in candidates[:200]:
            if time.monotonic() > deadline:
                incomplete = True
                break
            path = row["path"]
            text = _git(root, "show", f"{code_sha}:{path}")
            # Packets containing activations/policy edits cannot be approved as a generic design.
            mode = "ACTIVATE" if row["kind"] == "packet" else "DESIGN"
            out.append(core.item(ident="design:" + row["id"], kind=mode, title=row["title"],
                                 proposed_by=None, created_at=None, source="design_registry",
                                 doc=core.document(text, source_sha=code_sha, version=row["id"]),
                                 governed_href="/coordination?tab=work" if mode == "ACTIVATE" else None))
        return {"rows": out, "gap": "Design scan incomplete or invalid" if errors or incomplete or len(candidates) > 200 else None}

    def policy_prs():
        from scripts.lib.design_registry import work_board
        board = work_board()
        # Consume the existing board's background snapshot. A GET never starts a GitHub scan/job.
        if board.prs is None:
            raise core.Refused("POLICY_PR_SNAPSHOT_UNAVAILABLE", 503)
        out, missing = [], bool(board.prs_warning or board._prs_at is None or time.monotonic() - board._prs_at > 120)
        deadline = time.monotonic() + 1.5
        for pr in board.prs[:100]:
            if time.monotonic() > deadline:
                missing = True
                break
            head, base = (pr.get("head") or {}).get("sha", ""), (pr.get("base") or {}).get("sha", "")
            if not core.SHA.fullmatch(head) or not core.SHA.fullmatch(base):
                missing = True
                continue
            try:
                text, old = _git(root, "show", f"{head}:AGENTS.md"), _git(root, "show", f"{base}:AGENTS.md")
            except (subprocess.SubprocessError, UnicodeDecodeError):
                missing = True
                continue
            if text == old:
                continue
            version = re.search(r"^Policy-Version:\s*(\d+\.\d+\.\d+)\s*$", text, re.M)
            doc = core.document(text, base_text=old, source_sha=head, version=version[1] if version else "",
                                source_verified=True)
            out.append(core.item(ident=f"policy:{pr['number']}", kind="POLICY", title=pr["title"],
                                 proposed_by=(pr.get("user") or {}).get("login"), created_at=pr.get("created_at"),
                                 doc=doc, source="github_pr_snapshot", pr=pr["number"]))
        return {"rows": out, "gap": "Exact open PR snapshot or local commit objects incomplete" if missing or len(board.prs) >= 100 else None}

    def conflicts():
        from scripts.lib.conflicts.api import approval_rows
        projected = approval_rows(root=root, limit=200)
        if projected.get("gap") or projected.get("total") is None:
            raise core.Refused("CONFLICT_SOURCE_UNAVAILABLE", 503)
        if projected["total"] > len(projected["rows"]):
            raise core.Refused("CONFLICT_SOURCE_TRUNCATED", 503)
        rows = []
        for row in projected["rows"]:
            raw = row["document"]
            # W10's source_sha is its evidence digest, not necessarily a Git commit.
            # Preserve it as document version; bind the adapter code's exact commit separately.
            code_sha = _git(root, "rev-parse", "HEAD").strip()
            doc = core.document(raw["text"], source_sha=code_sha,
                                version=str(raw.get("version")) + ":" + str(raw.get("source_sha")))
            rows.append(core.item(ident="conflict:" + row["id"], kind="CONFLICT", title=row["title"],
                                  proposed_by=row.get("proposed_by"), created_at=row.get("created_at"), doc=doc,
                                  source="conflicts", governed_href=row.get("governed_href")))
        return rows

    def missing():
        raise core.Refused("EXACT_SOURCE_ADAPTER_PENDING", 503)

    def financial():
        from scripts.lib.cio_truth import financial_queue_items
        result = financial_queue_items(limit=200)
        code_sha, out = _git(root, "rev-parse", "HEAD").strip(), []
        for row in result["items"]:
            public = {k: row.get(k) for k in ("title", "kind", "symbol", "account_label", "status", "created_at", "expires_at", "category", "action")}
            ident = "financial:" + row["canonical_entity_id"]
            refs = [f"{ref['source']}:{ref['id']}" for ref in row.get("source_refs", [])
                    if isinstance(ref, dict) and ref.get("source") and ref.get("id") is not None]
            out.append(core.item(ident=ident, kind="FINANCIAL", title=row.get("title") or "Trade review",
                                 proposed_by=None, created_at=row.get("created_at"), source=row["source"],
                                 doc=core.document(json.dumps(public, indent=2, ensure_ascii=False), source_sha=code_sha),
                                 governed_href="/proposals", source_refs=refs + [row["canonical_entity_id"]]))
        return {"rows": out, "gap": None if result.get("complete") else "Financial queues incomplete"}

    # These missing adapters are explicit. Neither empty queues nor a complete global count are invented.
    return {"packages": packages, "conflicts": conflicts, "policy_prs": policy_prs,
            "guard_requests": guard_requests, "design_decisions": designs, "financial_queues": financial}


def iso_timestamp(value) -> str | None:
    try:
        return core.iso(datetime.fromtimestamp(float(value), tz=timezone.utc))
    except (TypeError, ValueError, OverflowError):
        return None


def default_ctx() -> Ctx:
    from scripts.lib import cc_auth
    from scripts.lib.approval_package import governance_dir
    cfg = cc_auth.load_config()

    def approved():
        registry = json.loads((ROOT / "config/data_source_authority.json").read_text())
        return core.writes_approved(registry)

    ledger = core.DecisionLedger(governance_dir() / "operator_decisions.jsonl", approved=approved)
    sources = _default_sources(ROOT)
    sources["rule_proposals"] = ledger.proposal_rows
    return Ctx(principal=cc_auth.current_principal,
               listener=lambda: (cc_auth.current_request_context() or {}).get("listener"),
               csrf=lambda m, p: cc_auth.command_csrf_check(cfg, m, p), allowed_logins=cfg.allowed_logins,
               sources=sources, ledger=ledger,
               policy=git_policy,
               can_read=lambda: cc_auth.current_principal() == "service-token")


def _operator(ctx: Ctx) -> str | None:
    actor = ctx.principal() or ""
    if (actor.startswith("tailnet:") and ctx.listener() == "serve_proxy"
            and actor[8:].strip().lower() in ctx.allowed_logins):
        return actor
    return None


def queue(ctx: Ctx) -> dict:
    return core.queue_projection(ctx.sources, decisions=ctx.ledger.rows(), now=ctx.clock())


def queue_summary(*, root: Path = ROOT, state_root: Path | None = None, now: datetime | None = None) -> dict:
    """Scoped administrative projection; never silently replaces the financial approval total."""
    from scripts.lib.approval_package import governance_dir
    ledger = core.DecisionLedger((state_root / "data/governance" if state_root else governance_dir()) / "operator_decisions.jsonl",
                                 approved=lambda: False)
    data = core.queue_projection(_default_sources(root), decisions=ledger.rows(), now=now or core.utc_now())
    return {key: data[key] for key in ("pending_count", "known_pending_count", "complete", "gaps", "as_of")} | {
        "scope": "operator_governance", "by_type": {kind: sum(r["kind"] == kind for r in data["items"]) for kind in core.KINDS}}


def handle(path: str, method: str, body=None, query=None, *, ctx: Ctx | None = None):
    base = (path or "").split("?", 1)[0].rstrip("/")
    if not (base == PREFIX or base.startswith(PREFIX + "/")):
        return None
    try:
        ctx = ctx or default_ctx()
        method = method.upper()
        sub = base[len(PREFIX):]
        actor = _operator(ctx)
        if method == "GET":
            if not actor and not ctx.can_read():
                raise core.Refused("AUTHENTICATED_READER_REQUIRED", 403)
            if sub == "/approvals":
                data = queue(ctx)
                q = query if isinstance(query, dict) else {}
                kind = q.get("kind")
                if isinstance(kind, list):
                    kind = kind[0] if kind else None
                if kind in core.KINDS:
                    data["items"] = [r for r in data["items"] if r["kind"] == kind]
                raw_offset = q.get("offset", 0)
                if isinstance(raw_offset, list):
                    raw_offset = raw_offset[0] if raw_offset else 0
                try:
                    offset = max(0, int(raw_offset))
                except (TypeError, ValueError):
                    offset = 0
                data["filtered_count"], data["offset"] = len(data["items"]), offset
                data["items"] = data["items"][offset:offset + 50]
                # Queue cards do not ship whole documents; the reader loads just the chosen item.
                data["items"] = [{k: v for k, v in it.items() if k != "document"} | {
                    "document_sha": it["document"]["document_sha"], "version": it["document"]["version"]}
                                 for it in data["items"]]
                return 200, {"ok": True, "data": data}
            if sub == "/policy":
                data = ctx.policy()
                q = query if isinstance(query, dict) else {}
                section = q.get("section")
                if isinstance(section, list):
                    section = section[0] if section else None
                all_rules = data["rules"]
                selected = [r for r in all_rules if not section or r["section"] == section]
                raw_offset = q.get("offset", 0)
                if isinstance(raw_offset, list):
                    raw_offset = raw_offset[0] if raw_offset else 0
                try:
                    offset = max(0, int(raw_offset))
                except (TypeError, ValueError):
                    offset = 0
                data["rules"], data["total_rules"], data["section_total"], data["offset"] = selected[offset:offset+40], len(all_rules), len(selected), offset
                data["positions"] = [r for r in ctx.ledger.rows() if r.get("event") == "RULE_FEEDBACK"][-100:]
                return 200, {"ok": True, "data": data}
            if sub.startswith("/approvals/"):
                ident = sub[len("/approvals/"):]
                return 200, {"ok": True, "data": _current(ctx, ident)()}
            raise core.Refused("NOT_FOUND", 404)
        if method != "POST":
            raise core.Refused("METHOD_NOT_ALLOWED", 405)
        if not actor:
            raise core.Refused("AGENT_CALLER_REFUSED", 403)
        ok, why = ctx.csrf("POST", base)
        if not ok:
            raise core.Refused("CSRF_REFUSED", 403)
        if not isinstance(body, dict):
            raise core.Refused("OBJECT_BODY_REQUIRED", 400)
        if sub == "/policy/feedback":
            result = ctx.ledger.feedback(actor, ctx.policy, body)
            return 200, {"ok": True, "data": result}
        parts = sub.strip("/").split("/")
        if len(parts) != 3 or parts[0] != "approvals":
            raise core.Refused("NOT_FOUND", 404)
        current = _current(ctx, parts[1])
        if parts[2] == "open":
            result = ctx.ledger.start(actor, current, body.get("document_sha"))
        elif parts[2] == "read":
            result = ctx.ledger.marker(actor, current, body)
        elif parts[2] == "decide":
            result = ctx.ledger.decide(actor, current, body)
        else:
            raise core.Refused("NOT_FOUND", 404)
        return 200, {"ok": True, "data": result}
    except core.Refused as exc:
        return exc.status, {"ok": False, "error": exc.code}
    except Exception as exc:
        return 503, {"ok": False, "error": "SOURCE_UNAVAILABLE", "detail": type(exc).__name__}


def _current(ctx: Ctx, ident: str):
    def current():
        # Re-read inside the ledger transaction so stale browser bodies cannot bind a newer document.
        matches = []
        for load in ctx.sources.values():
            try:
                rows = load()
                if isinstance(rows, dict):
                    if rows.get("gap"):
                        continue  # stale/incomplete source snapshots cannot authorize a decision
                    rows = rows.get("rows") or []
            except Exception:
                continue
            for row in rows:
                if row["id"] == ident:
                    matches.append(row)
        if len(matches) == 1:
            return matches[0]
        if matches:
            raise core.Refused("DUPLICATE_APPROVAL_ID", 503)
        raise core.Refused("ITEM_UNAVAILABLE", 404)
    return current
