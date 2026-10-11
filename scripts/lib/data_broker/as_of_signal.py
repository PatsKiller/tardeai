"""as_of_signal.py — the Data Broker domain ``as_of`` advance, read from files only (W5 event triggers).

CONSOLIDATION_PLAN.md §E.4: "the n8n event router fires a consumer when its input domain's projection ``as_of``
advances past the consumer's last receipt watermark". This module answers the first half — *what is the domain's
``as_of`` now* — for the gateway's ``coordination/due`` (source ``event``, ``scripts/lib/n8n_due.py``). The gateway
computes due every minute and holds no database credential (AGENTS.md §23.5), so every reader here is a small JSON
file under the persistent state root: no DB, no provider, no network, no write.

Two kinds of domain:

* **Owner already emits** — the owner's own receipt carries the ``as_of`` (no producer change):
    ``scalp_list``  max of ``data/trade_ai/scalp_universe_latest.json`` ``as_of`` (``TradeAIScalpUniverse@v1``,
                    single writer ``run_trade_ai_scalp_live.py``, 09:30-16:00 ET) and
                    ``data/runtime/momentum_scalp_refresh_receipt.json`` ``at`` when ``state == DONE``
                    (``MomentumScalpRefreshReceipt@v1``, the hot-tier refresh stage, 06:00-09:30 ET). Same files and
                    rules as the ``scalp_list`` projection (``scalp_list.read_universe`` / ``read_premarket``); that
                    module imports ``lib.*`` and so cannot be loaded by the gateway, which has only the repo root on
                    ``sys.path``.
* **Owner emits through** :func:`emit_as_of` — ``data/runtime/broker_as_of/<domain>.json`` (``BrokerAsOf@v1``):
    ``catalyst_news``  emitted by the news-ingest owner (``scripts/news_ingestion.py``) after a run that wrote rows
                       to ``news_articles``.

``as_of`` vs ``checked_at`` in ``BrokerAsOf@v1``: ``as_of`` advances only when the run wrote at least one row (the
store's content changed, so consumers have something new); ``checked_at`` advances on every successful run. An event
trigger reads ``as_of`` only, so an empty ingest run fires nothing.

Emit flag: ``DATA_BROKER_AS_OF_EMIT`` (default ``1`` = emit). ``0`` turns the emit off; the owner's own work and
exit code are unchanged either way, and :func:`emit_as_of` never raises into the owner.

AUTHORITY: READ_ONLY_ADVISORY for readers. The one write (:func:`emit_as_of`) is a bookkeeping file next to the lane
receipts; it is not a store of record. MBI_BEHAVIOR = 0: no broker, no order, no send.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

SCHEMA = "BrokerAsOf@v1"
EMIT_ENV = "DATA_BROKER_AS_OF_EMIT"
EMIT_DIR_REL = Path("data") / "runtime" / "broker_as_of"
SCALP_UNIVERSE_REL = Path("data") / "trade_ai" / "scalp_universe_latest.json"
SCALP_RECEIPT_REL = Path("data") / "runtime" / "momentum_scalp_refresh_receipt.json"
SCALP_RECEIPT_ENV = "MOMENTUM_SCALP_REFRESH_RECEIPT"
#: Domains whose owner emits through emit_as_of: domain -> the owner (documentation and the registry check).
EMIT_DOMAINS: dict[str, str] = {
    "catalyst_news": "scripts/news_ingestion.py (news-ingest owner; store news_articles)",
}
#: Domains whose owner's own receipt already carries the as_of: domain -> the files read.
OWNER_RECEIPT_DOMAINS: dict[str, str] = {
    "scalp_list": f"{SCALP_UNIVERSE_REL} as_of + {SCALP_RECEIPT_REL} at (state DONE)",
}
#: Every domain an event trigger (`dispatch.triggers[].domain`, source broker_as_of) may name.
DOMAINS = tuple(sorted(set(EMIT_DOMAINS) | set(OWNER_RECEIPT_DOMAINS)))
_MAX_FILE_BYTES = 1 << 20

NO_CONSUMER_REASON = (
    "Imported by scripts/lib/n8n_due.py (coordination/due source event) and by the owners that emit "
    "(scripts/news_ingestion.py); no lane runs it directly."
)


@dataclass(frozen=True)
class AsOf:
    """One domain's current as_of. ``as_of`` is None when no file says anything usable; ``error`` says why."""

    domain: str
    as_of: Optional[datetime]
    source: str
    error: Optional[str] = None


def parse_ts(value: Any) -> Optional[datetime]:
    """ISO-8601 -> aware UTC datetime. A naive value is host-local (the writers stamp ``datetime.now()``)."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc)


def _import(name: str):
    try:
        return __import__(f"scripts.lib.{name}", fromlist=[name])
    except ImportError:  # imported as lib.data_broker.as_of_signal (scripts/ on sys.path, repo root not)
        return __import__(f"lib.{name}", fromlist=[name])


def state_root(explicit: Path | str | None = None, env: Mapping[str, str] | None = None) -> Path:
    """Explicit root -> ``TRADEAI_STATE_ROOT`` -> the durable ``data/runtime`` resolver's root (as the lane receipts)."""
    if explicit:
        return Path(explicit)
    e = os.environ if env is None else env
    if e.get("TRADEAI_STATE_ROOT"):
        return Path(str(e["TRADEAI_STATE_ROOT"]))
    return Path(_import("lane_last_receipt").runtime_dir()).parent.parent


