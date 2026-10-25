"""Approvals review projection and operator-attributed, exact-document decision ledger.

This module never executes a grant, activation, policy edit, shell command or model.
Production writes require the separately approved operator_decisions authority row.
All clocks and sources are injected in tests; GET projections never write state.
"""
from __future__ import annotations

import difflib
import fcntl
import hashlib
import json
import os
import re
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

DECISION_REL = "data/governance/operator_decisions.jsonl"
WRITER = "scripts/lib/operator_approvals.py"
KINDS = ("POLICY", "RELEASE", "SPEND", "ACTIVATE", "DESIGN", "CONFLICT", "FINDING", "FINANCIAL")
# AGENTS.md itself is about 630 KB; a real before/after pair must fit.
MAX_DOCUMENT = 1_800_000
MAX_LEDGER = 32_000_000
REVIEW_TTL = timedelta(minutes=30)
SHA = re.compile(r"^[0-9a-f]{40}$")
PLAIN_RULES = {
    "MBI_BEHAVIOR": "An AI may advise, but it never places, sizes or changes a trade.",
    "Broker code is buildable only": "A named, time-limited operator grant is required even to build or simulate broker-related code. It never grants live trading authority.",
    "Never route around a permission denial": "When permission is refused, stop and report it. Do not try another route.",
    "A checkpoint is": "Save progress with a local commit. Sending it to GitHub needs separate authorization.",
    "Never auto-remediate divergent copies": "If authoritative copies disagree, show both to the operator instead of choosing one automatically.",
    "Never delete.": "Keep records by archiving them. Only the specifically approved cleanup jobs may delete their approved items.",
    "Dry-run before any live run": "Preview a consequential change before applying it.",
    "Exit code 0 is not evidence": "A successful exit alone does not prove work happened. Check the actual output.",
    "Operator-only decisions: propose and stop": "Agents prepare proposals. You make the decisions reserved for the operator.",
    "When a finding contradicts this file": "Report observed facts that conflict with the written rule and propose a correction.",
    "Claim, log, hand off.": "Reserve the files you will edit and keep notes so another worker can continue the work.",
}


class Refused(ValueError):
    def __init__(self, code: str, status: int = 409):
        super().__init__(code)
        self.code, self.status = code, status


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat()


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


def _paragraphs(text: str) -> list[dict]:
    """Small blocks can be completely visible even on a 390px phone."""
    out, section, cursor = [], "Document", 0
    for paragraph in re.split(r"\n\s*\n", text):
        if not paragraph.strip():
            continue
        heading = re.match(r"^#{1,6}\s+(.+)", paragraph)
        if heading:
            section = heading[1].strip()
        # Bound by characters AND lines, so a change cannot be taller than a viewport.
        for line in paragraph.splitlines():
            offset = text.find(line, cursor)
            if offset < 0:
                raise Refused("DOCUMENT_PARSE_FAILED", 503)
            for start in range(0, max(len(line), 1), 240):
                chunk = line[start:start + 240]
                out.append({"section": section, "text": chunk, "offset": offset + start})
            cursor = offset + len(line)
    return out


