#!/usr/bin/env python3
"""Poison-item quarantine: list a lane's quarantined items, or release one (dry run unless --apply).

python3 scripts/poison_quarantine.py list [--lane cio-ask-lifecycle]
python3 scripts/poison_quarantine.py release --lane cio-ask-lifecycle --item thr_x --note "fixed in #NNNN" [--apply]
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib import poison_quarantine as PQ  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--lane")
    rel = sub.add_parser("release")
    rel.add_argument("--lane", required=True)
    rel.add_argument("--item", required=True)
    rel.add_argument("--note", required=True)
    rel.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    cfg, root = PQ.load_config(), PQ.state_root()
    if a.cmd == "list":
        d = root / cfg["store_dir_rel"]
        files = [d / f"{a.lane}.json"] if a.lane else sorted(d.glob("*.json"))
        out = {f.stem: PQ.read_store(f)["quarantined"] for f in files if f.exists()}
        print(json.dumps(out, indent=1))
        return 0
    res = PQ.release(a.lane, a.item, note=a.note, apply=a.apply, cfg=cfg, root=root, by=getpass.getuser())
    print(json.dumps(res, indent=1, default=str))
    return 0 if res.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
