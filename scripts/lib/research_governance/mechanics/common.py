"""R2 shared contracts: units, input classes, dates, day-count, statuses.

Fail closed on unit mismatch, missing as-of, mixed date precision, or
ambiguous conventions. Pure stdlib. No provider/broker/DB calls.
"""
from __future__ import annotations

import calendar
import hashlib
import math
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

AUTHORITY = "READ_ONLY_ADVISORY"
CALCULATION_VERSION = "r2_mechanics_1.0.0"

REPO_ROOT = Path(__file__).resolve().parents[4]


class MechanicStatus(str, Enum):
    OK = "OK"
    UNAVAILABLE = "UNAVAILABLE"
    INVALID_INPUT = "INVALID_INPUT"
    AMBIGUOUS_CONVENTION = "AMBIGUOUS_CONVENTION"
    STALE_INPUT = "STALE_INPUT"
    UNSUPPORTED = "UNSUPPORTED"


class AssumptionClass(str, Enum):
    VERIFIED_FACT_INPUT = "VERIFIED_FACT_INPUT"
    ASSUMPTION_INPUT = "ASSUMPTION_INPUT"
    DERIVED_INPUT = "DERIVED_INPUT"
    CONVENTION = "CONVENTION"


class Unit(str, Enum):
    USD = "USD"
    USD_MILLIONS = "USD_MILLIONS"
    PERCENT = "PERCENT"
    DECIMAL_RATE = "DECIMAL_RATE"
    BASIS_POINTS = "BASIS_POINTS"
    PER_100_FACE = "PER_100_FACE"
    SHARES = "SHARES"
    FACE_VALUE = "FACE_VALUE"
    YEARS = "YEARS"
    DAYS = "DAYS"
    DIMENSIONLESS = "DIMENSIONLESS"


class DayCount(str, Enum):
    ACT_ACT_ISDA = "ACT/ACT_ISDA"
    ACT_360 = "ACT/360"
    ACT_365 = "ACT/365"
    THIRTY_360_US = "30/360_US"


class CouponFrequency(str, Enum):
    ANNUAL = "annual"
    SEMIANNUAL = "semiannual"
    QUARTERLY = "quarterly"
    MONTHLY = "monthly"


_FREQ_PERIODS = {
    CouponFrequency.ANNUAL: 1,
    CouponFrequency.SEMIANNUAL: 2,
    CouponFrequency.QUARTERLY: 4,
    CouponFrequency.MONTHLY: 12,
}

_FREQ_ALIASES = {
    "annual": CouponFrequency.ANNUAL,
    "annually": CouponFrequency.ANNUAL,
    "1": CouponFrequency.ANNUAL,
    "semiannual": CouponFrequency.SEMIANNUAL,
    "semi-annual": CouponFrequency.SEMIANNUAL,
    "semi": CouponFrequency.SEMIANNUAL,
    "2": CouponFrequency.SEMIANNUAL,
    "quarterly": CouponFrequency.QUARTERLY,
    "quarter": CouponFrequency.QUARTERLY,
    "4": CouponFrequency.QUARTERLY,
    "monthly": CouponFrequency.MONTHLY,
    "month": CouponFrequency.MONTHLY,
    "12": CouponFrequency.MONTHLY,
}

# Unambiguous unit conversions only.
_CONVERT = {
    (Unit.PERCENT, Unit.DECIMAL_RATE): lambda x: x / 100.0,
    (Unit.DECIMAL_RATE, Unit.PERCENT): lambda x: x * 100.0,
    (Unit.BASIS_POINTS, Unit.DECIMAL_RATE): lambda x: x / 10_000.0,
    (Unit.DECIMAL_RATE, Unit.BASIS_POINTS): lambda x: x * 10_000.0,
    (Unit.BASIS_POINTS, Unit.PERCENT): lambda x: x / 100.0,
    (Unit.PERCENT, Unit.BASIS_POINTS): lambda x: x * 100.0,
    (Unit.USD_MILLIONS, Unit.USD): lambda x: x * 1_000_000.0,
    (Unit.USD, Unit.USD_MILLIONS): lambda x: x / 1_000_000.0,
}


