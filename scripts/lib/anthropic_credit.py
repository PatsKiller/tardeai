"""Durable promotional-credit authorization, separate from provider spend metering.

The append-only journal contains amounts and opaque request identities only. A
partial/corrupt journal refuses dispatch. Unsettled amounts are never released from
the TOTAL cap merely because a worker stopped or a response timed out; they count
toward the UTC daily pace only on the UTC day they were reserved so a few ambiguous attempts cannot
pause the promotion for good.

Accounting failures (``accounting_unavailable`` / ``over_reservation``) make the
book UNAVAILABLE only for ``unavailable_cooldown_minutes``. A billing error is
EXHAUSTED until the operator appends an ``operator_reset`` event
(``scripts/anthropic_credit_reset.py``); the file is never edited in place.
Rows of an earlier ``promotion_id`` stay in the verified hash chain and are simply
not counted, so changing the promotion never makes the journal unreadable.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_DOWN, Decimal, InvalidOperation
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

try:
    from . import jsonl_tail
except ImportError:  # pragma: no cover - flat import layout
    import jsonl_tail  # type: ignore[no-redef] -- flat import layout (served scripts/ path), the package import is tried first


SCHEMA = "AnthropicCreditAuthorization@v1"
JOURNAL_REL = "data/runtime/provider_cost/anthropic_credit.jsonl"
TRANSIENT_FAILURES = frozenset({"accounting_unavailable", "over_reservation"})
RESET_SCOPES = frozenset({"billing_error", "unavailable", "all"})
DEFAULT_UNAVAILABLE_COOLDOWN_MINUTES = 30
MAX_UNAVAILABLE_COOLDOWN_MINUTES = 1440
# Operator 2026-11-02: emergency incident clearing may raise a per-process cap
# ONLY on the cheap tiers. No other tier may appear in an override.
CHEAP_TIERS = frozenset({"bulk", "mid"})
OPUS_FABLE_TIERS = frozenset({"standard", "high", "highest", "long_form", "premium"})
# LQ-20261107-196 (DSN-20261107-ANTHROPIC-FIRST-ROUTING §3A): per-tier daily sub-caps so Opus cannot eat the
# day. Every Opus/Fable tier shares the "standard" bucket; a share is a fraction of the UTC-day cap in force.
TIER_BUCKETS = frozenset({"bulk", "mid", "standard"})
TIER_CAP_REFUSAL = "ANTHROPIC_CREDIT_TIER_CAP"
# Monthly renewal: the daily cap is the monthly credit spread over 30 days.
MONTHLY_PACING_DAYS = 30


def tier_bucket(tier: Any) -> str | None:
    """The sub-cap bucket a credit tier spends from, or None for a tier outside every bucket."""
    if tier in CHEAP_TIERS:
        return str(tier)
    if tier in OPUS_FABLE_TIERS:
        return "standard"
    return None


class CreditDenied(RuntimeError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def amount(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CreditDenied("CREDIT_CONFIGURATION_INVALID") from exc
    if not result.is_finite() or result < 0:
        raise CreditDenied("CREDIT_CONFIGURATION_INVALID")
    return result


def money(value: Decimal) -> str:
    text = format(value, "f")
    if "." not in text:
        return text + ".00"
    return text + "0" if len(text.rsplit(".", 1)[1]) == 1 else text


def caller_identity(process_id: Any) -> tuple[str, str]:
    """The logical process id plus a stable OS process name for a reserve row.

    A caller that omits ``process_id`` no longer writes null (which made the row
    unattributable AND made the verified journal unreadable on the next read). It
    gets the loud sentinel ``unknown:<pid>`` instead of a hard refusal: the credit
    lane must stay usable during an incident, and the pid + entrypoint name are
    still actionable. No environment, credential or prompt content is read.
    """
    pid = os.getpid()
    if isinstance(process_id, str) and process_id.strip():
        name_id = process_id.strip()
    else:
        name_id = f"unknown:{pid}"
    try:
        entrypoint = os.path.basename(sys.argv[0] or "") if sys.argv else ""
    except (AttributeError, IndexError, TypeError):
        entrypoint = ""
    process_name = "".join(ch for ch in str(entrypoint) if ch.isalnum() or ch in "._-")[:80] or "unknown"
    return name_id, process_name


def _emergency_caps(raw: Any, models: dict[str, Any]) -> dict[str, dict[str, Decimal]]:
    """Per-process emergency cap overrides from the credit policy.

    Shape: ``{"per_process": {"<process_id>": {"bulk": "3.00", "mid": "3.00"}}}``.
    Only the cheap tiers may be raised; a premium tier or a cheap tier remapped to
    an Opus/Fable model invalidates the whole policy rather than silently widening
    the credit authority.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise CreditDenied("CREDIT_CONFIGURATION_INVALID")
    rows = raw.get("per_process")
    if not isinstance(rows, dict):
        raise CreditDenied("CREDIT_CONFIGURATION_INVALID")
    premium_models = {models.get(tier) for tier in OPUS_FABLE_TIERS if models.get(tier)}
    result: dict[str, dict[str, Decimal]] = {}
    for process_id, tiers in rows.items():
        if not isinstance(process_id, str) or not process_id.strip() or not isinstance(tiers, dict) or not tiers:
            raise CreditDenied("CREDIT_CONFIGURATION_INVALID")
        parsed: dict[str, Decimal] = {}
        for tier, usd in tiers.items():
            if tier not in CHEAP_TIERS:
                raise CreditDenied("CREDIT_CONFIGURATION_INVALID")
            if models.get(tier) in premium_models:
                raise CreditDenied("CREDIT_CONFIGURATION_INVALID")
            cap = amount(usd)
            if cap <= 0:
                raise CreditDenied("CREDIT_CONFIGURATION_INVALID")
            parsed[tier] = cap
        result[process_id.strip()] = parsed
    return result


