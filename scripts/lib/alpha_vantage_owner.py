"""alpha_vantage_owner — the single Alpha Vantage caller and its one budget.

WHY (2026-10-10)
----------------
The operator: "let's use Alpha Vantage for the gaps and prioritize which gaps that really make
sense." The free key allows 25 requests a day and 5 a minute. Before this module five places
called alphavantage.co on their own (catalyst_enrichment NEWS_SENTIMENT, external_market_data_ingest
OVERVIEW + NEWS_SENTIMENT, scalp_float_lookup OVERVIEW every 5 min, credential_monitor and
secret_validators GLOBAL_QUOTE on every key check) and only one of them consulted any budget —
a DB ledger that counted ~4,650 phantom calls a week (API_OVERLAP_CONSOLIDATION Q5). Nothing could
say how many of the 25 had been spent or by whom.

This module is the only code that sends an HTTP request to Alpha Vantage. Every caller names a
*job* from ``config/alpha_vantage_owner.json``; the owner decides, in this order:

  1. the job exists and the function is the job's own;
  2. the job's registry domain is in ``providers.alpha_vantage.supplies`` of
     ``config/data_source_authority.json`` (the operator's grant; AGENTS.md §7A rule 7) —
     otherwise ``refused_scope_not_granted``, up front, no request;
  3. the key is present (resolved by ``scripts/secrets/resolve_secret.py``; never logged);
  4. the provider has not already answered with its daily-limit notice today;
  5. the job's daily allotment and the hard cap (<= 23) both have room on BOTH the UTC day and
     the America/New_York day;
  6. the 12 s spacing slot is reachable within ``max_wait_s``.

Only then is the call counted (before it is sent — a call that fails still spent a request) and
sent. A refusal is never counted. A dry run decides everything and sends nothing and writes
nothing. Every decision leaves one receipt line.

AUTHORITY: READ_ONLY_ADVISORY. Market data only; nothing here touches a broker.
"""
from __future__ import annotations

import csv
import fcntl
import hashlib
import io
import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "config" / "alpha_vantage_owner.json"
REGISTRY_PATH = PROJECT_ROOT / "config" / "data_source_authority.json"
BASE_URL = "https://www.alphavantage.co/query"
PROVIDER = "alpha_vantage"
KEY_NAME = "ALPHA_VANTAGE_API_KEY"
ET = ZoneInfo("America/New_York")

LEDGER_SCHEMA = "AlphaVantageBudgetLedger@v1"
RECEIPT_SCHEMA = "AlphaVantageCallReceipt@v1"
CONFIG_SCHEMA = "AlphaVantageOwnerConfig@v1"

#: The free key's 25/day minus a margin of 2. A config asking for more is refused at load.
MAX_HARD_CAP = 23
#: 5 requests/minute.
MIN_SPACING_S = 12.0
#: Ledger day keys kept (older ones are dropped from the live ledger; receipts keep history).
LEDGER_DAYS_KEPT = 7


class OwnerConfigError(ValueError):
    """The owner config breaks a budget invariant; nothing may run on it."""


