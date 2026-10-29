#!/usr/bin/env python3
"""Incident supervisor — governed triage + allowlisted actions for open incidents (host timer every 10 min).

  incident_supervisor.py [--apply] [--json]

Dry run (default) calls no model, runs nothing and sends nothing: it prints what it would consider and escalate.
--apply: one governed call per eligible incident (process incident_supervisor: Anthropic credit Sonnet 5.5, <= $1/day;
OAuth grok/chatgpt answers are read-only triage; never DeepSeek), then ONLY config/incident_runbook_actions.json
actions, the section 28.14 fixer dispatch (PR only), or one P1 per incident through scripts/telegram_alert.py.
Never merges, pushes, promotes, deletes, orders, stops, sizes, writes a broker or reads a secret.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "lib"))
from scripts.lib import incident_supervisor as S  # noqa: E402
from scripts.lib import incidents as L  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--config", default=str(S.CONFIG))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    cfg = json.loads(Path(a.config).read_text(encoding="utf-8"))
    env_root = os.environ.get("TRADEAI_STATE_ROOT")
    if env_root:
        state_root = Path(env_root)
    else:
        from scripts.lib.persistent_state_root import good_persistent_root
        state_root = Path(good_persistent_root())
    d = L.incidents_dir() if os.environ.get("TRADEAI_INCIDENTS_DIR") else L.incidents_dir(state_root)
    release_root = Path(os.environ.get("PROJ") or ROOT)
    deps = S.Deps(model=S.default_model, run=S.default_run, notify=S.default_notify,
                  fixer=S.default_fixer_factory(cfg, cfg.get("python", sys.executable), Path(cfg.get("canonical_repo") or ROOT)))
    out = S.cycle(d=d, state_root=state_root, release_root=release_root, cfg=cfg, deps=deps,
                  apply=bool(a.apply and not a.dry_run))
    print(json.dumps(out, indent=1, default=str) if a.json else
          f"considered={len(out['considered'])} actions={len(out['actions'])} dispatched={len(out['dispatched'])} "
          f"blocked={len(out['blocked'])} escalated={len(out['escalated'])} would_escalate={len(out['would_escalate'])} "
          f"skipped={len(out['skipped'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
