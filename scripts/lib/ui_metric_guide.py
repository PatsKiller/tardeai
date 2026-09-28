"""Metric guide loader (PR3, 2026-09-27): assets/ui_metric_guide.yaml -> the payload served at
GET /api/v2/ui/metric-guide. Validates every entry (label, short, definition, why_it_matters,
interpretation are required; benchmark/watch/warning/unit/sources optional; keys are
dotted lowercase ids). Cached by file mtime; hermetic (no DB, no network)."""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any, Optional

REQUIRED = ("label", "short", "definition", "why_it_matters", "interpretation")
OPTIONAL = ("benchmark", "watch", "warning", "unit", "sources")
KEY_RE = re.compile(r"^[a-z0-9]+(\.[a-z0-9_\-]+)+$")
_CACHE: dict[str, Any] = {}


def guide_path(root: Optional[Path] = None) -> Path:
    base = root or Path(os.environ.get("TRADEAI_RUNTIME_ROOT") or Path(__file__).resolve().parents[2])
    return base / "assets" / "ui_metric_guide.yaml"


def validate(doc: dict[str, Any]) -> list[str]:
    """Problems with the document; empty when valid."""
    errs: list[str] = []
    if not isinstance(doc, dict):
        return ["document is not a mapping"]
    if not doc.get("version"):
        errs.append("missing version")
    entries = doc.get("entries")
    if not isinstance(entries, dict) or not entries:
        return errs + ["entries missing or empty"]
    for key, e in entries.items():
        if not KEY_RE.match(str(key)):
            errs.append(f"{key}: key must be dotted lowercase (group.metric)")
        if not isinstance(e, dict):
            errs.append(f"{key}: entry is not a mapping")
            continue
        for f in REQUIRED:
            if not str(e.get(f) or "").strip():
                errs.append(f"{key}: missing {f}")
        for f in e:
            if f not in REQUIRED and f not in OPTIONAL:
                errs.append(f"{key}: unknown field {f}")
        if "sources" in e and not isinstance(e["sources"], list):
            errs.append(f"{key}: sources must be a list")
    return errs


def load(root: Optional[Path] = None, *, strict: bool = False) -> dict[str, Any]:
    """The served payload: {ok, version, as_of, etag, count, entries, errors}."""
    import yaml
    p = guide_path(root)
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return {"ok": False, "error": f"metric guide not found at {p}", "entries": {}, "version": None}
    cached = _CACHE.get(str(p))
    if cached and cached["mtime"] == mtime:
        return cached["payload"]
    raw = p.read_text(encoding="utf-8")
    doc = yaml.safe_load(raw) or {}
    errs = validate(doc)
    if errs and strict:
        raise ValueError("; ".join(errs[:10]))
    entries = doc.get("entries") if isinstance(doc.get("entries"), dict) else {}
    payload = {
        "ok": not errs,
        "schema": "UiMetricGuide@v1",
        "version": str(doc.get("version") or ""),
        "as_of": str(doc.get("as_of") or ""),
        "etag": hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16],
        "count": len(entries),
        "entries": entries,
        "errors": errs[:20],
    }
    _CACHE[str(p)] = {"mtime": mtime, "payload": payload}
    return payload


def keys(root: Optional[Path] = None) -> list[str]:
    return sorted(load(root)["entries"].keys())
