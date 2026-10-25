"""Durable promotional-credit authorization, separate from provider spend metering.

The append-only journal contains amounts and opaque request identities only. A
partial/corrupt journal refuses dispatch. Pending amounts survive day boundaries
and are never released merely because a worker stopped or a response timed out.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import json
import os
from pathlib import Path
from typing import Any


SCHEMA = "AnthropicCreditAuthorization@v1"
JOURNAL_REL = "data/runtime/provider_cost/anthropic_credit.jsonl"


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


def utc(value: datetime | str) -> datetime:
    if not isinstance(value, (datetime, str)):
        raise CreditDenied("CREDIT_CLOCK_INVALID")
    dt = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise CreditDenied("CREDIT_CLOCK_INVALID")
    return dt.astimezone(timezone.utc)


class CreditBook:
    def __init__(self, root: Path, policy: dict[str, Any]):
        self.root = Path(root)
        self.path = self.root / JOURNAL_REL
        self.policy = dict(policy)
        self.promotion = str(policy["promotion_id"])
        self.total = amount(policy["total_cap_usd"])
        self.daily = amount(policy["daily_cap_usd"])
        self.credit = amount(policy["credit_usd"])
        self.start, self.expiry = utc(policy["starts_at"]), utc(policy["expires_at"])
        if not (0 < self.total <= self.credit and 0 < self.daily and self.start < self.expiry):
            raise CreditDenied("CREDIT_CONFIGURATION_INVALID")

    @contextmanager
    def _locked(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.with_suffix(".lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                yield
        except CreditDenied:
            raise
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise CreditDenied("CREDIT_UNAVAILABLE") from exc

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        previous = ""
        try:
            with self.path.open(encoding="utf-8") as handle:
                for line in handle:
                    row = json.loads(line)
                    checksum = row.pop("checksum")
                    expected = hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
                    if (checksum != expected or row["previous"] != previous
                            or row["schema"] != SCHEMA or row["promotion_id"] != self.promotion
                            or row["sequence"] != len(rows) + 1):
                        raise CreditDenied("CREDIT_UNAVAILABLE")
                    previous = checksum
                    row["checksum"] = checksum
                    rows.append(row)
        except (OSError, ValueError, KeyError, TypeError) as exc:
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
            offset = 0
            while offset < len(payload):
                written = os.write(fd, payload[offset:])
                if written <= 0:
                    raise CreditDenied("CREDIT_UNAVAILABLE")
                offset += written
            os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _requests(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        requests: dict[str, dict[str, Any]] = {}
        for row in rows:
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

    def _snapshot(self, rows: list[dict[str, Any]], now: datetime) -> dict[str, Any]:
        now = utc(now)
        requests = self._requests(rows)
        spent = held = today = Decimal(0)
        for row in requests.values():
            if row["status"] == "settled":
                value = amount(row["actual"])
                spent += value
                if utc(row["settled_at"]).date() == now.date():
                    today += value
            else:
                held += amount(row["projected"])
        failures = [r for r in rows if r["event"] == "failure"]
        exhausted = any(r.get("reason") == "billing_error" for r in failures)
        unavailable = any(r.get("reason") in {"accounting_unavailable", "over_reservation"} for r in failures)
        status = ("EXPIRED" if now >= self.expiry else "DISABLED" if self.policy.get("enabled") is not True or self.policy.get("provider_enabled", True) is not True
                  else "NOT_STARTED" if now < self.start else "UNAVAILABLE" if unavailable
                  else "EXHAUSTED" if exhausted or spent + held >= self.total
                  else "PAUSED_TODAY" if today + held >= self.daily else "OK")
        return {"status": status, "promotion_id": self.promotion,
                "credit_used_usd": money(spent), "reserved_usd": money(held),
                "today_used_usd": money(today), "total_cap_usd": money(self.total),
                "daily_cap_usd": money(self.daily),
                "remaining_budget_usd": money(max(Decimal(0), self.total - spent - held)),
                "estimated_credit_remaining_usd": money(max(Decimal(0), self.credit - spent - held)),
                "days_to_expiry": max(0, (self.expiry - now).total_seconds() / 86400),
                "last_fallback_reason": failures[-1]["reason"] if failures else None,
                "exhausted_reason": "billing_error" if exhausted else None,
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
        except (OSError, ValueError) as exc:
            raise CreditDenied("CREDIT_UNAVAILABLE") from exc

    @staticmethod
    def _key(request_id: str) -> str:
        return hashlib.sha256(str(request_id).encode()).hexdigest()

    def reserve(self, request_id: str, process_id: str, projected: Decimal, *, tier: str,
                now: datetime, process_cap: Decimal | None = None) -> str:
        projected = amount(projected)
        ceiling = amount(self.policy["per_call_caps_usd"][tier])
        if projected <= 0 or projected > ceiling:
            raise CreditDenied("CREDIT_PER_CALL_CAP")
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
            if amount(snapshot["today_used_usd"]) + amount(snapshot["reserved_usd"]) + projected > self.daily:
                raise CreditDenied("PAUSED_TODAY")
            if process_cap is not None:
                used = sum((amount(r.get("actual", r["projected"])) for r in requests.values()
                            if r.get("process") == process_id and
                            (r["status"] != "settled" or utc(r["settled_at"]).date() == utc(now).date())), Decimal(0))
                if used + projected > amount(process_cap):
                    raise CreditDenied("CREDIT_PROCESS_CAP")
            self._append(rows, "reserve", now, request=key, process=process_id,
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
                self._append(rows, "failure", now, reason="over_reservation")
                raise CreditDenied("CREDIT_OVER_RESERVATION")
            self._append(rows, "settle", now, request=key, actual=money(actual))

    def record_failure(self, reason: str, *, now: datetime) -> None:
        if reason not in {"billing_error", "auth_failure", "rate_limited", "overloaded", "timeout",
                          "invalid_response", "accounting_unavailable", "over_reservation"}:
            reason = "invalid_response"
        with self._locked():
            self._append(self._read(), "failure", now, reason=reason)

    def record_fallback(self, reason: str, *, now: datetime) -> None:
        # Only stable codes; never provider bodies or prompt text.
        permitted = {"NOT_CONFIGURED", "EXPIRED", "EXHAUSTED", "PAUSED_TODAY", "UNAVAILABLE",
                     "CREDIT_PER_CALL_CAP", "CREDIT_PROCESS_CAP", "CALL_COST_CEILING", "RATE_LIMITED",
                     "OVERLOADED", "AUTH_FAILURE", "BILLING_ERROR", "TOOLS_UNSUPPORTED",
                     "OUTPUT_INVALID", "DEADLINE_EXCEEDED", "TIMEOUT", "MODEL_MISMATCH"}
        reason = reason if reason in permitted else "PROVIDER_UNAVAILABLE"
        with self._locked():
            self._append(self._read(), "fallback", now, reason=reason)
