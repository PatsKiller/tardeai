"""One vocabulary for the engine and CIO prospect posture; no fuzzy matches."""
from .rulebook import RULEBOOK


def normalize(value):
    return str(value or "").strip().upper().replace("-", "_").replace(" ", "_")


def posture(value):
    value = normalize(value)
    config = RULEBOOK["security_stance"]
    if value in {normalize(v) for v in config["unmapped_labels"]}:
        return None
    for family, values in config["families"].items():
        if value in values:
            return {"buy": "buy", "hold": "hold", "stand_aside": "watch", "reduce": "sell"}[family]
    return None


def ordinal(value, held):
    label = normalize(value)
    family = posture(value)
    if family is None:
        return None
    if not held:
        return 0 if family == "buy" else 1
    if family == "buy":
        return 0
    if family == "hold" or label in {"WATCH", "WAIT", "MONITOR", "NEUTRAL", "NOT_YET"}:
        return 1
    return 3 if label in {"SELL", "EXIT", "EXIT_REVIEW", "INVALIDATED"} else 2
