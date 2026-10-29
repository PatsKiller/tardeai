#!/usr/bin/env python3
"""Render the n8n relay live-lane list from config/lane_registry.json into <release>/N8N_RELAY_LIVE_LANES.json.

Called by scripts/cio_phase2_exact_main_deploy.sh at prepare (render_relay_live_lanes, before the integrity
manifest), so every release carries the list its own registry + allowlist bytes imply, stamped with BUILD_SHA and
both files' sha256. The relay and the coordination gateway use it only while AGENTS.md 20.4.0 is ACTIVE
(scripts/lib/n8n_relay_live_lanes.py documents the eligibility rule and the pause-only override layers).

  render_n8n_relay_live_lanes.py [--root DIR] [--out FILE]      write (atomic, 0644); exit 0 ok, 2 refused
  render_n8n_relay_live_lanes.py --check [--root DIR]           compute + print, write nothing
  render_n8n_relay_live_lanes.py --diff-host-file FILE          lane ids only: legacy host list vs the render

Lane ids only on stdout. --diff-host-file reads ONLY the TRADEAI_N8N_RELAY_LIVE_LANES= line of the given file (a
lane-id list, no secret); every other line is skipped unread.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import n8n_relay_live_lanes as RLL  # noqa: E402

SCHEDULED_ENTRYPOINT = "deploy: cio_phase2_exact_main_deploy.sh prepare (render_relay_live_lanes)"


def _host_list(path: Path) -> dict[str, str]:
    """{LIVE_LANES_ENV: value} from the one line that names it; no other line is kept."""
    out: dict[str, str] = {}
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            s = line.strip()
            if s.startswith(RLL.LIVE_LANES_ENV + "="):
                out[RLL.LIVE_LANES_ENV] = s.split("=", 1)[1].strip().strip("'\"").replace(",", " ")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--check", action="store_true", help="compute and print; write nothing")
    ap.add_argument("--diff-host-file", type=Path, default=None)
    a = ap.parse_args(argv)
    root = a.root.resolve()
    if a.diff_host_file:
        try:
            env = _host_list(a.diff_host_file)
        except OSError as exc:
            print(json.dumps({"ok": False, "reason": "host_file_unreadable", "error": type(exc).__name__}))
            return 2
        rep = RLL.host_diff(env, root)
        print(json.dumps(rep, sort_keys=True))
        return 0 if rep.get("ok") else 2
    if a.check:
        try:
            reg = json.loads((root / RLL.REGISTRY_REL).read_text(encoding="utf-8"))
            al = json.loads((root / RLL.ALLOWLIST_REL).read_text(encoding="utf-8"))
            lanes, excluded = RLL.registry_live_lanes(reg, al)
        except (OSError, ValueError) as exc:
            print(json.dumps({"ok": False, "reason": "registry_unreadable", "error": type(exc).__name__}))
            return 2
        pol = RLL.policy_active(root)
        print(json.dumps({"ok": True, "lanes": lanes, "excluded": excluded, "policy_state": pol.get("state"),
                          "policy_detail": pol.get("detail")}, sort_keys=True))
        return 0
    rep = RLL.render(root, a.out)
    rep["policy_state"] = RLL.policy_active(root).get("state")
    print(json.dumps(rep, separators=(",", ":"), sort_keys=True), flush=True)
    return 0 if rep.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
