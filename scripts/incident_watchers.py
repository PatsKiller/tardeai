#!/usr/bin/env python3
"""Run the deterministic incident watchers once (host timer every 5 min; no model; dry run by default).

  incident_watchers.py [--apply] [--only deploy_failures,main_ci] [--json]

Reads existing producers' outputs under the state root ($TRADEAI_STATE_ROOT, else persistent-state), opens/auto-
resolves IncidentRecord@v1 rows (scripts/lib/incidents.py) and writes watchers_last.json beside the ledger.
Never sends, never writes another producer's store. Config: config/incident_watchers.json.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.lib import incident_watchers as W  # noqa: E402
from scripts.lib import incidents as L  # noqa: E402


def state_root() -> Path:
    env = os.environ.get("TRADEAI_STATE_ROOT")
    if env:
        return Path(env)
    from scripts.lib.persistent_state_root import good_persistent_root
    return Path(good_persistent_root())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default="")
    ap.add_argument("--config", default=str(W.CONFIG))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    if not cfg.get("enabled", False):
        print(json.dumps({"enabled": False}))
        return 0
    root = state_root()
    d = L.incidents_dir(root) if not os.environ.get("TRADEAI_INCIDENTS_DIR") else L.incidents_dir()
    out = W.run(state_root=root, incidents_dir=d, cfg=cfg, apply=bool(a.apply and not a.dry_run),
                only=[x for x in a.only.split(",") if x] or None)
    if a.json:
        print(json.dumps(out, indent=1, default=str))
    else:
        for wid, w in out["watchers"].items():
            print(f"{wid:18} findings={w.get('findings', '-')} gap={w.get('gap')}")
        for k in ("opened", "resolved", "would_open", "would_resolve"):
            for r in out[k]:
                print(f"{k}: {r.get('id', '')} {r['title']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
