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


def local_cost_policy() -> dict[str, Any]:
    """Local spend policy — NOT a provider limit. Independently overridable."""
    try:
        from scripts.lib.search_budget import DEFAULT_LIMITS, CALLER_DAILY_CAPS
    except ImportError:
        from lib.search_budget import DEFAULT_LIMITS, CALLER_DAILY_CAPS  # type: ignore
    brave = dict(DEFAULT_LIMITS.get("brave", {"daily": 120, "monthly": 1500}))
    return {
        "kind": "local_cost_policy",
        "provider": PROVIDER,
        "daily": brave.get("daily"),
        "monthly": brave.get("monthly"),
        "caller_daily_caps": dict(CALLER_DAILY_CAPS),
        "note": "operator-owned cost bound; not a Brave plan ceiling",
        "invented_provider_monthly_ceiling": False,
    }


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
) -> RouterResponse:
    """Governed search. Cache hit → no allocation. Miss → reserve → call → settle|refund."""
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
        health = write_health(clock=clock, root=root, last={"event": "budget_refused", "reason": str(exc)})
        return RouterResponse(
            ok=False, reason=f"BUDGET_REFUSED:{exc}",
            local_cost_policy=policy, health=health,
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
    try:
        data, resp_headers = xport(url, headers)
    except Exception as exc:
        try:
            refund_reservation(res.reservation_id, clock=clock, root=root)
        except Exception:
            pass
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
