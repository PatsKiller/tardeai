#!/usr/bin/env python3
"""WP-30 decision packet: no holdings writer; archive only after authorized metadata correction."""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import yaml

KEY = "moomoo_taxable_live"
LABEL = "moomoo Taxable"
DECISION = "UNRETIRE_ACCOUNT_RECORD"
CURRENT = Path("/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT")
PERSISTENT = Path("/home/johnclaw/trade-ai-releases/persistent-state")
TRIPWIRE = Path(
    "/home/johnclaw/trade-ai-releases/holdings-moomoo-retire-20260901-131731/RETIRED_moomoo_taxable_live.json"
)
STATES = {"LIVE", "STALE", "SERVICE_DOWN", "NO_API_MANUAL", "UNCLASSIFIED"}


@dataclass(frozen=True)
class Paths:
    holdings: Path = PERSISTENT / "data/portfolios/state/holdings.json"
    served_holdings: Path = CURRENT / "data/portfolios/state/holdings.json"
    registry: Path = CURRENT / "assets/portfolio_accounts.yaml"
    tripwire: Path = TRIPWIRE
    lock: Path = Path("/tmp/holdings_write.lock")
    cache: Path = Path.home() / ".cache/rtc"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_time(value):
    if not isinstance(value, str):
        return "NOT_MEASURED"
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return "NOT_MEASURED"


def snapshot(paths):
    if paths.served_holdings.resolve(strict=True) != paths.holdings.resolve(strict=True):
        raise ValueError("served/persistent holdings diverge; report both, do not choose")
    raw = paths.holdings.read_bytes()
    doc = json.loads(raw)
    summary = doc.get("account_summaries", {}).get(KEY)
    if not isinstance(summary, dict):
        raise ValueError("account summary missing; no record may be invented")
    registry_raw = paths.registry.read_bytes()
    registry = yaml.safe_load(registry_raw)
    account = (registry.get("accounts") or {}).get(KEY)
    if not isinstance(account, dict):
        raise ValueError("account registry row missing")
    tripwire_raw = paths.tripwire.read_bytes()
    archived = json.loads(tripwire_raw)
    if archived.get("schema") != "RetiredAccountRow@v1" or archived.get("account") != KEY:
        raise ValueError("unexpected tripwire schema/account")
    resolution = summary.get("retirement_resolution") or {}
    if not isinstance(resolution, dict):
        raise ValueError("existing resolution has unexpected shape")
    state = summary.get("state")
    safe = {
        "account_label": LABEL,
        "retired": summary.get("retired") if isinstance(summary.get("retired"), bool) else "NOT_MEASURED",
        "retired_at": safe_time(summary.get("retired_at")),
        "stored_state": state if isinstance(state, str) and state in STATES else "NOT_MEASURED",
        "state_as_of": safe_time(summary.get("state_as_of")),
        "registry_active": account.get("active") if isinstance(account.get("active"), bool) else "NOT_MEASURED",
        "holding_row_count": sum(
            1 for row in doc.get("holdings", []) if isinstance(row, dict) and row.get("account") == KEY
        ),
        "hashes": {"holdings": sha(raw), "registry": sha(registry_raw), "tripwire": sha(tripwire_raw)},
        "archive_ready": summary.get("retired") is False
        and resolution.get("decision") == DECISION
        and resolution.get("tripwire_sha256") == sha(tripwire_raw),
    }
    return safe, doc


def proposed_document(doc, observation, *, decision, now):
    if decision != DECISION:
        raise ValueError("an explicit operator decision is required; the worker cannot decide")
    if now.tzinfo is None:
        raise ValueError("zoned proposal timestamp required")
    if observation["retired"] is not True or observation["registry_active"] is not True:
        raise ValueError("expected retired summary plus already-active registry; inspect drift")
    proposed = copy.deepcopy(doc)
    summary = proposed["account_summaries"][KEY]
    if "retirement_resolution" in summary:
        raise ValueError("existing resolution must be reviewed, not overwritten")
    summary["retired"] = False
    summary["retirement_resolution"] = {
        "schema": "AccountRetirementResolutionProposal@v1",
        "decision": DECISION,
        "proposed_at": now.isoformat(),
        "tripwire_sha256": observation["hashes"]["tripwire"],
        "note": "Metadata only; retains historical retirement fields; no financial freshness or LIVE state asserted.",
    }
    return proposed


def private_folder(root, prefix):
    root.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix=prefix, dir=root))
    folder.chmod(0o700)
    return folder


