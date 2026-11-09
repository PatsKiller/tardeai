"""What a dead FINVIZ_COOKIE costs while the Elite API token still works (LQ-20261107-1289).

The credential-health verdict can be `token_ok`: every screener keeps running on `auth=`, but a
handful of call sites still fetch with the session cookie and have no token substitute in the code
as it stands. This module reads that list from `config/finviz_cookie_features.json` so the site
banner and the operator alert describe the same degradation from one source.

Fail-soft, never fail-open on the count: an unreadable file yields an empty list, and the caller
still says "cookie expired" — it just cannot name the features. Nothing here touches the network.

AUTHORITY: READ_ONLY_ADVISORY. MBI = 0.
"""
from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_REL = "config/finviz_cookie_features.json"


def load(path: Path | str | None = None) -> dict:
    """The feature document, or a well-formed empty one when it cannot be read."""
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8") if path else (PROJECT_ROOT / CONFIG_REL).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": "FinvizCookieFeatures@v1", "features": [], "error": "unreadable"}
    rows = doc.get("features") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        return {"schema": "FinvizCookieFeatures@v1", "features": [], "error": "no_features"}
    return doc


def features(path: Path | str | None = None) -> list[dict]:
    """Only the rows a banner/alert may name: a dict with a non-empty id and label."""
    return [row for row in load(path).get("features", [])
            if isinstance(row, dict) and str(row.get("id") or "").strip() and str(row.get("label") or "").strip()]


def labels(path: Path | str | None = None) -> list[str]:
    """Short labels, in file order, for the banner's `(list)` clause."""
    return [str(row["label"]).strip() for row in features(path)]


def summary(path: Path | str | None = None) -> tuple[int, str]:
    """`(count, "a, b, c")` — the count is the number of degraded features, never a guess."""
    names = labels(path)
    return len(names), ", ".join(names)


def paragraph(path: Path | str | None = None) -> str:
    """One line per feature: `label — impact`. Used by the Telegram alert only."""
    return "\n".join(f"• {row['label']} — {str(row.get('impact') or '').strip()}".rstrip(" —")
                     for row in features(path))
