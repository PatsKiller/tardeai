#!/usr/bin/env python3
"""Diff and hold changes to the n8n relay's effective live-lane set across a promote or a rollback.

  relay_live_set_gate.py diff --release NEW [--served DIR] [--host-file F] [--write] [--notify]
      prepare: print the difference, WARN when it is non-empty; --write saves <NEW>/N8N_RELAY_LIVE_SET_DIFF.json;
      --notify pages the operator at most once per diff_id (durable marker in host state). Always exit 0.
  relay_live_set_gate.py gate --release NEW [--served DIR] [--host-file F]
      promote: exit 0 when the set is unchanged or the operator has acknowledged this exact diff_id; exit 3 and a
      RELAY_LIVE_SET_HELD diff_id=<id> line on stderr otherwise.
  relay_live_set_gate.py status --release NEW [--served DIR] [--host-file F]
      read-only: the diff_id, the delta and whether it is acknowledged (and by which grant id).
  relay_live_set_gate.py latch-pin --release NEW
      promote, after the gate passed: create the host-state pin (one-way; never overwritten, never removed).
  relay_live_set_gate.py rollback-diff --release TARGET [--served DIR] [--host-file F] [--notify]
      rollback: the same diff computed with each release's own resolver; WARN and page once. Never blocks (exit 0).

The acknowledgement is an operator guard grant (scripts/lib/relay_live_set_gate.py module docstring). This tool has
no command that acknowledges anything, and it prints no command to run.
--served defaults to the resolved ~/trade-ai-releases/portfolio-server/CURRENT. --host-file defaults to
~/.config/tradeai/n8n-live-lanes.env, of which only the two lane-id keys are read. Lane ids only on stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from scripts.lib import n8n_relay_live_lanes as RLL  # noqa: E402
from scripts.lib import relay_live_set_gate as G  # noqa: E402

DEFAULT_SERVED = Path.home() / "trade-ai-releases" / "portfolio-server" / "CURRENT"


def _env(host_file: Path | None) -> dict[str, str]:
    env = G.host_env(host_file)
    if os.environ.get("TRADEAI_STATE_ROOT"):
        env["TRADEAI_STATE_ROOT"] = os.environ["TRADEAI_STATE_ROOT"]
    return env


def _write(release: Path, report: dict) -> None:
    out = release / G.DIFF_NAME
    tmp = out.with_name(f".{out.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, out)


def _summary(report: dict) -> dict:
    return {k: report[k] for k in ("changed", "diff_id", "added", "removed", "new", "served")} | {
        "exclusions": len(report["exclusions"])}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["diff", "gate", "status", "latch-pin", "rollback-diff"])
    ap.add_argument("--release", type=Path, required=True)
    ap.add_argument("--served", type=Path, default=DEFAULT_SERVED)
    ap.add_argument("--host-file", type=Path,
                    default=Path(os.environ.get("TRADEAI_N8N_LIVE_LANES_FILE") or G.DEFAULT_HOST_FILE))
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--notify", action="store_true")
    a = ap.parse_args(argv)
    release = a.release.resolve()
    env = _env(a.host_file)
    state = RLL.state_root(env)
    if a.cmd == "latch-pin":
        if not (release / RLL.SOURCE_REL).exists():
            print(json.dumps({"latched": False, "detail": "release_has_no_pin_config"}))
            return 0
        build = G._build(release)
        print(json.dumps(RLL.latch_host_pin(state, build=build), sort_keys=True))
        return 0
    report = G.compute(release, a.served.resolve(), env)
    if a.cmd == "status":
        ack = G.acknowledgement(report) if report["changed"] else None
        print(json.dumps(_summary(report) | {"acknowledged_by_grant": (ack or {}).get("grant_id")}, sort_keys=True))
        return 0
    if a.cmd == "gate":
        ok, why = G.gate(report)
        print(json.dumps({"ok": ok, "reason": why, "diff_id": report["diff_id"], "added": report["added"],
                          "removed": report["removed"], "new_source": report["new"]["source"],
                          "served_source": report["served"]["source"]}, sort_keys=True))
        if not ok:
            print(f"{G.HELD_MARKER} diff_id={report['diff_id']}: the relay live set would change by "
                  f"+{len(report['added'])}/-{len(report['removed'])} lanes and the operator has not acknowledged "
                  f"this diff_id", file=sys.stderr)
            return 3
        return 0
    event = "rollback" if a.cmd == "rollback-diff" else "promote"
    if report["changed"]:
        print(f"WARN relay live set would change at {event}: +{len(report['added'])} {report['added']} "
              f"-{len(report['removed'])} {report['removed']} (diff_id {report['diff_id']})", file=sys.stderr)
        if a.notify and os.environ.get("TRADE_AI_CI") != "1":
            report["page"] = G.notify(report, state, event=event)
    if a.write:
        _write(release, report)
    print(json.dumps(_summary(report) | ({"page": report["page"]} if "page" in report else {}), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
