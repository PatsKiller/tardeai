#!/usr/bin/env python3
"""n8n_platform_maturity.py — n8n platform maturity scorer (N8nPlatformMaturity@v1).

Scores the 12 dimensions of the N8N Maturity Acceleration program (plan 2026-10-09, master doc
docs/implementation/n8n-maturity/00-MASTER-PROGRAM.md) 0–10, equal weight, overall = mean.
Every score is derived ONLY from evidence the scorer reads — receipts, config/lane_registry.json,
the coordination ledger runs table, ``crontab -l``, ``systemctl --user`` (read), the guard log,
the n8n DB (SELECT via docker exec), the GitHub API via gh (read-only) and logs. Nothing is
self-reported; missing evidence scores 0 and is marked UNVERIFIED, never assumed.

The scorer is READ-ONLY on the host: the probe (scripts/lib/n8n_maturity/core.py) refuses any
non-read-only command; the only write is its own receipt under --write.

    n8n_platform_maturity.py               # dry run (default): print the scorecard JSON summary
    n8n_platform_maturity.py --markdown    # render the master-doc scorecard section
    n8n_platform_maturity.py --write       # append history + replace the latest receipt

Thresholds live in config/n8n_platform_maturity.json; the self-healing inventory in
config/self_healing_mechanisms.json. Modelled on scripts/maturity_remeasure.py (receipt window,
typed evidence).
"""
NO_CONSUMER_REASON = (
    "N8nPlatformMaturity@v1 is read by the n8n maturity master doc checkpoints (T0/T18/T30/T42) and the "
    "operator; lane n8n-platform-maturity is run by hand at checkpoints and is not scheduled"
)

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Optional

PROJ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJ / "scripts" / "lib"))

from n8n_maturity import core  # noqa: E402
from n8n_maturity import dims_governance, dims_healing, dims_scheduling, dims_signal  # noqa: E402

SCHEMA = "N8nPlatformMaturity@v1"
LANE = "n8n-platform-maturity"
CONFIG = PROJ / "config" / "n8n_platform_maturity.json"
ORDER = ("registry_truth", "rationalization", "scheduler_coverage", "observability", "alert_delivery",
         "self_healing", "governance", "security", "recovery", "reliability", "ci_signal", "docs_synced")


def collectors() -> dict[str, Callable[[core.Probe], dict]]:
    out: dict[str, Callable[[core.Probe], dict]] = {}
    for mod in (dims_scheduling, dims_signal, dims_healing, dims_governance):
        out.update(getattr(mod, "COLLECTORS", {}))
    return out


def state_root(env: dict) -> Path:
    if env.get("TRADEAI_STATE_ROOT"):
        return Path(env["TRADEAI_STATE_ROOT"])
    try:
        from canonical_store_registry import production_state_root  # type: ignore
        return Path(production_state_root())
    except Exception:  # noqa: BLE001
        return Path.home() / "trade-ai-releases" / "persistent-state"


def load_config(path: Path = CONFIG) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def score_all(probe: core.Probe, table: Optional[dict[str, Callable[[core.Probe], dict]]] = None) -> dict:
    """Run every collector (an exception scores that dimension 0 / UNVERIFIED) and assemble the receipt."""
    table = collectors() if table is None else table
    cfg_dims = (probe.config.get("dimensions") or {})
    rows: list[dict] = []
    for dim_id in ORDER:
        meta = cfg_dims.get(dim_id) or {}
        rule = meta.get("gate_rule") or "gate not configured"
        fn = table.get(dim_id)
        if fn is None:
            r = core.unverified(dim_id, rule, "no collector registered")
        else:
            try:
                r = fn(probe)
            except Exception as exc:  # noqa: BLE001
                r = core.unverified(dim_id, rule, f"collector raised {type(exc).__name__}: {str(exc)[:200]}")
        r["n"] = meta.get("n", ORDER.index(dim_id) + 1)
        r["title"] = meta.get("title", dim_id)
        r["baseline_estimate"] = meta.get("baseline")
        rows.append(r)
    overall = round(sum(r["score"] for r in rows) / len(rows), 2)
    target = float(probe.config.get("target_overall", 8.0))
    return {
        "schema": SCHEMA, "as_of": probe.now.isoformat(), "scorer": LANE, "authority": "READ_ONLY_ADVISORY",
        "overall": overall, "target": target, "stretch": probe.config.get("stretch_overall"),
        "overall_gate_pass": overall >= target and all(r["gate"]["pass"] for r in rows),
        "gates_passed": sum(1 for r in rows if r["gate"]["pass"]), "dimensions_total": len(rows),
        "unverified": [r["id"] for r in rows if r["status"] == core.UNVERIFIED],
        "dimensions": rows, "commands": probe.commands,
        "note": "scored from evidence only; missing evidence scores 0 (UNVERIFIED); a session never writes this file",
    }