def _read_json(path: Path) -> tuple[Optional[dict], Optional[str]]:
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            return None, "too_large"
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, "missing"
    except (OSError, ValueError):
        return None, "unreadable"
    return (doc, None) if isinstance(doc, dict) else (None, "not_an_object")


def _scalp_list(root: Path, env: Mapping[str, str]) -> AsOf:
    cands: list[datetime] = []
    errs: list[str] = []
    uni, err = _read_json(root / SCALP_UNIVERSE_REL)
    if uni is not None and uni.get("schema") == "TradeAIScalpUniverse@v1" and parse_ts(uni.get("as_of")):
        cands.append(parse_ts(uni.get("as_of")))  # type: ignore[arg-type]
    else:
        errs.append(f"universe:{err or 'schema_or_as_of'}")
    override = str(env.get(SCALP_RECEIPT_ENV) or "").strip()
    rec, err = _read_json(Path(override) if override else root / SCALP_RECEIPT_REL)
    if rec is not None and rec.get("state") == "DONE" and parse_ts(rec.get("at")):
        cands.append(parse_ts(rec.get("at")))  # type: ignore[arg-type]
    else:
        errs.append(f"refresh_receipt:{err or 'not_done'}")
    src = OWNER_RECEIPT_DOMAINS["scalp_list"]
    if not cands:
        return AsOf("scalp_list", None, src, ",".join(errs))
    return AsOf("scalp_list", max(cands), src)


def emit_path(domain: str, root: Path | str | None = None, env: Mapping[str, str] | None = None) -> Path:
    return state_root(root, env) / EMIT_DIR_REL / f"{domain}.json"


def _emitted(domain: str, root: Path, env: Mapping[str, str]) -> AsOf:
    path = root / EMIT_DIR_REL / f"{domain}.json"
    doc, err = _read_json(path)
    src = str(EMIT_DIR_REL / f"{domain}.json")
    if doc is None:
        return AsOf(domain, None, src, err)
    if doc.get("schema") != SCHEMA or doc.get("domain") != domain:
        return AsOf(domain, None, src, "schema_mismatch")
    ts = parse_ts(doc.get("as_of"))
    return AsOf(domain, ts, src, None if ts else "no_as_of")


_READERS: dict[str, Callable[[Path, Mapping[str, str]], AsOf]] = {"scalp_list": _scalp_list}


def read_as_of(domain: str, *, root: Path | str | None = None, env: Mapping[str, str] | None = None) -> AsOf:
    """The domain's current as_of from files only. Never raises; an unknown domain is an error value."""
    e = os.environ if env is None else env
    if domain not in DOMAINS:
        return AsOf(domain, None, "", "unknown_domain")
    try:
        r = state_root(root, e)
    except Exception as exc:  # noqa: BLE001 — a resolver failure is a reported error, never a crash in due
        return AsOf(domain, None, "", f"state_root:{type(exc).__name__}")
    reader = _READERS.get(domain)
    if reader is not None:
        return reader(r, e)
    return _emitted(domain, r, e)


def emit_enabled(env: Mapping[str, str] | None = None) -> bool:
    e = os.environ if env is None else env
    return str(e.get(EMIT_ENV, "1")).strip() != "0"


def emit_as_of(
    domain: str,
    *,
    rows_written: int,
    lane_id: str,
    source: str,
    at: datetime | None = None,
    root: Path | str | None = None,
    env: Mapping[str, str] | None = None,
) -> Optional[Path]:
    """Owner-side emit after a SUCCESSFUL real run (never from a dry run). ``as_of`` advances only when
    ``rows_written > 0``; ``checked_at`` always. Returns the path, or None (flag off, unknown domain, or a write
    failure — reported on stderr; never raises into the owner)."""
    if not emit_enabled(env):
        return None
    if domain not in EMIT_DOMAINS:
        print(f"[as_of_signal] refuse emit: {domain!r} is not an emit domain", file=sys.stderr)
        return None
    try:
        now = (at or datetime.now(timezone.utc)).astimezone(timezone.utc)
        path = emit_path(domain, root, env)
        prev, _err = _read_json(path)
        prev_ok = prev is not None and prev.get("schema") == SCHEMA and prev.get("domain") == domain
        prev_as_of = (prev or {}).get("as_of") if prev_ok else None
        wrote = max(0, int(rows_written))
        doc = {
            "schema": SCHEMA,
            "domain": domain,
            "as_of": now.isoformat() if wrote > 0 else prev_as_of,
            "checked_at": now.isoformat(),
            "rows_written": wrote,
            "lane_id": lane_id,
            "source": source,
        }
        _import("atomic_json_store").atomic_write_json(path, doc, indent=1)
        return path
    except Exception as exc:  # noqa: BLE001 — the owner's own result comes first
        print(f"[as_of_signal] emit {domain} failed: {type(exc).__name__}", file=sys.stderr)
        return None
