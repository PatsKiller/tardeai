"""Shared empty-value encoding for Bitwarden SM (cannot store truly empty strings).

SM rejects empty values. We store this sentinel and decode to "" at render time.
Never use this string as a real secret value.
"""
EMPTY_SENTINEL = "__TRADEAI_EMPTY__"

# Known slots that should exist in SM even when unset (scaffold / optional).
# Names only — values always start empty until operator fills via modal.
BLANK_SCAFFOLD_KEYS = (
    "ALPACA_IRA_API_KEY",
    "ALPACA_IRA_SECRET_KEY",
    "ALPACA_PAPER_API_KEY",
    "ALPACA_PAPER_SECRET_KEY",
    "GEMINI_API_KEY",
    "REPORT_CLAUDE_MODEL",
)


def encode_empty(value: str) -> str:
    if value is None or value == "":
        return EMPTY_SENTINEL
    return value


def decode_empty(value: str) -> str:
    if value is None:
        return ""
    if value == EMPTY_SENTINEL:
        return ""
    return value
