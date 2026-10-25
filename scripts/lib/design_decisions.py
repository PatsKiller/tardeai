"""Approvals → Designs: projection of design versions awaiting the operator, and the one-tap decision writer.

AGENTS.md §28.13 (proposed text in design/AGENTS_28_13.md), design/README.md. A page version in design/ becomes
APPROVED or REJECTED only by the operator's decision, recorded as a DECIDED row (kind DESIGN) in the operator
decisions ledger (data/governance/operator_decisions.jsonl, scripts/lib/operator_approvals.DecisionLedger: the same
file, the same hash chain and the same store-approval gate as every other Approvals decision). "Signed" here means
hash-chained and attributed to the authenticated operator identity by the server; it is NOT a cryptographic
signature.

After the ledger append, the server-side writer mirrors the effective state of that version to the private design
store (persistent-state/data/design/pages/<page>/<vNNN>/decision.json, 0600). The committed status.json in design/
is a mirror an agent updates later from the ledger; the ledger is the record.

Private mockup images are served only as PNG/JPEG data URIs, only for files listed (path + sha256) in that version's
status.json. Nothing here places, sizes or changes a trade (MBI_BEHAVIOR=0); every effect is RECORD_ONLY.
"""
from __future__ import annotations

import base64
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from scripts.lib import design_pages as dp
from scripts.lib import operator_approvals as core

ROOT = Path(__file__).resolve().parents[2]
ITEM_PREFIX = "design-version:"
MAX_IMAGE = 4_000_000
MAX_SPEC = 20_000
MAX_REASON = 2000
IMAGE_ROLES = ("mockups", "baselines", "capture")
IMAGE_TYPES = {".png": ("image/png", b"\x89PNG\r\n\x1a\n"), ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
               ".jpeg": ("image/jpeg", b"\xff\xd8\xff")}
REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{8,80}$")
WIDTH = re.compile(r"(?<!\d)(1440|412|390)(?!\d)")
# The 10-24 back-fill groups (one Board 19 "Decided recently" line per recorded approval, not one per page).
BACKFILL_LABELS = {
    "handoffs/desks-redesign-20261024/SPEC.md": "Desk + page mockups (desk boards)",
    "handoffs/tradeinview-redesign-20261024/SPEC.md": "TradeInView + My questions mockups",
    "handoffs/watch-row-redesign-20261024/SPEC.md": "Watch row redesign",
    "handoffs/site-audit-20261024/SPEC.md": "Site fix package",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def private_design_root() -> Path:
    """persistent-state/data/design (TRADEAI_PERSISTENT_STATE_ROOT honoured by the shared helper)."""
    from scripts.lib.persistent_state_root import good_persistent_root
    return good_persistent_root() / "data" / "design"


def item_id(page: str, version: str) -> str:
    return f"{ITEM_PREFIX}{page}/{version}"


def _status(root: Path, page: str, version: str) -> dict | None:
    if not dp.PAGE_ID.fullmatch(page or "") or not dp.VERSION.fullmatch(version or ""):
        raise core.Refused("INVALID_DESIGN_VERSION", 400)
    path = Path(root) / "design/pages" / page / "versions" / version / "status.json"
    if not path.is_file():
        return None
    status = json.loads(path.read_text(encoding="utf-8"))
    errs = dp.validate_status(page, version, status, spec_exists=(path.parent / "SPEC.md").is_file())
    if errs:
        raise core.Refused("DESIGN_VERSION_INVALID", 503)
    return status


def _width(path: str) -> int | None:
    m = WIDTH.search(Path(path).name)
    return int(m.group(1)) if m else None


def _ledger_decisions(rows: list[dict]) -> dict[str, dict]:
    """Latest DECIDED row per design-version item id."""
    out = {}
    for r in rows:
        if r.get("event") == "DECIDED" and str(r.get("item_id", "")).startswith(ITEM_PREFIX):
            out[r["item_id"]] = r
    return out


def _version_card(root: Path, page: str, version: str, status: dict, titles: dict[str, str]) -> dict:
    spec_path = Path(root) / "design/pages" / page / "versions" / version / "SPEC.md"
    spec = spec_path.read_text(encoding="utf-8")[:MAX_SPEC] if spec_path.is_file() else ""
    files = (status.get("private_assets") or {}).get("files") or []
    images = [{"path": f["path"], "width": _width(f["path"]), "sha256": f["sha256"]} for f in files
              if f.get("role") == "mockups" and Path(f["path"]).suffix.lower() in IMAGE_TYPES]
    return {"id": item_id(page, version), "page": page, "page_title": titles.get(page, page), "version": version,
            "title": status.get("title") or f"{page} {version}", "state": status.get("state"),
            "fingerprint": status.get("fingerprint"), "created": status.get("created"),
            "proposed_by": (status.get("history") or [{}])[-1].get("by"),
            "removals": dp.parse_removals(spec), "spec": spec, "images": images,
            "mockup_files": sum(1 for f in files if f.get("role") == "mockups")}


def projection(root: Path = ROOT, *, ledger_rows: list[dict], now: datetime | None = None, limit: int = 20) -> dict:
    """GET view: PROPOSED page versions (design/), PROPOSED DSN designs (docs/designs), decided recently."""
    now = now or utc_now()
    gaps: list[dict] = []
    titles: dict[str, str] = {}
    try:
        titles = {p["id"]: p.get("title") or p["id"] for p in dp.load_registry(root).get("pages") or []}
    except (OSError, ValueError, KeyError, TypeError):
        gaps.append({"source": "design_registry", "reason": "design/registry.json unreadable"})
    decided = _ledger_decisions(ledger_rows)
    proposed, recent = [], []
    for page, version, status, _ in dp.iter_versions(root):
        if not isinstance(status, dict):
            gaps.append({"source": "design_pages", "reason": f"{page}/{version}: status.json missing"})
            continue
        if dp.validate_status(page, version, status, spec_exists=True):
            gaps.append({"source": "design_pages", "reason": f"{page}/{version}: status.json invalid"})
            continue
        ledger = decided.get(item_id(page, version))
        if status.get("state") == "PROPOSED" and not (ledger and ledger.get("document_sha") == status.get("fingerprint")):
            proposed.append(_version_card(root, page, version, status, titles))
    for ident, r in decided.items():
        recent.append({"id": ident, "title": r.get("title") or ident[len(ITEM_PREFIX):], "decision": r.get("decision"),
                       "outcome": "Approved" if r.get("decision") == "APPROVE" else "Rejected", "at": r.get("at"),
                       "actor": r.get("actor"), "recorded": "ledger", "document_sha": r.get("document_sha"),
                       "comment": r.get("comment") or ""})
    for r in ledger_rows:  # existing Approvals reader decisions on DSN designs (kind DESIGN)
        if r.get("event") == "DECIDED" and r.get("kind") == "DESIGN" and not str(r.get("item_id", "")).startswith(ITEM_PREFIX):
            recent.append({"id": r.get("item_id"), "title": str(r.get("item_id", "")).removeprefix("design:"),
                           "decision": r.get("decision"),
                           "outcome": {"APPROVE": "Approved", "REJECT": "Rejected"}.get(r.get("decision"), "Changes requested"),
                           "at": r.get("at"), "actor": r.get("actor"), "recorded": "ledger",
                           "document_sha": r.get("document_sha"), "comment": r.get("comment") or ""})
    groups: dict[tuple, dict] = {}
    for page, version, status, _ in dp.iter_versions(root):
        a = (status or {}).get("approval") or {}
        if a.get("kind") != "recorded in handoff, back-filled 2026-10-25":
            continue
        for src in a.get("source") or []:
            g = groups.setdefault((src, a.get("at")), {
                "id": "backfill:" + src, "title": BACKFILL_LABELS.get(src, src), "decision": "APPROVE",
                "outcome": "Approved", "at": a.get("at"), "actor": "operator", "recorded": "recorded in handoff",
                "ref": a.get("ref"), "pages": []})
            g["pages"].append(f"{page}/{version}")
    recent.extend(groups.values())
    recent.sort(key=lambda r: str(r.get("at") or ""), reverse=True)
    dsn = []
    try:
        from scripts.lib.design_registry import DesignStore
        designs, errors = DesignStore(root).load()
        if errors:
            gaps.append({"source": "docs_designs", "reason": f"{len(errors)} design file(s) unreadable"})
        dsn = [{"id": d["id"], "title": d["title"], "path": d.get("path"), "approval": d.get("approval"),
                "href": "/approvals/" + "design%3A" + d["id"]} for d in designs if d.get("status") == "PROPOSED"]
    except Exception as exc:  # noqa: BLE001 — a failed source is a visible gap, never a reassuring empty list
        gaps.append({"source": "docs_designs", "reason": type(exc).__name__})
    return {"proposed": proposed, "dsn_proposed": dsn, "decided_recently": recent[:limit],
            "counts": {"proposed": len(proposed), "dsn_proposed": len(dsn)}, "complete": not gaps, "gaps": gaps,
            "as_of": core.iso(now), "signature": "hash-chained ledger row + authenticated operator identity (not a cryptographic signature)"}


def write_mirror(private_root: Path, page: str, version: str, row: dict) -> Path:
    """Atomic 0600 write of the effective state of one version to the private store."""
    target_dir = Path(private_root) / "pages" / page / version
    target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    state = "APPROVED" if row["decision"] == "APPROVE" else "REJECTED"
    doc = {"schema": "DesignDecisionMirror@v1", "page": page, "version": version, "state": state,
           "decision": row["decision"], "by": row["actor"], "at": row["at"], "fingerprint": row["document_sha"],
           "comment": row.get("comment") or "", "ledger": {"file": core.DECISION_REL, "hash_self": row["hash_self"]},
           "writer": "scripts/lib/design_decisions.py"}
    fd, tmp = tempfile.mkstemp(dir=target_dir, prefix=".decision.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, target_dir / "decision.json")
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return target_dir / "decision.json"


def decide(actor: str, body: dict, *, root: Path, ledger: core.DecisionLedger, private_root: Path) -> dict:
    """One-tap APPROVE / REJECT of a PROPOSED page version by the authenticated operator (caller verified)."""
    if not isinstance(body, dict):
        raise core.Refused("OBJECT_BODY_REQUIRED", 400)
    choice = body.get("decision")
    if choice not in ("APPROVE", "REJECT"):
        raise core.Refused("INVALID_DECISION", 400)
    request = body.get("request_id")
    if not isinstance(request, str) or not REQUEST_ID.fullmatch(request):
        raise core.Refused("REQUEST_ID_REQUIRED", 400)
    comment = body.get("reason") or ""
    if not isinstance(comment, str) or len(comment) > MAX_REASON:
        raise core.Refused("COMMENT_TOO_LONG", 400)
    if choice == "REJECT" and not comment.strip():
        raise core.Refused("REASON_REQUIRED", 400)
    page, version = str(body.get("page") or ""), str(body.get("version") or "")
    ident = item_id(page, version)
    with ledger._transaction() as (rows, append):
        for r in rows:  # idempotent replay first: a repeated tap returns the recorded row
            if r.get("event") == "DECIDED" and r.get("request_id") == request:
                if (r.get("actor"), r.get("item_id"), r.get("decision"), r.get("comment"), r.get("document_sha")) == \
                        (actor, ident, choice, comment, body.get("fingerprint")):
                    return {"row": r, "replayed": True, "mirror": "UNCHANGED"}
                raise core.Refused("IDEMPOTENCY_CONFLICT")
        status = _status(root, page, version)  # re-read inside the transaction: a stale card cannot bind a newer file
        if status is None:
            raise core.Refused("ITEM_UNAVAILABLE", 404)
        if status.get("fingerprint") != body.get("fingerprint"):
            raise core.Refused("DOCUMENT_CHANGED")
        if any(r.get("event") == "DECIDED" and r.get("item_id") == ident and r.get("document_sha") == status["fingerprint"] for r in rows):
            raise core.Refused("ALREADY_DECIDED")
        if status.get("state") != "PROPOSED":
            raise core.Refused("VERSION_NOT_PROPOSED")
        row = append({"event": "DECIDED", "actor": actor, "item_id": ident, "kind": "DESIGN",
                      "document_sha": status["fingerprint"], "source_sha": None, "review_id": None,
                      "decision": choice, "comment": comment, "request_id": request, "policy_token": None,
                      "effect": "RECORD_ONLY", "governed_href": None, "title": str(status.get("title") or ident)[:300],
                      "design": {"page": page, "version": version, "fingerprint": status["fingerprint"],
                                 "one_tap": True}})
    try:
        mirror = str(write_mirror(private_root, page, version, row).relative_to(private_root))
    except OSError as exc:  # the ledger row is the record; a failed mirror is reported, never hidden
        mirror = "FAILED:" + type(exc).__name__
    return {"row": row, "replayed": False, "mirror": mirror}


def image(root: Path, private_root: Path, page: str, version: str, rel: str) -> dict:
    """A private mockup/baseline image listed in that version's status.json, as a data URI."""
    status = _status(root, page, version)
    if status is None:
        raise core.Refused("ITEM_UNAVAILABLE", 404)
    entry = next((f for f in (status.get("private_assets") or {}).get("files") or [] if f.get("path") == rel), None)
    if not entry or entry.get("role") not in IMAGE_ROLES:
        raise core.Refused("ASSET_NOT_LISTED", 404)
    kind = IMAGE_TYPES.get(Path(rel).suffix.lower())
    if not kind:
        raise core.Refused("ASSET_TYPE_REFUSED", 415)
    base = (Path(private_root) / "pages" / page).resolve()
    path = (base / rel).resolve()
    if base not in path.parents or not path.is_file():
        raise core.Refused("ASSET_UNAVAILABLE", 404)
    if path.stat().st_size > MAX_IMAGE:
        raise core.Refused("ASSET_TOO_LARGE", 413)
    data = path.read_bytes()
    import hashlib
    if hashlib.sha256(data).hexdigest() != entry.get("sha256"):
        raise core.Refused("ASSET_CHANGED", 409)
    mime, magic = kind
    if not data.startswith(magic):
        raise core.Refused("ASSET_TYPE_REFUSED", 415)
    return {"page": page, "version": version, "path": rel, "mime": mime, "sha256": entry["sha256"],
            "width": _width(rel), "image": f"data:{mime};base64," + base64.b64encode(data).decode()}


def make_ledger(path: Path, approved: Callable[[], bool], clock: Callable[[], datetime] = utc_now) -> core.DecisionLedger:
    return core.DecisionLedger(path, approved=approved, clock=clock)
