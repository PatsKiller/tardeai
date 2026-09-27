"""approval_package — ApprovalPackage@v1: one consolidated approval per wave, in front of the guard (13).

An append-only, hash-chained JSONL ledger of packages and their per-item decisions, a renderer for the
one Telegram message, and a parser for the operator's typed reply
(``APPROVE <pkg> all|1,3,5`` · ``DENY <pkg> [items] ["reason"]`` · ``DEFER <pkg> <hours>``).

Ledger path: ``$TRADEAI_APPROVAL_LEDGER_PATH`` → ``<root>/data/governance/approval_packages.jsonl``.
Every row carries ``hash_prev`` (the previous row's ``hash_self``) so the audit (05) can verify the
chain. Rows are events: PACKAGE_CREATED, SUBMITTED, DECIDED (per item), STATE (package state), NOTE.

Nothing here mints a guard grant. Grant minting is the poller's job on APPROVED (13 §6) and is a
Wave 1 tranche-2 change to run_telegram_callback_poller; this module only records.

Approval: pkg-20260927-cogx-w1-d9e1 item 8. Authority: READ_ONLY_ADVISORY. Broker/per-order
approvals (A4/A5) never enter a package (13 §7) — ``CATEGORIES`` has no such category.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "ApprovalPackage@v1"
CATEGORIES = ("OPERATOR", "SECURITY", "INFRA", "SOFTWARE", "BUDGET")
ITEM_STATES = ("PENDING", "APPROVED", "DENIED", "DEFERRED", "EXPIRED", "NEEDS_LOCAL", "EXECUTED", "VALIDATED", "ROLLED_BACK")
PACKAGE_STATES = ("DRAFT", "SUBMITTED", "PARTIAL", "APPROVED", "EXECUTING", "VALIDATED", "DENIED", "EXPIRED")
REMOTE_FORBIDDEN_SCOPES = ("sudo", "destructive", "file-delete", "frozen-v2", "guard-config")
DEFAULT_WINDOW_HOURS = 24
REMINDERS_HOURS = (4, 12)
MAX_MSG_LEN = 4000

_REPLY = re.compile(r"^\s*(APPROVE|DENY|DEFER)\s+(pkg-[a-z0-9-]+)\s*(.*)$", re.I)


class LedgerError(RuntimeError):
    pass


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def ledger_path(root: Path | None = None, env: dict | None = None) -> Path:
    env = os.environ if env is None else env
    if env.get("TRADEAI_APPROVAL_LEDGER_PATH"):
        return Path(env["TRADEAI_APPROVAL_LEDGER_PATH"])
    base = Path(root) if root else Path(env.get("TRADEAI_ROOT") or Path.cwd())
    return base / "data" / "governance" / "approval_packages.jsonl"


def _hash(row: dict) -> str:
    body = {k: v for k, v in row.items() if k != "hash_self"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)

    def rows(self) -> list[dict]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                out.append(json.loads(line))
        return out

    def last_hash(self) -> str | None:
        rows = self.rows()
        return rows[-1].get("hash_self") if rows else None

    def append(self, row: dict) -> dict:
        row = dict(row)
        row.setdefault("ts", _now().isoformat())
        row["hash_prev"] = self.last_hash()
        row["hash_self"] = _hash(row)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
        return row

    def verify_chain(self) -> tuple[bool, int, str | None]:
        prev = None
        for i, row in enumerate(self.rows()):
            if row.get("hash_prev") != prev:
                return False, i, "hash_prev mismatch"
            if _hash(row) != row.get("hash_self"):
                return False, i, "hash_self mismatch"
            prev = row["hash_self"]
        return True, len(self.rows()), None

    def package(self, package_id: str) -> dict | None:
        """Fold the events into the current package view."""
        pkg: dict | None = None
        for row in self.rows():
            if row.get("package_id") != package_id:
                continue
            ev = row.get("event")
            if ev == "PACKAGE_CREATED":
                pkg = json.loads(json.dumps(row["package"]))
            elif pkg is None:
                continue
            elif ev == "SUBMITTED":
                pkg["state"] = "SUBMITTED"; pkg["telegram"] = row.get("telegram", {})
                pkg["submitted_at"] = row.get("ts")
            elif ev == "DECIDED":
                for it in pkg["items"]:
                    if it["item_no"] == row["item_no"]:
                        it["state"] = row["state"]; it["decided_by"] = row.get("decided_by"); it["reason"] = row.get("reason")
                pkg["state"] = derive_state(pkg)
            elif ev == "STATE":
                pkg["state"] = row["state"]
            elif ev == "NOTE":
                pkg.setdefault("notes", []).append({"ts": row.get("ts"), "note": row.get("note")})
        return pkg


def new_package(campaign: str, wave: str, summary: str, items: Iterable[dict], *, binds: dict | None = None,
                reviews: dict | None = None, window_hours: int = DEFAULT_WINDOW_HOURS, package_id: str | None = None,
                now: _dt.datetime | None = None) -> dict:
    now = now or _now()
    pid = package_id or f"pkg-{now.strftime('%Y%m%d')}-{re.sub(r'[^a-z0-9]+', '-', wave.lower())}-{uuid.uuid4().hex[:4]}"
    out_items = []
    for n, it in enumerate(items, start=1):
        cat = str(it.get("category", "OPERATOR")).upper()
        if cat not in CATEGORIES:
            raise ValueError(f"item {n}: category {cat!r} not in {CATEGORIES}")
        for k in ("title", "why", "rule", "rollback"):
            if not it.get(k):
                raise ValueError(f"item {n}: {k} is required")
        scopes = list(it.get("scopes_needed") or [])
        out_items.append({
            "item_no": n, "item_id": it.get("item_id") or f"I-{n}", "category": cat, "title": it["title"],
            "why": it["why"], "rule": it["rule"], "reversible": bool(it.get("reversible", True)),
            "rollback": it["rollback"], "depends_on": list(it.get("depends_on") or []),
            "scopes_needed": scopes, "state": "NEEDS_LOCAL" if any(s in REMOTE_FORBIDDEN_SCOPES for s in scopes) else "PENDING",
            "decided_by": None, "reason": None,
        })
    return {
        "schema": SCHEMA, "package_id": pid, "campaign": campaign, "wave": wave, "summary": summary,
        "created_at": now.isoformat(), "expires_at": (now + _dt.timedelta(hours=window_hours)).isoformat(),
        "reviews": {k: (reviews or {}).get(k, "MISSING") for k in ("architecture", "infrastructure", "security")},
        "binds": binds or {}, "items": out_items, "state": "DRAFT", "telegram": {},
        "does_not_touch": ["MBI_BEHAVIOR (stays 0)", "broker", "live flags", "2FA", "sudo/destructive scopes"],
        "authority": "READ_ONLY_ADVISORY",
    }


def derive_state(pkg: dict) -> str:
    states = [it["state"] for it in pkg["items"]]
    decidable = [s for s in states if s != "NEEDS_LOCAL"]
    if pkg.get("state") in ("EXECUTING", "VALIDATED"):
        return pkg["state"]
    if decidable and all(s == "DENIED" for s in decidable):
        return "DENIED"
    if decidable and all(s in ("APPROVED", "DENIED", "DEFERRED", "EXPIRED") for s in decidable):
        # approved when every non-denied item is approved and denied items have no approved dependents
        if all(s in ("APPROVED", "DENIED") for s in decidable):
            return "APPROVED"
        return "PARTIAL"
    if any(s != "PENDING" for s in decidable):
        return "PARTIAL"
    return pkg.get("state", "SUBMITTED") if pkg.get("state") != "DRAFT" else "DRAFT"


def parse_reply(text: str) -> dict | None:
    """``APPROVE pkg-… all`` · ``APPROVE pkg-… 1,3,5`` · ``DENY pkg-… 6 "reason"`` · ``DEFER pkg-… 12h``."""
    m = _REPLY.match(text or "")
    if not m:
        return None
    verb, pid, rest = m.group(1).upper(), m.group(2).lower(), m.group(3).strip()
    out: dict[str, Any] = {"verb": verb, "package_id": pid, "items": None, "reason": None, "hours": None}
    reason = re.search(r'"([^"]*)"', rest)
    if reason:
        out["reason"] = reason.group(1); rest = rest.replace(reason.group(0), "").strip()
    if verb == "DEFER":
        h = re.search(r"(\d+)\s*h?", rest)
        out["hours"] = int(h.group(1)) if h else 12
        return out
    head = rest.split(",")[0].strip().lower() if rest else ""
    if not rest or head == "all":
        out["items"] = "all"
    else:
        nums = []
        for tok in re.split(r"[,\s]+", rest):
            tok = tok.strip()
            if tok.isdigit():
                nums.append(int(tok))
        out["items"] = sorted(set(nums)) or None
    return out


def apply_reply(ledger: Ledger, reply: dict, *, decided_by: dict) -> dict:
    pkg = ledger.package(reply["package_id"])
    if pkg is None:
        raise LedgerError(f"unknown package {reply['package_id']}")
    if pkg["state"] in ("EXPIRED", "VALIDATED"):
        raise LedgerError(f"package {pkg['package_id']} is {pkg['state']}")
    verb = reply["verb"]
    targets = [it["item_no"] for it in pkg["items"] if it["state"] in ("PENDING", "DEFERRED")] if reply.get("items") in (None, "all") \
        else [n for n in reply["items"] if any(it["item_no"] == n for it in pkg["items"])]
    if verb == "DEFER":
        new_exp = _now() + _dt.timedelta(hours=reply.get("hours") or 12)
        ledger.append({"event": "NOTE", "package_id": pkg["package_id"], "note": f"deferred to {new_exp.isoformat()}", "decided_by": decided_by})
        for n in targets:
            ledger.append({"event": "DECIDED", "package_id": pkg["package_id"], "item_no": n, "state": "DEFERRED", "decided_by": decided_by, "reason": reply.get("reason")})
    else:
        state = "APPROVED" if verb == "APPROVE" else "DENIED"
        for n in targets:
            it = next(i for i in pkg["items"] if i["item_no"] == n)
            if it["state"] == "NEEDS_LOCAL":
                continue
            ledger.append({"event": "DECIDED", "package_id": pkg["package_id"], "item_no": n, "state": state, "decided_by": decided_by, "reason": reply.get("reason")})
    return ledger.package(pkg["package_id"])


def render_message(pkg: dict) -> str:
    """The one consolidated message (13 §4). Markdown-safe: only the title is bold; no underscores."""
    def safe(s: Any) -> str:
        return str(s).replace("_", "-").replace("*", "")
    lines = [f"🔐 *Approval package {safe(pkg['package_id'])} — {safe(pkg['wave'])}*",
             f"Campaign: {safe(pkg['campaign'])}" + (f" · PR #{pkg['binds'].get('pr')}" if pkg.get('binds', {}).get('pr') else "")
             + (f" · sha {safe(pkg['binds'].get('sha'))}" if pkg.get('binds', {}).get('sha') else ""),
             "Reviews: " + " · ".join(f"{k} = {safe(v)}" for k, v in pkg["reviews"].items()),
             "Does NOT touch: " + ", ".join(safe(x) for x in pkg.get("does_not_touch", [])),
             f"Expires: {safe(pkg['expires_at'][:16])} UTC (reminders +{REMINDERS_HOURS[0]}h, +{REMINDERS_HOURS[1]}h)", ""]
    if pkg.get("summary"):
        lines += [safe(pkg["summary"]), ""]
    lines.append("NEEDS YOUR ANSWER (each item names its rule and rollback in the ledger):")
    for cat in CATEGORIES:
        its = [it for it in pkg["items"] if it["category"] == cat]
        if not its:
            continue
        lines.append(cat)
        for it in its:
            flag = "✓" if it["reversible"] else "✗"
            local = "  NEEDS-LOCAL" if it["state"] == "NEEDS_LOCAL" else ""
            scopes = f"  needs: {','.join(safe(s) for s in it['scopes_needed'])}" if it["scopes_needed"] else ""
            lines.append(f" {it['item_no']}. {safe(it['title'])}  reversible {flag}{scopes}{local}")
    pid = safe(pkg["package_id"])
    lines += ["", "Reply here or in Claude Code:", f" APPROVE {pid} all", f" APPROVE {pid} 1,2,3", f" DENY {pid} 6 \"reason\"   ·   DEFER {pid} 12h"]
    text = "\n".join(lines)
    return text


def chunks(text: str, limit: int = MAX_MSG_LEN) -> list[str]:
    try:
        from telegram_transport import split_for_telegram  # type: ignore
        return split_for_telegram(text)
    except Exception:  # noqa: BLE001
        out, cur = [], ""
        for line in text.splitlines(keepends=True):
            if len(cur) + len(line) > limit:
                out.append(cur); cur = ""
            cur += line
        if cur:
            out.append(cur)
        return out


__all__ = ["Ledger", "new_package", "derive_state", "parse_reply", "apply_reply", "render_message", "chunks",
           "ledger_path", "SCHEMA", "CATEGORIES", "ITEM_STATES", "PACKAGE_STATES", "REMOTE_FORBIDDEN_SCOPES", "LedgerError"]
