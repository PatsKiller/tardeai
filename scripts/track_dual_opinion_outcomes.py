#!/usr/bin/env python3
"""Track outcomes of operator advisory choices — TradeAI vs Hermes."""
import json, os, sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

def track_outcomes():
    """Compare operator choices against available outcomes."""
    choices_dir = PROJECT_ROOT / "data" / "advisory" / "operator_choices"
    choices = []
    if choices_dir.exists():
        for f in sorted(choices_dir.glob("*.jsonl")):
            for line in f.read_text().splitlines():
                if line.strip():
                    try: choices.append(json.loads(line))
                    except: pass

    results = {
        "timestamp": datetime.now().isoformat(),
        "total_choices": len(choices),
        "tradeai_preferred": sum(1 for c in choices if c.get("operator_choice") == "KEEP_TRADEAI_ORIGINAL"),
        "hermes_preferred": sum(1 for c in choices if c.get("operator_choice") == "USE_HERMES_ENHANCEMENT"),
        "keep_both": sum(1 for c in choices if c.get("operator_choice") == "KEEP_BOTH"),
        "rejected": sum(1 for c in choices if c.get("operator_choice") == "REJECT_BOTH"),
        "escalated": sum(1 for c in choices if c.get("operator_choice") == "ESCALATE_HIGH_LLM"),
        "outcomes_available": 0,  # Will grow as trades close / catalysts validate
        "outcomes_pending": len(choices),
        "insufficient_data": True,
        "winner": "INSUFFICIENT_DATA",
        "choices": choices,
    }

    out_dir = PROJECT_ROOT / "data" / "advisory" / "outcomes"
    out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    (out_dir / f"{today}_dual_opinion_outcomes.json").write_text(json.dumps(results, indent=2, default=str))
    return results

if __name__ == "__main__":
    r = track_outcomes()
    print(f"Opinion Outcome Tracker")
    print(f"  Choices: {r['total_choices']}")
    print(f"  TradeAI preferred: {r['tradeai_preferred']}")
    print(f"  Hermes preferred: {r['hermes_preferred']}")
    print(f"  Keep both: {r['keep_both']}")
    print(f"  Outcomes available: {r['outcomes_available']}")
    print(f"  Pending: {r['outcomes_pending']}")
    print(f"  Winner: {r['winner']}")
