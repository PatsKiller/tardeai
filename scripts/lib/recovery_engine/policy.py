"""Policy loading and the three decision rules piece A owns: residual-aware held, materiality tier, eligibility.

Every value comes from ``config/recovery_policy.yaml``. A missing or malformed key is a refusal, never a silent default —
the failure mode this engine exists to kill is a quiet assumption.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

POLICY_REL = Path("config/recovery_policy.yaml")
MARKET_RISK_REL = Path("config/market_risk_policy.yaml")
SCHEMA = "RecoveryPolicy@v1"


class PolicyError(Exception):
    """The policy file is missing or cannot be trusted."""


@dataclass(frozen=True)
class Policy:
    materiality: Mapping[str, float]
    residual: Mapping[str, Any]
    triggers: Mapping[str, Any]
    confidence: Mapping[str, Any]
    eligibility: Mapping[str, Any]
    notification: Mapping[str, Any]
    as_of: str = ""
    source: str = ""

    @property
    def residual_fraction(self) -> float:
        return float(self.residual["residual_remaining_fraction"])

    @property
    def residual_abs_floor(self) -> float:
        return float(self.residual.get("residual_abs_floor_shares") or 0.0)


def load_policy(path: Optional[Path] = None) -> Policy:
    """Load and validate the policy. Refuses rather than defaulting."""
    target = Path(path or POLICY_REL)
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise PolicyError(f"recovery policy is missing ({target}): {exc}") from exc
    try:
        doc = _parse_yaml(text)
    except ValueError as exc:
        raise PolicyError(f"recovery policy is not readable YAML ({target}): {exc}") from exc
    if doc.get("schema") != SCHEMA:
        raise PolicyError(f"recovery policy schema is {doc.get('schema')!r}, expected {SCHEMA!r}")
    for section, keys in (
        ("materiality", ("t1_loss_usd", "t1_weight_pct", "t2_loss_usd", "t2_weight_pct")),
        ("residual", ("residual_remaining_fraction",)),
        ("triggers", ("r1_reclaim_exit_pct", "decay_sessions")),
        ("confidence", ("weights", "ready_floor")),
        ("eligibility", ("taxable_hold_days",)),
        ("notification", ("renudge_floor_minutes", "t1_never_suppressed")),
    ):
        block = doc.get(section)
        if not isinstance(block, Mapping):
            raise PolicyError(f"recovery policy has no usable {section!r} section")
        missing = [key for key in keys if key not in block]
        if missing:
            raise PolicyError(f"recovery policy {section} is missing {', '.join(missing)}")
    if float(doc["materiality"]["t1_loss_usd"]) <= float(doc["materiality"]["t2_loss_usd"]):
        raise PolicyError("materiality: t1_loss_usd must be larger than t2_loss_usd")
    fraction = float(doc["residual"]["residual_remaining_fraction"])
    if not 0.0 < fraction < 1.0:
        raise PolicyError("residual: residual_remaining_fraction must be between 0 and 1")
    if doc["notification"].get("t1_never_suppressed") is not True:
        raise PolicyError("notification: t1_never_suppressed must be true — a T1 case may never be silenced")
    _cross_check_operator_policy(doc, Path(path or POLICY_REL).parent.parent / MARKET_RISK_REL)
    return Policy(
        materiality=dict(doc["materiality"]),
        residual=dict(doc["residual"]),
        triggers=dict(doc["triggers"]),
        confidence=dict(doc["confidence"]),
        eligibility=dict(doc["eligibility"]),
        notification=dict(doc["notification"]),
        as_of=str(doc.get("as_of") or ""),
        source=str(target),
    )


def _cross_check_operator_policy(recovery: Mapping[str, Any], market_risk: Path) -> None:
    """The residual fraction and the wash window are operator-owned in market_risk_policy.yaml; never fork them."""
    try:
        import yaml  # local import: the recovery engine must not depend on PyYAML for its own file
        doc = yaml.safe_load(market_risk.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError, ImportError):
        return  # market-risk policy absent (tests, trimmed trees): the recovery file stands alone
    watch = ((doc.get("reentry_watch") or {}) if isinstance(doc, Mapping) else {}) or {}
    fraction = watch.get("residual_remaining_fraction")
    if fraction not in (None, "") and abs(float(fraction) - float(recovery["residual"]["residual_remaining_fraction"])) > 1e-9:
        raise PolicyError(
            f"recovery policy residual fraction {recovery['residual']['residual_remaining_fraction']} disagrees with "
            f"market_risk_policy.yaml reentry_watch.residual_remaining_fraction {fraction}")
    wash = watch.get("wash_sale_days")
    if wash not in (None, "") and int(wash) != int(recovery["eligibility"]["taxable_hold_days"]):
        raise PolicyError(
            f"recovery policy taxable_hold_days {recovery['eligibility']['taxable_hold_days']} disagrees with "
            f"market_risk_policy.yaml reentry_watch.wash_sale_days {wash}")


def _parse_yaml(text: str) -> dict[str, Any]:
    """Parse the small YAML subset this file uses, without a PyYAML dependency.

    Supports mappings, nested mappings by indentation, ``key: value`` scalars (str/int/float/bool),
    ``key: [a, b]`` inline lists, ``key: {}`` / ``[]`` empties and ``#`` comments. Anything else raises, so a policy
    file that grows a feature this parser does not understand fails loudly instead of being half-read.
    """
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip() if not _inside_quote(raw) else raw.rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        body = line.strip()
        if ":" not in body:
            raise ValueError(f"unexpected line: {raw!r}")
        key, _, value = body.partition(":")
        key = key.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        if not stack:
            raise ValueError(f"bad indentation near {raw!r}")
        parent = stack[-1][1]
        value = value.strip()
        if value == "":
            child: dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
            continue
        parent[key] = _scalar(value)
    return root


def _inside_quote(raw: str) -> bool:
    return raw.count('"') % 2 == 1 or raw.count("'") % 2 == 1


def _scalar(value: str) -> Any:
    if value in ("{}", "[]"):
        return {} if value == "{}" else []
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        return [_scalar(part.strip()) for part in inner.split(",")] if inner else []
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        return value[1:-1]
    lowered = value.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            continue
    return value


# ── Rule 1: residual-aware held ───────────────────────────────────────────────────────────────────────────────
def is_held(pre_exit_shares: Optional[float], residual_shares: Optional[float], policy: Policy) -> bool:
    """Is the position still *held* for re-entry purposes?

    The spec's failure: SPCX kept a 200-share taxable residual after being cut from ~1,000 by stops, and the engine
    treated the symbol as fully held, which killed the whole re-entry path. A residual is not a position unless it is a
    material fraction of what was there before. "Held" therefore requires:

    * a known pre-exit size — an unknown size can never mean held (policy ``unknown_pre_exit`` says not-held);
    * residual >= ``residual_remaining_fraction`` of pre-exit shares;
    * residual >= ``residual_abs_floor_shares`` when that floor is set.

    A fully closed position (residual 0) is obviously not held.
    """
    try:
        residual = float(residual_shares or 0.0)
    except (TypeError, ValueError):
        return False
    if residual <= 0:
        return False
    if pre_exit_shares in (None, ""):
        return str(policy.residual.get("unknown_pre_exit", "not_held")) == "held"
    try:
        pre_exit = float(pre_exit_shares)
    except (TypeError, ValueError):
        return False
    if pre_exit <= 0:
        return False
    if residual < policy.residual_fraction * pre_exit:
        return False
    if policy.residual_abs_floor and residual < policy.residual_abs_floor:
        return False
    return True


# ── Rule 2: materiality tier ─────────────────────────────────────────────────────────────────────────────────
def materiality_tier(realized_loss_usd: float, pre_exit_weight_pct: Optional[float], policy: Policy) -> str:
    """T1 / T2 / T3 from the realized loss or the former weight of the position. Losses are negative numbers."""
    loss = abs(float(realized_loss_usd or 0.0))
    weight = abs(float(pre_exit_weight_pct)) if pre_exit_weight_pct not in (None, "") else 0.0
    m = policy.materiality
    if loss >= float(m["t1_loss_usd"]) or weight >= float(m["t1_weight_pct"]):
        return "T1"
    if loss >= float(m["t2_loss_usd"]) or weight >= float(m["t2_weight_pct"]):
        return "T2"
    return "T3"


# ── Rule 3: per-account eligibility ──────────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class Eligibility:
    account: str
    eligible: bool
    eligible_from: Optional[str]
    reason: str

    def line(self) -> str:
        if self.eligible:
            return f"{self.account}: now"
        when = self.eligible_from or "unknown"
        return f"{self.account}: {when} ({self.reason})"


def eligibility_for(account: str, exit_date: date, policy: Policy, *, today: Optional[date] = None) -> Eligibility:
    """Per-account eligibility: a taxable exit carries the house hold; an IRA is eligible now (policy-controlled).

    The status word is always "IRA" / "taxable" derived from the account key, so the card can say
    "IRA: now · Taxable: 11-27" in one line per account.
    """
    conf = policy.eligibility
    key = str(account or "")
    lower = key.lower()
    is_ira = "ira" in lower or "roth" in lower or "401" in lower
    overrides = conf.get("accounts") or {}
    override = overrides.get(key) if isinstance(overrides, Mapping) else None
    if isinstance(override, Mapping):
        if override.get("eligible_now") is True:
            return Eligibility(key, True, None, "account policy: eligible now")
        if override.get("eligible_now") is False:
            when = override.get("eligible_from")
            return Eligibility(key, False, when, str(override.get("reason") or "account policy"))
    if is_ira and conf.get("ira_eligible_now") is True:
        return Eligibility(key, True, None, "IRA — wash/house hold does not apply")
    hold_days = int(conf.get("taxable_hold_days") or 0)
    eligible_from = exit_date + timedelta(days=hold_days)
    current = today or datetime.now(timezone.utc).date()
    if current >= eligible_from:
        return Eligibility(key, True, None, f"house hold ({hold_days} days) has passed")
    return Eligibility(key, False, eligible_from.isoformat(), f"house hold {hold_days} days after a taxable sale")
