"""Hermes LLM extraction for Ross Cameron daily trade catalog.

Refines regex noise (AI, MACD, VWAP) into validated ticker lists + P&L from recap transcripts.
Uses local_llm.generate() with JSON-only response; falls back to regex hints on parse failure.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

# Trading jargon / English tokens that regex often mis-tags as tickers
_NOISE = {
    "I", "A", "AM", "PM", "ET", "EST", "EDT", "UTC", "USD", "CEO", "CFO", "IPO", "SEC", "FDA",
    "ATH", "ATL", "VWAP", "EMA", "SMA", "MACD", "RSI", "ATR", "OTC", "NYSE", "NASDAQ", "ETF",
    "AI", "US", "UK", "EU", "PRE", "POST", "RTH", "HALT", "LIVE", "RECAP", "TRADE", "TRADES",
    "ALL", "AND", "ARE", "BUT", "CAN", "DAY", "FOR", "GET", "HAD", "HAS", "HER", "HIS", "HOW",
    "ITS", "LET", "MAY", "NEW", "NOT", "NOW", "OFF", "ONE", "OUR", "OUT", "RED", "RUN", "SAY",
    "SEE", "SET", "THE", "TOO", "TOP", "TRY", "TWO", "USE", "WAS", "WAY", "WHO", "WHY", "WIN",
    "YES", "YOU", "BIG", "LOW", "HIGH", "GAP", "RVOL", "LONG", "SHORT", "STOP", "OPEN", "GREEN",
    "LOSS", "GAIN", "MADE", "FROM", "VERY", "MOST", "BEST", "WELL", "JUST", "ONLY", "ALSO",
    "THEN", "THAN", "WITH", "HAVE", "BEEN", "WERE", "WHAT", "WHEN", "WILL", "YOUR", "THEY",
    "THIS", "THAT", "HERE", "THERE", "OVER", "UNDER", "INTO", "BACK", "DOWN", "UP", "ON", "IN",
    "AT", "BY", "AS", "IS", "BE", "DO", "GO", "NO", "SO", "IF", "AN", "OR", "OF", "TO", "IT",
    "WE", "HE", "SHE", "MY", "ME", "STOCK", "STOCKS", "MARKET", "SHARE", "SHARES", "POINT",
    "POINTS", "DOLLAR", "DOLLARS", "GREEN", "MONEY", "ACCOUNT", "SIZE", "FLOAT", "VOLUME",
    "CHART", "LEVEL", "LEVELS", "BREAK", "BREAKOUT", "PULLBACK", "ENTRY", "EXIT", "SETUP",
}

_SYM_RE = re.compile(r"^[A-Z]{2,5}$")
_PNL_CAP = 150_000.0
_PNL_FLOOR = 50.0


def is_valid_ticker(sym: str, known: set[str] | None = None) -> bool:
    s = str(sym or "").strip().upper()
    if not _SYM_RE.match(s):
        return False
    if s in _NOISE:
        return False
    if known and s not in known:
        # Prefer known symbols but allow novel tickers Ross traded outside our scan window
        pass
    return True


def filter_symbols(symbols: list[str], known: set[str] | None = None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in symbols or []:
        s = str(raw or "").strip().upper()
        if not is_valid_ticker(s, known) or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def sanitize_pnl(val: Any) -> float | None:
    if val is None:
        return None
    try:
        v = float(str(val).replace("$", "").replace(",", ""))
    except (TypeError, ValueError):
        return None
    if v < _PNL_FLOOR or v > _PNL_CAP:
        return None
    return round(v, 2)


def _parse_json_response(text: str) -> dict | None:
    clean = (text or "").strip()
    if "</think>" in clean:
        idx = clean.find("</think>")
        if idx >= 0:
            clean = clean[idx + len("</think>"):].strip()
    if clean.startswith("```"):
        parts = clean.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("{"):
                clean = part
                break
    start = clean.find("{")
    end = clean.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(clean[start : end + 1])
    except json.JSONDecodeError:
        return None


def build_hermes_prompt(
    title: str,
    text: str,
    trade_date: date | None,
    regex_hints: dict | None = None,
) -> str:
    excerpt = (text or "")[:8000]
    hints = regex_hints or {}
    hint_syms = ", ".join(hints.get("symbols_traded") or [])[:200]
    hint_pnl = hints.get("net_pnl_usd")
    td = str(trade_date) if trade_date else "unknown"
    return f"""You extract Ross Cameron / Warrior Trading day-trade recap facts from a YouTube transcript.

