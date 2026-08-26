"""Export-by-key P0. Fail closed if the provider does not expose key identity."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .identity import fingerprint_key, redacted_key_id
from .schema import money

KEY_ATTRIBUTION_UNAVAILABLE = "KEY_ATTRIBUTION_UNAVAILABLE"

# DeepSeek's public API (api-docs.deepseek.com, retrieved 2026-08-17) documents
# chat/completions only. There is no documented usage-by-key REST resource.
# Console CSV may contain key columns if an operator exports them.
_DEEPSEEK_DOCUMENTED_SURFACES = (
    "platform.deepseek.com usage UI (account totals, model/day in screenshots)",
    "no documented /v1/usage or /v1/billing/keys endpoint in official API docs",
    "chat completions return usage tokens but not the key id that spent them",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_operator_export(path: Path) -> list[dict[str, Any]]:
    """Ingest an operator-supplied CSV/JSON usage export. Never invent keys."""
    text = path.read_text(encoding="utf-8", errors="replace")
    rows: list[dict[str, Any]] = []
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        items = data if isinstance(data, list) else data.get("rows") or data.get("items") or []
        for item in items:
            if isinstance(item, dict):
                rows.append(item)
        return rows
    # CSV
    import csv
    from io import StringIO

    reader = csv.DictReader(StringIO(text))
    for item in reader:
        rows.append({k.strip(): v for k, v in item.items() if k})
    return rows


def _row_has_key_identity(row: dict[str, Any]) -> bool:
    for k in ("api_key_id", "key_id", "key_fingerprint", "api_key", "key"):
        v = str(row.get(k) or "").strip()
        if v and v.upper() not in {"UNKNOWN", "N/A", "NONE", ""}:
            return True
    return False


def export_by_key(
    *,
    start: str,
    end: str,
    provider: str = "deepseek",
    operator_export: Optional[Path] = None,
    raw_key: Optional[str] = None,
) -> dict[str, Any]:
    """Canonical export-by-key result.

    If an operator file contains key identity, normalize it.
    Otherwise return KEY_ATTRIBUTION_UNAVAILABLE with evidence.
    """
    exported_at = _now()
    if operator_export and Path(operator_export).is_file():
        raw_rows = parse_operator_export(Path(operator_export))
        if any(_row_has_key_identity(r) for r in raw_rows):
            out_rows = []
            for r in raw_rows:
                raw = r.get("api_key") or r.get("key")
                fp = r.get("key_fingerprint") or fingerprint_key(raw, provider=provider)
                redacted = r.get("key_id_redacted") or r.get("api_key_id")
                if raw and not redacted:
                    redacted = redacted_key_id(raw, provider=provider)
                if str(redacted).upper() in {"UNKNOWN", ""}:
                    redacted = None
                out_rows.append(
                    {
                        "period_start": start,
                        "period_end": end,
                        "provider": provider,
                        "account": r.get("account") or r.get("api_key_label"),
                        "organization": r.get("organization"),
                        "project": r.get("project"),
                        "key_id_redacted": redacted,
                        "key_fingerprint": fp,
                        "model": r.get("model"),
                        "input_tokens": _int(r.get("input_tokens") or r.get("input_cache_miss_tokens")),
                        "cached_input_tokens": _int(r.get("cached_input_tokens") or r.get("input_cache_hit_tokens")),
                        "output_tokens": _int(r.get("output_tokens")),
                        "reasoning_tokens": _int(r.get("reasoning_tokens")),
                        "other_billable_units": r.get("other_billable_units") or r.get("total_tokens"),
                        "provider_cost_usd": money(r.get("provider_cost_usd") or r.get("billed_cost_usd")),
                        "currency": r.get("currency") or "USD",
                        "source": str(operator_export),
                        "exported_at": exported_at,
                    }
                )
            return {
                "ok": True,
                "status": "OK",
                "key_attribution": True,
                "rows": out_rows,
                "exported_at": exported_at,
            }
        return {
            "ok": False,
            "status": KEY_ATTRIBUTION_UNAVAILABLE,
            "key_attribution": False,
            "reason": "operator export present but no API-key identity columns with values",
            "provider_exposes": list(_DEEPSEEK_DOCUMENTED_SURFACES),
            "rows": [],
            "exported_at": exported_at,
        }

    # No operator file: documented API cannot group by key.
    env_url = os.environ.get("DEEPSEEK_USAGE_API_URL")
    if env_url:
        return {
            "ok": False,
            "status": KEY_ATTRIBUTION_UNAVAILABLE,
            "key_attribution": False,
            "reason": (
                "DEEPSEEK_USAGE_API_URL is set but this program will not call "
                "undocumented billing endpoints from tests or default live runs"
            ),
            "provider_exposes": list(_DEEPSEEK_DOCUMENTED_SURFACES),
            "rows": [],
            "exported_at": exported_at,
        }

    local_fp = fingerprint_key(raw_key, provider=provider) if raw_key else None
    return {
        "ok": False,
        "status": KEY_ATTRIBUTION_UNAVAILABLE,
        "key_attribution": False,
        "reason": (
            "DeepSeek official API docs document chat/completions only; "
            "no usage-by-key export exists for historical reconstruction. "
            "Application-layer key fingerprints are recorded going forward."
        ),
        "provider_exposes": list(_DEEPSEEK_DOCUMENTED_SURFACES),
        "future_key_fingerprint": local_fp,
        "rows": [],
        "period_start": start,
        "period_end": end,
        "exported_at": exported_at,
    }


def _int(value: Any) -> Optional[int]:
    if value is None or value == "" or str(value).upper() == "UNKNOWN":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