def utc(value: datetime | str) -> datetime:
    if not isinstance(value, (datetime, str)):
        raise CreditDenied("CREDIT_CLOCK_INVALID")
    try:
        dt = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError("timezone required")
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError) as exc:
        raise CreditDenied("CREDIT_CLOCK_INVALID") from exc


def _daily_overrides(raw: Any) -> list[tuple[date, date, Decimal]]:
    """Temporary UTC-day cap overrides: ``[{"usd", "from", "until"}]``; ``until`` is exclusive."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise CreditDenied("CREDIT_CONFIGURATION_INVALID")
    result = []
    for row in raw:
        if not isinstance(row, dict):
            raise CreditDenied("CREDIT_CONFIGURATION_INVALID")
        try:
            start, until = date.fromisoformat(str(row["from"])), date.fromisoformat(str(row["until"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise CreditDenied("CREDIT_CONFIGURATION_INVALID") from exc
        usd = amount(row.get("usd"))
        if usd <= 0 or until <= start:
            raise CreditDenied("CREDIT_CONFIGURATION_INVALID")
        result.append((start, until, usd))
    return result


def _renewal(raw: Any) -> dict[str, Any]:
    """``one_time`` (default): one total cap for the promotion. ``monthly``: a fresh
    allowance each UTC month; the journal keeps every period, only the current period
    counts toward the total.

    Two monthly shapes are read:

    * ``monthly_credit_usd`` + ``period_start`` (LQ-20261107-196, the operator's renewing
      credit): total = the monthly credit, daily cap = monthly / 30 (rounded down to the cent,
      ``daily_cap_usd`` is not used), periods run from ``period_start`` to the same day each
      month, and nothing is admitted before ``period_start``.
    * ``monthly_allowance_usd`` + ``renews_on_day`` (2026-10-26 shape): total = the allowance,
      ``daily_cap_usd`` still paces the day.

    Naming both amounts, or a ``renews_on_day`` that disagrees with ``period_start``, is ambiguous
    and refuses the configuration rather than guessing which one the operator meant.
    """
    if raw is None:
        return {"mode": "one_time", "monthly_allowance_usd": None, "renews_on_day": None,
                "period_start": None, "daily_from_monthly": False}
    if not isinstance(raw, dict) or raw.get("mode") not in {"one_time", "monthly"}:
        raise CreditDenied("CREDIT_CONFIGURATION_INVALID")
    day = raw.get("renews_on_day")
    if day is not None and (isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= 28):
        raise CreditDenied("CREDIT_CONFIGURATION_INVALID")
    credit = raw.get("monthly_credit_usd")
    allowance = raw.get("monthly_allowance_usd")
    if raw["mode"] == "monthly" and credit is not None and allowance is not None:
        raise CreditDenied("CREDIT_CONFIGURATION_INVALID")
    start = raw.get("period_start")
    anchor = None
    if start is not None:
        try:
            anchor = date.fromisoformat(str(start))
        except ValueError as exc:
            raise CreditDenied("CREDIT_CONFIGURATION_INVALID") from exc
        # Day 29-31 does not exist every month; the period must start on the same day each month.
        if anchor.day > 28 or (day is not None and day != anchor.day):
            raise CreditDenied("CREDIT_CONFIGURATION_INVALID")
        day = anchor.day
    monthly = credit if credit is not None else allowance
    if raw["mode"] == "monthly" and (monthly is None or amount(monthly) <= 0):
        raise CreditDenied("CREDIT_CONFIGURATION_INVALID")
    return {"mode": raw["mode"], "monthly_allowance_usd": monthly, "renews_on_day": day,
            "period_start": anchor, "daily_from_monthly": credit is not None}


def _tier_shares(raw: Any) -> dict[str, Decimal]:
    """``{"bulk": "0.40", "mid": "0.45", "standard": "0.15"}``: each bucket's share of the UTC-day cap.

    Absent means no sub-caps. Unknown buckets, a share outside (0, 1] or shares summing above 1
    refuse the whole policy instead of silently dropping a cap.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict) or not raw:
        raise CreditDenied("CREDIT_CONFIGURATION_INVALID")
    shares: dict[str, Decimal] = {}
    for bucket, value in raw.items():
        share = amount(value)
        if bucket not in TIER_BUCKETS or not 0 < share <= 1:
            raise CreditDenied("CREDIT_CONFIGURATION_INVALID")
        shares[bucket] = share
    if sum(shares.values(), Decimal(0)) > 1:
        raise CreditDenied("CREDIT_CONFIGURATION_INVALID")
    return shares


