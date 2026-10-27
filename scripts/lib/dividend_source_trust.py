"""Which ``ticker_dividend_data`` rows a reader may trust (operator decision 2026-10-26).

The dividends domain's retired providers are named in ``config/data_source_authority.json``
(domain ``dividends``, ``retired``). Rows they wrote are SUPERSEDED: never deleted (AGENTS.md §0 rule 6),
marked by ``migrations/2026_10_26_ticker_dividend_superseded.sql`` (``superseded_at`` / ``superseded_reason``),
and ignored by every reader through :data:`TRUSTED_ROW_SQL`. The prospectus accuracy audit (2026-10-26, A2)
measured the retired vendor's fund rows at 3-5x the real annual distribution.

The predicate keys on the ``source`` column, which exists before the migration is applied, so readers stop
using the retired rows the moment this code is live; the migration adds the audit marker only.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_AUTHORITY = Path(__file__).resolve().parents[2] / "config" / "data_source_authority.json"
_DEFAULT_RETIRED = ("fmp",)
_NAME = re.compile(r"^[a-z0-9]+$")


def retired_providers(path: Path | None = None) -> tuple[str, ...]:
    """Retired providers of the ``dividends`` domain (registry; the documented default if unreadable)."""
    try:
        doc = json.loads((path or _AUTHORITY).read_text(encoding="utf-8"))
        for row in doc.get("domains") or []:
            if isinstance(row, dict) and row.get("domain") == "dividends":
                names = tuple(str(n).strip().lower() for n in row.get("retired") or [] if _NAME.match(str(n).strip().lower()))
                return names or _DEFAULT_RETIRED
    except (OSError, ValueError, AttributeError):
        pass
    return _DEFAULT_RETIRED


def is_retired_source(source: object, providers: tuple[str, ...] | None = None) -> bool:
    """``fmp`` / ``fmp_api`` / ``fmp-legacy`` are retired when ``fmp`` is; ``yfinance`` is not."""
    s = str(source or "").strip().lower()
    return any(s == p or s.startswith(p + "_") or s.startswith(p + "-") for p in (providers or retired_providers()))


def trusted_row_sql(column: str = "source", providers: tuple[str, ...] | None = None) -> str:
    """SQL boolean: the row was not written by a retired provider. No ``%`` (safe inside psycopg2 strings)."""
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_.]*$", column):
        raise ValueError(f"bad column {column!r}")
    alt = "|".join(providers or retired_providers())
    return f"(COALESCE({column}, '') !~* '^({alt})([_-]|$)')"


#: ``... FROM ticker_dividend_data WHERE <...> AND {TRUSTED_ROW_SQL}``
TRUSTED_ROW_SQL = trusted_row_sql()