class MechanicError(Exception):
    def __init__(self, status: MechanicStatus, reason: str, **extra: Any) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason
        self.extra = extra


@dataclass(frozen=True)
class Quantity:
    value: float
    unit: Unit

    def __post_init__(self) -> None:
        if not isinstance(self.unit, Unit):
            raise MechanicError(MechanicStatus.INVALID_INPUT, f"unknown unit: {self.unit!r}")
        if not isinstance(self.value, (int, float)) or not math.isfinite(float(self.value)):
            raise MechanicError(MechanicStatus.INVALID_INPUT, f"non-finite quantity: {self.value!r}")
        object.__setattr__(self, "value", float(self.value))


@dataclass(frozen=True)
class InputDatum:
    name: str
    value: Any
    unit: Optional[Unit]
    klass: AssumptionClass
    source: str = ""
    as_of: Optional[str] = None
    convention: Optional[str] = None

    def require_as_of(self) -> str:
        if not self.as_of or not str(self.as_of).strip():
            raise MechanicError(
                MechanicStatus.UNAVAILABLE,
                f"missing critical source_as_of for {self.name}",
                reason_code="MISSING_SOURCE_AS_OF",
            )
        return str(self.as_of).strip()


def parse_coupon_frequency(raw: Any) -> CouponFrequency:
    if isinstance(raw, CouponFrequency):
        return raw
    if raw is None:
        raise MechanicError(MechanicStatus.INVALID_INPUT, "coupon frequency missing")
    key = str(raw).strip().lower()
    if key not in _FREQ_ALIASES:
        raise MechanicError(MechanicStatus.INVALID_INPUT, f"coupon frequency invalid: {raw!r}")
    return _FREQ_ALIASES[key]


def periods_per_year(freq: CouponFrequency) -> int:
    return _FREQ_PERIODS[freq]


def parse_day_count(raw: Any) -> DayCount:
    if isinstance(raw, DayCount):
        return raw
    if raw is None:
        raise MechanicError(MechanicStatus.AMBIGUOUS_CONVENTION, "day-count convention missing")
    key = str(raw).strip().upper().replace(" ", "").replace("-", "/")
    aliases = {
        "ACT/ACT": DayCount.ACT_ACT_ISDA,
        "ACT/ACT_ISDA": DayCount.ACT_ACT_ISDA,
        "ACT/ACTISDA": DayCount.ACT_ACT_ISDA,
        "ACTUAL/ACTUAL": DayCount.ACT_ACT_ISDA,
        "ACT/360": DayCount.ACT_360,
        "ACTUAL/360": DayCount.ACT_360,
        "ACT/365": DayCount.ACT_365,
        "ACTUAL/365": DayCount.ACT_365,
        "ACT/365F": DayCount.ACT_365,
        "30/360_US": DayCount.THIRTY_360_US,
        "30/360US": DayCount.THIRTY_360_US,
        "30/360SIA": DayCount.THIRTY_360_US,
        "30/360NASD": DayCount.THIRTY_360_US,
    }
    if key in ("30/360", "30U/360", "BOND"):
        raise MechanicError(
            MechanicStatus.AMBIGUOUS_CONVENTION,
            "ambiguous day-count '30/360' — specify 30/360_US (other 30/360 variants unsupported)",
        )
    if key not in aliases:
        raise MechanicError(MechanicStatus.AMBIGUOUS_CONVENTION, f"unknown day-count: {raw!r}")
    return aliases[key]


def require_unit(qty: Quantity, expected: Unit, *, name: str = "value") -> float:
    if qty.unit != expected:
        raise MechanicError(
            MechanicStatus.INVALID_INPUT,
            f"{name} unit mismatch: got {qty.unit.value}, expected {expected.value}",
            reason_code="UNIT_MISMATCH",
        )
    return qty.value