class CreditBook:
    def __init__(self, root: Path, policy: dict[str, Any]):
        try:
            self.root = Path(root)
            self.path = self.root / JOURNAL_REL
            self.policy = dict(policy)
            self.promotion = policy["promotion_id"]
            self.total = amount(policy["total_cap_usd"])
            self.daily = amount(policy["daily_cap_usd"])
            self.credit = amount(policy["credit_usd"])
            self.start, self.expiry = utc(policy["starts_at"]), utc(policy["expires_at"])
            self.overrides = _daily_overrides(policy.get("daily_cap_overrides"))
            self.renewal = _renewal(policy.get("renewal"))
            if self.renewal["mode"] == "monthly":
                self.total = amount(self.renewal["monthly_allowance_usd"])
                if self.renewal["daily_from_monthly"]:
                    self.daily = (self.total / MONTHLY_PACING_DAYS).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
                anchor = self.renewal["period_start"]
                if anchor is not None:
                    self.start = max(self.start, datetime(anchor.year, anchor.month, anchor.day, tzinfo=timezone.utc))
            self.tier_shares = _tier_shares(policy.get("tier_daily_cap_shares"))
            caps = policy["per_call_caps_usd"]
            if (not isinstance(self.promotion, str) or not self.promotion.strip()
                    or not isinstance(caps, dict) or not caps
                    or any(not isinstance(tier, str) or amount(cap) <= 0 for tier, cap in caps.items())
                    or not (0 < self.total and 0 < self.daily and self.start < self.expiry)
                    or (self.renewal["mode"] == "one_time" and self.total > self.credit)):
                raise CreditDenied("CREDIT_CONFIGURATION_INVALID")
            self.emergency_caps = _emergency_caps(
                policy.get("emergency_process_caps"), policy.get("models") or {})
        except (CreditDenied, KeyError, TypeError, ValueError, OverflowError) as exc:
            raise CreditDenied("CREDIT_CONFIGURATION_INVALID") from exc

    @contextmanager
    def _locked(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.with_suffix(".lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                self._archive_torn_tail()
                yield
        except CreditDenied:
            raise
        except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
            raise CreditDenied("CREDIT_UNAVAILABLE") from exc

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        previous = ""
        try:
            raw = self.path.read_bytes()
            tail = jsonl_tail.truncated_tail(raw)
            if tail is not None:
                # A half-written LAST record (disk full mid-write; LQ-20261107-307: 21 bytes torn at
                # 2026-11-03T14:00:31Z kept the lane off for four days). Only the final, unterminated,
                # unparseable segment is skipped; every complete row above it is still chain-verified, and
                # any damage ABOVE the last line still fails closed below. Skipping it never under-counts
                # spend: a torn row is a write that raised. A torn reserve was refused (the call is made only
                # after reserve() returns); a torn settle/uncertain leaves its reserve open, still holding the
                # full projected amount. A torn failure/fallback/operator_reset loses that one marker, the
                # same as if the write had failed cleanly.
                # The next writer archives the bytes beside the journal (_archive_torn_tail).
                jsonl_tail.report(
                    self.path,
                    len(tail[1]),
                    action="torn final record skipped by readers; the next credit write archives it",
                )
                raw = raw[: tail[0]]
            for line in raw.decode("utf-8").splitlines(keepends=True):
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise CreditDenied("CREDIT_UNAVAILABLE")
                checksum = row.pop("checksum")
                expected = hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                # Every row (any promotion) is chain-verified; only this
                # promotion's rows are counted (see _own).
                if (checksum != expected or row["previous"] != previous
                        or row["schema"] != SCHEMA or not isinstance(row.get("promotion_id"), str)
                        or row["sequence"] != len(rows) + 1):
                    raise CreditDenied("CREDIT_UNAVAILABLE")
                if (not isinstance(row.get("event"), str)
                        or not isinstance(row.get("at"), str)
                        or not isinstance(row.get("sequence"), int)
                        or isinstance(row["sequence"], bool)):
                    raise CreditDenied("CREDIT_UNAVAILABLE")
                try:
                    utc(row["at"])
                    event = row["event"]
                    if event in {"reserve", "settle", "uncertain", "batch", "batch_collection_started", "batch_collected"}:
                        if not isinstance(row.get("request"), str) or not row["request"]:
                            raise CreditDenied("CREDIT_UNAVAILABLE")
                    if event == "reserve":
                        amount(row["projected"])
                        if not isinstance(row.get("process"), str) or not isinstance(row.get("tier"), str):
                            raise CreditDenied("CREDIT_UNAVAILABLE")
                    if event in {"batch", "batch_collection_started", "batch_collected"}:
                        if not isinstance(row.get("batch_id"), str):
                            raise CreditDenied("CREDIT_UNAVAILABLE")
                    if event == "batch":
                        if (not isinstance(row.get("model"), str) or not isinstance(row.get("process_id"), str)
                                or not isinstance(row.get("ambiguous"), bool)):
                            raise CreditDenied("CREDIT_UNAVAILABLE")
                    if event in {"settle", "batch_collected"}:
                        amount(row["actual"])
                    if event in {"failure", "fallback"} and not isinstance(row.get("reason"), str):
                        raise CreditDenied("CREDIT_UNAVAILABLE")
                    if event == "operator_reset" and row.get("scope") not in RESET_SCOPES:
                        raise CreditDenied("CREDIT_UNAVAILABLE")
                except CreditDenied as exc:
                    raise CreditDenied("CREDIT_UNAVAILABLE") from exc
                previous = checksum
                row["checksum"] = checksum
                rows.append(row)
        except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
            raise CreditDenied("CREDIT_UNAVAILABLE") from exc
        return rows

    def _append(self, rows: list[dict[str, Any]], event: str, now: datetime, **fields: Any) -> None:
        row = {"schema": SCHEMA, "promotion_id": self.promotion,
               "sequence": len(rows) + 1, "previous": rows[-1]["checksum"] if rows else "",
               "event": event, "at": utc(now).isoformat(), **fields}
        row["checksum"] = hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        payload = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            # Every writer holds the flock (_locked), so the size cannot move under us.
            start = os.fstat(fd).st_size
            try:
                offset = 0
                while offset < len(payload):
                    written = os.write(fd, payload[offset:])
                    if written <= 0:
                        raise CreditDenied("CREDIT_UNAVAILABLE")
                    offset += written
                os.fsync(fd)
            except BaseException:
                # A partial row (ENOSPC mid-write) is cut back to the last whole row, so the journal is never
                # left torn by this writer. If even the cut fails, readers skip the torn tail and the next
                # writer archives it (_archive_torn_tail). The caller still sees the failure.
                try:
                    os.ftruncate(fd, start)
                    os.fsync(fd)
                except OSError:
                    pass
                raise
        finally:
            os.close(fd)

    def _archive_torn_tail(self) -> None:
        """Under the write lock: move a torn final record beside the journal before anything is appended.

        Without this the next row would be glued onto the fragment and the damage would move ABOVE the last
        line, where readers (rightly) fail closed for good. Archive, never delete: the bytes go to a unique
        ``anthropic_credit.jsonl.corrupt-tail-<epoch>`` (scripts/lib/jsonl_tail.py), the same rule
        persistent_wake_store applies.
        """
        if not self.path.exists():
            return
        tail = jsonl_tail.truncated_tail(self.path.read_bytes())
        if tail is not None:
            archive = jsonl_tail.quarantine_tail(self.path, *tail)
            jsonl_tail.report(self.path, len(tail[1]), action=f"torn final record archived to {archive.name}")

    def _own(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [row for row in rows if row.get("promotion_id") == self.promotion]

    def daily_cap(self, now: datetime) -> Decimal:
        """The UTC-day cap in force at ``now``: an active override, else the base cap."""
        day = utc(now).date()
        active = [usd for start, until, usd in self.overrides if start <= day < until]
        return active[-1] if active else self.daily

    def period_start(self, now: datetime) -> datetime | None:
        """Start of the current monthly renewal period, or None for a one-time credit."""
        if self.renewal["mode"] != "monthly":
            return None
        now = utc(now)
        day = self.renewal["renews_on_day"] or 1
        start = now.replace(day=day, hour=0, minute=0, second=0, microsecond=0)
        if start > now:
            month, year = (now.month - 1, now.year) if now.month > 1 else (12, now.year - 1)
            start = start.replace(year=year, month=month)
        return start

    def _minutes(self, key: str, default: int) -> float:
        try:
            value = amount(self.policy.get(key, default))
        except CreditDenied:
            value = Decimal(default)
        return float(min(Decimal(MAX_UNAVAILABLE_COOLDOWN_MINUTES), value))

    def _requests(self, rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        requests: dict[str, dict[str, Any]] = {}
        for row in self._own(rows):
            event = row["event"]
            if event == "reserve":
                if row["request"] in requests:
                    raise CreditDenied("CREDIT_UNAVAILABLE")
                requests[row["request"]] = dict(row, status="reserved")
            elif event in {"settle", "uncertain"}:
                request = requests.get(row["request"])
                if request is None:
                    raise CreditDenied("CREDIT_UNAVAILABLE")
                if event == "settle":
                    request.update(status="settled", actual=row["actual"], settled_at=row["at"])
                else:
                    request["status"] = "uncertain"
        return requests

    @staticmethod
    def _counts_today(request: dict[str, Any], now: datetime) -> bool:
        """A settled call paces the UTC day it settled on; an open hold the day it was reserved."""
        stamp = request["settled_at"] if request["status"] == "settled" else request["at"]
        return utc(stamp).date() == utc(now).date()

    def tier_caps(self, now: datetime) -> dict[str, Decimal]:
        """Each bucket's UTC-day sub-cap at ``now`` (shares of the cap in force, overrides included)."""
        daily = self.daily_cap(now)
        return {bucket: (daily * share).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
                for bucket, share in self.tier_shares.items()}

    def _tier_used_today(self, requests: dict[str, dict[str, Any]], now: datetime) -> dict[str, Decimal]:
        used = {bucket: Decimal(0) for bucket in self.tier_shares}
        for request in requests.values():
            bucket = tier_bucket(request.get("tier"))
            if bucket in used and self._counts_today(request, now):
                used[bucket] += amount(request.get("actual", request["projected"]))
        return used

    def _resets(self, rows: list[dict[str, Any]], scope: str) -> int:
        latest = 0
        for row in self._own(rows):
            if row["event"] == "operator_reset" and row.get("scope") in {scope, "all"}:
                latest = row["sequence"]
        return latest

    def _snapshot(self, rows: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
        now = utc(now)
        requests = self._requests(rows)
        own = self._own(rows)
        daily = self.daily_cap(now)
        period = self.period_start(now)
        spent = held = today = held_today = expired = Decimal(0)
        for row in requests.values():
            if period is not None and utc(row["at"]) < period:
                continue  # an earlier monthly period; kept in the journal, not counted
            if row["status"] == "settled":
                value = amount(row["actual"])
                spent += value
                if utc(row["settled_at"]).date() == now.date():
                    today += value
            else:
                value = amount(row["projected"])
                held += value
                reserved_at = utc(row["at"])
                # Unsettled holds stay in the TOTAL; they pace only the UTC day they
                # were reserved on; they never expire within that same UTC day.
                if reserved_at.date() == now.date():
                    held_today += value
                else:
                    expired += value
        failures = [r for r in own if r["event"] == "failure"]
        billing_reset = self._resets(rows, "billing_error")
        unavailable_reset = self._resets(rows, "unavailable")
        billing = [r for r in failures if r.get("reason") == "billing_error"
                   and r["sequence"] > billing_reset]
        exhausted = bool(billing)
        cooldown = timedelta(minutes=self._minutes("unavailable_cooldown_minutes", DEFAULT_UNAVAILABLE_COOLDOWN_MINUTES))
        transient = [r for r in failures if r.get("reason") in TRANSIENT_FAILURES
                     and r["sequence"] > unavailable_reset]
        unavailable_until = (max(utc(r["at"]) for r in transient) + cooldown) if transient else None
        unavailable = unavailable_until is not None and now < unavailable_until
        status = ("EXPIRED" if now >= self.expiry else "DISABLED" if self.policy.get("enabled") is not True or self.policy.get("provider_enabled", True) is not True
                  else "NOT_STARTED" if now < self.start else "UNAVAILABLE" if unavailable
                  else "EXHAUSTED" if exhausted or spent + held >= self.total
                  else "PAUSED_TODAY" if today + held_today >= daily else "OK")
        resets = [r for r in own if r["event"] == "operator_reset"]
        tier_caps = tier_used = None
        if self.tier_shares:
            tier_caps = {b: money(v) for b, v in self.tier_caps(now).items()}
            tier_used = {b: money(v) for b, v in self._tier_used_today(requests, now).items()}
        return {"status": status, "promotion_id": self.promotion,
                "tier_daily_caps_usd": tier_caps, "tier_today_used_usd": tier_used,
                "credit_used_usd": money(spent), "reserved_usd": money(held),
                "reserved_today_usd": money(held_today), "expired_unsettled_usd": money(expired),
                "today_used_usd": money(today), "total_cap_usd": money(self.total),
                "daily_cap_usd": money(daily), "daily_cap_base_usd": money(self.daily),
                "daily_cap_override_active": daily != self.daily or any(
                    start <= now.date() < until for start, until, _ in self.overrides),
                "renewal_mode": self.renewal["mode"],
                "period_start": period.isoformat() if period is not None else None,
                "remaining_budget_usd": money(max(Decimal(0), self.total - spent - held)),
                "estimated_credit_remaining_usd": money(max(Decimal(0), self.credit - spent - held)),
                "days_to_expiry": max(0, (self.expiry - now).total_seconds() / 86400),
                "last_fallback_reason": failures[-1]["reason"] if failures else None,
                "exhausted_reason": "billing_error" if exhausted else None,
                "billing_error_at": billing[0]["at"] if billing else None,
                "unavailable_reason": transient[-1]["reason"] if unavailable else None,
                "unavailable_until": unavailable_until.isoformat() if unavailable else None,
                "reset_sequence": resets[-1]["sequence"] if resets else 0,
                "open_reservations": sum(r["status"] != "settled" for r in requests.values()),
                "settled_calls": sum(r["status"] == "settled" for r in requests.values()),
                "as_of": now.isoformat(), "expiry": self.expiry.isoformat(),
                "remaining_is_estimated": True, "pacing_timezone": "UTC"}

    def snapshot(self, *, now: datetime) -> dict[str, Any]:
        # Health/dry-run reads never create a journal, directory or lock file.
        if not self.path.exists():
            return self._snapshot([], now)
        try:
            with self.path.with_suffix(".lock").open("r") as lock:
                fcntl.flock(lock, fcntl.LOCK_SH)
                return self._snapshot(self._read(), now)
        except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
            raise CreditDenied("CREDIT_UNAVAILABLE") from exc

    @staticmethod
    def _key(request_id: str) -> str:
        return hashlib.sha256(str(request_id).encode()).hexdigest()

    def effective_process_cap(self, process_id: str, tier: str, base: Decimal | None) -> Decimal | None:
        """The per-process cap after the configured emergency override.

        The override is keyed on the process id AND applies on cheap tiers only, so
        it can never raise another process's cap or widen the global/daily caps. It
        raises and never lowers: a registry cap above the override still binds.
        """
        override = (self.emergency_caps.get(process_id) or {}).get(tier)
        if override is None:
            return None if base is None else amount(base)
        if base is None:
            return override
        return max(amount(base), override)

    def reserve(self, request_id: str, process_id: str, projected: Decimal, *, tier: str,
                now: datetime, process_cap: Decimal | None = None) -> str:
        projected = amount(projected)
        process_id, process_name = caller_identity(process_id)
        try:
            ceiling = amount(self.policy["per_call_caps_usd"][tier])
        except (KeyError, TypeError) as exc:
            raise CreditDenied("CREDIT_CONFIGURATION_INVALID") from exc
        if projected <= 0 or projected > ceiling:
            raise CreditDenied("CREDIT_PER_CALL_CAP")
        # Operator 2026-11-02: a process named for emergency work may spend only on
        # the cheap tiers. Enforced at the ledger boundary so no caller can omit it.
        if process_id in self.emergency_caps and tier not in CHEAP_TIERS:
            raise CreditDenied("EMERGENCY_TIER_REFUSED")
        key = self._key(request_id)
        with self._locked():
            rows = self._read()
            snapshot = self._snapshot(rows, now)
            if snapshot["status"] != "OK":
                raise CreditDenied(snapshot["status"])
            requests = self._requests(rows)
            if key in requests:
                raise CreditDenied("CREDIT_REPLAY_REFUSED")
            if amount(snapshot["credit_used_usd"]) + amount(snapshot["reserved_usd"]) + projected > self.total:
                raise CreditDenied("EXHAUSTED")
            if amount(snapshot["today_used_usd"]) + amount(snapshot["reserved_today_usd"]) + projected > self.daily_cap(now):
                raise CreditDenied("PAUSED_TODAY")
            if self.tier_shares:
                # A tier outside every configured bucket is refused, never uncapped.
                bucket = tier_bucket(tier)
                cap = self.tier_caps(now).get(bucket) if bucket else None
                if cap is None or self._tier_used_today(requests, now)[bucket] + projected > cap:
                    raise CreditDenied(TIER_CAP_REFUSAL)
            effective_cap = self.effective_process_cap(process_id, tier, process_cap)
            if effective_cap is not None:
                used = sum((amount(r.get("actual", r["projected"])) for r in requests.values()
                            if r.get("process") == process_id and self._counts_today(r, now)), Decimal(0))
                if used + projected > effective_cap:
                    raise CreditDenied("CREDIT_PROCESS_CAP")
            self._append(rows, "reserve", now, request=key, process=process_id,
                         process_id=process_id, process_name=process_name,
                         projected=money(projected), tier=tier)
        return key

    def settle(self, request_id: str, actual: Decimal | None, *, now: datetime) -> None:
        key = self._key(request_id)
        with self._locked():
            rows = self._read()
            request = self._requests(rows).get(key)
            if request is None:
                raise CreditDenied("CREDIT_UNKNOWN_RESERVATION")
            if request["status"] == "settled":
                if actual is not None and amount(actual) != amount(request["actual"]):
                    raise CreditDenied("CREDIT_SETTLEMENT_CONFLICT")
                return
            if actual is None:
                if request["status"] != "uncertain":
                    self._append(rows, "uncertain", now, request=key)
                return
            actual = amount(actual)
            if actual > amount(request["projected"]):
                # Book the real amount so the total stays truthful, then pause
                # (time-bounded) because the projection under-estimated.
                self._append(rows, "failure", now, reason="over_reservation")
                self._append(self._read(), "settle", now, request=key, actual=money(actual))
                raise CreditDenied("CREDIT_OVER_RESERVATION")
            self._append(rows, "settle", now, request=key, actual=money(actual))

    def record_failure(self, reason: str, *, now: datetime) -> None:
        if reason not in {"billing_error", "auth_failure", "rate_limited", "overloaded", "timeout",
                          "invalid_response", "accounting_unavailable", "over_reservation"}:
            reason = "invalid_response"
        with self._locked():
            self._append(self._read(), "failure", now, reason=reason)

    def record_fallback(self, reason: str, *, now: datetime, process_id: Any = None) -> None:
        # Only stable codes; never provider bodies or prompt text. A cap refusal
        # writes no reserve row, so the fallback carries the caller identity too;
        # an omitted id still becomes unknown:<pid>, never null.
        permitted = {"NOT_CONFIGURED", "EXPIRED", "EXHAUSTED", "PAUSED_TODAY", "UNAVAILABLE",
                     "CREDIT_PER_CALL_CAP", "CREDIT_PROCESS_CAP", TIER_CAP_REFUSAL, "EMERGENCY_TIER_REFUSED",
                     "CALL_COST_CEILING", "RATE_LIMITED",
                     "OVERLOADED", "AUTH_FAILURE", "BILLING_ERROR", "TOOLS_UNSUPPORTED",
                     "OUTPUT_INVALID", "DEADLINE_EXCEEDED", "TIMEOUT", "MODEL_MISMATCH"}
        reason = reason if reason in permitted else "PROVIDER_UNAVAILABLE"
        process_id, process_name = caller_identity(process_id)
        with self._locked():
            self._append(self._read(), "fallback", now, reason=reason, process=process_id,
                         process_id=process_id, process_name=process_name)

    def operator_reset(self, scope: str, *, now: datetime, note_code: str = "operator") -> dict[str, Any]:
        """Append an operator reset; never edits or removes journal rows.

        ``billing_error`` clears a billing-error EXHAUSTED state (after the operator
        fixed the key/org), ``unavailable`` ends an accounting cooldown early, ``all``
        does both. Totals, holds and settled spend are unchanged.
        """
        if scope not in RESET_SCOPES:
            raise CreditDenied("CREDIT_RESET_SCOPE_INVALID")
        code = "".join(ch for ch in str(note_code) if ch.isalnum() or ch in "-_")[:40] or "operator"
        with self._locked():
            rows = self._read()
            self._append(rows, "operator_reset", now, scope=scope, note=code)
            return self._snapshot(self._read(), now)