Return ONLY valid JSON (no markdown, no commentary) with this schema:
{{
  "trade_date": "YYYY-MM-DD",
  "net_pnl_usd": number or null,
  "symbols_traded": ["TICKER", ...],
  "winners": [{{"symbol": "TICKER", "pnl_usd": number or null, "note": "short"}}],
  "losers": [{{"symbol": "TICKER", "pnl_usd": number or null, "note": "short"}}],
  "confidence": 0.0-1.0,
  "notes": "brief extraction caveats"
}}

Rules:
- symbols_traded: ONLY real US stock tickers Ross actually traded that session (2-5 uppercase letters).
- EXCLUDE jargon: VWAP, MACD, EMA, AI, US, IPO, FDA, RVOL, PRE, POST, HALT, etc.
- net_pnl_usd: Ross's stated net P&L for the day in USD (not account size, not per-share). Typical day: $500-$50,000. null if unclear.
- winners/losers: symbols he calls out as wins/losses; pnl_usd only if explicitly stated for that symbol.
- trade_date: MUST be {td} (from video title/publish date — do not guess other years).
- confidence: how sure you are about symbols_traded list.

Video title: {title}
Regex hints (may be noisy — verify): symbols=[{hint_syms}] pnl={hint_pnl}

Transcript excerpt:
{excerpt}
"""


def _load_env() -> None:
    import os
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent.parent
    env_path = root / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def _call_llm_DEPRECATED(prompt: str, timeout: int = 90, *, skip_ollama: bool = False) -> str:
    """Deprecated — migrated to llm_lane.generate(lane='deepseek-flash')."""
    import json
    import os
    import urllib.request

    _load_env()
    ollama_timeout = min(timeout, 12)

    if not skip_ollama:
        try:
            import sys
            from pathlib import Path

            scripts = Path(__file__).resolve().parent.parent
            if str(scripts) not in sys.path:
                sys.path.insert(0, str(scripts))
            from local_llm_config import get_local_llm_base_url, get_local_llm_model

            payload = json.dumps({
                "model": get_local_llm_model(),
                "stream": False,
                "messages": [{"role": "user", "content": prompt}],
                "think": False,
                "options": {"temperature": 0.1, "num_predict": 1200},
            }).encode()
            req = urllib.request.Request(
                f"{get_local_llm_base_url().rstrip('/')}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=ollama_timeout) as resp:
                data = json.loads(resp.read())
                text = (data.get("message") or {}).get("content", "").strip()
                if text:
                    return text
        except Exception:
            pass

    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if openai_key:
        try:
            payload = json.dumps({
                "model": os.environ.get("ROSS_CATALOG_LLM", "gpt-4o-mini"),
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 1200,
            }).encode()
            req = urllib.request.Request(
                "https://api.openai.com/v1/chat/completions",
                data=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {openai_key}",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=min(timeout, 60)) as resp:
                data = json.loads(resp.read())
                text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
                if text:
                    return text
        except Exception:
            pass

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key)
            msg = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1200,
                messages=[{"role": "user", "content": prompt}],
            )
            return msg.content[0].text
        except Exception:
            pass
    return ""


def _call_llm(prompt: str, timeout: int = 90, *, skip_ollama: bool = False) -> str:
    """Ollama (fast fail) → DeepSeek Flash via llm_lane. Loads .env; no toll gate.
    Replaces OpenAI + Anthropic fallbacks with DeepSeek Flash for cataloging tasks."""
    import json
    import os
    import urllib.request

    _load_env()
    ollama_timeout = min(timeout, 12)

    if not skip_ollama:
        try:
            import sys
            from pathlib import Path

            scripts = Path(__file__).resolve().parent.parent
            if str(scripts) not in sys.path:
                sys.path.insert(0, str(scripts))
            from local_llm_config import get_local_llm_base_url, get_local_llm_model

            payload = json.dumps({
                "model": get_local_llm_model(),
                "stream": False,
                "messages": [{"role": "user", "content": prompt}],
                "think": False,
                "options": {"temperature": 0.1, "num_predict": 1200},
            }).encode()
            req = urllib.request.Request(
                f"{get_local_llm_base_url().rstrip('/')}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=ollama_timeout) as resp:
                data = json.loads(resp.read())
                text = (data.get("message") or {}).get("content", "").strip()
                if text:
                    return text
        except Exception:
            pass

    # Fallback to DeepSeek Flash (replaces OpenAI + Anthropic)
    try:
        from llm_lane import generate
        result = generate(prompt, lane="deepseek-flash", timeout=60)
        if result:
            return result
    except Exception:
        pass
    return ""


def extract_with_hermes(
    title: str,
    text: str,
    trade_date: date | None = None,
    known_symbols: set[str] | None = None,
    regex_hints: dict | None = None,
    *,
    use_llm: bool = True,
    skip_ollama: bool = False,
) -> dict[str, Any]:
    """LLM extraction with validation. Returns empty dict on total failure."""
    if not use_llm:
        return {}

    try:
        prompt = build_hermes_prompt(title, text, trade_date, regex_hints)
        raw = _call_llm(prompt, timeout=60, skip_ollama=skip_ollama)
    except Exception:
        return {}

    parsed = _parse_json_response(raw)
    if not parsed:
        return {}

    syms = filter_symbols(parsed.get("symbols_traded") or [], known_symbols)
    if not syms:
        # Merge winner/loser symbols as fallback
        for bucket in (parsed.get("winners") or []) + (parsed.get("losers") or []):
            if isinstance(bucket, dict) and bucket.get("symbol"):
                syms = filter_symbols(syms + [bucket["symbol"]], known_symbols)

    pnl = sanitize_pnl(parsed.get("net_pnl_usd"))
    if pnl is None and regex_hints:
        pnl = sanitize_pnl(regex_hints.get("net_pnl_usd"))

    winners = []
    for w in parsed.get("winners") or []:
        if not isinstance(w, dict):
            continue
        sym = str(w.get("symbol", "")).strip().upper()
        if not is_valid_ticker(sym, known_symbols):
            continue
        winners.append({
            "symbol": sym,
            "pnl_usd": sanitize_pnl(w.get("pnl_usd")),
            "note": str(w.get("note") or "hermes winner")[:80],
        })

    losers = []
    for lo in parsed.get("losers") or []:
        if not isinstance(lo, dict):
            continue
        sym = str(lo.get("symbol", "")).strip().upper()
        if not is_valid_ticker(sym, known_symbols):
            continue
        losers.append({
            "symbol": sym,
            "pnl_usd": sanitize_pnl(lo.get("pnl_usd")),
            "note": str(lo.get("note") or "hermes loser")[:80],
        })

    conf = parsed.get("confidence")
    try:
        conf_f = float(conf) if conf is not None else 0.7
    except (TypeError, ValueError):
        conf_f = 0.7

    td_raw = parsed.get("trade_date") or (str(trade_date) if trade_date else None)
    td_out = None
    if td_raw:
        try:
            td_out = date.fromisoformat(str(td_raw)[:10])
        except ValueError:
            td_out = trade_date

    return {
        "trade_date": td_out,
        "symbols_traded": syms,
        "winners": winners or [{"symbol": s, "pnl_usd": None, "note": "hermes traded"} for s in syms[:15]],
        "losers": losers,
        "net_pnl_usd": pnl,
        "extraction_confidence": min(max(conf_f, 0.5), 0.98),
        "hermes_review_json": {
            "model_notes": str(parsed.get("notes") or "")[:300],
            "raw_symbol_count": len(parsed.get("symbols_traded") or []),
            "validated_symbol_count": len(syms),
        },
    }


def merge_regex_and_hermes(regex_entry: dict, hermes: dict) -> dict:
    """Prefer Hermes symbols/P&L when confident; keep regex as fallback."""
    out = dict(regex_entry)
    if not hermes:
        return out

    if hermes.get("symbols_traded"):
        out["symbols_traded"] = hermes["symbols_traded"]
    if hermes.get("winners"):
        out["winners"] = hermes["winners"]
    if hermes.get("losers") is not None:
        out["losers"] = hermes["losers"]
    if hermes.get("net_pnl_usd") is not None:
        out["net_pnl_usd"] = hermes["net_pnl_usd"]
    # Keep regex/title-derived trade_date — LLM often hallucinates wrong years.

    out["extraction_method"] = "hermes"
    out["extraction_confidence"] = hermes.get("extraction_confidence", out.get("extraction_confidence", 0.7))
    hrj = dict(out.get("hermes_review_json") or {})
    hrj.update(hermes.get("hermes_review_json") or {})
    hrj["regex_symbols"] = regex_entry.get("symbols_traded")
    hrj["regex_pnl"] = regex_entry.get("net_pnl_usd")
    out["hermes_review_json"] = hrj
    return out