def convert_quantity(qty: Quantity, target: Unit) -> Quantity:
    if qty.unit == target:
        return qty
    fn = _CONVERT.get((qty.unit, target))
    if fn is None:
        raise MechanicError(
            MechanicStatus.INVALID_INPUT,
            f"no unambiguous conversion {qty.unit.value} → {target.value}",
            reason_code="UNIT_MISMATCH",
        )
    return Quantity(fn(qty.value), target)


def as_decimal_rate(qty: Quantity, *, name: str = "rate") -> float:
    if qty.unit == Unit.DECIMAL_RATE:
        return qty.value
    if qty.unit in (Unit.PERCENT, Unit.BASIS_POINTS):
        return convert_quantity(qty, Unit.DECIMAL_RATE).value
    raise MechanicError(
        MechanicStatus.INVALID_INPUT,
        f"{name} must be DECIMAL_RATE, PERCENT, or BASIS_POINTS, got {qty.unit.value}",
        reason_code="UNIT_MISMATCH",
    )


def parse_date_only(value: Any, *, name: str = "date") -> date:
    if isinstance(value, datetime):
        raise MechanicError(
            MechanicStatus.INVALID_INPUT,
            f"{name} is a datetime; contractual dates must be date-only",
        )
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        raise MechanicError(MechanicStatus.UNAVAILABLE, f"{name} missing")
    v = value.strip()
    if "T" in v or " " in v:
        raise MechanicError(
            MechanicStatus.INVALID_INPUT,
            f"{name} mixes datetime precision; expected YYYY-MM-DD",
        )
    try:
        return date.fromisoformat(v)
    except ValueError as exc:
        raise MechanicError(MechanicStatus.INVALID_INPUT, f"{name} unparseable: {v}") from exc


def parse_timestamp(value: Any, *, name: str = "timestamp") -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise MechanicError(MechanicStatus.INVALID_INPUT, f"{name} is naive (timezone required)")
        return value.astimezone(timezone.utc)
    if isinstance(value, date) and not isinstance(value, datetime):
        raise MechanicError(
            MechanicStatus.INVALID_INPUT,
            f"{name} is date-only; time-of-day comparison requires an aware datetime",
        )
    if not isinstance(value, str) or not value.strip():
        raise MechanicError(MechanicStatus.UNAVAILABLE, f"{name} missing")
    v = value.strip()
    if len(v) == 10 and v[4] == "-" and v[7] == "-":
        raise MechanicError(
            MechanicStatus.INVALID_INPUT,
            f"{name} is date-only; time-of-day comparison requires an aware datetime",
        )
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MechanicError(MechanicStatus.INVALID_INPUT, f"{name} unparseable: {v}") from exc
    if dt.tzinfo is None:
        raise MechanicError(MechanicStatus.INVALID_INPUT, f"{name} is naive (timezone required)")
    return dt.astimezone(timezone.utc)


def _last_day_of_month(d: date) -> int:
    return calendar.monthrange(d.year, d.month)[1]


def _is_leap(year: int) -> bool:
    return calendar.isleap(year)


def year_fraction(start: date, end: date, convention: DayCount) -> float:
    if end < start:
        raise MechanicError(MechanicStatus.INVALID_INPUT, "year_fraction end before start")
    if end == start:
        return 0.0
    if convention == DayCount.ACT_360:
        return (end - start).days / 360.0
    if convention == DayCount.ACT_365:
        return (end - start).days / 365.0
    if convention == DayCount.THIRTY_360_US:
        return _thirty_360_us_days(start, end) / 360.0
    if convention == DayCount.ACT_ACT_ISDA:
        return _act_act_isda(start, end)
    raise MechanicError(MechanicStatus.AMBIGUOUS_CONVENTION, f"unsupported day-count {convention}")


def _thirty_360_us_days(d1: date, d2: date) -> int:
    """US (NASD/SIA) 30/360. Explicitly not ICMA 30E/360 or ISDA 30/360."""
    y1, m1, day1 = d1.year, d1.month, d1.day
    y2, m2, day2 = d2.year, d2.month, d2.day
    if m1 == 2 and day1 == _last_day_of_month(d1):
        day1 = 30
    if day1 == 31:
        day1 = 30
    if day2 == 31 and day1 >= 30:
        day2 = 30
    return 360 * (y2 - y1) + 30 * (m2 - m1) + (day2 - day1)


