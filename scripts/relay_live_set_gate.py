#!/usr/bin/env python3
"""Diff, hold and acknowledge changes to the n8n relay's effective live-lane set across a promote.

  relay_live_set_gate.py diff --release NEW [--served DIR] [--host-file F] [--write] [--notify]
      prepare: print the difference, WARN when it is non-empty; --write saves <NEW>/N8N_RELAY_LIVE_SET_DIFF.json;
      --notify pages the operator once (communications gateway). Always exit 0 (prepare is never failed by this).
  relay_live_set_gate.py gate --release NEW [--served DIR] [--host-file F]
      promote: exit 0 when the set is unchanged or the exact change is acknowledged; exit 3 otherwise.
  relay_live_set_gate.py ack --release NEW --by NAME [--served DIR] [--host-file F]
      OPERATOR ONLY: record that the change computed now (bound to NEW's build sha) is acknowledged.

--served defaults to the resolved ~/trade-ai-releases/portfolio-server/CURRENT. --host-file defaults to
~/.config/tradeai/n8n-live-lanes.env, of which only the two lane-id keys are read. Acks go to
$TRADEAI_STATE_ROOT/data/governance/relay_live_set_acks.jsonl. Lane ids only on stdout.
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


def _ack_cmd(release: Path) -> str:
    return f"python3 {release}/scripts/relay_live_set_gate.py ack --release {release} --by <you>"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["diff", "gate", "ack"])
    ap.add_argument("--release", type=Path, required=True)
    ap.add_argument("--served", type=Path, default=DEFAULT_SERVED)
    ap.add_argument("--host-file", type=Path,
                    default=Path(os.environ.get("TRADEAI_N8N_LIVE_LANES_FILE") or G.DEFAULT_HOST_FILE))
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--notify", action="store_true")
    ap.add_argument("--by", default="")
    a = ap.parse_args(argv)
    release, served = a.release.resolve(), a.served.resolve()
    env = _env(a.host_file)
    report = G.compute(release, served, env)
    state = RLL.state_root(env)
    if a.cmd == "ack":
        if not report["changed"]:
            print(json.dumps({"ok": True, "acked": False, "reason": "unchanged"}))
            return 0
        row = G.record_ack(state, report, a.by)
        print(json.dumps({"ok": True, "acked": True, "diff_id": row["diff_id"], "added": row["added"],
                          "removed": row["removed"]}, sort_keys=True))
        return 0
    if a.cmd == "gate":
        ok, why = G.gate(report, state)
        out = {"ok": ok, "reason": why, "diff_id": report["diff_id"], "added": report["added"],
               "removed": report["removed"], "new_source": report["new"]["source"],
               "served_source": report["served"]["source"]}
        print(json.dumps(out, sort_keys=True))
        if not ok:
            print(f"REFUSED: relay live set changes by +{len(report['added'])}/-{len(report['removed'])} lanes and "
                  f"the operator has not acknowledged it. To acknowledge: {_ack_cmd(release)}", file=sys.stderr)
            return 3
        return 0
    # diff
    if report["changed"]:
        print(f"WARN relay live set would change: +{len(report['added'])} {report['added']} "
              f"-{len(report['removed'])} {report['removed']} (diff_id {report['diff_id']})", file=sys.stderr)
        if a.notify and os.environ.get("TRADE_AI_CI") != "1":
            report["page"] = G.notify(report, _ack_cmd(release))
    if a.write:
        out = release / G.DIFF_NAME
        tmp = out.with_name(f".{out.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, out)
    print(json.dumps({k: report[k] for k in ("changed", "diff_id", "added", "removed", "new", "served")}
                     | {"exclusions": len(report["exclusions"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
