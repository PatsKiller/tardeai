"""
ticker_memory.py — Persistent ticker intelligence store.
14-day rolling window. PostgreSQL-ready via db_adapter pattern.

Schema per ticker:
{
  "ACHV": {
    "observations": [
      {
        "date": "2026-04-16",
        "run_label": "0700",
        "score": 27,
        "decision": "AVOID",
        "catalyst_type": "dilution",
        "catalyst_headline": "Achieve Life Sciences Announces $354M Private Placement",
        "ollama_flag": "TRAP",
        "ollama_risk": "Private placement = dilution. Bearish for small cap.",
        "ollama_score": 3,
        "outcome": null
      }
    ],
    "pattern": "dilution_repeat",
    "times_seen": 1,
    "times_go": 0,
    "times_trap": 1,
    "last_seen": "2026-04-16",
    "trust_score": -2,
    "first_seen": "2026-04-16"
  }
}
"""
from __future__ import annotations
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

MEMORY_FILE = "data/state/ticker_memory.json"
RETENTION_DAYS = 14


def _memory_path(project_root: str = ".") -> Path:
    p = Path(project_root) / MEMORY_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_memory(project_root: str = ".") -> Dict[str, Any]:
    """Load ticker memory, purging entries older than RETENTION_DAYS."""
    path = _memory_path(project_root)
    if not path.exists():
        return {}
    try:
        memory = json.loads(path.read_text())
    except Exception:
        return {}

    # Purge old observations
    cutoff = (datetime.now() - timedelta(days=RETENTION_DAYS)).strftime("%Y-%m-%d")
    purged = 0
    to_delete = []
    for sym, data in memory.items():
        obs = data.get("observations", [])
        fresh = [o for o in obs if o.get("date", "") >= cutoff]
        if not fresh:
            to_delete.append(sym)
        else:
            purged += len(obs) - len(fresh)
            data["observations"] = fresh
    for sym in to_delete:
        del memory[sym]

    if purged or to_delete:
        _save_memory(memory, path)

    return memory


def _save_memory(memory: Dict, path: Path) -> None:
    path.write_text(json.dumps(memory, indent=2, default=str))


def save_memory(memory: Dict, project_root: str = ".") -> None:
    _save_memory(memory, _memory_path(project_root))


def add_observation(memory: Dict, symbol: str, observation: Dict) -> Dict:
    """Add a new observation for a ticker. Updates pattern stats."""
    if symbol not in memory:
        memory[symbol] = {
            "observations": [],
            "pattern": "unknown",
            "times_seen": 0,
            "times_go": 0,
            "times_trap": 0,
            "last_seen": "",
            "first_seen": observation.get("date", ""),
            "trust_score": 0,
        }

    entry = memory[symbol]
    entry["observations"].append(observation)
    entry["times_seen"] += 1
    entry["last_seen"] = observation.get("date", "")

    # Update stats
    if observation.get("decision") == "GO":
        entry["times_go"] += 1
        entry["trust_score"] = min(10, entry["trust_score"] + 1)
    if observation.get("ollama_flag") in ("TRAP", "DILUTION", "AVOID"):
        entry["times_trap"] += 1
        entry["trust_score"] = max(-10, entry["trust_score"] - 2)

    # Derive pattern
    entry["pattern"] = _derive_pattern(entry)
    return memory


def _derive_pattern(entry: Dict) -> str:
    """Derive a pattern label from observation history."""
    obs = entry.get("observations", [])
    if not obs:
        return "unknown"

    trap_count = entry.get("times_trap", 0)
    go_count = entry.get("times_go", 0)
    seen = entry.get("times_seen", 0)

    if trap_count >= 2:
        return "repeat_trap"
    if trap_count >= 1 and seen >= 2:
        return "dilution_repeat" if any(
            "dilut" in (o.get("catalyst_type", "") + o.get("ollama_risk", "")).lower()
            for o in obs
        ) else "trap_history"
    if go_count >= 2:
        return "proven_mover"
    if seen >= 3:
        # Check if scores are building
        scores = [o.get("score", 0) for o in obs[-3:]]
        if scores == sorted(scores):
            return "building_momentum"
        return "frequent_scanner"
    return "new_ticker"


def get_ticker_context(memory: Dict, symbol: str) -> Optional[Dict]:
    """Get memory context for a ticker to inject into Ollama prompt."""
    if symbol not in memory:
        return None
    entry = memory[symbol]
    recent = entry.get("observations", [])[-3:]  # last 3 obs
    return {
        "times_seen": entry.get("times_seen", 0),
        "pattern": entry.get("pattern", "unknown"),
        "trust_score": entry.get("trust_score", 0),
        "times_go": entry.get("times_go", 0),
        "times_trap": entry.get("times_trap", 0),
        "recent": [
            {
                "date": o.get("date"),
                "score": o.get("score"),
                "flag": o.get("ollama_flag"),
                "catalyst": o.get("catalyst_headline", "")[:80],
            }
            for o in recent
        ],
    }


if __name__ == "__main__":
    # Quick test
    mem = load_memory(".")
    print(f"Loaded {len(mem)} tickers from memory")
    for sym, data in list(mem.items())[:3]:
        print(f"  {sym}: seen={data['times_seen']} pattern={data['pattern']}")
