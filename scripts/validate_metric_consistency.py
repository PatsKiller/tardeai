#!/usr/bin/env python3
"""
Metric consistency validator for Command Center v3.

Read-only. Validates that visible headline KPI names are backed by the
canonical config/metric_registry.yaml and flags ambiguous labels such as a bare
"WIN RATE" without denominator/scope.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

REGISTRY = Path("config/metric_registry.yaml")
DEFAULT_SCAN_PATHS = [
    Path("apps/command-center-v3/src"),
    Path("scripts"),
    Path("docs/project"),
]
# Ambiguous visible KPI labels are a Command Center concern — scan v3 UI only.
AMBIGUOUS_SCAN_PATHS = [Path("apps/command-center-v3/src")]

REQUIRED_METRICS = {
    "portfolio_value",
    "today_pnl",
    "journal_pnl",
    "journal_win_rate",
    "paper_validation_win_rate",
    "setup_counts",
    "market_regime",
    "vix",
    "last_pipeline_run",
    "live_blocked_state",
    "broker_protective_stop_state",
    "rotation_candidates",
}

AMBIGUOUS_LABELS = [
    re.compile(r"\bWIN RATE\b", re.I),
    re.compile(r"\bLIVE BLOCKED\b", re.I),
]

ALLOWED_CONTEXT_HINTS = (
    "journal",
    "paper validation",
    "paper trade",
    "paper win",
    "paper-readiness",
    "validation",
    "denominator",
    "scope",
    "live trading status",
    "protective stop",
    "broker protective",
    "backtest",
    "replay",
    "strategy",
    "by strategy",
    "source:",
    "win_rate",
    "datakey",
    "round-trip",
    "kpis",
    "tip:",
    "performance",
    "2fa live",
    "auto live",
    "api/v2",
)


def load_registry_text() -> str:
    if not REGISTRY.exists():
        raise SystemExit(f"missing {REGISTRY}")
    return REGISTRY.read_text()


def metric_ids_from_registry(text: str) -> set[str]:
    found = set()
    for line in text.splitlines():
        m = re.match(r"^\s{2}([a-zA-Z0-9_]+):\s*$", line)
        if m:
            found.add(m.group(1))
    return found


def iter_files(paths: list[Path]):
    for root in paths:
        if root.is_file():
            yield root
        elif root.exists():
            for p in root.rglob("*"):
                if p.is_file() and p.suffix.lower() in {".ts", ".tsx", ".py", ".md", ".yaml", ".yml", ".json"}:
                    if any(part in {"node_modules", "dist", ".venv", "__pycache__"} for part in p.parts):
                        continue
                    yield p


_SCOPED_WIN_RATE = re.compile(
    r"\b(journal|paper|paper-trade|backtest|source|validation|strategy)\s+win\s+rate\b", re.I
)


def scan_ambiguous_labels(paths: list[Path]) -> list[dict]:
    hits: list[dict] = []
    for p in iter_files(paths):
        try:
            txt = p.read_text(errors="ignore")
        except Exception:
            continue
        for i, line in enumerate(txt.splitlines(), start=1):
            for rx in AMBIGUOUS_LABELS:
                if not rx.search(line):
                    continue
                lowered = line.lower()
                if _SCOPED_WIN_RATE.search(line):
                    continue
                if not any(hint in lowered for hint in ALLOWED_CONTEXT_HINTS):
                    hits.append({"path": str(p), "line": i, "text": line.strip()[:220], "pattern": rx.pattern})
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true", help="exit nonzero on warnings")
    args = ap.parse_args()

    reg_text = load_registry_text()
    ids = metric_ids_from_registry(reg_text)
    missing = sorted(REQUIRED_METRICS - ids)
    extra = sorted(ids - REQUIRED_METRICS)
    ambiguous = scan_ambiguous_labels(AMBIGUOUS_SCAN_PATHS)

    report = {
        "ok": not missing and not ambiguous,
        "registry": str(REGISTRY),
        "metric_count": len(ids),
        "missing_required_metrics": missing,
        "extra_metrics": extra,
        "ambiguous_label_hits": ambiguous[:100],
        "ambiguous_label_count": len(ambiguous),
        "rules": [
            "Every visible KPI must map to a metric_id.",
            "Win rate labels must disclose scope and denominator.",
            "General live trading and protective-stop authorization must not share one ambiguous label.",
        ],
    }

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"Metric registry: {REGISTRY}")
        print(f"Metric count: {len(ids)}")
        print(f"Missing required: {missing or 'none'}")
        print(f"Ambiguous label hits: {len(ambiguous)}")
        for hit in ambiguous[:20]:
            print(f"WARN {hit['path']}:{hit['line']}: {hit['text']}")

    return 1 if args.strict and not report["ok"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
