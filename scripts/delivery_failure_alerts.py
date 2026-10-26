#!/usr/bin/env python3
"""delivery_failure_alerts.py — page the operator (Telegram + email + SMS) on any delivery failure (AGENTS.md §29).

    python3 scripts/delivery_failure_alerts.py                 # dry run (default): render + channel list, send nothing
    python3 scripts/delivery_failure_alerts.py --live          # send due P1 alerts, update dedupe state
    python3 scripts/delivery_failure_alerts.py --channels      # which channels are configured (key names only)

Temp-root proof (never the live state):
    python3 scripts/delivery_failure_alerts.py --state-root $T/state --release-state-dir $T/rw \
        --deploy-state-dir $T/deploy --no-github --no-systemd

Triggers, message format, dedupe and rate limits: scripts/lib/delivery_failure_alerts.py. Exit 0 = ran (incidents are
output, not failures); 1 = a live message reached no channel; 2 = usage/config error.
MBI_BEHAVIOR = 0. Authority: OPERATOR_NOTIFY_SYSTEM_OPS. Never reads a credential value.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.lib import delivery_failure_alerts as DFA  # noqa: E402


def _ci_reader():
    import main_ci_watch as MCW
    import pr_hygiene_audit as PHA

    slug = PHA.resolve_slug(None, PHA.Git(PHA.resolve_repo(None)))
    if not slug:
        raise RuntimeError("no GitHub slug")
    return MCW.watch(PHA.Gh(slug))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], allow_abbrev=False)
    ap.add_argument("--live", action="store_true", help="send (default: dry run)")
    ap.add_argument("--channels", action="store_true", help="print channel readiness and exit")
    ap.add_argument("--config", type=Path, default=DFA.CONFIG_PATH)
    ap.add_argument("--state-root", type=Path)
    ap.add_argument("--release-state-dir", type=Path)
    ap.add_argument("--deploy-state-dir", type=Path)
    ap.add_argument("--only", action="append", choices=DFA.TRIGGERS, help="limit to these triggers (repeatable)")
    ap.add_argument("--no-github", action="store_true", help="main CI: read the receipt only, never call GitHub")
    ap.add_argument("--no-systemd", action="store_true", help="request slots: skip systemd (temp-root proofs)")
    ap.add_argument("--now", help="ISO time (proofs and tests)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    try:
        cfg = DFA.load_config(a.config)
    except (OSError, ValueError) as exc:
        print(f"[delivery-failure-alerts] config: {exc}", file=sys.stderr)
        return 2
    if a.channels:
        for ch, r in DFA.channel_readiness(cfg).items():
            print(f"{ch:9s} {r['status']:15s} {r['why']}")
        return 0
    state_root = a.state_root or Path(
        os.environ.get("TRADEAI_STATE_ROOT") or Path.home() / "trade-ai-releases" / "persistent-state"
    )
    rsd = a.release_state_dir or Path(
        os.environ.get("TRADEAI_RELEASE_WINDOW_STATE_DIR") or state_root / "data" / "runtime" / "release_window"
    )
    dsd = a.deploy_state_dir or Path.home() / ".local" / "state" / "cio-phase2-exact-main"
    now = DFA.parse_ts(a.now) if a.now else datetime.now(timezone.utc)
    ctx = DFA.Context(
        state_root=state_root,
        release_state_dir=rsd,
        deploy_state_dir=dsd,
        now=now,
        config=cfg,
        ci_reader=None if a.no_github else _ci_reader,
        systemd_timers=(lambda: []) if a.no_systemd else None,
    )
    receipt = DFA.run(ctx, live=a.live, only=a.only)
    if a.json:
        print(json.dumps(receipt, indent=2, default=str))
    else:
        print(
            f"[delivery-failure-alerts] {receipt['mode']} {receipt['as_of']}: {len(receipt['incidents'])} incident(s), "
            f"{len(receipt['due'])} due, {len(receipt['held_rate_limited'])} held by the hourly cap"
        )
        for m in receipt["messages"]:
            print("---")
            print(m["rendered"]["text"])
            print(
                "  channels: "
                + ", ".join(
                    f"{c}={v['status']}"
                    + (f" ({v.get('why') or v.get('error')})" if v.get("why") or v.get("error") else "")
                    for c, v in m["channels"].items()
                )
            )
        for n in receipt["notes"]:
            print(f"  note: {n}")
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
