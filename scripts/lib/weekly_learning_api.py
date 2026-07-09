"""Helpers for /api/v2/weekly-learning — review text cleanup + tier rollups."""
from __future__ import annotations

import json
import re


def review_snippet(text: str | None, *, max_len: int = 600) -> str:
    """Plain-text snippet for UI: unwrap ```json weekly summaries when present."""
    if not text:
        return ""
    s = str(text).strip()
    if s.startswith("```"):
        s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\s*```$", "", s)
        try:
            obj = json.loads(s)
            if isinstance(obj, dict):
                if obj.get("weekly_summary"):
                    s = str(obj["weekly_summary"])
                elif obj.get("summary"):
                    s = str(obj["summary"])
        except Exception:
            pass
    s = re.sub(r"\s+", " ", s).strip()
    return s[:max_len] if len(s) > max_len else s