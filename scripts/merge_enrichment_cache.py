#!/usr/bin/env python3
"""merge_enrichment_cache.py — fold the non-record Finviz enrichment cache copy into the store of record.

Operator decision 2026-10-10 ~17:45 ET (CONSOLIDATION_PLAN.md §D.3): the store of record for the
``finviz_enrichment`` domain is ``data/state/ticker_enrichment_cache.json`` (single writer
``scripts/finviz_enrichment.py``). The second copy, ``data/portfolios/state/ticker_enrichment_cache.json``,
is archived — never deleted — and its entries are merged into the store by **per-symbol newest
timestamp** (``cached_at``).

Two divergent copies of an authoritative store are never reconciled by an agent alone (AGENTS.md
§0 rule 5): the rule is the operator's, and the live ``--apply`` additionally needs a release-write
grant. Without ``--apply`` this tool is read-only: it reads both files, prints the plan and, with
``--report``, writes the plan as JSON to a path outside both stores. It re-hashes both files at the
end and fails if either changed while it ran.

Per symbol (``record_as_of`` reads a naive ``cached_at`` as host-local, the writer's convention):

    only in the copy                         -> ADD      (copied into the store)
    in both, copy strictly newer             -> REPLACE  (copy's record wins)
    in both, store newer or equal            -> KEEP     (store's record stays)
    copy record has no parseable cached_at   -> KEEP if the store has the symbol, else ADD_UNDATED
                                                (nothing is dropped; an undated record is still data)

``--apply`` (needs ``--grant-ref`` and ``--expect-copy-sha256`` from the dry run; refuses on drift):

    1. copy the copy file into ``<archive root>/<UTC stamp>/`` with a manifest row (sha256, size,
       mtime, origin path), and verify the archived bytes hash to the same sha256;
    2. merge the ADD/REPLACE/ADD_UNDATED records through ``finviz_enrichment.save_cache`` — the
       writer's own lock, re-read, merge and atomic replace, so the store keeps one writer;
    3. replace the copy path with a relative symlink to the store (``../../state/…``) so the ~40
       readers of the old path keep reading — one copy, served from the store of record;
    4. write a receipt (``MergeEnrichmentCacheReceipt@v1``) next to the archived file.

The archive root is ``check_served_copy_split.ENRICHMENT_CACHE_ARCHIVE_ROOT``, which is in that
monitor's ``ARCHIVE_ROOTS``: any live reference to it from scripts/, config/, the crontab or a unit
file trips the hourly ``[PLATFORM_AVAILABILITY]`` tripwire (AGENTS.md §0 rule 6).

Usage:
    python3 scripts/merge_enrichment_cache.py                       # dry run, summary
    python3 scripts/merge_enrichment_cache.py --report plan.json    # dry run + JSON plan
    python3 scripts/merge_enrichment_cache.py --apply --grant-ref <grant> --expect-copy-sha256 <sha>

AUTHORITY: READ_ONLY_ADVISORY. Market reference data only; never touches a broker or an order.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

SCHEMA = "MergeEnrichmentCachePlan@v1"
RECEIPT_SCHEMA = "MergeEnrichmentCacheReceipt@v1"
STORE_REL = "data/state/ticker_enrichment_cache.json"
COPY_REL = "data/portfolios/state/ticker_enrichment_cache.json"
#: the alias left at COPY_REL, relative to data/portfolios/state/
ALIAS_TARGET = "../../state/ticker_enrichment_cache.json"
SAMPLE = 10


def _archive_root() -> Path:
    from check_served_copy_split import ENRICHMENT_CACHE_ARCHIVE_ROOT

    return Path(ENRICHMENT_CACHE_ARCHIVE_ROOT)


def _state_root(root: str | None) -> Path:
    if root:
        return Path(root)
    try:
        from lib.canonical_store_registry import production_state_root
    except Exception:  # noqa: BLE001
        return PROJECT_ROOT
    return Path(production_state_root())


def _record_as_of(record: Any) -> datetime | None:
    from lib.data_broker.finviz_enrichment_snapshot import record_as_of

    return record_as_of(record)


def file_facts(path: Path) -> dict[str, Any]:
    """sha256 / size / mtime / is_symlink / resolved path — read-only."""
    out: dict[str, Any] = {"path": str(path), "exists": path.exists(), "is_symlink": path.is_symlink()}
    if path.is_symlink():
        out["symlink_target"] = os.readlink(path)
    if not path.is_file():
        return out
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    st = path.stat()
    out.update(
        sha256=h.hexdigest(),
        size=st.st_size,
        mtime=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
        resolved=str(path.resolve()),
    )
    return out


def _load(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top level is {type(data).__name__}, not an object")
    return data


def plan_merge(store: dict[str, Any], copy: dict[str, Any]) -> dict[str, Any]:
    """Pure. Per-symbol decision for every symbol in ``copy``; the merged result; counts."""
    decisions: dict[str, list[str]] = {"ADD": [], "REPLACE": [], "KEEP": [], "ADD_UNDATED": []}
    winners: dict[str, Any] = {}
    for sym, rec in copy.items():
        if str(sym).startswith("_"):
            continue  # metadata keys are not symbols
        mine = store.get(sym)
        c_dt = _record_as_of(rec)
        if mine is None:
            kind = "ADD" if c_dt is not None else "ADD_UNDATED"
        else:
            s_dt = _record_as_of(mine)
            kind = "REPLACE" if (c_dt is not None and (s_dt is None or c_dt > s_dt)) else "KEEP"
        decisions[kind].append(sym)
        if kind != "KEEP":
            winners[sym] = rec
    merged = dict(store)
    merged.update(winners)
    return {
        "decisions": {k: sorted(v) for k, v in decisions.items()},
        "counts": {k: len(v) for k, v in decisions.items()},
        "winners": winners,
        "merged": merged,
    }


def build_plan(state_root: Path) -> dict[str, Any]:
    store_p, copy_p = state_root / STORE_REL, state_root / COPY_REL
    before = {"store": file_facts(store_p), "copy": file_facts(copy_p)}
    if not before["store"].get("sha256"):
        raise SystemExit(f"REFUSE: store of record missing: {store_p}")
    if before["copy"]["is_symlink"]:
        return {
            "schema": SCHEMA,
            "state_root": str(state_root),
            "status": "ALREADY_ALIASED",
            "before": before,
            "detail": "the copy path is already a symlink; nothing to merge",
        }
    if not before["copy"].get("sha256"):
        raise SystemExit(f"REFUSE: copy missing: {copy_p}")
    store, copy = _load(store_p), _load(copy_p)
    p = plan_merge(store, copy)
    merged_bytes = json.dumps(p["merged"], indent=2, default=str).encode()
    newest_store = max((d for d in (_record_as_of(r) for r in store.values()) if d), default=None)
    newest_copy = max((d for d in (_record_as_of(r) for r in copy.values()) if d), default=None)
    plan = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "state_root": str(state_root),
        "status": "DRY_RUN",
        "rule": "per-symbol newest cached_at wins; ties keep the store; nothing dropped (operator §D.3)",
        "before": before,
        "entries": {
            "store": len(store),
            "copy": len(copy),
            "overlap": len(set(store) & set(copy)),
            "store_only": len(set(store) - set(copy)),
            "copy_only": len(set(copy) - set(store)),
        },
        "newest_cached_at": {
            "store": newest_store.isoformat() if newest_store else None,
            "copy": newest_copy.isoformat() if newest_copy else None,
        },
        "counts": p["counts"],
        "samples": {k: v[:SAMPLE] for k, v in p["decisions"].items()},
        "after": {
            "entries": len(p["merged"]),
            "sha256_if_written_by_save_cache_format": hashlib.sha256(merged_bytes).hexdigest(),
        },
        "apply_would": [
            f"archive {copy_p} -> {_archive_root()}/<UTC stamp>/ticker_enrichment_cache.json (+ MANIFEST.json), verify sha256",
            f"finviz_enrichment.save_cache({p['counts']['ADD'] + p['counts']['REPLACE'] + p['counts']['ADD_UNDATED']} records) "
            f"under the writer's lock into {store_p}",
            f"replace {copy_p} with symlink -> {ALIAS_TARGET}",
        ],
        "decisions": p["decisions"],
    }
    return plan


def apply_merge(state_root: Path, grant_ref: str, expect_copy_sha: str) -> dict[str, Any]:
    """The live run. Refuses on any drift from the dry run the grant was given on."""
    store_p, copy_p = state_root / STORE_REL, state_root / COPY_REL
    plan = build_plan(state_root)
    if plan["status"] != "DRY_RUN":
        raise SystemExit(f"REFUSE: {plan['status']}: {plan.get('detail')}")
    if plan["before"]["copy"]["sha256"] != expect_copy_sha:
        raise SystemExit(
            f"REFUSE: copy drifted since the dry run: sha256 {plan['before']['copy']['sha256']} "
            f"!= expected {expect_copy_sha}"
        )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    arch_dir = _archive_root() / stamp
    arch_dir.mkdir(parents=True, exist_ok=False)
    arch_file = arch_dir / "ticker_enrichment_cache.json"
    shutil.copy2(copy_p, arch_file)
    arch_facts = file_facts(arch_file)
    if arch_facts.get("sha256") != expect_copy_sha:
        raise SystemExit(
            f"REFUSE: archived copy hash {arch_facts.get('sha256')} != {expect_copy_sha}; "
            f"live files untouched, archive left at {arch_dir}"
        )
    (arch_dir / "MANIFEST.json").write_text(
        json.dumps(
            {
                "schema": "ArchiveManifest@v1",
                "items": [
                    {
                        "path": str(arch_file),
                        "origin": str(copy_p),
                        "verdict": "SUPERSEDED",
                        "evidence": "operator decision 2026-10-10 CONSOLIDATION_PLAN §D.3: store of record is data/state",
                        "date": stamp[:8],
                        "sha256": expect_copy_sha,
                        "size": arch_facts.get("size"),
                        "origin_mtime": plan["before"]["copy"].get("mtime"),
                        "grant_ref": grant_ref,
                        "restore_command": f"cp -p {arch_file} {copy_p}  # after removing the alias symlink",
                    }
                ],
            },
            indent=2,
        )
        + "\n"
    )
    # Merge through the single writer (lock + re-read + merge + atomic replace).
    import finviz_enrichment

    winners = plan_merge(_load(store_p), _load(arch_file))["winners"]
    finviz_enrichment.save_cache(dict(winners), root=state_root)
    # Alias: the old path now reads the store of record.
    tmp_link = copy_p.with_name(copy_p.name + ".alias.tmp")
    if tmp_link.is_symlink() or tmp_link.exists():
        raise SystemExit(f"REFUSE: stray {tmp_link}")
    os.symlink(ALIAS_TARGET, tmp_link)
    os.replace(tmp_link, copy_p)
    after_store = _load(store_p)
    missing = sorted(s for s in winners if s not in after_store)
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "applied_at": datetime.now(timezone.utc).isoformat(),
        "grant_ref": grant_ref,
        "state_root": str(state_root),
        "archive": str(arch_file),
        "archive_sha256": arch_facts["sha256"],
        "counts": plan["counts"],
        "store_entries_before": plan["entries"]["store"],
        "store_entries_after": len(after_store),
        "winners_missing_after": missing,
        "store_after": file_facts(store_p),
        "copy_after": file_facts(copy_p),
    }
    (arch_dir / "RECEIPT.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", help="state root (default: production_state_root())")
    ap.add_argument("--report", help="write the dry-run plan as JSON here (outside both stores)")
    ap.add_argument("--apply", action="store_true", help="LIVE: archive, merge, alias (needs a release-write grant)")
    ap.add_argument("--grant-ref", help="the operator grant reference recorded in the archive manifest and receipt")
    ap.add_argument("--expect-copy-sha256", help="the copy's sha256 from the dry run the grant was given on")
    args = ap.parse_args(argv)
    state_root = _state_root(args.root)
    if args.apply:
        if not args.grant_ref or not args.expect_copy_sha256:
            print("REFUSE: --apply needs --grant-ref and --expect-copy-sha256 (from the dry run)", file=sys.stderr)
            return 2
        print(json.dumps(apply_merge(state_root, args.grant_ref, args.expect_copy_sha256), indent=2))
        return 0
    plan = build_plan(state_root)
    if args.report:
        rp = Path(args.report).resolve()
        if str(rp).startswith(str((state_root / "data").resolve())):
            print(f"REFUSE: --report must be outside the state tree ({rp})", file=sys.stderr)
            return 2
        rp.write_text(json.dumps(plan, indent=2, default=str) + "\n")
    after = {"store": file_facts(state_root / STORE_REL), "copy": file_facts(state_root / COPY_REL)}
    unchanged = all(
        after[k].get("sha256") == plan["before"][k].get("sha256")
        and after[k].get("mtime") == plan["before"][k].get("mtime")
        for k in ("store", "copy")
    )
    summary = {k: v for k, v in plan.items() if k != "decisions"}
    summary["read_only_verified"] = unchanged
    summary["after_run_files"] = after
    print(json.dumps(summary, indent=2, default=str))
    return 0 if unchanged else 1


if __name__ == "__main__":
    raise SystemExit(main())
