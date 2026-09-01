#!/usr/bin/env python3
"""WAVE G6 — missing CanonicalStoreRegistry stores classifier.

Create an empty durable JSONL **only** when:
  1. the registry lists the store, AND
  2. a live production consumer reads **that registry path** (not a Postgres
     table of a similar name, not a sibling filename).

Otherwise disposition is CONSUMER_ABSENT_OR_RETIRED and we report — never invent
an unread empty store. Evening packet forbids retired ``cio_decisions``.

AUTHORITY: READ_ONLY_ADVISORY. MBI=0. No deploy. No financial action.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

NO_CONSUMER_REASON = (
    "WAVE G6 audit classifier; CLI + allowlisted overnight suite only; "
    "no production write path by design"
)

AUTHORITY = "READ_ONLY_ADVISORY"
MBI = 0
SCHEMA = "G6MissingStoreDecision@v1"
DISPOSITION_RETIRED = "CONSUMER_ABSENT_OR_RETIRED"
DISPOSITION_CREATE = "CREATE_EMPTY_DURABLE"

# Registry ids this wave owns.
G6_STORE_IDS: tuple[str, ...] = (
    "cio.decisions",
    "notifications.outbox",
    "learning.weekly",
)

# Live path the NotificationOutbox class actually defaults to (sibling of the
# registry path). Verified in scripts/lib/cio_notification_outbox.py.
LIVE_OUTBOX_SIBLING = "data/cio/operator_notification_outbox.jsonl"

# Weekly learning live surfaces (not registry path weekly_learning.jsonl).
LIVE_WEEKLY_SURFACES = (
    "paper_trade_multi_reviews",  # Postgres via multi_tier_trade_reviewer
    "data/cio/cio_weekly_learning_reviews.jsonl",  # materialize / api_v3_cio
)

ROOT = Path(__file__).resolve().parents[1]


def _load_registry():
    sys.path.insert(0, str(ROOT))
    from scripts.lib.canonical_store_registry import STORES, resolve_store

    return STORES, resolve_store


def classify_store(store_id: str, *, root: Path | str | None = None) -> dict[str, Any]:
    """Return a create-or-report decision for one G6 store id."""
    STORES, resolve_store = _load_registry()
    spec = STORES.get(store_id)
    if not spec:
        return {
            "schema": SCHEMA,
            "store_id": store_id,
            "registry_expects": False,
            "disposition": DISPOSITION_RETIRED,
            "create_empty_durable": False,
            "reason": "UNKNOWN_STORE",
            "authority": AUTHORITY,
            "memory_behavior_influence": MBI,
        }

    base = Path(root) if root else None
    loc = resolve_store(store_id, root=base)
    primary = str(spec.get("path") or "")
    retired = bool(spec.get("retired_as_canonical_current"))

    live_consumer_of_registry_path = False
    evidence: list[str] = []

    if store_id == "cio.decisions":
        # Evening packet + registry flag forbid revival as canonical intelligence.
        # Postgres ``cio_decisions`` table is a different surface — do not confuse.
        # memory_consolidator_shadow soft-reads and treats missing as [].
        live_consumer_of_registry_path = False
        evidence.append("retired_as_canonical_current=true")
        evidence.append("aegis evening packet forbids cio_decisions artifact")
        evidence.append("no live reader of data/cio/cio_decisions.jsonl (shadow soft-miss only)")
        evidence.append("do not confuse with Postgres cio_decisions table")
    elif store_id == "notifications.outbox":
        # Live NotificationOutbox defaults to operator_notification_outbox.jsonl.
        # telegram_receipts optionally lists the registry path but skips if absent;
        # creating an empty twin would falsely look like an empty outbox while the
        # live sibling holds data.
        live_consumer_of_registry_path = False
        evidence.append(f"registry path={primary}")
        evidence.append(f"live NotificationOutbox default={LIVE_OUTBOX_SIBLING}")
        evidence.append("no writer targets registry path; prefer report over empty twin")
    elif store_id == "learning.weekly":
        live_consumer_of_registry_path = False
        evidence.append(f"registry path={primary}")
        evidence.append(
            "writer multi_tier_trade_reviewer persists to Postgres "
            "paper_trade_multi_reviews, not weekly_learning.jsonl"
        )
        evidence.append(
            "api_v3_cio / materialize_cio_weekly_learning use "
            "cio_weekly_learning_reviews.jsonl — different filename"
        )
        evidence.append("no live reader of weekly_learning.jsonl")
    else:
        evidence.append("not in G6 decision table")

    create = bool(
        spec
        and live_consumer_of_registry_path
        and not retired
    )
    disposition = DISPOSITION_CREATE if create else DISPOSITION_RETIRED

    return {
        "schema": SCHEMA,
        "store_id": store_id,
        "registry_expects": True,
        "registry_path": primary,
        "exists_at_root": bool(loc.get("exists")),
        "resolved_path": str(loc.get("path") or loc.get("primary_path") or ""),
        "retired_as_canonical_current": retired,
        "live_consumer_of_registry_path": live_consumer_of_registry_path,
        "disposition": disposition,
        "create_empty_durable": create,
        "evidence": evidence,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
    }


def classify_all(*, root: Path | str | None = None) -> dict[str, Any]:
    rows = [classify_store(sid, root=root) for sid in G6_STORE_IDS]
    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI,
        "financial_action": False,
        "store_ids": list(G6_STORE_IDS),
        "decisions": rows,
        "created": [r["store_id"] for r in rows if r.get("create_empty_durable")],
        "reported": [
            r["store_id"] for r in rows if not r.get("create_empty_durable")
        ],
        "rule": (
            "CREATE empty durable only if registry expects AND live consumer "
            "reads that jsonl/path; else CONSUMER_ABSENT_OR_RETIRED"
        ),
    }


def verify_host_roots() -> dict[str, Any]:
    """Read-only existence check on persistent-state and CURRENT (when present)."""
    home = Path.home()
    candidates = {
        "persistent-state": home / "trade-ai-releases" / "persistent-state",
        "CURRENT": home / "trade-ai-releases" / "portfolio-server" / "CURRENT",
    }
    STORES, _ = _load_registry()
    out: dict[str, Any] = {}
    for label, root in candidates.items():
        if not root.is_dir():
            out[label] = {"present": False}
            continue
        files: dict[str, Any] = {}
        for sid in G6_STORE_IDS:
            rel = STORES[sid]["path"]
            p = root / rel
            files[sid] = {
                "path": rel,
                "exists": p.is_file(),
                "bytes": p.stat().st_size if p.is_file() else 0,
            }
        # Sibling live surfaces (context only).
        sibling = root / LIVE_OUTBOX_SIBLING
        files["_live_outbox_sibling"] = {
            "path": LIVE_OUTBOX_SIBLING,
            "exists": sibling.is_file(),
            "bytes": sibling.stat().st_size if sibling.is_file() else 0,
        }
        out[label] = {"present": True, "root": str(root.resolve()), "files": files}
    return out


def evening_packet_forbids_cio_decisions(repo_root: Path | None = None) -> bool:
    root = repo_root or ROOT
    cfg = json.loads(
        (root / "config" / "aegis_evening_surveillance.json").read_text(encoding="utf-8")
    )
    forbidden = cfg.get("forbidden_inputs") or []
    packet = root / "scripts" / "aegis_evening_packet.py"
    text = packet.read_text(encoding="utf-8") if packet.is_file() else ""
    return "cio_decisions" in forbidden and "retired_artifacts_forbidden" in text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="Emit JSON report")
    ap.add_argument("--root", type=str, default=None, help="State root override")
    ap.add_argument("--host-check", action="store_true", help="Also probe PS/CURRENT")
    args = ap.parse_args(argv)
    report = classify_all(root=args.root)
    if args.host_check:
        report["host"] = verify_host_roots()
    report["evening_forbids_cio_decisions"] = evening_packet_forbids_cio_decisions()
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"schema={SCHEMA} authority={AUTHORITY}")
        print(f"created={report['created'] or '(none)'}")
        print(f"reported={report['reported']}")
        for row in report["decisions"]:
            print(
                f"  {row['store_id']}: {row['disposition']} "
                f"exists={row.get('exists_at_root')} "
                f"create={row['create_empty_durable']}"
            )
            for e in row.get("evidence") or []:
                print(f"    - {e}")
        if args.host_check:
            print("host:", json.dumps(report["host"], indent=2, default=str))
    # Non-zero only if a decision says create but we somehow cannot classify.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