# ── config ───────────────────────────────────────────────────────────────────


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Read and validate the owner config. Raises OwnerConfigError on any broken invariant."""
    p = path or CONFIG_PATH
    cfg = json.loads(Path(p).read_text(encoding="utf-8"))
    validate_config(cfg)
    return cfg


def validate_config(cfg: dict[str, Any]) -> None:
    if cfg.get("schema") != CONFIG_SCHEMA:
        raise OwnerConfigError(f"schema {cfg.get('schema')!r} != {CONFIG_SCHEMA}")
    b = cfg.get("budget") or {}
    cap = int(b.get("hard_daily_cap") or 0)
    if not 0 < cap <= MAX_HARD_CAP:
        raise OwnerConfigError(f"hard_daily_cap {cap} outside 1..{MAX_HARD_CAP}")
    if float(b.get("min_spacing_s") or 0) < MIN_SPACING_S:
        raise OwnerConfigError(f"min_spacing_s below {MIN_SPACING_S}")
    jobs = cfg.get("jobs") or {}
    if not jobs:
        raise OwnerConfigError("no jobs")
    total = 0
    for name, j in jobs.items():
        a = int(j.get("daily_allotment") or 0)
        if a < 0:
            raise OwnerConfigError(f"{name}: negative allotment")
        if not j.get("function"):
            raise OwnerConfigError(f"{name}: no function")
        total += a
    if total > cap:
        raise OwnerConfigError(f"allotments sum {total} > hard_daily_cap {cap}")


# ── registry scope (the operator's grant) ────────────────────────────────────


def granted_domains(registry_path: Path | None = None) -> set[str]:
    """Domains the registry lets alpha_vantage supply. Unreadable registry -> nothing (fail closed)."""
    try:
        reg = json.loads(Path(registry_path or REGISTRY_PATH).read_text(encoding="utf-8"))
        row = (reg.get("providers") or {}).get(PROVIDER) or {}
    except (OSError, ValueError):
        return set()
    if row.get("status") not in ("active", "active_paid"):
        return set()
    appr = row.get("approval") or {}
    if not all(str(appr.get(k) or "").strip() for k in ("approved_by", "approved_on", "reference", "scope")):
        return set()
    return {str(d) for d in (row.get("supplies") or [])}


# ── time ─────────────────────────────────────────────────────────────────────


def day_keys(now: datetime) -> tuple[str, str]:
    """(UTC day, ET day) for one instant — a call counts against both."""
    u = now.astimezone(timezone.utc)
    return u.strftime("%Y-%m-%d"), now.astimezone(ET).strftime("%Y-%m-%d")


def _iso(now: datetime) -> str:
    return now.astimezone(timezone.utc).isoformat()


# ── response classification ──────────────────────────────────────────────────


def classify(status_code: int, text: str) -> tuple[str, Any]:
    """(outcome, payload). Alpha Vantage answers limits and errors with HTTP 200.

    outcome: ok | quota_notice | burst_notice | key_rejected | information_notice | error_message |
             notice_in_csv | http_error | empty
    """
    if status_code != 200:
        return "http_error", None
    body = (text or "").strip()
    if not body or body == "{}":
        return "empty", None
    if body.startswith("{") or body.startswith("["):
        try:
            data = json.loads(body)
        except ValueError:
            return "error_message", None
        if isinstance(data, dict):
            notice = str(data.get("Information") or data.get("Note") or "")
            low = notice.lower()
            if notice:
                if "per second" in low or "spreading out" in low:
                    return "burst_notice", data
                if "api key" in low and ("invalid" in low or "claim your free" in low):
                    return "key_rejected", data
                if "per day" in low or "rate limit" in low or "requests per" in low:
                    return "quota_notice", data
                # e.g. "This is a premium endpoint": a refusal, but not the daily limit.
                return "information_notice", data
            if "Error Message" in data:
                msg = str(data["Error Message"]).lower()
                return ("key_rejected" if "apikey" in msg or "api key" in msg else "error_message"), data
        return "ok", data
    # CSV endpoints (EARNINGS_CALENDAR, IPO_CALENDAR, LISTING_STATUS).
    rows = list(csv.reader(io.StringIO(body)))
    if len(rows) < 2:
        return "empty", rows
    header = rows[0]
    # A notice on a CSV endpoint arrives as the header followed by the notice text split one
    # character per column ("I,n,f,o,r,m,a" — observed 2026-10-10 on the documented demo URL).
    first = rows[1]
    if len(first) == len(header) and all(len(c) <= 1 for c in first):
        return "notice_in_csv", rows
    return "ok", rows


# ── the ledger ───────────────────────────────────────────────────────────────


def _empty_ledger() -> dict[str, Any]:
    return {"schema": LEDGER_SCHEMA, "days": {}, "last_request_ts": None,
            "last_success": None, "last_failure": None, "provider_exhausted_days": []}


@dataclass
class OwnerResult:
    ok: bool
    outcome: str                      # ok | refused_* | dry_run_would_call | <classify outcome> | network_error
    job: str
    function: str
    payload: Any = None
    http_status: Optional[int] = None
    counted: bool = False
    detail: str = ""
    receipt: dict[str, Any] = field(default_factory=dict)


def _default_http(params: dict[str, Any], timeout: float) -> tuple[int, str]:
    import requests  # lazy: tests inject a transport and never import requests here
    r = requests.get(BASE_URL, params=params, timeout=timeout, headers={"User-Agent": "TradeAI/1.0"})
    return r.status_code, r.text


def _default_key() -> str:
    import sys
    sec = PROJECT_ROOT / "scripts" / "secrets"
    if str(sec) not in sys.path:
        sys.path.insert(0, str(sec))
    try:
        from resolve_secret import resolve_secret  # the single secret path (tmpfs SM -> env -> .env)
        return (resolve_secret(KEY_NAME, "") or "").strip()
    except Exception:  # noqa: BLE001 — a resolver failure is "no key", never a crash
        return (os.environ.get(KEY_NAME) or "").strip()


def state_dir() -> Path:
    env = (os.environ.get("TRADEAI_AV_OWNER_DIR") or "").strip()
    return Path(env) if env else PROJECT_ROOT / "data" / "runtime" / "alpha_vantage"


class AlphaVantageOwner:
    """The one Alpha Vantage gateway. Inject ``http``/``key_loader``/``clock``/``sleeper`` in tests."""

    def __init__(self, *, config: dict[str, Any] | None = None, state: Path | None = None,
                 http: Callable[[dict[str, Any], float], tuple[int, str]] | None = None,
                 key_loader: Callable[[], str] | None = None,
                 clock: Callable[[], datetime] | None = None,
                 sleeper: Callable[[float], None] | None = None,
                 registry_path: Path | None = None, dry_run: bool = False,
                 report: Callable[..., None] | None = None, timeout: float = 30.0,
                 scope_override: set[str] | None = None):
        if scope_override is not None and not dry_run:
            raise ValueError("scope_override is a dry-run preview only; a live call needs the registry grant")
        self.scope_override = scope_override
        self.cfg = config if config is not None else load_config()
        validate_config(self.cfg)
        self.state = Path(state) if state is not None else state_dir()
        self._http = http or _default_http
        self._key_loader = key_loader or _default_key
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._sleep = sleeper or time.sleep
        self.registry_path = registry_path
        self.dry_run = bool(dry_run)
        self._report = report
        self.timeout = timeout
        self.requests_sent = 0

    # paths
    @property
    def ledger_path(self) -> Path:
        return self.state / "budget_ledger.json"

    def receipts_path(self, now: datetime) -> Path:
        return self.state / f"receipts_{now.astimezone(timezone.utc).strftime('%Y%m')}.jsonl"

    # ledger io
    def read_ledger(self) -> dict[str, Any]:
        try:
            led = json.loads(self.ledger_path.read_text(encoding="utf-8"))
            if led.get("schema") == LEDGER_SCHEMA:
                return led
        except (OSError, ValueError):
            pass
        return _empty_ledger()

    def _write_ledger(self, led: dict[str, Any]) -> None:
        self.state.mkdir(parents=True, exist_ok=True)
        keep = sorted(led.get("days", {}))[-LEDGER_DAYS_KEPT * 2:]
        led["days"] = {k: led["days"][k] for k in keep}
        led["provider_exhausted_days"] = sorted(set(led.get("provider_exhausted_days") or []))[-LEDGER_DAYS_KEPT:]
        tmp = self.ledger_path.with_name(f".{self.ledger_path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(led, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self.ledger_path)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        if self.dry_run:
            yield  # a dry run creates nothing, not even the lock file
            return
        self.state.mkdir(parents=True, exist_ok=True)
        with open(self.state / ".budget_ledger.lock", "a+") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def ledger_sha256(self) -> str | None:
        try:
            return hashlib.sha256(self.ledger_path.read_bytes()).hexdigest()
        except OSError:
            return None

    # receipts
    def _receipt(self, now: datetime, res: OwnerResult, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        rec = {"schema": RECEIPT_SCHEMA, "at": _iso(now), "job": res.job, "function": res.function,
               "outcome": res.outcome, "counted": res.counted, "http_status": res.http_status,
               "dry_run": self.dry_run, "detail": res.detail[:300]}
        if extra:
            rec.update(extra)
        res.receipt = rec
        if not self.dry_run:
            self.state.mkdir(parents=True, exist_ok=True)
            with self.receipts_path(now).open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, sort_keys=True) + "\n")
        return rec

    # decisions
    def job_spec(self, job: str) -> dict[str, Any] | None:
        return (self.cfg.get("jobs") or {}).get(job)

    def remaining(self, job: str, led: dict[str, Any] | None = None, now: datetime | None = None) -> dict[str, int]:
        led = led or self.read_ledger()
        now = now or self._clock()
        cap = int(self.cfg["budget"]["hard_daily_cap"])
        allot = int((self.job_spec(job) or {}).get("daily_allotment") or 0)
        out_total, out_job = cap, allot
        for d in day_keys(now):
            day = (led.get("days") or {}).get(d) or {}
            out_total = min(out_total, cap - int(day.get("total") or 0))
            out_job = min(out_job, allot - int((day.get("jobs") or {}).get(job) or 0))
        return {"total": max(0, out_total), "job": max(0, out_job)}

    def _scrub(self, s: Any, key: str) -> str:
        text = str(s)
        return text.replace(key, "<KEY>") if key else text

    def request(self, job: str, params: dict[str, Any] | None = None) -> OwnerResult:
        """Decide, count, send and classify one Alpha Vantage call for ``job``."""
        now = self._clock()
        spec = self.job_spec(job)
        params = dict(params or {})
        fn = str(params.pop("function", "") or (spec or {}).get("function") or "")
        if spec is None:
            res = OwnerResult(False, "refused_unknown_job", job, fn, detail="job not in config/alpha_vantage_owner.json")
            self._receipt(now, res)
            return res
        if fn != spec["function"]:
            res = OwnerResult(False, "refused_wrong_function", job, fn, detail=f"job {job} may call {spec['function']} only")
            self._receipt(now, res)
            return res
        if spec.get("class") == "disabled" or int(spec.get("daily_allotment") or 0) <= 0:
            res = OwnerResult(False, "refused_job_disabled", job, fn, detail=spec.get("why", "")[:200])
            self._receipt(now, res)
            return res
        dom = spec.get("domain")
        granted = self.scope_override if self.scope_override is not None else granted_domains(self.registry_path)
        if dom and dom not in granted:
            res = OwnerResult(False, "refused_scope_not_granted", job, fn,
                              detail=f"registry providers.alpha_vantage.supplies lacks '{dom}' — operator grant pending (AGENTS.md §7A, §17)")
            self._receipt(now, res)
            return res
        key = self._key_loader() or ""
        if not key:
            res = OwnerResult(False, "refused_no_key", job, fn, detail=f"{KEY_NAME} not set")
            self._receipt(now, res)
            return res

        b = self.cfg["budget"]
        spacing = max(MIN_SPACING_S, float(b.get("min_spacing_s") or MIN_SPACING_S))
        max_wait = float(b.get("max_wait_s") or 30)
        with self._locked():
            led = self.read_ledger()
            u_day, e_day = day_keys(now)
            if u_day in led.get("provider_exhausted_days", []) or e_day in led.get("provider_exhausted_days", []):
                res = OwnerResult(False, "refused_provider_exhausted", job, fn,
                                  detail="the provider returned its daily-limit notice today; no further calls")
                self._receipt(now, res)
                return res
            rem = self.remaining(job, led, now)
            if rem["job"] <= 0:
                res = OwnerResult(False, "refused_job_allotment_spent", job, fn,
                                  detail=f"daily_allotment {spec['daily_allotment']} spent")
                self._receipt(now, res, {"remaining": rem})
                return res
            if rem["total"] <= 0:
                res = OwnerResult(False, "refused_hard_cap", job, fn,
                                  detail=f"hard_daily_cap {b['hard_daily_cap']} spent")
                self._receipt(now, res, {"remaining": rem})
                return res
            last = led.get("last_request_ts")
            wait = max(0.0, (float(last) + spacing) - now.timestamp()) if last else 0.0
            if wait > max_wait:
                res = OwnerResult(False, "refused_spacing_wait_exceeded", job, fn,
                                  detail=f"next slot in {wait:.1f}s > max_wait_s {max_wait}")
                self._receipt(now, res)
                return res
            if self.dry_run:
                res = OwnerResult(True, "dry_run_would_call", job, fn,
                                  detail=f"would wait {wait:.1f}s then send {fn}")
                self._receipt(now, res, {"remaining": rem, "params": {k: v for k, v in params.items()},
                                         "would_wait_s": round(wait, 1)})
                return res
            if wait > 0:
                self._sleep(wait)
                now = self._clock()
                u_day, e_day = day_keys(now)
            # Count BEFORE sending: a request that times out still spent one of the 25.
            for d in {u_day, e_day}:
                day = led.setdefault("days", {}).setdefault(d, {"total": 0, "jobs": {}})
                day["total"] = int(day.get("total") or 0) + 1
                day["jobs"][job] = int(day["jobs"].get(job) or 0) + 1
            led["last_request_ts"] = now.timestamp()
            self._write_ledger(led)

        sent_params = {"function": fn, **params, "apikey": key}
        try:
            status, text = self._http(sent_params, self.timeout)
            self.requests_sent += 1
        except Exception as exc:  # noqa: BLE001 — requests errors embed the URL (and the key): scrub
            self.requests_sent += 1
            res = OwnerResult(False, "network_error", job, fn, counted=True,
                              detail=f"{type(exc).__name__}: {self._scrub(exc, key)[:200]}")
            self._finish(now, res, key)
            return res
        outcome, payload = classify(status, text)
        res = OwnerResult(outcome == "ok", outcome, job, fn, payload=payload, http_status=status, counted=True)
        if outcome != "ok":
            notice = payload.get("Information") or payload.get("Note") or payload.get("Error Message") \
                if isinstance(payload, dict) else ""
            res.detail = self._scrub(notice or outcome, key)[:300]
        self._finish(now, res, key)
        return res

    def _finish(self, now: datetime, res: OwnerResult, key: str) -> None:
        with self._locked():
            led = self.read_ledger()
            mark = {"at": _iso(now), "job": res.job, "function": res.function,
                    "outcome": res.outcome, "http_status": res.http_status}
            if res.ok:
                led["last_success"] = mark
            else:
                led["last_failure"] = dict(mark, detail=res.detail[:200])
            if res.outcome == "quota_notice":
                led.setdefault("provider_exhausted_days", []).extend(day_keys(now))
            self._write_ledger(led)
        self._receipt(now, res)
        rep = self._report
        if rep is None:
            try:
                from lib.data_source_report import report_source as rep  # type: ignore
            except Exception:  # noqa: BLE001
                rep = None
        if rep is not None:
            try:
                rep(PROVIDER, res.ok, rows=None, error=None if res.ok else f"{res.outcome}: {res.detail[:120]}")
            except Exception:  # noqa: BLE001 — liveness reporting never breaks a call
                pass

    # status (no request)
    def key_status(self, now: datetime | None = None) -> dict[str, Any]:
        """Key health from the owner's own last calls. Spends nothing."""
        now = now or self._clock()
        led = self.read_ledger()
        fresh_h = float(self.cfg.get("key_check_fresh_hours") or 36)
        out: dict[str, Any] = {"key_present": bool(self._key_loader()), "last_success": led.get("last_success"),
                               "last_failure": led.get("last_failure"), "fresh_hours": fresh_h}
        ls = led.get("last_success") or {}
        lf = led.get("last_failure") or {}
        try:
            age = (now - datetime.fromisoformat(ls["at"])).total_seconds() / 3600 if ls.get("at") else None
        except (KeyError, ValueError):
            age = None
        out["last_success_age_hours"] = round(age, 2) if age is not None else None
        if not out["key_present"]:
            out["status"] = "missing"
        elif lf.get("outcome") == "key_rejected" and (not ls.get("at") or lf.get("at", "") > ls.get("at", "")):
            out["status"] = "rejected"
        elif age is not None and age <= fresh_h:
            out["status"] = "ok"
        else:
            out["status"] = "unknown"
        return out

    def budget_status(self, now: datetime | None = None) -> dict[str, Any]:
        now = now or self._clock()
        led = self.read_ledger()
        u_day, e_day = day_keys(now)
        return {"hard_daily_cap": self.cfg["budget"]["hard_daily_cap"], "utc_day": u_day, "et_day": e_day,
                "spent": {d: (led.get("days") or {}).get(d, {"total": 0, "jobs": {}}) for d in (u_day, e_day)},
                "remaining": {j: self.remaining(j, led, now) for j in self.cfg["jobs"]},
                "provider_exhausted_today": any(d in (led.get("provider_exhausted_days") or []) for d in (u_day, e_day)),
                "granted_domains": sorted(granted_domains(self.registry_path))}