def document(text: str, *, source_sha: str, version: str = "", base_text: str = "",
             annotations: dict | None = None, tests: dict | None = None, source_verified: bool = False) -> dict:
    if not isinstance(text, str) or not text.strip() or len(text) + len(base_text) > MAX_DOCUMENT:
        raise Refused("DOCUMENT_UNAVAILABLE", 503)
    if not SHA.fullmatch(source_sha):
        raise Refused("EXACT_COMMIT_REQUIRED", 503)
    old, new = _paragraphs(base_text), _paragraphs(text)
    changes = []
    matcher = difflib.SequenceMatcher(a=[b["text"] for b in old], b=[b["text"] for b in new], autojunk=False)
    for tag, a, b, c, d in matcher.get_opcodes():
        if tag == "equal":
            continue
        for before, after in [(v, None) for v in old[a:b]] + [(None, v) for v in new[c:d]]:
            block = after or before
            ident = "change_" + digest([len(changes), tag, before, after])[:24]
            note = (annotations or {}).get(ident) or {}
            changes.append({"id": ident, "section": block["section"], "before": before["text"] if before else "",
                            "after": after["text"] if after else "", "kind": "added" if after else "removed",
                            "plain": note.get("plain"), "reason": note.get("reason"),
                            "before_offset": before["offset"] if before else None,
                            "after_offset": after["offset"] if after else None})
    # Every decision binds the base, text, commit, and explanatory metadata shown to the reader.
    doc_sha = digest({"reader_format": 1, "text": text, "base_text": base_text, "source_sha": source_sha,
                      "version": version, "annotations": annotations or {}})
    sections = list(dict.fromkeys(b["section"] for b in new + old))
    sensitive = sorted({m.group(1) for change in changes
                        if (m := re.match(r"(?:§\s*)?(0|2|17)(?:\s|[.·])", change["section"]))})
    removed = sum(c["kind"] == "removed" for c in changes)
    test_proof = tests if isinstance(tests, dict) and tests.get("source_sha") == source_sha else None
    return {"text": text, "base_text": base_text, "source_sha": source_sha, "version": version,
            "document_sha": doc_sha, "changes": changes, "sections": sections, "source_verified": source_verified,
            "prechecks": {"sensitive_sections": sensitive, "removed_blocks": removed,
                          "weakens_rules": "REVIEW_REQUIRED" if removed else "NOT_ASSESSED",
                          "policy_tests": test_proof or {"state": "UNKNOWN", "reason": "No test receipt for this commit"}}}


def item(*, ident: str, kind: str, title: str, proposed_by: str | None, created_at: str | None,
         doc: dict, source: str, pr: int | None = None, governed_href: str | None = None,
         source_refs: list[str] | None = None) -> dict:
    if kind not in KINDS or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", ident):
        raise Refused("INVALID_SOURCE_ITEM", 503)
    # Only known local UI destinations; source text never supplies an executable command or arbitrary URL.
    href = governed_href if governed_href and governed_href.startswith(("/system/ops-controls", "/coordination", "/watch", "/trading?tab=Proposals", "/cio", "/conflicts/rules?proposal=")) and not governed_href.startswith("//") else None
    return {"id": ident, "kind": kind, "title": title[:300], "proposed_by": proposed_by,
            "created_at": created_at, "document": doc, "source": source, "pr": pr,
            "source_refs": list(dict.fromkeys([source + ":" + ident] + (source_refs or []))),
            "governed_href": href, "decision_mode": "GOVERNED_PATH" if kind in ("RELEASE", "SPEND", "ACTIVATE", "CONFLICT", "FINANCIAL") else "RECORD"}


