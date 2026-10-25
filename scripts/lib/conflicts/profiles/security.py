"""Binding T0–T4/R1–R16 security rules. All inputs and clocks are supplied."""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import math
from zoneinfo import ZoneInfo

from ..engine import COMPATIBLE, OPPOSITE, SAME, UNKNOWN, Finding, Input, side
from .rulebook import RULEBOOK
from .vocabulary import normalize, ordinal, posture

SEC = RULEBOOK["security_stance"]


def _at(value):
    return value if isinstance(value, datetime) and value.tzinfo and value.utcoffset() is not None else None


def material_at(item):
    """Explicit material watermark dominates run time; never stamp a poll clock."""
    return _at(item.inputs_as_of) if item.inputs_as_of is not None or item.metadata.get("material_time_required") else _at(item.as_of)


def trading_age(at, now):
    if not at:
        return None
    from scripts.lib.cio_market_session import NYSESessionService
    service = NYSESessionService()
    current = now.astimezone(ZoneInfo("America/New_York"))
    day = at.astimezone(service.tz).date() + timedelta(days=1)
    count = 0
    while day <= current.date():
        if service.is_trading_day(day):
            opened, _, _ = service.official_bounds(day)
            if day < current.date() or current >= opened:
                count += 1
        day += timedelta(days=1)
    return count