def render_markdown(rec: dict) -> str:
    lines = [f"## Maturity scorecard ({rec['schema']}, {rec['as_of'][:16]}Z)", "",
             f"**Overall {rec['overall']:.2f} / 10** (target {rec['target']}, stretch {rec.get('stretch')}). "
             f"Gates passed: {rec['gates_passed']}/{rec['dimensions_total']}. "
             f"Unverified: {', '.join(rec['unverified']) or 'none'}.", "",
             "| # | Dimension | Score | Status | 8.0 gate | Pass | Key metrics |",
             "|---|---|---|---|---|---|---|"]
    for r in rec["dimensions"]:
        km = "; ".join(f"{k}={_short(v)}" for k, v in list((r.get("metrics") or {}).items())[:5])
        lines.append(f"| {r['n']} | {r['title']} | {r['score']:.1f} | {r['status']} | {r['gate']['rule']} | "
                     f"{'yes' if r['gate']['pass'] else 'no'} | {km} |")
    lines += ["", "### Evidence and notes", ""]
    for r in rec["dimensions"]:
        lines.append(f"**{r['n']}. {r['title']}** — {r['score']:.1f} ({r['status']})")
        for n in r.get("notes") or []:
            lines.append(f"- {n}")
        for e in (r.get("evidence") or [])[:8]:
            detail = ", ".join(f"{k}={_short(v)}" for k, v in e.items() if k != "source")
            lines.append(f"- `{e.get('source')}`" + (f": {detail}" if detail else ""))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _short(v: Any) -> str:
    s = json.dumps(v, default=str) if not isinstance(v, str) else v
    return (s[:60] + "…") if len(s) > 61 else s


def write_receipt(rec: dict, root: Path, cfg: dict) -> tuple[Path, Path]:
    r = cfg.get("receipt") or {}
    latest = root / r.get("latest", "data/governance/n8n_platform_maturity_latest.json")
    hist = root / r.get("history", "data/governance/n8n_platform_maturity_history.jsonl")
    latest.parent.mkdir(parents=True, exist_ok=True)
    with hist.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, sort_keys=True, default=str) + "\n")
    tmp = latest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, indent=1, default=str) + "\n", encoding="utf-8")
    os.replace(tmp, latest)
    return latest, hist


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="print the scorecard (default)")
    mode.add_argument("--write", action="store_true", help="write the receipt (latest + history)")
    ap.add_argument("--markdown", action="store_true", help="print the master-doc scorecard section")
    ap.add_argument("--json", action="store_true", help="print the full receipt JSON")
    ap.add_argument("--root", help="persistent state root (default: production state root)")
    ap.add_argument("--config", help="threshold config (default config/n8n_platform_maturity.json)")
    a = ap.parse_args(argv)
    env = dict(os.environ)
    cfg = load_config(Path(a.config) if a.config else CONFIG)
    root = Path(a.root) if a.root else state_root(env)
    probe = core.Probe(root=root, proj=PROJ, now=_dt.datetime.now(_dt.timezone.utc), env=env, config=cfg)
    rec = score_all(probe)
    if a.markdown:
        print(render_markdown(rec), end="")
    elif a.json:
        print(json.dumps(rec, indent=1, default=str))
    else:
        print(json.dumps({"overall": rec["overall"], "gates_passed": rec["gates_passed"],
                          "dimensions": {r["id"]: [r["score"], r["status"], "PASS" if r["gate"]["pass"] else "FAIL"]
                                         for r in rec["dimensions"]}}, indent=1))
    if a.write:
        latest, hist = write_receipt(rec, root, cfg)
        print(f"wrote {latest} (+ {hist.name})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
