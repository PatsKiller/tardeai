"""Governed Brave / search router — CampaignInterfaces@v1 / Lane C.

Single chokepoint for provider search calls. Every Brave request in the serving
tree must go through ``search()`` here (or an explicit DISABLED/CLASSIFIED
disposition recorded by the bypass scan).

Properties:
  * Atomic reserve → settle | refund under flock, with reservation ledger.
  * Injected clock used for both reservation day/month keys and enforcement.
  * Shared durable cache — cache hits allocate no provider budget.
  * Fail-closed on corrupt/unreadable quota or reservation state.
  * Provider-reported limits (headers) kept separate from local cost policy.
  * Historical provider-header evidence labelled historical, never current proof.
  * No paid call unless a transport is injected (tests) or live is explicitly armed.
  * Spill (Phase 5, 2026-09-13): a Brave denial for DAILY_EXHAUSTED /
    MONTHLY_EXHAUSTED / HTTP 429 resolves the next provider from
    config/data_source_authority.json (``domains[web_search].backup`` =
    searxng, tavily; ``spill_on`` decides which reasons) and asks it the same
    question, budget-checked under the backup's own cap. Every denial writes a
    receipt row (provider, reason, spilled_to, ts) into the budget ledger next
    to the counters. Callers that must have Brave-quality results pass
    ``no_spill=True``; the default spills. Measured before the fix: 38
    DAILY_EXHAUSTED denials on 09-13, 22 on 09-11, every one of them lost while
    the self-hosted SearXNG sat idle. Tavily has no client in this tree and is
    recorded in the receipt as a declared-but-unwired slot.
"""
from __future__ import annotations

import hashlib
import json
import os
import fcntl
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import gzip

SCHEMA = "GovernedBraveRouter@v1"
INTERFACE_VERSION = "CampaignInterfaces@v1"
PROVIDER = "brave"

BRAVE_WEB_URL = "https://api.search.brave.com/res/v1/web/search"
BRAVE_NEWS_URL = "https://api.search.brave.com/res/v1/news/search"

# Feature flag: OFF → new path produces no durable side effect and no provider call.
FLAG_ENABLED = "BRAVE_ROUTER_ENABLED"
# Explicit arm for a real network call. Tests never set this.
FLAG_LIVE = "BRAVE_ROUTER_LIVE"


Clock = Callable[[], datetime]
Transport = Callable[[str, dict[str, str]], tuple[dict[str, Any], dict[str, str]]]


class RouterDisabled(RuntimeError):
    """Router feature flag is OFF — no side effects."""


class BudgetRefused(RuntimeError):
    """Local cost policy refused the reservation."""


class QuotaCorrupt(RuntimeError):
    """Quota / reservation ledger unreadable — fail closed."""


class DoubleSettlement(RuntimeError):
    """Reservation already settled or refunded."""