def write_private(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
    path.chmod(0o600)


def preview(paths, now):
    if now.tzinfo is None:
        raise ValueError("zoned preview timestamp required")
    observation, _ = snapshot(paths)
    folder = private_folder(paths.cache, "wp30-preview-")
    receipt = {
        "schema": "MoomooRetirementPreview@v1",
        "at": now.isoformat(),
        "observation": observation,
        "holdings_apply_available": False,
        "decision": "OPERATOR_REQUIRED",
    }
    write_private(folder / "preview.json", receipt)
    return folder / "preview.json", observation


def prepare(paths, now, *, decision):
    observation, doc = snapshot(paths)
    candidate = proposed_document(doc, observation, decision=decision, now=now)
    folder = private_folder(paths.cache, "wp30-proposal-")
    write_private(folder / "candidate.PRIVATE.json", candidate)
    write_private(
        folder / "proposal.json",
        {
            "schema": "MoomooRetirementProposal@v1",
            "at": now.isoformat(),
            "observation": observation,
            "decision_proposed": decision,
            "candidate_sha256": sha((folder / "candidate.PRIVATE.json").read_bytes()),
            "requires": [
                "operator decision",
                "named state-write grant authorizing a one-time metadata writer",
                "existing shared holdings lock and protected_holdings_write",
                "exact readback before archive",
            ],
            "production_changed": False,
        },
    )
    return folder / "proposal.json"


@contextmanager
def shared_lock(path):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def archive(paths, now, preview_path, *, decision):
    if now.tzinfo is None:
        raise ValueError("zoned archive timestamp required")
    if decision != DECISION:
        raise ValueError("operator decision required")
    preview_path = Path(preview_path)
    if preview_path.is_symlink() or preview_path.stat().st_uid != os.getuid() or preview_path.stat().st_mode & 0o077:
        raise ValueError("preview must be private and owned by this operator")
    receipt = json.loads(preview_path.read_text())
    if receipt.get("schema") != "MoomooRetirementPreview@v1":
        raise ValueError("not a preview receipt")
    at = datetime.fromisoformat(receipt["at"])
    if at.tzinfo is None or not 0 <= (now - at).total_seconds() <= 900:
        raise ValueError("preview expired/future/unzoned")
    with shared_lock(paths.lock):
        current, _ = snapshot(paths)
        if current != receipt["observation"] or not current["archive_ready"]:
            raise ValueError(
                "drift or unresolved retirement; authorized holdings correction/readback must happen first"
            )
        if paths.tripwire.is_symlink():
            raise ValueError("tripwire must not be symlinked")
        folder = private_folder(paths.tripwire.parent, "resolved-unretirement-")
        write_private(
            folder / "resolution.STARTED.json",
            {
                "schema": "RetirementTripwireArchive@v1",
                "at": now.isoformat(),
                "decision": decision,
                "account_label": LABEL,
                "tripwire_sha256": current["hashes"]["tripwire"],
                "holdings_sha256": current["hashes"]["holdings"],
                "original": str(paths.tripwire),
            },
        )
        target = folder / paths.tripwire.name
        paths.tripwire.rename(target)
        target.chmod(0o600)
        if sha(target.read_bytes()) != current["hashes"]["tripwire"]:
            raise ValueError("archived bytes mismatch; preserve archive and inspect")
        write_private(
            folder / "resolution.COMPLETE.json",
            {
                "schema": "RetirementTripwireArchive@v1",
                "at": now.isoformat(),
                "decision": decision,
                "account_label": LABEL,
                "archived": str(target),
                "tripwire_sha256": current["hashes"]["tripwire"],
                "production_holdings_changed": False,
            },
        )
        return folder / "resolution.COMPLETE.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "prepare", "archive", "apply-holdings"))
    parser.add_argument("--decision", choices=(DECISION,))
    parser.add_argument("--approved-preview")
    args = parser.parse_args()
    paths = Paths()
    now = datetime.now(timezone.utc)
    if args.action == "apply-holdings":
        raise ValueError(
            "NOT IMPLEMENTED: §7A requires a named new-writer grant and §9.4 protected_holdings_write; no direct JSON writer provided"
        )
    if args.action == "preview":
        receipt, safe = preview(paths, now)
        print(json.dumps({"receipt": str(receipt), "safe_observation": safe}, indent=2))
    elif args.action == "prepare":
        print(prepare(paths, now, decision=args.decision))
    else:
        if not args.approved_preview or not args.decision:
            raise ValueError("archive requires an approved fresh preview and explicit operator decision")
        if not sys.stdin.isatty() or input(f"Type {DECISION}-ARCHIVE: ") != DECISION + "-ARCHIVE":
            raise ValueError("operator TTY and exact phrase required")
        print(archive(paths, datetime.now(timezone.utc), args.approved_preview, decision=args.decision))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError) as exc:
        raise SystemExit(f"REFUSED: {exc}")