def queue_projection(sources: dict[str, Callable[[], list[dict]]], *, decisions: list[dict], now: datetime) -> dict:
    rows, gaps = [], []
    for name, load in sources.items():
        try:
            batch = load()
            if isinstance(batch, dict):
                if batch.get("gap"):
                    gaps.append({"source": name, "reason": str(batch["gap"])[:160]})
                batch = batch.get("rows")
            if not isinstance(batch, list) or len(batch) > 500:
                raise Refused("SOURCE_BUDGET_EXCEEDED", 503)
            rows.extend(batch)
        except Exception as exc:  # a failed source never becomes a reassuring zero
            gaps.append({"source": name, "reason": exc.code if isinstance(exc, Refused) else type(exc).__name__})
    seen = set()
    for row in rows:
        if row["id"] in seen:
            raise Refused("DUPLICATE_APPROVAL_ID", 503)
        seen.add(row["id"])
    # Union only explicit authoritative references. Titles, symbols and account names are not identity.
    groups: list[list[dict]] = []
    for row in rows:
        overlap = [group for group in groups if set(row.get("source_refs") or []) &
                   {ref for member in group for ref in member.get("source_refs") or []}]
        if not overlap:
            groups.append([row])
        else:
            merged = [row]
            for group in overlap:
                merged.extend(group)
                groups.remove(group)
            groups.append(merged)
    rows = []
    for group in groups:
        group.sort(key=lambda r: (r["kind"] == "FINANCIAL", r["id"]))
        primary = dict(group[0])
        primary["related_sources"] = [{"id": r["id"], "source": r["source"]} for r in group[1:]]
        primary["requires_governed_action"] = any(r["decision_mode"] == "GOVERNED_PATH" for r in group)
        rows.append(primary)
    recent = [r for r in decisions if r.get("event") == "DECIDED"]
    terminal = {(r["item_id"], r["document_sha"]) for r in recent}
    pending = [r for r in rows if r["requires_governed_action"] or (r["id"], r["document"]["document_sha"]) not in terminal]
    pending.sort(key=lambda r: (r.get("created_at") or "9999", r["id"]))
    return {"items": pending, "known_pending_count": len(pending), "pending_count": len(pending) if not gaps else None,
            "complete": not gaps, "gaps": gaps, "as_of": iso(now), "recent": recent[-30:][::-1]}


def writes_approved(registry: dict) -> bool:
    """A build directive is not the new-store sign-off. No env flag can replace it."""
    domains = registry.get("domains") or {}
    rows = domains.values() if isinstance(domains, dict) else domains
    for row in rows:
        approval = row.get("approval") or {}
        store = row.get("store") or {}
        if not isinstance(store, dict):
            continue
        if (row.get("id", row.get("domain")) == "operator_decisions" and store.get("file") == "governance/operator_decisions.jsonl"
                and row.get("writer") == WRITER and approval.get("approved_by") == "operator"
                and approval.get("approved_on") and approval.get("reference")):
            return True
    return False


