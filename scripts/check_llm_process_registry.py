#!/usr/bin/env python3
"""One route per process: `deepseek_only` and `anthropic_first` may not coexist.

LQ-20261107-1808. `hermes_external_research` declared `lane_policy: "deepseek_only"` and also
`anthropic_first: true`. The promotional router (`anthropic_routing.eligible`) reads the flag, so the
"deepseek" research lane's calls actually executed on Anthropic (`claude-haiku-5-5`) and 219 of the
last 24 h failed `ANTHROPIC_INPUT_LIMIT_EXCEEDED`. Two honest queries then disagreed: the alert
measured the raw lane and was right; a `model_lane`-grouped audit measured deepseek-flash and saw
almost nothing. A declaration that names two routes is the defect (Constitution Rule 7), not the
alert.

This checker names every process carrying both. It does not fix them: removing `anthropic_first`
from a row changes that process's production route, and the 2026-10-25 Anthropic-first promotion
(`docs/ops/ANTHROPIC_FIRST_20261025.md`) was operator-approved, so decommissioning it for other
processes is an operator decision.

    python3 scripts/check_llm_process_registry.py                  # human report
    python3 scripts/check_llm_process_registry.py --json           # machine report
    python3 scripts/check_llm_process_registry.py --fail-on-violation   # CI: exit 1 on any

READ-ONLY: the committed registry only. No DB, no network, no mutations.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = ROOT / "config" / "llm_process_registry.json"

#: The declaration that contradicts `lane_policy: "deepseek_only"`.
CONTRADICTING_FLAG = "anthropic_first"


def load_registry(path: str | Path | None = None) -> dict[str, Any]:
    """The registry document. An unreadable file raises — a checker that cannot read is not a pass."""
    p = Path(path or DEFAULT_REGISTRY)
    return json.loads(p.read_text(encoding="utf-8"))


def _rows(doc: Any) -> Iterable[dict[str, Any]]:
    rows = doc.get("processes") if isinstance(doc, dict) else doc
    for row in rows or []:
        if isinstance(row, dict):
            yield row


def route_contradictions(doc: Any) -> list[dict[str, Any]]:
    """Every process that declares both `lane_policy: deepseek_only` and `anthropic_first: true`.

    Returned in registry order, one `{"id", "lane_policy"}` row each. An empty list is a real
    measurement: it means the document was read and held no such pair.
    """
    out: list[dict[str, Any]] = []
    for row in _rows(doc):
        if str(row.get("lane_policy") or "").strip() != "deepseek_only":
            continue
        if row.get(CONTRADICTING_FLAG) is not True:
            continue
        out.append({"id": str(row.get("id") or "(no id)"), "lane_policy": "deepseek_only"})
    return out


def report(doc: Any) -> dict[str, Any]:
    rows = list(_rows(doc))
    violations = route_contradictions(doc)
    return {
        "schema": "LlmProcessRegistryRoutes@v1",
        "processes": len(rows),
        "violations": violations,
        "ok": not violations,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Every registry process must name one route.")
    ap.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    ap.add_argument("--json", action="store_true", help="machine report instead of human text")
    ap.add_argument("--fail-on-violation", action="store_true",
                    help="exit 1 when any process declares both deepseek_only and anthropic_first")
    args = ap.parse_args(argv)
    try:
        doc = load_registry(args.registry)
    except (OSError, ValueError) as exc:
        print(f"registry unreadable: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    rec = report(doc)
    if args.json:
        print(json.dumps(rec, indent=2))
    elif rec["ok"]:
        print(f"ok: {rec['processes']} processes, no deepseek_only process carries {CONTRADICTING_FLAG}")
    else:
        print(f"{len(rec['violations'])} process(es) declare deepseek_only AND {CONTRADICTING_FLAG}:")
        for v in rec["violations"]:
            print(f"  • {v['id']}")
        print("One route per process. Removing the flag changes that process's route: operator decision.")
    return 1 if (args.fail_on_violation and not rec["ok"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
