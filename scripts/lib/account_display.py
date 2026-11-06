"""account_display — the one short human name for each account (operator 2026-10-23).

Operator, verbatim: "you need to actually put which account right here. Like, for example, there are
two SpaceX and two different accounts." and then "just a name, not the account numbers."

Every Command Center row that carries a position, a held or formerly-held name, a fill, a stop, a P/L or
a trade gets two fields from here:

    account_id     the canonical account key (``schwab_rollover_ira``) — an internal key, never a number
    account_label  the short human name (``Schwab Rollover IRA``) — never an account number, never digits

Names live in ``config/account_display_names.json``. A key that is not configured is title-cased from
the key; a key that looks like a broker account number (a run of 3+ digits, or a masked ``...258`` /
``··1234`` form) is never echoed: it becomes ``Unlabelled account``.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

_CONFIG = Path(__file__).resolve().parents[2] / "config" / "account_display_names.json"
UNLABELLED = "Unlabelled account"
_DIGIT_RUN = re.compile(r"\d{3,}")
_MASK = re.compile(r"(\.\.\.|··|…|\*\*|xx)\s*\w*\d", re.I)
ACCOUNT_FIELDS = ("account_id", "account", "account_key", "accountId", "broker_account")


def _read_config(path: str) -> Optional[dict]:
    """Read the registry fresh. ``None`` means unreadable or not a JSON object (never a guess)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


@lru_cache(maxsize=1)
def _load(path: str = str(_CONFIG)) -> dict:
    data = _read_config(path)
    return data if data is not None else {"aliases": {}, "names": {}}


def looks_like_number(text: str) -> bool:
    """True when text would leak an account number (a 3+ digit run or a masked tail)."""
    s = str(text or "")
    return bool(_DIGIT_RUN.search(s) or _MASK.search(s))


def _canonical(raw: Any, cfg: Mapping) -> str:
    key = str(raw or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not key:
        return ""
    return str((cfg.get("aliases") or {}).get(key, key))


def _label(key: str, cfg: Mapping) -> str:
    if not key:
        return UNLABELLED
    entry = (cfg.get("names") or {}).get(key)
    name = entry.get("name") if isinstance(entry, Mapping) else None
    if not name:
        if looks_like_number(key):
            return UNLABELLED
        name = re.sub(r"\bIra\b", "IRA", key.replace("_", " ").title())
    return UNLABELLED if looks_like_number(name) else str(name)


def canonical_key(raw: Any) -> str:
    return _canonical(raw, _load())


def account_label(raw: Any) -> str:
    """The short human name for an account key. Never contains an account number."""
    return _label(canonical_key(raw), _load())


def location_facts(row: Mapping[str, Any]) -> dict[str, str]:
    """Names and declared account type for specialist context; no account number.

    Type/status come from the same registry row as the display name. A symbol,
    legacy narrative or friendly label never infers tax treatment.
    """
    key = row_account(row)
    entry = (_load().get("names") or {}).get(key) or {}
    entry = entry if isinstance(entry, Mapping) else {}
    return {
        "account_name": account_label(key),
        "account_type": str(entry.get("type") or "unknown"),
        "account_name_status": str(entry.get("status") or "unknown"),
        "account_metadata_source": "config/account_display_names.json",
    }


def labels_map(keys: Iterable[Any] | None = None) -> dict[str, str]:
    """{account_key: label} for the given keys, or for every configured account."""
    if keys is None:
        keys = list((_load().get("names") or {}).keys())
    return {str(k): account_label(k) for k in keys if str(k or "").strip()}


def _humanized(key: Any) -> set[str]:
    s = str(key or "").strip().lower().replace("-", "_")
    return {s, s.replace("_", " ")} if s else set()


def redaction_terms() -> tuple[str, ...]:
    """Every string that can name a configured account, longest first, for an egress guard.

    Prose sent to an external model must not carry account identity. The terms are the display
    label, the registry name, the account key and its aliases (and their humanized forms), the
    broker (a broker alone can identify the one account held there), and the label with its broker
    prefix stripped when what remains is still distinctive ("Rollover IRA", "Roth IRA").

    The registry is read **fresh** on every call: identity evidence at an egress boundary must not be
    a stale cache (a file edited or removed after a cache warm is a changed or unreadable source). An
    incomplete snapshot yields ``()``: an unreadable file, a non-object, or a registry with no
    ``names`` entries (aliases alone cannot say which accounts exist). Callers must fail closed on
    ``()`` rather than treating any non-empty term list as permission to send prose.
    """
    cfg = _read_config(str(_CONFIG))
    if not isinstance(cfg, Mapping):
        return ()
    names = cfg.get("names")
    if not isinstance(names, Mapping) or not names:
        return ()  # no account entries: not a complete identity snapshot
    terms: set[str] = set()
    for key, entry in names.items():
        entry = entry if isinstance(entry, Mapping) else {}
        label = _label(_canonical(key, cfg), cfg)
        terms.add(str(key))
        terms.add(label)
        for field_name in ("name", "registry_name", "broker"):
            if entry.get(field_name):
                terms.add(str(entry[field_name]))
        terms.update(_humanized(key))
        bits = label.split()
        if len(bits) >= 3:
            terms.add(" ".join(bits[1:]))
    aliases = cfg.get("aliases")
    if isinstance(aliases, Mapping):
        for alias in aliases:
            terms.add(str(alias))
            terms.update(_humanized(alias))
    return tuple(sorted((t.strip() for t in terms if str(t).strip()), key=len, reverse=True))


def row_account(row: Mapping[str, Any]) -> str:
    for f in ACCOUNT_FIELDS:
        v = row.get(f) if isinstance(row, Mapping) else None
        if v not in (None, "") and not looks_like_number(v):
            return canonical_key(v)
    return ""


def label_row(row: dict) -> dict:
    """Add ``account_id`` + ``account_label`` to one row in place (keeps any existing ``account``)."""
    if not isinstance(row, dict):
        return row
    key = row_account(row)
    if key:
        row["account_id"] = key
        row["account_label"] = account_label(key)
    elif any(row.get(f) for f in ACCOUNT_FIELDS):
        row["account_label"] = UNLABELLED
    return row


def label_rows(rows: Iterable[Any]) -> list:
    """Shallow copies of the rows with ``account_id`` + ``account_label`` (a cached input is never mutated)."""
    return [label_row(dict(r)) if isinstance(r, dict) else r for r in (rows or [])]


def multi_account_symbols(rows: Iterable[Mapping[str, Any]], symbol_field: str = "symbol") -> dict[str, list[str]]:
    """{SYMBOL: [account keys]} for symbols held in two or more accounts (rows of one per account holding)."""
    seen: dict[str, list[str]] = {}
    for r in rows or []:
        if not isinstance(r, Mapping):
            continue
        sym = str(r.get(symbol_field) or "").strip().upper()
        acct = row_account(r)
        if sym and acct and acct not in seen.setdefault(sym, []):
            seen[sym].append(acct)
    return {s: a for s, a in seen.items() if len(a) >= 2}
