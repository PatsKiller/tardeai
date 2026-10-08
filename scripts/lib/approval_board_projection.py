"""Approval board — every open approval package and every active guard grant, with its time to expiry.

Roadmap Phase 2 PR-C (2026-10-08). The board is a READ-ONLY projection of two authorities that
stay exactly where they are: the hash-chained approval ledger (scripts/lib/approval_package.py,
``$TRADEAI_STATE_ROOT/data/governance/approval_packages.jsonl``) and the guard grant ledger
(``.cursor/hooks/guard_ledger.py list``). Nothing here approves, grants, consumes, sends or
decides; n8n never sees a grant value or a Telegram token.

Why: on 2026-10-07 two approved grants expired unused because nobody had one list with
"what is open, and how long until it dies". The board is that list, and the dispatcher turns
a row that is about to expire into ONE coordination event (see n8n_pilot_dispatch).

Pure functions over injected loaders so the proofs run without a ledger or a guard CLI.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

SCHEMA = "ApprovalBoard@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
RECEIPT_REL = "data/runtime/approval_board_last.json"
OPEN_PACKAGE_STATES = ("SUBMITTED", "PARTIAL")
PACKAGE_EXPIRY_WARN_MIN = 30     # an OPEN package within 30 min of its window end becomes an event
GRANT_EXPIRY_WARN_MIN = 10       # an active grant within 10 min of expiry becomes an event
REASON_MAX = 160

ROOT = Path(__file__).resolve().parents[2]
GUARD_LEDGER_CLI = ROOT / ".cursor" / "hooks" / "guard_ledger.py"


def _utc(ts: Any) -> Optional[_dt.datetime]:
    if ts is None or ts == "":
        return None
    if isinstance(ts, (int, float)):
        return _dt.datetime.fromtimestamp(float(ts), tz=_dt.timezone.utc)
    try:
        d = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=_dt.timezone.utc)


def _iso(d: Optional[_dt.datetime]) -> Optional[str]:
    return d.isoformat() if d else None


def _minutes(a: Optional[_dt.datetime], b: Optional[_dt.datetime]) -> Optional[int]:
    if a is None or b is None:
        return None
    return int((a - b).total_seconds() // 60)


# ── loaders (the only two places that touch an authority; both read-only) ─────────────────────

def load_packages(ledger_path: Optional[Path] = None) -> list[dict[str, Any]]:
    """Every package in the ledger, folded to its current view (same fold the reminder uses)."""
    try:
        from scripts.lib import approval_package as ap
    except ImportError:  # scripts/lib on sys.path only
        import approval_package as ap  # type: ignore
    path = Path(ledger_path) if ledger_path else ap.ledger_path()
    ledger = ap.Ledger(path)
    ids: list[str] = []
    for row in ledger.rows():
        pid = row.get("package_id")
        if row.get("event") == "PACKAGE_CREATED" and pid and pid not in ids:
            ids.append(pid)
    out = []
    for pid in ids:
        pkg = ledger.package(pid)
        if pkg:
            out.append(pkg)
    return out


def load_grants(cli: Optional[Path] = None, *, timeout_s: float = 10.0) -> dict[str, Any]:
    """`guard_ledger.py list` → {state, grants: {tier: {expires, uses, reason, created_at?, grant_id?}}, active: [..]}.
    Values only; never the ledger file itself, never a write."""
    cli = Path(cli) if cli else GUARD_LEDGER_CLI
    if not cli.is_file():
        raise FileNotFoundError(f"guard ledger CLI absent: {cli}")
    proc = subprocess.run([sys.executable, str(cli), "list"], capture_output=True, text=True, timeout=timeout_s)
    if proc.returncode != 0:
        raise RuntimeError(f"guard ledger list rc={proc.returncode}: {(proc.stderr or proc.stdout)[:120]}")
    doc = json.loads(proc.stdout or "{}")
    if not isinstance(doc, dict) or not isinstance(doc.get("grants"), dict):
        raise RuntimeError("guard ledger list: malformed document")
    return doc


# ── pure projection ────────────────────────────────────────────────────────────────────────────

def package_rows(packages: Iterable[Mapping[str, Any]], *, now: _dt.datetime) -> list[dict[str, Any]]:
    rows = []
    for pkg in packages:
        created = _utc(pkg.get("submitted_at") or pkg.get("created_at"))
        expires = _utc(pkg.get("expires_at"))
        state = str(pkg.get("state") or "DRAFT")
        is_open = state in OPEN_PACKAGE_STATES and (expires is None or expires > now)
        if state in OPEN_PACKAGE_STATES and expires is not None and expires <= now:
            state = "EXPIRED"   # the ledger has not recorded it yet; the board reports the clock, not the row
        items = pkg.get("items") or []
        pending = sum(1 for it in items if str(it.get("state")) in ("PENDING", "NEEDS_LOCAL"))
        rows.append({
            "kind": "package", "id": str(pkg.get("package_id")), "scope": str(pkg.get("campaign") or "") + ":" + str(pkg.get("wave") or ""),
            "state": "OPEN" if is_open else state, "ledger_state": str(pkg.get("state") or "DRAFT"),
            "created_at": _iso(created), "expires_at": _iso(expires),
            "age_min": _minutes(now, created), "ttl_min_left": _minutes(expires, now), "uses_left": None,
            "items_total": len(items), "items_pending": pending,
            "reason": str(pkg.get("summary") or "")[:REASON_MAX],
        })
    return rows


def grant_rows(ledger_doc: Mapping[str, Any], *, now: _dt.datetime) -> list[dict[str, Any]]:
    rows = []
    for tier, rec in (ledger_doc.get("grants") or {}).items():
        if not isinstance(rec, Mapping):
            continue
        expires = _utc(rec.get("expires"))
        created = _utc(rec.get("created_at"))
        uses = int(rec.get("uses", 0) or 0)
        active = bool(expires and expires > now and (uses < 0 or uses > 0))
        if active:
            state = "ACTIVE"
        elif expires and expires <= now:
            state = "EXPIRED"
        else:
            state = "CONSUMED"
        rows.append({
            "kind": "grant", "id": str(rec.get("grant_id") or tier), "scope": str(tier), "state": state,
            "created_at": _iso(created), "expires_at": _iso(expires),
            "age_min": _minutes(now, created), "ttl_min_left": _minutes(expires, now),
            "uses_left": (None if uses < 0 else uses), "items_total": None, "items_pending": None,
            "reason": str(rec.get("reason") or "")[:REASON_MAX],
        })
    return rows


def expiring(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Rows the operator must act on NOW: open packages within 30 min of their window end,
    active grants within 10 min of expiry. Expired and consumed rows are history, not alarms."""
    out = []
    for r in rows:
        ttl = r.get("ttl_min_left")
        if ttl is None or ttl < 0:
            continue
        if r["kind"] == "package" and r["state"] == "OPEN" and ttl <= PACKAGE_EXPIRY_WARN_MIN:
            out.append(dict(r))
        elif r["kind"] == "grant" and r["state"] == "ACTIVE" and ttl <= GRANT_EXPIRY_WARN_MIN:
            out.append(dict(r))
    return out


