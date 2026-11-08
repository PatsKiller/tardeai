"""Load ``config/market_outlook_policy.yaml`` — the operator-owned priors of the Market Outlook Engine.

The policy's content hash is the ``policy_version`` stamped on every record (§2, §4.6), so a changed prior is
visible on each record written after it. Nothing in ``scripts/lib/market_outlook/`` may carry a numeric prior of its
own; a missing key is a hard error, never a default.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from . import SCHEMA_POLICY

PROJECT_ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = PROJECT_ROOT / "config" / "market_outlook_policy.yaml"


class PolicyError(ValueError):
    """The policy file is missing, unreadable, or not a MarketOutlookPolicy@v1."""


def policy_version(path: Path | str = POLICY_PATH) -> str:
    """sha256 of the policy file's bytes — the ``policy_version`` of every record (§2)."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_policy(path: Path | str = POLICY_PATH) -> dict[str, Any]:
    """Parse and structurally validate the policy. Raises PolicyError; never substitutes a default."""
    p = Path(path)
    if not p.is_file():
        raise PolicyError(f"{p}: market outlook policy not found")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:  # a corrupt policy must stop the run, not score with half of it
        raise PolicyError(f"{p}: not parseable YAML: {exc}") from exc
    if data.get("schema") != SCHEMA_POLICY:
        raise PolicyError(f"{p}: expected schema {SCHEMA_POLICY}, got {data.get('schema')!r}")
    _validate(data, p)
    return data


def _validate(data: dict[str, Any], p: Path) -> None:
    cats = data.get("categories")
    if not isinstance(cats, list) or not cats:
        raise PolicyError(f"{p}: categories must be a non-empty list")
    total = 0.0
    for cat in cats:
        for key in ("key", "title", "weight", "min_coverage", "indicators"):
            if key not in cat:
                raise PolicyError(f"{p}: category {cat.get('key', '?')!r} is missing {key!r}")
        if not cat.get("indicators"):
            raise PolicyError(f"{p}: category {cat['key']!r} has no indicators")
        for ind in cat["indicators"]:
            if not {"key", "label", "type", "weight"} <= set(ind):
                raise PolicyError(f"{p}: category {cat['key']!r} indicator is missing key/label/type/weight")
        intra = sum(float(i["weight"]) for i in cat["indicators"])
        if abs(intra - 1.0) > 1e-6:
            raise PolicyError(f"{p}: category {cat['key']!r} indicator weights sum to {intra}, not 1.0")
        total += float(cat["weight"])
    if abs(total - 100.0) > 1e-6:
        raise PolicyError(f"{p}: category weights sum to {total}, not 100")
    for required in ("normalization", "regimes", "bands", "hysteresis", "confidence", "events", "sources", "runtime"):
        if required not in data:
            raise PolicyError(f"{p}: missing section {required!r}")


def category(data: dict[str, Any], key: str) -> dict[str, Any]:
    """The category block for ``key``; KeyError when the policy has no such category."""
    for cat in data["categories"]:
        if cat["key"] == key:
            return cat
    raise KeyError(f"policy has no category {key!r}")