def _act_act_isda(start: date, end: date) -> float:
    total = 0.0
    y = start.year
    cursor = start
    while cursor < end:
        year_end = date(y + 1, 1, 1)
        stop = end if end < year_end else year_end
        denom = 366.0 if _is_leap(y) else 365.0
        total += (stop - cursor).days / denom
        cursor = stop
        y += 1
    return total


def time_gap_seconds(a: datetime, b: datetime) -> float:
    return abs((a - b).total_seconds())


def producer_git_sha() -> str:
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return "unknown"


def producer_source_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_canonical(payload: dict[str, Any]) -> str:
    from scripts.lib.research_governance.models import _stable_hash
    return _stable_hash(payload)


@dataclass
class MechanicResult:
    """Canonical R2 calculation envelope. Not a governed receipt by itself."""

    calculation_id: str
    mechanic_type: str
    instrument_id: str
    status: MechanicStatus
    result: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    input_values: dict[str, Any] = field(default_factory=dict)
    input_units: dict[str, str] = field(default_factory=dict)
    input_conventions: dict[str, str] = field(default_factory=dict)
    input_as_of: dict[str, Optional[str]] = field(default_factory=dict)
    input_sources: dict[str, str] = field(default_factory=dict)
    input_quality: dict[str, str] = field(default_factory=dict)
    assumptions: dict[str, Any] = field(default_factory=dict)
    assumption_sources: dict[str, str] = field(default_factory=dict)
    assumption_as_of: dict[str, Optional[str]] = field(default_factory=dict)
    calculation_version: str = CALCULATION_VERSION
    producer_source_sha256: str = ""
    producer_git_sha: str = ""
    result_digest: str = ""
    generated_at: str = ""
    reason: str = ""
    reason_code: str = ""
    authority: str = AUTHORITY

    def to_payload(self) -> dict[str, Any]:
        return {
            "calculation_id": self.calculation_id,
            "mechanic_type": self.mechanic_type,
            "instrument_id": self.instrument_id,
            "status": self.status.value,
            "result": self.result,
            "warnings": list(self.warnings),
            "limitations": list(self.limitations),
            "input_values": dict(self.input_values),
            "input_units": dict(self.input_units),
            "input_conventions": dict(self.input_conventions),
            "input_as_of": dict(self.input_as_of),
            "input_sources": dict(self.input_sources),
            "input_quality": dict(self.input_quality),
            "assumptions": dict(self.assumptions),
            "assumption_sources": dict(self.assumption_sources),
            "assumption_as_of": dict(self.assumption_as_of),
            "calculation_version": self.calculation_version,
            "producer_source_sha256": self.producer_source_sha256,
            "producer_git_sha": self.producer_git_sha,
            "reason": self.reason,
            "reason_code": self.reason_code,
            "authority": self.authority,
            "generated_at": self.generated_at,
        }

    def seal(self, source_path: Path) -> "MechanicResult":
        self.generated_at = self.generated_at or utcnow_iso()
        self.producer_git_sha = self.producer_git_sha or producer_git_sha()
        self.producer_source_sha256 = producer_source_sha256(source_path)
        self.result_digest = sha256_canonical(self.to_payload())
        return self


def fail_result(
    *,
    calculation_id: str,
    mechanic_type: str,
    instrument_id: str,
    status: MechanicStatus,
    reason: str,
    reason_code: str = "",
    source_path: Path,
    **kwargs: Any,
) -> MechanicResult:
    r = MechanicResult(
        calculation_id=calculation_id,
        mechanic_type=mechanic_type,
        instrument_id=instrument_id,
        status=status,
        reason=reason,
        reason_code=reason_code or status.value,
        **kwargs,
    )
    return r.seal(source_path)
