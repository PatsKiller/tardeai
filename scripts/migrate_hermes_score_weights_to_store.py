#!/usr/bin/env python3
"""Recover the learned Hermes factor weights into the durable store (LQ-20261107-55).

The tuner used to write ``config/hermes_score_weights.yaml`` INSIDE the release directory. Every
promote replaced that tree, so each learned graft was reset to the git seed: the live scorer has
been ranking on v9 (2026-08-13) while the last surviving learned state is v20 (2026-11-01). The
graft archive under persistent-state is the only place those 42 grafts still exist.

This script copies the newest archived document into the store that cannot be overwritten —
``config_documents`` (key ``hermes_score_weights``) first, then the persistent-state mirror. It
NEVER writes the release seed.

    python3 scripts/migrate_hermes_score_weights_to_store.py            # dry run (default)
    python3 scripts/migrate_hermes_score_weights_to_store.py --apply    # write DB + mirror

Dry run is read-only: one SELECT against config_documents and file reads. The DB write needs a
writable role; under the read-only proof session it fails loudly, which is the intended behaviour
for this host's agent lanes (the operator/lead runs --apply after review).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib import hermes_score_weights as store  # noqa: E402

STAMP = re.compile(r"\.(\d{8}T\d{6}Z)\.ya?ml$")
VERSION = re.compile(r"\.v(\d+)\.")


def archive_dirs() -> list[Path]:
    dirs: list[Path] = []
    env = os.environ.get("HERMES_WEIGHT_GRAFT_ARCHIVE", "").strip()
    if env:
        dirs.append(Path(env))
    try:
        dirs.append(store.state_root() / "data" / "runtime" / "weight_grafts")
    except Exception as exc:  # noqa: BLE001  -- state_root may be unresolvable here; the code-root archive is still searched
        # Name the missing candidate instead of skipping it silently: a recovery that finds nothing
        # must say which archive it could not look in.
        print(f"[migrate] WARN persistent-state graft archive unavailable "
              f"({type(exc).__name__}: {exc}); searching the code-root archive", file=sys.stderr)
    dirs.append(PROJECT_ROOT / "data" / "runtime" / "weight_grafts")
    out: list[Path] = []
    for d in dirs:
        if d.is_dir() and all(d.resolve() != x.resolve() for x in out):
            out.append(d)
    return out


def _order(path: Path) -> tuple[str, int]:
    """Newest by the UTC stamp in the name, then the highest version (names sort by version first)."""
    stamp = STAMP.search(path.name)
    version = VERSION.search(path.name)
    return (stamp.group(1) if stamp else "", int(version.group(1)) if version else -1)


def _version(value) -> int | None:
    """A document's version as an int, or None when absent/unparseable — never 0 for 'unknown'."""
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def newest_archive() -> Path | None:
    files = [p for d in archive_dirs() for p in d.glob("hermes_score_weights.v*.y*ml")]
    return max(files, key=_order) if files else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", help="archive to recover (default: the newest graft archive)")
    ap.add_argument("--apply", action="store_true", help="write DB first, then the mirror (default: dry run)")
    ap.add_argument("--json", action="store_true", help="machine-readable summary")
    a = ap.parse_args(argv)

    src = Path(a.source) if a.source else newest_archive()
    if not src or not src.is_file():
        print("ERROR no graft archive found to recover", file=sys.stderr)
        return 2

    import yaml

    doc = store.normalise(yaml.safe_load(src.read_text(encoding="utf-8")))
    if doc is None:
        print(f"ERROR {src} is not a usable weights document", file=sys.stderr)
        return 2
    total = round(sum(doc["weights"].values()), 6)
    if not 0.98 <= total <= 1.02:
        print(f"ERROR {src} weights sum to {total}, outside 0.98-1.02 — refusing to publish it", file=sys.stderr)
        return 2

    current = store.resolve(seed=store.seed_file())
    plan = {
        "source": str(src),
        "version": doc.get("version"),
        "auto_grafted_at": doc.get("auto_grafted_at"),
        "weights_sum": total,
        "checksum": store.checksum(doc),
        "current_source": current["source"],
        "current_version": current["doc"].get("version"),
        "current_errors": current["errors"],
        "db_key": store.CONFIG_KEY,
        "mirror": str(store.mirror_file()),
        "apply": bool(a.apply),
    }

    if a.apply:
        # An absent or non-numeric version is UNKNOWN, never v0: a v0 store would let any archive
        # through as an upgrade, and a v0 archive would look like a downgrade that is not one.
        cur_v = _version(current["doc"].get("version"))
        new_v = _version(doc.get("version"))
        if cur_v is None or new_v is None:
            plan["result"] = "refused_unknown_version"
            plan["detail"] = (f"store version={current['doc'].get('version')!r}, "
                              f"archive version={doc.get('version')!r} — cannot prove this is not a downgrade")
        elif current["source"] == store.SOURCE_DB and cur_v > new_v:
            plan["result"] = "refused_downgrade"
            plan["detail"] = f"store holds v{cur_v}; archive is v{new_v}"
        else:
            plan["write"] = store.save(
                doc,
                changed_by="migrate_hermes_score_weights_to_store",
                notes=f"LQ-20261107-55 recovery: newest surviving learned graft ({src.name})",
                seed=store.seed_file(),
            )
            plan["result"] = "written"
        rc = 0 if plan["result"] == "written" else 3
    else:
        plan["result"] = "dry_run"
        rc = 0

    if a.json:
        print(json.dumps(plan, indent=2, default=str))
    else:
        print(f"source         {plan['source']}")
        print(f"  version      v{plan['version']}  auto_grafted_at {plan['auto_grafted_at']}")
        print(f"  weights      sum {total}  checksum {plan['checksum']}")
        print(f"store now      {plan['current_source']} v{plan['current_version']}")
        for err in plan["current_errors"]:
            print(f"  not usable   {err}")
        print(f"target         config_documents:{plan['db_key']} + {plan['mirror']}")
        print(f"result         {plan['result']}")
        if a.apply and plan.get("write"):
            w = plan["write"]
            print(f"  db           {w['db'] or w['db_error']}")
            print(f"  mirror       {w['mirror'] or w['mirror_error']}")
            print(f"  seed written {w['wrote_seed']}")
        elif plan.get("detail"):
            print(f"  detail       {plan['detail']}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