class ReplayCollision(RuntimeError):
    """Idempotency key already used."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def router_enabled(env: Optional[dict[str, str]] = None) -> bool:
    src = env if env is not None else os.environ
    return str(src.get(FLAG_ENABLED, "")).strip() in {"1", "true", "TRUE", "yes", "on"}


def live_armed(env: Optional[dict[str, str]] = None) -> bool:
    src = env if env is not None else os.environ
    return str(src.get(FLAG_LIVE, "")).strip() in {"1", "true", "TRUE", "yes", "on"}


def _state_root(root: Optional[Path] = None) -> Path:
    if root is not None:
        return Path(root)
    try:
        from scripts.lib.canonical_store_registry import production_state_root
        return Path(production_state_root())
    except Exception:
        try:
            from lib.canonical_store_registry import production_state_root  # type: ignore
            return Path(production_state_root())
        except Exception:
            return Path.home() / "trade-ai-releases" / "persistent-state"


def reservation_path(root: Optional[Path] = None) -> Path:
    return _state_root(root) / "data" / "runtime" / "brave_router_reservations.json"


def cache_path(root: Optional[Path] = None) -> Path:
    return _state_root(root) / "data" / "runtime" / "brave_router_cache.json"


def health_path(root: Optional[Path] = None) -> Path:
    return _state_root(root) / "data" / "runtime" / "brave_router_health.json"


def capacity_history_path(root: Optional[Path] = None) -> Path:
    return _state_root(root) / "data" / "runtime" / "brave_provider_capacity_history.jsonl"


@contextmanager
def _exclusive(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(path.suffix + ".lock")
    if not lock.exists():
        lock.touch()
    with open(lock, "a+") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            try:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass


def _load_json(path: Path, *, empty: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(empty)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise QuotaCorrupt(f"unreadable ledger at {path}: {exc}") from exc
    if not isinstance(doc, dict):
        raise QuotaCorrupt(f"malformed ledger at {path}")
    return doc


def _save_json(path: Path, doc: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


@dataclass
class Reservation:
    reservation_id: str
    caller: str
    purpose: str
    idempotency_key: str
    state: str  # RESERVED | SETTLED | REFUNDED
    reserved_at: str
    units: int = 1
    settled_at: Optional[str] = None
    refunded_at: Optional[str] = None


@dataclass
class SearchResult:
    title: str
    url: str
    description: str
    age: str = ""
    source: str = ""


@dataclass
class RouterResponse:
    schema: str = SCHEMA
    interface_version: str = INTERFACE_VERSION
    ok: bool = False
    reason: str = ""
    results: list[dict[str, Any]] = field(default_factory=list)
    cache_hit: bool = False
    reservation_id: Optional[str] = None
    budget_allocated: bool = False
    provider_capacity: Optional[dict[str, Any]] = None
    local_cost_policy: Optional[dict[str, Any]] = None
    health: Optional[dict[str, Any]] = None
    #: Which provider actually answered — ``brave`` or the backup that took the spill.
    provider: str = PROVIDER
    #: Denial receipt (provider, reason, spilled_to, ts) when Brave refused; else None.
    receipt: Optional[dict[str, Any]] = None


def local_cost_policy() -> dict[str, Any]:
    """Local spend policy — NOT a provider limit. Independently overridable.

    Caps come from ``search_budget.limits`` which reads the registry's
    ``providers[brave].budget`` over the module constants (Phase 5).
    """
    try:
        from scripts.lib.search_budget import limits, CALLER_DAILY_CAPS
    except ImportError:
        from lib.search_budget import limits, CALLER_DAILY_CAPS  # type: ignore
    brave = dict(limits(PROVIDER))
    return {
        "kind": "local_cost_policy",
        "provider": PROVIDER,
        "daily": brave.get("daily"),
        "monthly": brave.get("monthly"),
        "caller_daily_caps": dict(CALLER_DAILY_CAPS),
        "note": "operator-owned cost bound; not a Brave plan ceiling",
        "invented_provider_monthly_ceiling": False,
        "source": "config/data_source_authority.json providers[].budget, DEFAULT_LIMITS fallback, env override",
    }


# ── Spill to the registry's backup chain ─────────────────────────────────────

SPILL_DOMAIN = "web_search"
#: Fallback when the registry cannot be read. The registry wins when it can.
DEFAULT_SPILL_ON = frozenset({"DAILY_EXHAUSTED", "MONTHLY_EXHAUSTED", "HTTP_429"})

#: A backup transport answers ``(query, kind, count) -> list[result dict]``.
SpillTransport = Callable[[str, str, int], list[dict[str, Any]]]


def _resolve_spill_chain() -> list[str]:
    """``domains[web_search].backup`` minus retired — from the registry, never a constant.

    Tests disable spilling (the pre-fix behaviour) by monkeypatching this to
    return ``[]``. An unreadable registry also yields ``[]``: the question is
    then lost exactly as before, but the receipt says so.
    """
    try:
        try:
            from scripts.lib.data_source_authority import resolve_backup
        except ImportError:
            from lib.data_source_authority import resolve_backup  # type: ignore
        return list(resolve_backup(SPILL_DOMAIN))
    except Exception:
        return []


def _spill_reasons() -> frozenset[str]:
    try:
        try:
            from scripts.lib.data_source_authority import spill_on
        except ImportError:
            from lib.data_source_authority import spill_on  # type: ignore
        reasons = spill_on(SPILL_DOMAIN)
        return reasons or DEFAULT_SPILL_ON
    except Exception:
        return DEFAULT_SPILL_ON


def _is_http_429(exc: BaseException) -> bool:
    for attr in ("code", "status", "status_code"):
        try:
            if int(getattr(exc, attr, None) or 0) == 429:
                return True
        except (TypeError, ValueError):
            pass
    return " 429" in f" {exc}" or "HTTP_429" in str(exc) or "Too Many Requests" in str(exc)


def _searxng_transport(query: str, kind: str, count: int) -> list[dict[str, Any]]:
    """Live SearXNG hop through the ONE shared client (scripts/lib/searxng_client).

    Self-hosted and free, but still a network socket: like Brave it refuses to
    leave the host unless ``BRAVE_ROUTER_LIVE`` is armed. Tests inject a
    ``spill_transport``. Error rows from the client are raised so the caller
    refunds the backup's budget unit and moves to the next slot.
    """
    if not live_armed():
        raise RuntimeError("BRAVE_ROUTER_LIVE is not set — refusing network SearXNG call; inject spill_transport")
    try:
        from scripts.lib.searxng_client import searx_search
    except ImportError:
        from lib.searxng_client import searx_search  # type: ignore
    hits = searx_search(query, categories="news" if kind == "news" else "general", limit=int(count))
    errors = [h for h in hits if isinstance(h, dict) and h.get("error") and not h.get("url")]
    if errors and len(errors) == len(hits):
        raise RuntimeError(f"searxng: {errors[0].get('error')}")
    return [h for h in hits if isinstance(h, dict) and h.get("url")]


#: Backup slots this router can actually call. Tavily is declared in the registry
#: (providers.tavily, status configured_unused, 20/day) but no client exists in
#: this tree; it stays a declared-but-unwired slot and the receipt says so.
SPILL_ADAPTERS: dict[str, SpillTransport] = {
    "searxng": _searxng_transport,
}


def _normalize_spill_results(provider: str, hits: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    out = []
    for h in hits:
        row = {
            "title": str(h.get("title") or ""),
            "url": str(h.get("url") or ""),
            "description": str(h.get("description") or h.get("snippet") or h.get("content") or ""),
            "age": str(h.get("age") or h.get("publishedDate") or ""),
            "provider": provider,
        }
        if kind == "news":
            row["source"] = str(h.get("source") or h.get("domain") or "")
        out.append(row)
    return out


def _spill(
    query: str,
    *,
    kind: str,
    count: int,
    reason: str,
    caller: str,
    clock: Clock,
    root: Optional[Path],
    spill_transport: Optional[SpillTransport],
) -> tuple[Optional[str], list[dict[str, Any]], dict[str, Any]]:
    """Ask the backup chain the same question. Returns (provider|None, results, detail).

    Each slot is budget-checked under ITS OWN cap (searxng 10,000/day in the
    registry) via ``try_consume``; a refused or failed slot is refunded where
    a unit was spent and the chain moves on. ``detail`` names every slot tried
    and why it did not answer, so a receipt with ``spilled_to: null`` is never
    silent about which lanes were exhausted.
    """
    try:
        from scripts.lib.search_budget import try_consume, refund
    except ImportError:
        from lib.search_budget import try_consume, refund  # type: ignore

    detail: dict[str, Any] = {"denial_reason": reason, "chain": [], "tried": {}}
    chain = _resolve_spill_chain()
    detail["chain"] = list(chain)
    if not chain:
        detail["tried"]["_"] = "NO_BACKUP_CHAIN"
        return None, [], detail
    for prov in chain:
        adapter = spill_transport if (spill_transport is not None and prov == chain[0]) else SPILL_ADAPTERS.get(prov)
        if adapter is None:
            detail["tried"][prov] = "NO_ADAPTER (declared in registry, not wired)"
            continue
        verdict = try_consume(prov, caller=caller, now=clock(), root=root)
        if not verdict.get("allowed"):
            detail["tried"][prov] = f"BUDGET_REFUSED:{verdict.get('reason')}"
            continue
        try:
            hits = adapter(query, kind, count)
        except Exception as exc:
            try:
                refund(prov, caller=caller, now=clock(), root=root)
            except Exception:
                pass
            detail["tried"][prov] = f"PROVIDER_ERROR:{type(exc).__name__}:{exc}"
            continue
        results = _normalize_spill_results(prov, list(hits or []), kind)
        detail["tried"][prov] = f"OK:{len(results)}"
        return prov, results, detail
    return None, [], detail


def _write_receipt(reason: str, *, spilled_to: Optional[str], caller: str, kind: str,
                   detail: dict[str, Any], clock: Clock, root: Optional[Path]) -> Optional[dict[str, Any]]:
    try:
        from scripts.lib.search_budget import write_denial_receipt
    except ImportError:
        from lib.search_budget import write_denial_receipt  # type: ignore
    try:
        return write_denial_receipt(PROVIDER, reason, spilled_to=spilled_to, caller=caller,
                                    kind=kind, detail=detail, now=clock(), root=root)
    except Exception:
        return None


def _deny_or_spill(
    query: str,
    *,
    reason: str,
    kind: str,
    count: int,
    caller: str,
    clock: Clock,
    root: Optional[Path],
    no_spill: bool,
    spill_transport: Optional[SpillTransport],
    policy: dict[str, Any],
    reservation_id: Optional[str] = None,
    ck: Optional[str] = None,
) -> RouterResponse:
    """The one place a Brave denial is turned into a response — with a receipt."""
    spilled_to: Optional[str] = None
    results: list[dict[str, Any]] = []
    detail: dict[str, Any] = {"denial_reason": reason}
    if no_spill:
        detail["no_spill"] = True
    elif reason not in _spill_reasons():
        detail["not_a_spill_reason"] = sorted(_spill_reasons())
    else:
        spilled_to, results, detail = _spill(
            query, kind=kind, count=count, reason=reason, caller=caller,
            clock=clock, root=root, spill_transport=spill_transport,
        )
    receipt = _write_receipt(reason, spilled_to=spilled_to, caller=caller, kind=kind,
                             detail=detail, clock=clock, root=root)
    if spilled_to:
        if ck:
            try:
                _write_cache(root, ck, results, now=clock())
            except Exception:
                pass
        health = write_health(clock=clock, root=root, last={
            "event": "spilled", "reason": reason, "spilled_to": spilled_to, "n": len(results)})
        return RouterResponse(
            ok=True, reason=f"SPILLED:{spilled_to}", results=results,
            reservation_id=reservation_id, budget_allocated=False,
            local_cost_policy=policy, health=health, provider=spilled_to, receipt=receipt,
        )
    event = "provider_error" if reason == "HTTP_429" else "budget_refused"
    health = write_health(clock=clock, root=root, last={"event": event, "reason": reason, "spilled_to": None})
    prefix = "PROVIDER_ERROR:HTTP 429" if reason == "HTTP_429" else f"BUDGET_REFUSED:{reason}"
    return RouterResponse(
        ok=False, reason=prefix, reservation_id=reservation_id,
        budget_allocated=reservation_id is not None,
        local_cost_policy=policy, health=health, receipt=receipt,
    )


def _cache_key(kind: str, query: str, freshness: Optional[str], count: int) -> str:
    raw = f"{kind}|{query}|{freshness or ''}|{count}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _read_cache(root: Optional[Path], key: str, *, now: datetime, ttl_s: int) -> Optional[list]:
    path = cache_path(root)
    try:
        doc = _load_json(path, empty={"schema": "BraveRouterCache@v1", "entries": {}})
    except QuotaCorrupt:
        return None
    entry = (doc.get("entries") or {}).get(key)
    if not entry:
        return None
    try:
        ts = datetime.fromisoformat(str(entry["ts"]).replace("Z", "+00:00"))
    except Exception:
        return None
    if (now - ts).total_seconds() > ttl_s:
        return None
    return entry.get("results")


def _write_cache(root: Optional[Path], key: str, results: list, *, now: datetime) -> None:
    path = cache_path(root)
    with _exclusive(path):
        try:
            doc = _load_json(path, empty={"schema": "BraveRouterCache@v1", "entries": {}})
        except QuotaCorrupt:
            # Corrupt cache: rotate aside and start fresh (cache is not quota).
            bak = path.with_suffix(path.suffix + ".corrupt")
            try:
                path.replace(bak)
            except Exception:
                pass
            doc = {"schema": "BraveRouterCache@v1", "entries": {}}
        doc.setdefault("entries", {})[key] = {
            "ts": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "results": results,
        }
        _save_json(path, doc)


def _reservation_ledger_load(root: Optional[Path]) -> dict[str, Any]:
    return _load_json(
        reservation_path(root),
        empty={"schema": "BraveRouterReservations@v1", "by_id": {}, "by_idempotency": {}},
    )


def reserve(
    *,
    caller: str,
    purpose: str,
    idempotency_key: str,
    clock: Clock,
    root: Optional[Path] = None,
    units: int = 1,
) -> Reservation:
    """Atomically reserve budget and record a reservation row.

    Fail-closed on corrupt ledger. Replay of the same idempotency_key returns
    the existing reservation without double-spending when already RESERVED/SETTLED.
    """
    now = clock()
    path = reservation_path(root)
    try:
        from scripts.lib.search_budget import try_consume, BudgetUnavailable
    except ImportError:
        from lib.search_budget import try_consume, BudgetUnavailable  # type: ignore

    with _exclusive(path):
        try:
            doc = _reservation_ledger_load(root)
        except QuotaCorrupt:
            raise

        existing_id = (doc.get("by_idempotency") or {}).get(idempotency_key)
        if existing_id:
            row = (doc.get("by_id") or {}).get(existing_id)
            if row:
                if row.get("state") in {"RESERVED", "SETTLED"}:
                    return Reservation(**{k: row[k] for k in Reservation.__dataclass_fields__})
                if row.get("state") == "REFUNDED":
                    # Prior attempt refunded — allow a new reservation under same key
                    # only after minting a new id; treat as fresh spend.
                    pass

        try:
            verdict = try_consume(PROVIDER, caller=caller, now=now, root=root)
        except BudgetUnavailable as exc:
            raise QuotaCorrupt(str(exc)) from exc
        except Exception as exc:
            raise QuotaCorrupt(f"budget unavailable: {exc}") from exc
        if not verdict.get("allowed"):
            raise BudgetRefused(str(verdict.get("reason") or "BUDGET_REFUSED"))

        rid = hashlib.sha256(
            f"{idempotency_key}|{now.isoformat()}|{caller}".encode("utf-8")
        ).hexdigest()[:32]
        res = Reservation(
            reservation_id=rid,
            caller=caller,
            purpose=purpose,
            idempotency_key=idempotency_key,
            state="RESERVED",
            reserved_at=now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            units=units,
        )
        doc.setdefault("by_id", {})[rid] = asdict(res)
        doc.setdefault("by_idempotency", {})[idempotency_key] = rid
        _save_json(path, doc)
        return res


def settle(reservation_id: str, *, clock: Clock, root: Optional[Path] = None) -> Reservation:
    now = clock()
    path = reservation_path(root)
    with _exclusive(path):
        doc = _reservation_ledger_load(root)
        row = (doc.get("by_id") or {}).get(reservation_id)
        if not row:
            raise QuotaCorrupt(f"unknown reservation {reservation_id}")
        if row["state"] == "SETTLED":
            raise DoubleSettlement(reservation_id)
        if row["state"] == "REFUNDED":
            raise DoubleSettlement(f"{reservation_id} already refunded")
        row["state"] = "SETTLED"
        row["settled_at"] = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        doc["by_id"][reservation_id] = row
        _save_json(path, doc)
        return Reservation(**{k: row[k] for k in Reservation.__dataclass_fields__})


def refund_reservation(
    reservation_id: str, *, clock: Clock, root: Optional[Path] = None
) -> Reservation:
    now = clock()
    path = reservation_path(root)
    try:
        from scripts.lib.search_budget import refund
    except ImportError:
        from lib.search_budget import refund  # type: ignore

    with _exclusive(path):
        doc = _reservation_ledger_load(root)
        row = (doc.get("by_id") or {}).get(reservation_id)
        if not row:
            raise QuotaCorrupt(f"unknown reservation {reservation_id}")
        if row["state"] == "REFUNDED":
            raise DoubleSettlement(f"{reservation_id} already refunded")
        if row["state"] == "SETTLED":
            raise DoubleSettlement(f"{reservation_id} already settled")
        ok = refund(PROVIDER, caller=row["caller"], now=now, root=root)
        if not ok:
            # Still mark refunded locally so crash-recovery does not double-refund
            # into invented credit; surface via health.
            row["refund_budget_ok"] = False
        else:
            row["refund_budget_ok"] = True
        row["state"] = "REFUNDED"
        row["refunded_at"] = now.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        doc["by_id"][reservation_id] = row
        _save_json(path, doc)
        fields = Reservation.__dataclass_fields__
        return Reservation(**{k: row.get(k) for k in fields})


def _report_provider_health(ok: bool, *, rows: Optional[int] = None, error: Optional[str] = None) -> None:
    """Record the outcome of a REAL provider call in data_source_health ('brave_search').

    Wired 2026-09-13: Brave made 163 governed calls in a month while its health row
    read 'unknown' forever, because nothing called report_source() for it. Only a
    live network call is evidence about the provider -- cache hits, budget refusals,
    a disabled router and injected test transports say nothing about Brave and are
    not reported. Never raises; never touches the caller's transaction.
    """
    try:
        try:
            from scripts.lib.data_source_report import report_source
        except ImportError:
            from lib.data_source_report import report_source  # type: ignore
        report_source("brave_search", ok, rows=rows, error=error)
    except Exception:
        pass


def _default_transport(url: str, headers: dict[str, str]) -> tuple[dict[str, Any], dict[str, str]]:
    if not live_armed():
        raise RuntimeError(
            "BRAVE_ROUTER_LIVE is not set — refusing paid/network Brave call. "
            "Inject a transport for tests/fixtures."
        )
    req = Request(url, headers=headers, method="GET")
    with urlopen(req, timeout=10) as resp:
        raw = resp.read()
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
        data = json.loads(raw)
        hdrs = {k.lower(): v for k, v in dict(resp.headers).items()}
        return data, hdrs


def _observe_capacity_historical(
    headers: dict[str, str], *, clock: Clock, root: Optional[Path]
) -> dict[str, Any]:
    """Parse provider headers and append as HISTORICAL evidence — never current proof."""
    try:
        from scripts.lib.research_provider_truth import parse_provider_capacity
    except ImportError:
        from lib.research_provider_truth import parse_provider_capacity  # type: ignore

    cap = parse_provider_capacity(PROVIDER, headers)
    record = {
        "kind": "historical_provider_header_evidence",
        "not_current_proof": True,
        "observed_at": clock().replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "capacity": cap.to_dict() if hasattr(cap, "to_dict") else dict(cap),
    }
    path = capacity_history_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    return record


def write_health(
    *,
    clock: Clock,
    root: Optional[Path] = None,
    last: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    now = clock()
    try:
        from scripts.lib.search_budget import status as budget_status
        st = budget_status(PROVIDER, now=now, root=root)
        budget_ok = True
    except Exception as exc:
        st = {"error": str(exc)}
        budget_ok = False
    doc = {
        "schema": "BraveRouterHealth@v1",
        "as_of": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "router_enabled": router_enabled(),
        "live_armed": live_armed(),
        "budget_readable": budget_ok,
        "budget_status": st,
        "local_cost_policy": local_cost_policy(),
        "last": last or {},
        "fail_closed_on_corrupt_quota": True,
    }
    try:
        _save_json(health_path(root), doc)
    except Exception:
        pass
    return doc


def search(
    query: str,
    *,
    kind: str = "web",
    count: int = 5,
    freshness: Optional[str] = None,
    caller: str = "default",
    purpose: str = "research",
    idempotency_key: Optional[str] = None,
    clock: Optional[Clock] = None,
    root: Optional[Path] = None,
    transport: Optional[Transport] = None,
    api_key: Optional[str] = None,
    enabled: Optional[bool] = None,
    cache_ttl_s: Optional[int] = None,
    no_spill: bool = False,
    spill_transport: Optional[SpillTransport] = None,
) -> RouterResponse:
    """Governed search. Cache hit → no allocation. Miss → reserve → call → settle|refund.

    A Brave denial for a reason in the registry's ``web_search.spill_on``
    (DAILY_EXHAUSTED, MONTHLY_EXHAUSTED, HTTP 429) spills to the registry's
    backup chain unless ``no_spill=True``; ``response.provider`` names who
    answered and ``response.receipt`` is the denial row written to the ledger.
    ``spill_transport`` is the test seam for the first backup slot.
    """
    clock = clock or _utc_now
    now = clock()
    policy = local_cost_policy()
    is_on = router_enabled() if enabled is None else bool(enabled)

    if not is_on:
        health = write_health(clock=clock, root=root, last={"event": "disabled"})
        return RouterResponse(
            ok=False,
            reason="ROUTER_DISABLED",
            local_cost_policy=policy,
            health=health,
        )

    ttl = cache_ttl_s if cache_ttl_s is not None else (3600 if kind == "news" else 300)
    ck = _cache_key(kind, query, freshness, count)
    cached = _read_cache(root, ck, now=now, ttl_s=ttl)
    if cached is not None:
        health = write_health(
            clock=clock, root=root,
            last={"event": "cache_hit", "query_hash": ck[:12]},
        )
        return RouterResponse(
            ok=True,
            reason="CACHE_HIT",
            results=list(cached),
            cache_hit=True,
            budget_allocated=False,
            local_cost_policy=policy,
            health=health,
        )

    idem = idempotency_key or f"{caller}|{kind}|{ck}|{now.strftime('%Y%m%d%H%M%S')}"
    try:
        res = reserve(
            caller=caller, purpose=purpose, idempotency_key=idem,
            clock=clock, root=root,
        )
    except BudgetRefused as exc:
        return _deny_or_spill(
            query, reason=str(exc), kind=kind, count=count, caller=caller,
            clock=clock, root=root, no_spill=no_spill, spill_transport=spill_transport,
            policy=policy, ck=ck,
        )
    except QuotaCorrupt as exc:
        health = write_health(clock=clock, root=root, last={"event": "quota_corrupt", "reason": str(exc)})
        return RouterResponse(
            ok=False, reason=f"QUOTA_CORRUPT:{exc}",
            local_cost_policy=policy, health=health,
        )

    key = api_key or os.environ.get("BRAVE_SEARCH_API_KEY", "")
    if not key and transport is None:
        try:
            refund_reservation(res.reservation_id, clock=clock, root=root)
        except Exception:
            pass
        return RouterResponse(
            ok=False, reason="NO_API_KEY",
            reservation_id=res.reservation_id, budget_allocated=True,
            local_cost_policy=policy,
        )

    params = {
        "q": query,
        "count": str(min(int(count), 20)),
        "search_lang": "en",
        "country": "US",
    }
    if freshness:
        params["freshness"] = freshness
    if kind == "web":
        params["text_decorations"] = "false"
        url = f"{BRAVE_WEB_URL}?{urlencode(params)}"
    else:
        url = f"{BRAVE_NEWS_URL}?{urlencode(params)}"

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": key or "fixture",
    }
    xport = transport or _default_transport
    # A real provider call happened only when no test transport was injected AND
    # the live arm is set (otherwise _default_transport refuses before the wire).
    real_call = transport is None and live_armed()
    try:
        data, resp_headers = xport(url, headers)
    except Exception as exc:
        try:
            refund_reservation(res.reservation_id, clock=clock, root=root)
        except Exception:
            pass
        if real_call:
            # Phase 3: the ledger hears about every real failure, 429 included.
            _report_provider_health(False, error=f"PROVIDER_ERROR:{exc}")
        if _is_http_429(exc):
            # The provider refused, not us — same shape as a budget denial for the
            # question's purposes, and the registry lists HTTP_429 in spill_on.
            return _deny_or_spill(
                query, reason="HTTP_429", kind=kind, count=count, caller=caller,
                clock=clock, root=root, no_spill=no_spill, spill_transport=spill_transport,
                policy=policy, reservation_id=res.reservation_id, ck=ck,
            )
        health = write_health(clock=clock, root=root, last={"event": "provider_error", "error": str(exc)})
        return RouterResponse(
            ok=False, reason=f"PROVIDER_ERROR:{exc}",
            reservation_id=res.reservation_id, budget_allocated=True,
            local_cost_policy=policy, health=health,
        )

    hist = _observe_capacity_historical(resp_headers, clock=clock, root=root)

    if kind == "news":
        raw_results = data.get("results") or []
        results = [
            {
                "title": i.get("title", ""),
                "url": i.get("url", ""),
                "description": i.get("description", ""),
                "age": i.get("age", ""),
                "source": (i.get("meta_url") or {}).get("hostname", ""),
            }
            for i in raw_results
        ]
    else:
        raw_results = (data.get("web") or {}).get("results") or []
        results = [
            {
                "title": i.get("title", ""),
                "url": i.get("url", ""),
                "description": i.get("description", ""),
                "age": i.get("age", ""),
            }
            for i in raw_results
        ]

    try:
        settle(res.reservation_id, clock=clock, root=root)
    except DoubleSettlement:
        pass

    if real_call:
        _report_provider_health(True, rows=len(results))

    _write_cache(root, ck, results, now=clock())
    health = write_health(
        clock=clock, root=root,
        last={"event": "settled", "reservation_id": res.reservation_id, "n": len(results)},
    )
    return RouterResponse(
        ok=True,
        reason="OK",
        results=results,
        cache_hit=False,
        reservation_id=res.reservation_id,
        budget_allocated=True,
        provider_capacity=hist,
        local_cost_policy=policy,
        health=health,
    )


def search_web(query: str, **kwargs: Any) -> list[dict[str, Any]]:
    """Compatibility shim used by callers migrating off brave_search.search."""
    resp = search(query, kind="web", **kwargs)
    return list(resp.results) if resp.ok else []


def search_news(query: str, **kwargs: Any) -> list[dict[str, Any]]:
    resp = search(query, kind="news", **kwargs)
    return list(resp.results) if resp.ok else []