@dataclass
class SecurityStanceProfile:
    name: str = "security_stance"
    canonical_source: str = "the CIO"
    canonical_max_age: timedelta = timedelta(days=2)
    flap_limit: int = RULEBOOK["universal"]["flap_limit"]
    flap_window: timedelta = timedelta(days=RULEBOOK["universal"]["flap_window_days"])

    def describe(self, value):
        if isinstance(value, dict):
            return f"{value.get('exposure_pct', 'unknown')}% exposure; {value.get('limit_pct', 'unknown')}% IPS limit"
        return normalize(value).replace("_", " ") or "—"

    def compare(self, a, b, subject):
        x, y = ordinal(a, subject.context.get("held")), ordinal(b, subject.context.get("held"))
        if x is None or y is None:
            return UNKNOWN
        if x == y:
            return SAME if normalize(a) == normalize(b) else COMPATIBLE
        if not subject.context.get("held"):
            return OPPOSITE
        return COMPATIBLE if abs(x - y) == 1 and not (subject.context.get("held") and {x, y} == {0, 2}) else OPPOSITE

    def supersede_after(self, source):
        days = SEC["supersede_days"].get(source, SEC["default_supersede_days"])
        return timedelta(days=min(14, days))

    def owner_review_action(self):
        return "queue_review"

    def evaluate_domain(self, subject, canonical, inputs, *, now, history):
        ctx = subject.context
        inputs = [replace(item, role="claim") if item.source == "trade_ai" and normalize(item.value) == "AVOID"
                  and item.role == "gate" else item for item in inputs]
        if ctx.get("archived") or ctx.get("unwatched") or ctx.get("expired") or ctx.get("paper"):
            return []
        pre = f"{subject.kind}:{subject.id}"
        output = []
        held = ctx.get("held")

        def finding(kind, rule, summary, clears, rows=(), *, action="none", owner="the CIO", never=False, suffix=""):
            value = Finding(kind, rule, summary, clears, action, "operator" if kind == "NEEDS_OPERATOR" else
                            "block" if kind == "GATE" else "warn" if kind in {"DATA_ERROR", "CONFLICT"} else "info",
                            [side(i, self) for i in rows], f"{pre}:{rule}" + (":" + suffix if suffix else ""),
                            owner=owner, next_run=ctx.get("next_run") or "next registered producer run", never_auto=never)
            value.tier = 0 if rule == "T0" else 1 if kind == "DATA_ERROR" or rule in {"T1", "R9", "R12", "R16"} else 2 if rule == "R13" else 3 if rule in {"R3", "R7", "R7b"} else 4
            output.append(value)
            return value

        # T0 and T1 always survive the presence of a recorded judgment.
        for item in inputs:
            value = normalize(item.value)
            if item.role == "safety" and value in {"ENGAGED", "BLOCKED", "LOCKED", "HALT"}:
                finding("GATE", "T0", f"Blocked: {item.source}", "the operator clears the hard safety gate at its owner",
                        [item], owner="operator", never=True, suffix=item.source)
        invalid = []
        for item in ([canonical] if canonical else []) + inputs:
            if item.metadata.get("quality", "complete") != "complete":
                continue
            if any(value is not None and _at(value) is None for value in (item.as_of, item.inputs_as_of)) or any(
                    _at(value) and value > now for value in (item.as_of, item.inputs_as_of)):
                finding("DATA_ERROR", "R1", f"{item.source}: invalid material time", "the source corrects its evidence timestamp",
                        [], owner="source owner", suffix=item.source)
                invalid.append(item)
        if canonical in invalid:
            return output
        inputs = [item for item in inputs if item not in invalid]
        if subject.kind != "security" or not ctx.get("identity_confirmed", bool(subject.id)):
            finding("GATE", "R16", "Identity unresolved — every action is blocked", "the identity owner confirms the GUID",
                    owner="identity owner", never=True)
            return output
        if not isinstance(held, bool):
            finding("DATA_ERROR", "T1", "Ownership is unknown", "the canonical positions owner confirms ownership",
                    owner="positions owner", never=True)
            return output
        for item in ([canonical] if canonical else []) + inputs:
            if item.subject_id and item.subject_id != subject.id:
                finding("DATA_ERROR", "T1", "Sources identify different securities", "the source owner fixes the GUID join",
                        [item], owner="identity owner", never=True)
                return output
        facts = [i for i in inputs if i.role in {"fact", "protection"}]
        freeze = ctx.get("pending_fill", False)
        for item in facts:
            state = normalize(item.value)
            if item.role == "fact" and item.metadata.get("mismatch"):
                finding("DATA_ERROR", "T1", f"{item.source}: facts disagree", "the authoritative producer repairs the fact",
                        [item], owner="source owner", never=True, suffix=item.source)
                freeze = True
            if held and item.role == "protection" and state in {"AWAITING_FILL", "FILLED", "PENDING_ACTIVATION", "NONE", "UNKNOWN"}:
                finding("DATA_ERROR" if state in {"AWAITING_FILL", "FILLED"} else "NEEDS_OPERATOR", "R12",
                        f"Protection state: {self.describe(state)}", "the broker/positions owner confirms the fill or protection plan",
                        [item], action="notify_operator", owner="operator", never=True, suffix=f"{item.source}:{item.account or ''}")
                freeze = freeze or state in {"AWAITING_FILL", "FILLED"}
        if freeze:
            if not any(f.rule == "R12" for f in output):
                finding("DATA_ERROR", "R12", "Pending fill — stance evaluation frozen", "positions and the pending fill reconcile",
                        facts, owner="positions owner", never=True)
            return output
        # T4 operator > recorded CIO > curator > opinions; approval never overrides T0/T1.
        decisions = []
        for item in inputs:
            if item.metadata.get("recorded_by") in {"operator", "cio"}:
                expires = item.metadata.get("expires_at")
                if item.metadata.get("reason") and _at(expires) and expires > now:
                    decisions.append(item)
        if decisions:
            original = canonical
            canonical = min(decisions, key=lambda i: 0 if i.metadata["recorded_by"] == "operator" else 1)
            if original:
                inputs = [*inputs, original]
        if canonical is None or canonical.value is None:
            finding("GATE", "R7", "No CIO stance — " + ("HOLD" if held else "WATCH") + " by default",
                    "a working CIO producer records a stance from current evidence", action="queue_review")
            return output
        if posture(canonical.value) is None:
            finding("DATA_ERROR", "R8", f"Unmapped stance: {self.describe(canonical.value)}",
                    "the source supplies a label in the shared vocabulary", [canonical], owner="source owner")
            return output
        positive = ordinal(canonical.value, held) == 0
        can_at = material_at(canonical)
        if not can_at:
            finding("GATE", "R1", "Unknown: CIO material evidence time is missing", "the CIO refreshes its oldest material input",
                    [canonical], action="queue_refresh")
        elif can_at > now:
            finding("DATA_ERROR", "R1", "CIO material evidence is in the future", "the producer corrects its evidence time",
                    [canonical], owner="source owner")
            return output
        age = trading_age(can_at, now)
        if age is not None and (age > SEC["refresh_after_trading_days"] or positive and age > SEC["canonical_max_age_trading_days"]):
            finding("GATE", "R7b", f"CIO stance material evidence is {age} trading days old",
                    "the CIO refreshes its material evidence", [canonical], action="queue_refresh")
        for item in inputs:
            value = normalize(item.value)
            if item.role == "policy" and isinstance(item.value, dict):
                policy = item.value
                weight, limit = policy.get("exposure_pct"), policy.get("limit_pct")
                known = not policy.get("gap") and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                                                     for v in (weight, limit))
                value = "BREACH" if known and weight > limit else "CLEAR" if known else "UNKNOWN"
                if value == "UNKNOWN" and positive:
                    finding("GATE", "R13", "Unknown: " + (item.detail or "look-through exposure"),
                            "the canonical exposure and fund coverage are complete", [item], owner="positions owner", suffix=item.source)
                near = policy.get("near_limit_pct", policy.get("near_pct"))
                if known and isinstance(near, (int, float)) and near <= weight <= limit:
                    finding("AGREEMENT", "R13", "Near policy limit: " + (item.detail or item.source),
                            "exposure falls below the canonical near-limit threshold", [item], owner="positions owner", suffix=item.source)
            if item.role == "policy" and value == "BREACH":
                finding("NEEDS_OPERATOR" if positive else "GATE", "R13", "Blocked: IPS headroom",
                        "headroom satisfies the single IPS limit or the operator records a permitted exception",
                        [item], owner="operator", action="notify_operator" if positive else "none", never=positive, suffix=item.account or "all")
            if positive and item.source.startswith("wash_sale") and value not in {"PASS", "OK", "CLEAR"}:
                finding("GATE", "R9", "Blocked: taxable loss wash window applies to buys in every account",
                        "the canonical wash window expires", [item], owner="tax owner", never=True, suffix="all_accounts")
            elif positive and item.role == "gate":
                is_trade = item.source in {"trade_ai", "entry_state"}
                if is_trade and value == "AVOID":
                    continue
                allowed = value in (SEC["trade_go_clear"] if is_trade else SEC["gate_clear"])
                if not allowed or material_at(item) is None:
                    unknown = material_at(item) is None or value in {"STALE", "DATA_UNAVAILABLE", "UNKNOWN", ""}
                    finding("GATE", "R3", ("Unknown: " if unknown else "Blocked: ") + (item.detail or item.source),
                            f"{item.source} passes with current data", [item, canonical], suffix=f"{item.source}:{item.account or 'all'}")
        if positive and held and not any(f.rule == "R13" for f in output):
            policy = ctx.get("concentration_policy") or {}
            weight, limit = policy.get("weight_pct"), policy.get("limit_pct")
            if policy.get("gap") or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                                            for v in (weight, limit)) or limit <= 0:
                finding("GATE", "R13", "Unknown: IPS headroom", "the canonical aggregate supplies the current position weight",
                        [canonical], owner="positions owner")
            elif policy.get("status") == "breach" or weight > limit:
                finding("NEEDS_OPERATOR", "R13", f"Blocked: IPS {policy.get('instrument_class', 'position')} limit {limit:g}%",
                        "the position satisfies the canonical IPS headroom rule", [canonical], owner="operator",
                        action="notify_operator", never=True)
            elif policy.get("status") == "near_limit" or isinstance(policy.get("near_limit_pct"), (int, float)) and weight >= policy["near_limit_pct"]:
                finding("AGREEMENT", "R13", "Near IPS concentration limit", "exposure falls below the canonical near-limit threshold",
                        [canonical], owner="positions owner")
        candidates = []
        fresh_sides = []
        for item in inputs:
            if item is canonical or item.role not in {"claim", "judgment"} or item.metadata.get("recorded_by"):
                continue
            if item.metadata.get("paper") or item.metadata.get("quality", "complete") != "complete" or item.metadata.get("intra_synthesis"):
                continue
            if item.metadata.get("instrument", "equity") != "equity":
                if normalize(item.value) in {"LONG_CALL", "BUY_CALL"} and ordinal(canonical.value, held) == 3:
                    finding("NEEDS_OPERATOR", "R10", "Long-call thesis contradicts equity EXIT", "the owners record the cross-instrument decision",
                            [canonical, item], owner="operator", action="notify_operator", never=True)
                continue
            relation = self.compare(canonical.value, item.value, subject)
            if relation == UNKNOWN:
                finding("DATA_ERROR", "R8", f"Unmapped stance: {self.describe(item.value)}", "the source uses the shared vocabulary",
                        [item], owner="source owner", suffix=item.source)
                continue
            item_at = material_at(item)
            cadence = item.metadata.get("cadence_days")
            limit = min(14, 2 * cadence) if isinstance(cadence, (int, float)) and cadence > 0 else self.supersede_after(item.source).days
            if item_at and now - item_at <= timedelta(days=limit):
                fresh_sides.append(item)
            if relation in {SAME, COMPATIBLE}:
                finding("AGREEMENT", "R6", "Compatible action" + (" (strength differs)" if relation == COMPATIBLE else ""),
                        "—", [canonical, item], suffix=item.source)
                continue
            if not item_at or (now - item_at) > timedelta(days=limit):
                finding("SUPERSEDED", "R1", f"{item.source} material evidence is stale", f"{item.source} rewrites the compared input",
                        [item, canonical], action="queue_refresh" if item.metadata.get("writes_compared_input", False) else "none", suffix=item.source)
                continue
            candidates.append(item)
        if candidates:
            sides = [canonical, *fresh_sides]
            key = f"{pre}:R11" if len(sides) >= 3 else f"{pre}:U7:{candidates[0].source}"
            # One conflict, every fresh side. No majority vote.
            protected = held and any({ordinal(canonical.value, held), ordinal(i.value, held)} == {0, 3} for i in candidates)
            protected = protected or len(sides) >= 3 and any(i.metadata.get("recorded_by") for i in sides)
            recent = [h for h in history if h.get("key") == key and _at(h.get("opened_at")) and
                      timedelta(0) <= now - h["opened_at"] <= self.flap_window]
            protected = protected or len(recent) >= self.flap_limit
            signature = tuple(sorted((i.source, ordinal(i.value, held)) for i in sides))
            anchor = ctx.get("decision_anchor") or {}
            conviction = ctx.get("conviction")
            delta = abs(conviction - anchor.get("conviction", conviction)) if isinstance(conviction, (int, float)) and isinstance(
                anchor.get("conviction", conviction), (int, float)) else 0
            if anchor.get("signature") == [list(pair) for pair in signature] and delta < RULEBOOK["hysteresis"]["conviction_delta"]:
                finding("AGREEMENT", "R15", "Recorded resolution still holds", "—", sides)
                return output
            previous = history[-1] if history else {}
            matching = previous.get("key") == key and previous.get("signature") == [list(pair) for pair in signature]
            if not protected and not matching:
                observation = finding("AGREEMENT", "R15", "Disagreement observed — confirmation due next run", "—", sides)
                observation.key = key
                return output
            verdict = finding("NEEDS_OPERATOR" if protected else "CONFLICT", "R11" if len(sides) >= 3 else "U7",
                              "; ".join(f"{i.source}: {self.describe(i.value)}" for i in sides),
                              "the owner records a decision, reason and expiry against every side", sides,
                              action="notify_operator" if protected else "queue_review", owner="operator" if protected else "the CIO", never=protected)
            verdict.key = key
        return output
