"""Multiwindow multi-burn-rate SLO alerting (Google SRE Workbook, ch. 5).

WHY THIS EXISTS
---------------
Measured 2026-09-22: ``grep -rl "error_budget|slo_target|burn_rate" scripts/ config/``
returned nothing. Every alarm in this repository is a threshold on a CAUSE
("queue depth > N", "table age > N days"). Nothing anywhere alerts on a SYMPTOM
against a BUDGET, which is why one AUTO-RETRY cause alert was able to become
57% of the identity spine while the thing operators actually care about --
did the alert reach a human, is the card fresh -- had no number at all.

THE THREE THINGS AN EARLIER DRAFT GOT WRONG, pinned here so they cannot return:

1. ``window_seconds`` must DRIVE the math, not be stored and ignored. The
   Workbook's table works because the short window is 1/12 of the long one and
   the SAME threshold is applied to both: the long window decides *whether*
   budget is burning fast, the short window decides whether it is *still*
   burning, which is what stops an alert latching for hours after the incident
   ends. Both halves are therefore validated (``BurnRateTier.__post_init__``
   rejects a ratio that is not ~12) and both are read (``evaluate`` looks its
   samples up BY ``window_seconds`` and fires only if both exceed threshold).

2. ``consumed_budget_pct`` is NOT ``burn_rate * 100``. Burn rate is a RATE --
   a multiple of the budget-exhausting pace. What fraction of the budget it
   actually consumes depends on how long it is sustained relative to the SLO
   period. Burn rate 14.4 for one hour against a 30-day budget consumes
   14.4 * 3600 / 2592000 = 2%, not 1440%. That 2% is precisely why 14.4 is the
   Workbook's page threshold, and reporting 1440% would make every tier look
   identically catastrophic.

3. Validation belongs where the caller constructs the thing. A bad target is a
   bad CONFIG, so ``SLOConfig``/``BurnRateTier`` raise ``ValueError`` at
   construction; deferring it to ``evaluate`` means a malformed config sits in
   the tree looking valid until something reads it.

PURE. No database, no network, no clock of its own (``now`` is always passed
in). AUTHORITY: READ_ONLY_ADVISORY -- this module computes a verdict and
returns it. It sends nothing and schedules nothing.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

SCHEMA = "SLOBurnRateVerdict@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

SEVERITY_PAGE = "PAGE"
SEVERITY_TICKET = "TICKET"
VALID_SEVERITIES = (SEVERITY_PAGE, SEVERITY_TICKET)

STATUS_OK = "OK"
STATUS_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
STATUS_NO_DATA = "NO_DATA"

#: The Workbook pairs each long window with a short window 1/12 its length.
WORKBOOK_WINDOW_RATIO = 12.0
#: How far the configured ratio may stray from 12 before it is rejected. A
#: 6h/30m pair is exactly 12; allowing a little slack lets an operator express
#: e.g. 24h/2h (exactly 12) or 72h/6h (exactly 12) without float pedantry, but
#: a 24h/23h "pair" -- which would make the short window decorative -- is out.
WINDOW_RATIO_TOLERANCE = 0.30


def _as_positive_number(value: Any, field: str) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number, got {value!r}") from exc
    if out <= 0:
        raise ValueError(f"{field} must be > 0, got {out}")
    return out


@dataclass(frozen=True)
class BurnRateTier:
    """One row of the Workbook's multiwindow table.

    ``threshold`` is applied to BOTH windows. ``severity`` says what firing
    means: PAGE (wake a human) or TICKET (fix it during the week).
    """

    label: str
    long_window_seconds: int
    short_window_seconds: int
    threshold: float
    severity: str

    def __post_init__(self) -> None:
        if not str(self.label or "").strip():
            raise ValueError("tier label must be a non-empty string")
        long_s = _as_positive_number(self.long_window_seconds, f"{self.label}.long_window_seconds")
        short_s = _as_positive_number(self.short_window_seconds, f"{self.label}.short_window_seconds")
        _as_positive_number(self.threshold, f"{self.label}.threshold")
        if self.severity not in VALID_SEVERITIES:
            raise ValueError(f"{self.label}.severity must be one of {VALID_SEVERITIES}, got {self.severity!r}")
        if short_s >= long_s:
            raise ValueError(
                f"{self.label}: short_window_seconds ({short_s:g}) must be shorter than "
                f"long_window_seconds ({long_s:g})"
            )
        # The short window is the "is it STILL burning?" half. If it is not
        # roughly 1/12 of the long window it stops doing that job, and the
        # shared threshold -- the reason one number can govern both -- no
        # longer corresponds to the same budget consumption on each side.
        ratio = long_s / short_s
        lo = WORKBOOK_WINDOW_RATIO * (1.0 - WINDOW_RATIO_TOLERANCE)
        hi = WORKBOOK_WINDOW_RATIO * (1.0 + WINDOW_RATIO_TOLERANCE)
        if not (lo <= ratio <= hi):
            raise ValueError(
                f"{self.label}: long/short window ratio {ratio:.2f} is outside the Workbook band "
                f"[{lo:.2f}, {hi:.2f}] (expected ~{WORKBOOK_WINDOW_RATIO:g}:1)"
            )

    @property
    def window_seconds(self) -> tuple[int, int]:
        return (int(self.long_window_seconds), int(self.short_window_seconds))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> BurnRateTier:
        missing = {"label", "long_window_seconds", "short_window_seconds", "threshold", "severity"} - set(data)
        if missing:
            raise ValueError(f"burn-rate tier is missing keys: {sorted(missing)}")
        return cls(
            label=str(data["label"]),
            long_window_seconds=int(data["long_window_seconds"]),
            short_window_seconds=int(data["short_window_seconds"]),
            threshold=float(data["threshold"]),
            severity=str(data["severity"]),
        )


@dataclass(frozen=True)
class SLOConfig:
    """A target, a period, and the tiers that decide when to shout about it.

    Raises ``ValueError`` from the CONSTRUCTOR on any malformed field -- see
    point 3 in the module docstring.
    """

    name: str
    description: str
    slo_target: float
    period_days: int
    tiers: tuple[BurnRateTier, ...]
    min_events: int

    def __post_init__(self) -> None:
        if not str(self.name or "").strip():
            raise ValueError("slo name must be a non-empty string")
        try:
            target = float(self.slo_target)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{self.name}: slo_target must be a number, got {self.slo_target!r}") from exc
        # A target of exactly 1.0 means a zero error budget: every burn-rate
        # division would be by zero and no budget could ever be "spent at 3x".
        # A target of 0 means nothing is ever an error. Both are configuration
        # mistakes, not edge cases to paper over downstream.
        if not (0.0 < target < 1.0):
            raise ValueError(f"{self.name}: slo_target must be strictly between 0 and 1, got {target}")
        try:
            period = int(self.period_days)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{self.name}: period_days must be an integer, got {self.period_days!r}") from exc
        if period <= 0:
            raise ValueError(f"{self.name}: period_days must be > 0, got {period}")
        if not self.tiers:
            raise ValueError(f"{self.name}: at least one burn-rate tier is required")
        for tier in self.tiers:
            if not isinstance(tier, BurnRateTier):
                raise ValueError(f"{self.name}: tiers must be BurnRateTier instances, got {type(tier).__name__}")
            if tier.long_window_seconds > self.period_seconds:
                raise ValueError(
                    f"{self.name}/{tier.label}: long_window_seconds ({tier.long_window_seconds}) exceeds the "
                    f"SLO period ({self.period_seconds} s) -- a window cannot be longer than the budget it spends"
                )
        try:
            min_events = int(self.min_events)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{self.name}: min_events must be an integer, got {self.min_events!r}") from exc
        if min_events < 1:
            raise ValueError(f"{self.name}: min_events must be >= 1, got {min_events}")

    @property
    def period_seconds(self) -> int:
        return int(self.period_days) * 86400

    @property
    def error_budget_ratio(self) -> float:
        """The share of events allowed to fail before the budget is gone."""
        return 1.0 - float(self.slo_target)

    def window_seconds(self) -> tuple[int, ...]:
        """Every distinct window this config needs a sample for."""
        seen: list[int] = []
        for tier in self.tiers:
            for w in tier.window_seconds:
                if w not in seen:
                    seen.append(w)
        return tuple(sorted(seen))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], default_tiers: Any = None) -> SLOConfig:
        """Build one config. ``default_tiers`` supplies the document-level table.

        The Workbook tier table is one shared set of numbers; repeating it under
        every SLO invites the three copies to drift apart, so the document may
        declare it once and an individual SLO may still override.
        """
        raw_tiers = data.get("tiers", default_tiers)
        missing = {"name", "slo_target", "period_days"} - set(data)
        if missing:
            raise ValueError(f"slo config is missing keys: {sorted(missing)}")
        if not raw_tiers:
            raise ValueError(f"{data.get('name')}: no burn-rate tiers (neither per-SLO nor document-level)")
        return cls(
            name=str(data["name"]),
            description=str(data.get("description") or ""),
            slo_target=float(data["slo_target"]),
            period_days=int(data["period_days"]),
            tiers=tuple(BurnRateTier.from_dict(t) for t in raw_tiers),
            min_events=int(data.get("min_events", 1)),
        )


@dataclass(frozen=True)
class WindowSample:
    """Good-vs-total over one window. ``window_seconds`` is the join key."""

    window_seconds: int
    good: int
    total: int

    def __post_init__(self) -> None:
        _as_positive_number(self.window_seconds, "window_seconds")
        if int(self.total) < 0 or int(self.good) < 0:
            raise ValueError(f"good/total must be non-negative, got good={self.good} total={self.total}")
        if int(self.good) > int(self.total):
            raise ValueError(f"good ({self.good}) cannot exceed total ({self.total})")

    def as_dict(self) -> dict[str, Any]:
        return {"window_seconds": int(self.window_seconds), "good": int(self.good), "total": int(self.total)}


def burn_rate(good: int, total: int, slo_target: float) -> float:
    """How many times faster than "budget exactly exhausted at period end".

    ``failure_rate / error_budget_ratio``. Burn rate 1.0 spends the whole
    budget in exactly one SLO period; 14.4 spends it in 1/14.4 of a period.
    """
    total_i = int(total)
    if total_i <= 0:
        raise ValueError("burn_rate needs at least one event; guard with min_events first")
    good_i = int(good)
    if good_i > total_i or good_i < 0:
        raise ValueError(f"good ({good_i}) must be within [0, total={total_i}]")
    budget = 1.0 - float(slo_target)
    if budget <= 0:
        raise ValueError(f"slo_target {slo_target} leaves no error budget to burn")
    failure_rate = (total_i - good_i) / total_i
    return failure_rate / budget


def consumed_budget_pct(rate: float, window_seconds: float, period_seconds: float) -> float:
    """Percent of the period's error budget spent by sustaining ``rate`` for ``window_seconds``.

    NOT ``rate * 100`` -- see point 2 in the module docstring. This is the
    function that makes ``window_seconds`` arithmetically load-bearing.
    """
    window = _as_positive_number(window_seconds, "window_seconds")
    period = _as_positive_number(period_seconds, "period_seconds")
    if float(rate) < 0:
        raise ValueError(f"burn rate must be non-negative, got {rate}")
    return float(rate) * (window / period) * 100.0


def freshness_window_sample(
    *,
    event_times: Sequence[float],
    now: float,
    window_seconds: int,
    bucket_seconds: int,
    staleness_budget_seconds: int,
) -> WindowSample:
    """Turn producer timestamps into good/total for a FRESHNESS SLI.

    A freshness SLI has no natural "event" the way a delivery SLI does -- the
    absence of rows IS the failure, so counting rows would score a dead feed as
    100% good. So the window is cut into fixed buckets and each bucket asks the
    operator's actual question: *at that moment, was the newest row younger
    than the staleness budget?* Buckets are the units; ``window_seconds``
    determines how many there are, which is the other half of making the
    window drive the math.

    ``event_times`` and ``now`` are POSIX seconds. ``event_times`` must cover
    ``[now - window_seconds - staleness_budget_seconds, now]``, or early
    buckets will be scored stale for want of history rather than for want of
    freshness -- the caller is responsible for querying that wider range.
    """
    window = int(_as_positive_number(window_seconds, "window_seconds"))
    bucket = int(_as_positive_number(bucket_seconds, "bucket_seconds"))
    staleness = int(_as_positive_number(staleness_budget_seconds, "staleness_budget_seconds"))
    if bucket > window:
        raise ValueError(f"bucket_seconds ({bucket}) cannot exceed window_seconds ({window})")

    ordered = sorted(float(t) for t in event_times)
    n_buckets = window // bucket
    if n_buckets <= 0:
        raise ValueError(f"window_seconds ({window}) yields no whole buckets of {bucket} s")

    start = float(now) - window
    good = 0
    for k in range(n_buckets):
        at = start + (k + 1) * bucket
        # newest event at or before this bucket edge
        idx = bisect.bisect_right(ordered, at)
        if idx and (at - ordered[idx - 1]) <= staleness:
            good += 1
    return WindowSample(window_seconds=window, good=good, total=n_buckets)


def evaluate(config: SLOConfig, samples: Mapping[int, WindowSample]) -> dict[str, Any]:
    """Apply every tier and return a receipt-shaped verdict.

    A tier fires only when BOTH its windows exceed the shared threshold, and
    is suppressed entirely when either window carries fewer than
    ``config.min_events`` -- low traffic makes the failure ratio noise, and
    paging on noise is how a burn-rate alert becomes the next AUTO-RETRY storm.
    """
    if not isinstance(config, SLOConfig):
        raise ValueError(f"evaluate needs an SLOConfig, got {type(config).__name__}")

    tier_results: list[dict[str, Any]] = []
    fired: list[str] = []
    evaluated_any = False

    for tier in config.tiers:
        long_s, short_s = tier.window_seconds
        long_sample = samples.get(long_s)
        short_sample = samples.get(short_s)
        row: dict[str, Any] = {
            "label": tier.label,
            "severity": tier.severity,
            "threshold": float(tier.threshold),
            "long_window_seconds": long_s,
            "short_window_seconds": short_s,
        }
        if long_sample is None or short_sample is None:
            row["status"] = STATUS_NO_DATA
            row["why"] = "no sample supplied for " + (
                "long window" if long_sample is None else "short window"
            )
            tier_results.append(row)
            continue
        if long_sample.total < config.min_events or short_sample.total < config.min_events:
            row["status"] = STATUS_INSUFFICIENT_DATA
            row["why"] = (
                f"min_events={config.min_events}; long total={long_sample.total}, short total={short_sample.total}"
            )
            row["long"] = long_sample.as_dict()
            row["short"] = short_sample.as_dict()
            tier_results.append(row)
            continue

        evaluated_any = True
        long_rate = burn_rate(long_sample.good, long_sample.total, config.slo_target)
        short_rate = burn_rate(short_sample.good, short_sample.total, config.slo_target)
        row["long"] = {
            **long_sample.as_dict(),
            "burn_rate": round(long_rate, 4),
            "consumed_budget_pct": round(consumed_budget_pct(long_rate, long_s, config.period_seconds), 4),
        }
        row["short"] = {
            **short_sample.as_dict(),
            "burn_rate": round(short_rate, 4),
            "consumed_budget_pct": round(consumed_budget_pct(short_rate, short_s, config.period_seconds), 4),
        }
        if long_rate >= tier.threshold and short_rate >= tier.threshold:
            row["status"] = tier.severity
            fired.append(tier.label)
        else:
            row["status"] = STATUS_OK
            row["why"] = (
                "long window below threshold"
                if long_rate < tier.threshold
                else "short window below threshold (burn has stopped)"
            )
        tier_results.append(row)

    if any(r["status"] == SEVERITY_PAGE for r in tier_results):
        status = SEVERITY_PAGE
    elif any(r["status"] == SEVERITY_TICKET for r in tier_results):
        status = SEVERITY_TICKET
    elif evaluated_any:
        status = STATUS_OK
    else:
        status = STATUS_INSUFFICIENT_DATA

    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "slo": config.name,
        "description": config.description,
        "slo_target": float(config.slo_target),
        "error_budget_ratio": config.error_budget_ratio,
        "period_days": int(config.period_days),
        "min_events": int(config.min_events),
        "status": status,
        "fired_tiers": fired,
        "tiers": tier_results,
    }


def load_slo_configs(data: Mapping[str, Any]) -> dict[str, SLOConfig]:
    """Build configs from a parsed ``config/slo_targets.json``-shaped mapping."""
    slos = data.get("slos")
    if not isinstance(slos, list) or not slos:
        raise ValueError("slo config document must carry a non-empty 'slos' list")
    default_tiers = data.get("tiers")
    out: dict[str, SLOConfig] = {}
    for entry in slos:
        cfg = SLOConfig.from_dict(entry, default_tiers=default_tiers)
        if cfg.name in out:
            raise ValueError(f"duplicate slo name: {cfg.name}")
        out[cfg.name] = cfg
    return out
