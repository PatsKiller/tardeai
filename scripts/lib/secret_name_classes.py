"""Central classification of environment-variable NAMES into broker / provider / credential classes.

2026-10-09 (n8n maturity B2-D2): the n8n run relay loaded the full secrets env (146 names, 38 broker and
provider keys) although it holds neither. Any process that must prove it holds no broker or provider
credential classifies the names in its environment with this module. Names only: nothing here reads,
returns, or logs a value.

  broker     -- brokerage / account-aggregation credentials and switches (Schwab, Alpaca, SnapTrade, Moomoo...)
  provider   -- paid LLM, market-data, search, and messaging vendor credentials
  credential -- any other secret-shaped name (token, secret, password, DSN, webhook, cookie, *_API_KEY...)

classify_name() returns the first matching class in that order, or None for a non-secret name.
"""

from __future__ import annotations

import re
from typing import Iterable

BROKER_NAME_RE = re.compile(
    r"^(SCHWAB|ALPACA|SNAPTRADE|MOOMOO|BROKER|IBKR|TRADIER|ROBINHOOD|FIDELITY|WEBULL|TASTY(TRADE|WORKS)?|ETRADE|"
    r"PLAID|TD_?AMERITRADE)(_|$)",
    re.I,
)
PROVIDER_NAME_RE = re.compile(
    r"^(OPENAI|ANTHROPIC|CLAUDE_API|GEMINI|GOOGLE_API|XAI|GROK|DEEPSEEK|MISTRAL|COHERE|GROQ|OPENROUTER|"
    r"TOGETHER|PERPLEXITY|FIREWORKS|HUGGINGFACE|HF|POLYGON|FINNHUB|FMP|ALPHA_VANTAGE|FRED|NEWSAPI|BRAVE|"
    r"FINVIZ|YOUTUBE|TWOCAPTCHA|TWILIO|SLACK|TELEGRAM|SMTP|REDDIT|TIINGO|IEX|QUANDL|NASDAQ_DATA)(_|$)",
    re.I,
)
CREDENTIAL_NAME_RE = re.compile(
    r"(api[_-]?key|secret|token|passw(or)?d|_pwd|bearer|credential|cookie|webhook|(^|_)dsn($|_)|"
    r"private_key|encryption_key|hmac_key|auth_token|access_key|client_id|consumer_key|login)",
    re.I,
)
CLASSES = ("broker", "provider", "credential")


def classify_name(name: str) -> str | None:
    text = str(name or "")
    if BROKER_NAME_RE.search(text):
        return "broker"
    if PROVIDER_NAME_RE.search(text):
        return "provider"
    if CREDENTIAL_NAME_RE.search(text):
        return "credential"
    return None


def classified(names: Iterable[str]) -> dict[str, list[str]]:
    """{class: sorted names} for every secret-shaped name. Names only."""
    out: dict[str, list[str]] = {cls: [] for cls in CLASSES}
    for name in names:
        cls = classify_name(name)
        if cls:
            out[cls].append(name)
    return {cls: sorted(v) for cls, v in out.items()}