class DecisionLedger:
    """One append-only hash chain, serialized with flock; fail closed on corruption.

    Hashes detect edits; operator attribution comes from the authenticated server context.
    This is not a cryptographic signature or an alternative to a passkey/grant.
    """
    def __init__(self, path: Path, *, approved: Callable[[], bool], clock: Callable[[], datetime] = utc_now):
        self.path, self.approved, self.clock = Path(path), approved, clock

    def _read(self, file) -> list[dict]:
        file.seek(0)
        raw = file.read(MAX_LEDGER + 1)
        if len(raw) > MAX_LEDGER:
            raise Refused("LEDGER_READ_BUDGET_EXCEEDED", 503)
        out, prev = [], None
        try:
            for line in raw.splitlines():
                row = json.loads(line)
                recorded = row.pop("hash_self")
                if row.get("hash_prev") != prev or digest(row) != recorded:
                    raise ValueError("chain")
                row["hash_self"] = recorded
                out.append(row)
                prev = recorded
        except (ValueError, KeyError, TypeError):
            raise Refused("LEDGER_CORRUPT", 503) from None
        return out

    def rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open(encoding="utf-8") as file:
            fcntl.flock(file, fcntl.LOCK_SH)
            return self._read(file)

    @contextmanager
    def _transaction(self):
        if not self.approved():
            raise Refused("STORE_APPROVAL_PENDING", 503)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a+", encoding="utf-8") as file:
            fcntl.flock(file, fcntl.LOCK_EX)
            rows = self._read(file)
            def append(row):
                row = {**row, "at": iso(self.clock()), "hash_prev": rows[-1]["hash_self"] if rows else None}
                row["hash_self"] = digest(row)
                file.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
                file.flush()
                os.fsync(file.fileno())
                rows.append(row)
                return row
            yield rows, append

    def start(self, actor: str, current: Callable[[], dict], expected_sha: str) -> dict:
        with self._transaction() as (rows, append):
            it = current()
            if it["document"]["document_sha"] != expected_sha:
                raise Refused("DOCUMENT_CHANGED")
            return append({"event": "READ_STARTED", "actor": actor, "item_id": it["id"],
                           "document_sha": expected_sha, "review_id": "review_" + secrets.token_hex(16)})

    def _session(self, rows: list[dict], actor: str, review_id: str, it: dict, sha: str) -> dict:
        start = next((r for r in rows if r.get("event") == "READ_STARTED" and r.get("review_id") == review_id), None)
        if not start or start["actor"] != actor or start["item_id"] != it["id"]:
            raise Refused("REVIEW_SESSION_REFUSED", 403)
        if sha != it["document"]["document_sha"] or sha != start["document_sha"]:
            raise Refused("DOCUMENT_CHANGED")
        if self.clock() - datetime.fromisoformat(start["at"]) > REVIEW_TTL:
            raise Refused("REVIEW_EXPIRED")
        return start

    def marker(self, actor: str, current: Callable[[], dict], body: dict) -> dict:
        with self._transaction() as (rows, append):
            it, review = current(), str(body.get("review_id") or "")
            sha, ident, phase = body.get("document_sha"), body.get("change_id"), body.get("phase")
            self._session(rows, actor, review, it, sha)
            if ident not in {c["id"] for c in it["document"]["changes"]} or phase not in ("enter", "leave", "read"):
                raise Refused("INVALID_READ_MARKER", 400)
            prior = [r for r in rows if r.get("review_id") == review and r.get("change_id") == ident]
            if phase == "read":
                if not prior or prior[-1].get("phase") != "enter" or (self.clock() - datetime.fromisoformat(prior[-1]["at"])).total_seconds() < 3:
                    raise Refused("CHANGE_NOT_READ")
            return append({"event": "READ_MARKER", "actor": actor, "item_id": it["id"], "review_id": review,
                           "document_sha": sha, "change_id": ident, "phase": phase})

    def decide(self, actor: str, current: Callable[[], dict], body: dict) -> dict:
        choice = body.get("decision")
        if choice not in ("APPROVE", "REJECT", "REQUEST_CHANGES"):
            raise Refused("INVALID_DECISION", 400)
        request = body.get("request_id")
        if not isinstance(request, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", request):
            raise Refused("REQUEST_ID_REQUIRED", 400)
        comment = body.get("comment") or ""
        if not isinstance(comment, str) or len(comment) > 4000:
            raise Refused("COMMENT_TOO_LONG", 400)
        if choice == "REQUEST_CHANGES" and not comment.strip():
            raise Refused("COMMENT_REQUIRED", 400)
        with self._transaction() as (rows, append):
            it, review = current(), str(body.get("review_id") or "")
            sha = body.get("document_sha")
            self._session(rows, actor, review, it, sha)
            for r in rows:
                if r.get("event") == "DECIDED" and r.get("request_id") == request:
                    if (r["actor"], r["item_id"], r["document_sha"], r["decision"], r["comment"]) == (actor, it["id"], sha, choice, comment):
                        return r
                    raise Refused("IDEMPOTENCY_CONFLICT")
            if any(r.get("event") == "DECIDED" and r.get("item_id") == it["id"] and r.get("document_sha") == sha for r in rows):
                raise Refused("ALREADY_DECIDED")
            token = None
            if choice == "APPROVE":
                if it["decision_mode"] == "GOVERNED_PATH":
                    raise Refused("GOVERNED_ACTION_REQUIRED")
                read = {r.get("change_id") for r in rows if r.get("review_id") == review and r.get("phase") == "read"}
                if not {c["id"] for c in it["document"]["changes"]}.issubset(read):
                    raise Refused("CHANGES_UNREAD")
                if it["kind"] == "POLICY":
                    version = it["document"]["version"]
                    if (not it["document"].get("source_verified") or not re.fullmatch(r"\d+\.\d+\.\d+", version)
                            or type(it.get("pr")) is not int or it["pr"] < 1):
                        raise Refused("POLICY_BINDING_REQUIRED")
                    token = f"APPROVE_AGENTS_POLICY_{version.replace('.', '_')} {it['pr']} {it['document']['source_sha']}"
            return append({"event": "DECIDED", "actor": actor, "item_id": it["id"], "kind": it["kind"],
                           "document_sha": sha, "source_sha": it["document"]["source_sha"], "review_id": review,
                           "decision": choice, "comment": comment, "request_id": request, "policy_token": token,
                           "effect": "RECORD_ONLY", "governed_href": it["governed_href"]})

    def feedback(self, actor: str, current_policy: Callable[[], dict], body: dict) -> dict:
        if body.get("position") not in ("AGREE", "QUESTION", "DISAGREE"):
            raise Refused("INVALID_POSITION", 400)
        comment = body.get("comment") or ""
        if not isinstance(comment, str) or len(comment) > 4000:
            raise Refused("COMMENT_TOO_LONG", 400)
        if body["position"] != "AGREE" and not comment.strip():
            raise Refused("COMMENT_REQUIRED", 400)
        with self._transaction() as (rows, append):
            policy = current_policy()
            if body.get("document_sha") != policy["document_sha"]:
                raise Refused("DOCUMENT_CHANGED")
            rule = next((r for r in policy["rules"] if r["id"] == body.get("rule_id")), None)
            if not rule:
                raise Refused("RULE_UNAVAILABLE", 404)
            return append({"event": "RULE_FEEDBACK", "actor": actor, "document_sha": policy["document_sha"],
                           "source_sha": policy["source_sha"], "rule_id": rule["id"], "section": rule["section"],
                           "rule_text": rule["text"], "position": body["position"], "comment": comment,
                           "proposal_id": "feedback_" + secrets.token_hex(12), "effect": "PROPOSAL_ONLY"})

    def proposal_rows(self) -> list[dict]:
        out = []
        for row in self.rows():
            if row.get("event") == "AUDIT_FINDINGS":
                for index, finding in enumerate(row["findings"]):
                    doc = document(json.dumps(finding, ensure_ascii=False, indent=2), source_sha=row["source_sha"],
                                   version=row["document_sha"])
                    out.append(item(ident=f"audit:{row['audit_key']}:{index}", kind="FINDING", title=finding["title"],
                                    proposed_by=row["actor"], created_at=row["at"], source="policy_enforcement_audit", doc=doc))
                continue
            if row.get("event") != "RULE_FEEDBACK" or row.get("position") != "DISAGREE":
                continue
            doc = document(f"{row['section']}\n\n{row['rule_text']}\n\nRequested change:\n{row['comment']}",
                           source_sha=row["source_sha"], version=row["document_sha"])
            out.append(item(ident=row["proposal_id"], kind="DESIGN", title="Proposed rule change: " + row["section"],
                            proposed_by=row["actor"], created_at=row["at"], source="operator_decisions", doc=doc))
        return out

    def audit_findings(self, *, policy: dict, audit_key: str, findings: list[dict], evidence_refs: set[str]) -> dict:
        """Host audit proposes evidence-backed findings; it cannot write a decision event."""
        if not re.fullmatch(r"[0-9a-f]{40}", audit_key) or not 0 <= len(findings) <= 50:
            raise Refused("INVALID_AUDIT_PROPOSAL", 400)
        normalized = []
        for finding in findings:
            refs = finding.get("evidence_refs")
            if (not isinstance(refs, list) or not refs or any(not isinstance(r, str) or r not in evidence_refs for r in refs)
                    or not isinstance(finding.get("title"), str) or not isinstance(finding.get("detail"), str)):
                raise Refused("UNSUPPORTED_AUDIT_FINDING", 400)
            normalized.append({"title": finding["title"][:300], "detail": finding["detail"][:3000],
                               "rule_id": str(finding.get("rule_id") or "")[:100], "evidence_refs": refs,
                               "status": "PROPOSED", "auto_apply": False})
        with self._transaction() as (rows, append):
            existing = next((r for r in rows if r.get("event") == "AUDIT_FINDINGS" and r.get("audit_key") == audit_key), None)
            if existing:
                if existing["document_sha"] != policy["document_sha"]:
                    raise Refused("AUDIT_IDENTITY_CONFLICT")
                return existing
            return append({"event": "AUDIT_FINDINGS", "actor": "audit:policy-enforcement-audit", "audit_key": audit_key,
                           "document_sha": policy["document_sha"], "source_sha": policy["source_sha"],
                           "findings": normalized, "effect": "PROPOSAL_ONLY"})


_LIST_ITEM = re.compile(r"^(?P<indent> {0,3})(?P<marker>[-*+]|\d{1,3}[.)])\s+(?P<body>\S.*)$")
_SECTION_NUMBER = re.compile(r"^(?:§\s*)?\d+[A-Z]?\s*(?:·|\.|\s)")
_HISTORY_SECTION = re.compile(r"\b(?:version history|changelog|change log)\b", re.I)
AUDIT_NOT_RUN = "The enforcement audit has not run against this policy version, so no rule has measured evidence yet."


def _rule_items(text: str) -> list[dict]:
    """Real rule items: top-level numbered or bulleted list items under a section.

    Skipped: the document title and its preamble (header fence, version banners, intro), headings,
    code fences, tables, block quotes, HTML comments, horizontal rules and version-history sections.
    A list item keeps its continuation lines and nested sub-items as part of its text. A section
    written only as prose (no list at all, e.g. §17) contributes its paragraphs instead, except
    bare labels such as "**At session start:**".
    """
    items: list[dict] = []
    prose: list[dict] = []
    section, subsection = None, None
    first_heading = True
    skip_section = True  # until the first real section heading
    in_fence = in_comment = False
    current: dict | None = None
    paragraph: dict | None = None
    blank_run = 0

    seq = 0

    def joined(lines: list[str]) -> str:
        # Source line wraps become spaces; a blank line or a nested item starts a new line.
        out = ""
        for line in lines:
            if not out:
                out = line.lstrip("\n")
            elif line.startswith("\n"):
                out += "\n" + line.lstrip("\n")
            elif line.startswith("- "):
                out += "\n" + line
            else:
                out += " " + line
        return out.strip()

    def close_item():
        nonlocal current, seq
        if current is not None:
            body = joined(current.pop("lines"))
            if body:
                seq += 1
                items.append({**current, "text": body, "_seq": seq})
        current = None

    def close_paragraph():
        nonlocal paragraph, seq
        if paragraph is not None:
            body = joined(paragraph.pop("lines"))
            label = re.fullmatch(r"\*\*[^*]+\*\*:?|[^\s].{0,80}:", body)
            if body and not label:
                seq += 1
                prose.append({**paragraph, "text": body, "_seq": seq})
        paragraph = None

    def close():
        close_item()
        close_paragraph()

    for raw in text.splitlines():
        stripped = raw.strip()
        if in_comment:
            if "-->" in stripped:
                in_comment = False
            continue
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            close()
            continue
        if in_fence:
            continue
        if stripped.startswith("<!--"):
            close()
            in_comment = "-->" not in stripped
            continue
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", raw)
        if heading:
            close()
            level, title = len(heading[1]), heading[2].strip()
            if level == 1:
                # The first H1 is the document title unless it is itself a numbered section.
                is_title = first_heading and not _SECTION_NUMBER.match(title)
                section, subsection = title, None
                skip_section = is_title or bool(_HISTORY_SECTION.search(title))
            else:
                if section is None:
                    section, skip_section = title, bool(_HISTORY_SECTION.search(title))
                subsection = title
            first_heading = False
            continue
        if skip_section or section is None:
            continue
        if not stripped:
            close_paragraph()
            blank_run += 1
            continue
        if stripped.startswith(("|", ">")) or re.fullmatch(r"[-*_]{3,}", stripped):
            close()
            blank_run = 0
            continue
        match = _LIST_ITEM.match(raw)
        if match and not match["indent"]:
            close()
            marker = match["marker"]
            current = {"section": section, "subsection": subsection,
                       "number": marker.rstrip(".)") if marker[0].isdigit() else None, "lines": [match["body"]]}
            blank_run = 0
            continue
        if current is not None and (raw.startswith((" ", "\t")) or not blank_run):
            nested = _LIST_ITEM.match(raw.strip())
            line = "- " + nested["body"] if nested and not nested["marker"][0].isdigit() else raw.strip()
            current["lines"].append(("\n" if blank_run else "") + line)
            blank_run = 0
            continue
        close_item()
        blank_run = 0
        if paragraph is None:
            paragraph = {"section": section, "subsection": subsection, "number": None, "lines": []}
        paragraph["lines"].append(stripped)
    close()
    listed = {item["section"] for item in items}
    extra = [p for p in prose if p["section"] not in listed]
    # Document order.
    return [{k: v for k, v in r.items() if k != "_seq"} for r in sorted([*items, *extra], key=lambda r: r["_seq"])]


def policy_projection(text: str, *, source_sha: str, enforcement: dict | None = None) -> dict:
    doc = document(text, source_sha=source_sha)
    rules = []
    # ``enforcement`` is None when no audit result applies to this document; then the measured
    # tiles are a gap ("Audit not run"), never 0.
    measured = enforcement is not None
    per_section: dict[str, int] = {}
    for block in _rule_items(text):
        ordinal = per_section.get(block["section"], 0)
        per_section[block["section"]] = ordinal + 1
        key = "rule_" + digest([block["section"], ordinal, block["text"]])[:20]
        proof = (enforcement or {}).get(key) or {}
        # An existence map is not runtime proof. Evidence must bind the exact policy document.
        same = proof.get("document_sha") == doc["document_sha"]
        status = "WRITTEN-only"
        if same and proof.get("violation_evidence"):
            status = "VIOLATED"
        elif same and proof.get("test_passed") and proof.get("test_receipt"):
            status = "ENFORCED" if proof.get("runtime_passed") and proof.get("runtime_receipt") else "TESTED"
        plain = next((meaning for anchor, meaning in PLAIN_RULES.items() if anchor in block["text"]), None)
        rules.append({"id": key, **block, "plain": proof.get("plain") if same and proof.get("plain") else plain, "status": status,
                      "evidence": proof if same else {},
                      "reason": None if same else ("No evidence for this document version" if measured else "Audit not run")})
    counts = {"RULES": len(rules)}
    for name in ("ENFORCED", "TESTED", "WRITTEN-only", "VIOLATED"):
        counts[name] = sum(r["status"] == name for r in rules) if measured or name == "WRITTEN-only" else None
    sections = list(per_section)
    section_status = {}
    rank = {"VIOLATED": 0, "WRITTEN-only": 1, "TESTED": 2, "ENFORCED": 3}
    for rule in rules:
        prior = section_status.get(rule["section"])
        if prior is None or rank[rule["status"]] < rank[prior]:
            section_status[rule["section"]] = rule["status"]
    return {"document_sha": doc["document_sha"], "source_sha": source_sha, "sections": sections,
            "section_counts": per_section, "section_status": section_status if measured else {},
            "rules": rules, "counts": counts, "counts_measured": measured,
            "audit": {"state": "NOT_MEASURED", "last_audit": None, "last_run": None, "reason": AUDIT_NOT_RUN}}


def unverified_audit(report: dict) -> dict:
    """An audit report exists but does not bind this exact policy version: name its run time, measure nothing."""
    when = report.get("as_of") if isinstance(report, dict) and isinstance(report.get("as_of"), str) else None
    reason = ("The last enforcement audit run does not match the served policy version, so its results are not shown."
              if when else AUDIT_NOT_RUN)
    return {"state": "NOT_MEASURED", "last_audit": None, "last_run": when, "reason": reason}