def event_plan(row: Mapping[str, Any]) -> dict[str, Any]:
    """One coordination event per (kind, id, expiry). The key and the subject use the EXPIRY INSTANT
    (the bucket), never the live minutes-left, so repeated runs inside the bucket carry an identical
    payload and the gateway answers `duplicate`, not `idempotency_conflict`."""
    bucket = str(row.get("expires_at") or "no-expiry")
    key = "apx-" + hashlib.sha256(f"{row['kind']}|{row['id']}|{bucket}".encode("utf-8")).hexdigest()[:20]
    return {
        "idempotency_key": key,
        "subject_key": f"approval:{row['kind']}:{row['id']}:expires_at={bucket[:16]}"[:200],
        "artifact_rel": RECEIPT_REL,          # root-relative, like every other pilot artifact
        "store": "data/runtime",
        "at": row.get("created_at") or row.get("expires_at"),
        "kind": row["kind"], "id": row["id"], "expires_at": row.get("expires_at"), "ttl_min_left": row.get("ttl_min_left"),
    }


def build_board(now: Optional[_dt.datetime] = None, *,
                packages_loader: Optional[Callable[[], Iterable[Mapping[str, Any]]]] = None,
                grants_loader: Optional[Callable[[], Mapping[str, Any]]] = None) -> dict[str, Any]:
    """The payload the route serves and the dispatcher writes as its receipt. Each source is
    fail-soft and names its own status; a dead source is UNAVAILABLE, never an empty OK."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    sources: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    try:
        pkgs = list((packages_loader or load_packages)())
        rows += package_rows(pkgs, now=now)
        sources["packages"] = {"status": "OK", "count": len(pkgs)}
    except Exception as exc:  # noqa: BLE001 — a missing ledger is a named status
        sources["packages"] = {"status": "UNAVAILABLE", "reason": f"{type(exc).__name__}: {str(exc)[:120]}"}
    try:
        doc = (grants_loader or load_grants)()
        rows += grant_rows(doc, now=now)
        sources["grants"] = {"status": "OK", "ledger_state": doc.get("state"), "count": len(doc.get("grants") or {})}
    except Exception as exc:  # noqa: BLE001
        sources["grants"] = {"status": "UNAVAILABLE", "reason": f"{type(exc).__name__}: {str(exc)[:120]}"}
    counts: dict[str, dict[str, int]] = {}
    for r in rows:
        counts.setdefault(r["kind"], {})
        counts[r["kind"]][r["state"]] = counts[r["kind"]].get(r["state"], 0) + 1
    rows.sort(key=lambda r: (r["ttl_min_left"] if r["ttl_min_left"] is not None else 10**9, r["kind"], r["id"]))
    exp = expiring(rows)
    status = "OK" if all(s.get("status") == "OK" for s in sources.values()) else "PARTIAL" if any(
        s.get("status") == "OK" for s in sources.values()) else "UNAVAILABLE"
    return {"schema": SCHEMA, "authority": AUTHORITY, "as_of": now.isoformat(), "status": status, "sources": sources,
            "counts": counts, "expiring": exp, "expiring_count": len(exp), "total": len(rows), "items": rows,
            "note": "open packages and active grants with time-to-expiry; nothing here approves, grants or sends"}


def load_board(now: Optional[_dt.datetime] = None) -> dict[str, Any]:
    """Route entry point: the live ledgers, read-only."""
    return build_board(now)


def write_receipt(board: Mapping[str, Any], root: Path) -> Path:
    out = root / RECEIPT_REL
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(board, indent=1, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, out)
    return out
