#!/usr/bin/env python3
"""Organic LLM volume on SecurityResearchSpine — remasure (READ_ONLY_ADVISORY).

Counts latest tips with latest_llm. Organic excludes contribution tags canary/backfill.
Writes data/runtime/spine_llm_organic.json when --write.
"""
from __future__ import annotations

NO_CONSUMER_REASON = (
    "ops CLI / dashboard metric writer; operator or agent invokes; "
    "runtime JSON under data/runtime/ is the consumer artifact"
)

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_EXCLUDE = frozenset({"canary", "backfill"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_latest_tips(spine_path: Path) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    if not spine_path.exists():
        return latest
    with spine_path.open(encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("symbol"):
                latest[str(row["symbol"]).upper()] = row
    return latest


def measure(root: Path) -> dict:
    spine_path = root / "data" / "cio" / "security_research_spine.jsonl"
    latest = load_latest_tips(spine_path)
    by_source: Counter[str] = Counter()
    with_llm = 0
    organic = 0
    canary_or_backfill = 0
    organic_symbols: list[str] = []
    for sym, row in sorted(latest.items()):
        llm = row.get("latest_llm") or {}
        if not (llm.get("source") or llm.get("model") or llm.get("as_of")):
            continue
        with_llm += 1
        src = str(llm.get("source") or "unknown")
        by_source[src] += 1
        # Organic vs canary/backfill is decided on the LATEST LLM contribution only.
        # Tip-level tags accumulate (a prior canary must not permanently poison a later
        # organic desk/gap stamp on the same symbol).
        llm_contrib_excluded = False
        saw_llm_contrib = False
        for c in reversed(list(row.get("contributions") or [])):
            if not isinstance(c, dict):
                continue
            tags = set(str(t).lower() for t in (c.get("tags") or []))
            if "llm_research" in tags or "llm_curation" in tags or "llm_flash" in tags:
                saw_llm_contrib = True
                llm_contrib_excluded = bool(tags & _EXCLUDE)
                break
        if not saw_llm_contrib:
            # Fall back to tip tags only when contributions lack LLM tags
            tip_tags = set(str(t).lower() for t in (row.get("tags") or []))
            llm_contrib_excluded = bool(tip_tags & _EXCLUDE)
        if llm_contrib_excluded:
            canary_or_backfill += 1
        else:
            organic += 1
            organic_symbols.append(sym)
    return {
        "schema": "SecurityResearchSpineLlmOrganic@v1",
        "authority": "READ_ONLY_ADVISORY",
        "as_of": _now(),
        "spine_symbols": len(latest),
        "tips_with_latest_llm": with_llm,
        "organic_latest_llm": organic,
        "canary_or_backfill_latest_llm": canary_or_backfill,
        "by_source": dict(by_source),
        "organic_symbols_sample": organic_symbols[:40],
        "exclude_tags": sorted(_EXCLUDE),
        "note": "organic excludes tips whose LLM contribution tags include canary or backfill",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    out = measure(args.root)
    if args.write:
        dest = args.root / "data" / "runtime" / "spine_llm_organic.json"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(out, indent=2, default=str) + "\n", encoding="utf-8")
        out["written_to"] = str(dest)
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        print(
            f"spine_llm organic={out['organic_latest_llm']} "
            f"canary_backfill={out['canary_or_backfill_latest_llm']} "
            f"with_llm={out['tips_with_latest_llm']} tips={out['spine_symbols']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
