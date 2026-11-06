"""Filter a cached symbol-cards payload by query without rebuilding the map."""
from __future__ import annotations

import hashlib
from typing import Any


def apply_symbol_cards_query(payload: dict[str, Any] | None, query: dict | None = None) -> dict[str, Any]:
    out = dict(payload) if isinstance(payload, dict) else {"cards": {}}
    q = query or {}
    raw_syms = q.get("symbols") or q.get("symbol")
    if not raw_syms:
        return out
    if isinstance(raw_syms, list):
        raw_syms = raw_syms[0] if raw_syms else ""
    wanted = {s.strip().upper() for s in str(raw_syms).split(",") if s.strip()}
    cards = out.get("cards") if isinstance(out.get("cards"), dict) else {}
    if wanted:
        out["cards"] = {k: v for k, v in cards.items() if str(k).upper() in wanted}
        out["count"] = len(out["cards"])
        # A filtered body must not reuse the full payload's ETag: portfolio_server caches serialized bodies by
        # ETag, so a subset would otherwise be served to a later full (or differently filtered) request.
        etag = out.get("__etag__")
        if isinstance(etag, str) and etag:
            digest = hashlib.sha1(",".join(sorted(wanted)).encode()).hexdigest()[:10]
            out["__etag__"] = etag[:-1] + "-" + digest + '"' if etag.endswith('"') else f"{etag}-{digest}"
    return out