def validate_key_via_owner(owner: AlphaVantageOwner | None = None) -> tuple[Optional[bool], str]:
    """For key checkers: the owner's last success first; one GLOBAL_QUOTE from the key_check reserve
    only when the owner has no success inside key_check_fresh_hours. Never shows the key."""
    o = owner or AlphaVantageOwner()
    ks = o.key_status()
    if ks["status"] == "missing":
        return False, f"{KEY_NAME} not set"
    if ks["status"] == "ok":
        return True, f"owner last success {ks['last_success']['at']} ({ks['last_success_age_hours']} h ago; no request spent)"
    if ks["status"] == "rejected":
        return False, f"rejected by provider at {ks['last_failure']['at']} (owner ledger; no request spent)"
    res = o.request("key_check", dict((o.job_spec("key_check") or {}).get("params") or {}))
    if res.outcome.startswith("refused_"):
        return None, f"no recent owner success and the key_check reserve refused ({res.outcome}) — unknown, no request spent"
    if res.ok:
        return True, f"HTTP {res.http_status} via owner key_check (1 of the reserve)"
    if res.outcome in ("quota_notice", "burst_notice"):
        return True, f"key recognised; provider limit notice ({res.outcome})"
    return False, f"{res.outcome} (HTTP {res.http_status})"
