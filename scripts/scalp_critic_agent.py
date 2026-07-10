#!/usr/bin/env python3
"""scalp_critic_agent.py — Post-scoring critique for Trade AI pipeline.

Three-stage review per ticker:
  Stage 1: Instant danger flags (reverse splits, micro-float, sub-dollar spikes)
  Stage 2: Catalyst headline validation (generic/mismatched detection + Yahoo fallback)
  Stage 3: LLM critique via qwen3:1.7b (verdict: CONFIRM / DOWNGRADE / BLOCK)

Called by trade_ai_orchestrator.py after score_all() returns.
Modifies the scored ticker dicts in-place:
  - Adds critic_verdict, critic_reasoning, critic_flags, etc.
  - Can change decision (GO → WAIT, GO → NO_GO)
  - Stores original_decision for audit trail

Can also run standalone: python3 scripts/scalp_critic_agent.py --test
"""
import os, sys, re, json, time, logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger('scalp_critic')

# ── Stage 1: Danger Flags ────────────────────────────────────────────────────

def check_danger_flags(symbol: str, ticker: dict) -> List[str]:
    """Fast checks — no LLM needed. Returns list of flag strings."""
    flags = []

    # Reverse split in last 60 days
    try:
        import yfinance as yf
        import pandas as pd
        actions = yf.Ticker(symbol).actions
        if actions is not None and not actions.empty and 'Stock Splits' in actions.columns:
            cutoff = pd.Timestamp.now(tz=actions.index.tz) - timedelta(days=60) if actions.index.tz else pd.Timestamp.now() - timedelta(days=60)
            recent = actions[(actions.index >= cutoff) & (actions['Stock Splits'] > 0) & (actions['Stock Splits'] < 1.0)]
            if not recent.empty:
                ratio = recent['Stock Splits'].iloc[-1]
                dt = recent.index[-1].strftime('%Y-%m-%d')
                flags.append(f"REVERSE_SPLIT:{ratio:.2f}:1 on {dt} (delisting avoidance)")
    except Exception as e:
        log.debug(f"{symbol} split check: {e}")

    # Float < 2M
    try:
        float_m = float(ticker.get('float_m', 0) or 0)
        if 0 < float_m < 2.0:
            flags.append(f"MICRO_FLOAT:{float_m:.1f}M shares (manipulation/halt risk)")
    except Exception:
        pass

    # Sub-$2 price + >30% spike
    try:
        price = float(ticker.get('price', 0) or 0)
        change = abs(float(ticker.get('change_percent', ticker.get('change_pct', 0)) or 0))
        if price > 0 and price < 2.0 and change > 30:
            flags.append(f"LOW_PRICE_SPIKE:${price:.2f} up {change:.0f}% (pump/split distortion)")
    except Exception:
        pass

    # Momentum scalp float/RVOL/catalyst assessment
    # Ideal setup: float <20M (prime <10M), RVOL 5x+, catalyst present
    # Only flag negatives — the setup itself is NOT a danger signal
    try:
        float_m = float(ticker.get('float_m', 0) or 0)
        rvol = float(ticker.get('relative_volume', ticker.get('rvol', 0)) or 0)
        catalyst = ticker.get('catalyst') or ticker.get('catalyst_headline') or ''
        catalyst_verified = ticker.get('catalyst_verified', False)

        # Float assessment
        if float_m > 20.0:
            flags.append(f"FLOAT_TOO_LARGE:{float_m:.1f}M (momentum scalp wants <20M, prime <10M)")
        elif float_m < 0.5 and rvol > 15.0:
            # Sub-500K float with extreme RVOL = genuine halt risk
            flags.append(f"MICRO_FLOAT_HALT_RISK:{rvol:.1f}x on {float_m:.1f}M float (halt likely)")

        # RVOL assessment — 5x+ is REQUIRED for momentum scalps
        if 0 < rvol < 5.0 and float_m < 20.0:
            flags.append(f"RVOL_INSUFFICIENT:{rvol:.1f}x (momentum scalp needs 5x+ min)")

        # Catalyst assessment — required for conviction
        if float_m < 20.0 and rvol >= 5.0 and not catalyst and not catalyst_verified:
            flags.append(f"NO_CATALYST:RVOL {rvol:.1f}x on {float_m:.1f}M float — no catalyst found (verify before entry)")
    except Exception:
        pass

    return flags


# ── Stage 2: Catalyst Validation ─────────────────────────────────────────────

_GENERIC_PATTERNS = [re.compile(p, re.I) for p in [
    r"top gainers and losers", r"after.hours session", r"get insights into",
    r"stocks experiencing", r"biggest movers", r"market wrap",
    r"most active stocks", r"pre.?market movers", r"watch.*this week",
]]

def validate_catalyst(symbol: str, company: str, headline: str) -> tuple:
    """Returns (is_relevant, confidence, reason)."""
    if not headline or not headline.strip():
        return False, 0.0, "empty"
    hl = headline.lower()
    for p in _GENERIC_PATTERNS:
        if p.search(hl):
            return False, 0.05, f"generic_placeholder"
    score = 0.0
    parts = []
    if re.search(r'\b' + re.escape(symbol.lower()) + r'\b', hl):
        score += 0.6; parts.append("ticker_match")
    stop = {'inc','corp','ltd','llc','the','and','for','of','holdings','limited','group'}
    words = [w for w in re.split(r'\W+', company.lower()) if len(w) >= 3 and w not in stop]
    matched = [w for w in words if w in hl]
    if matched:
        score += min(0.6, len(matched) * 0.3); parts.append(f"company({','.join(matched[:2])})")
    return score >= 0.3, round(score, 2), ','.join(parts) or 'no_match'


def yahoo_headline_fallback(symbol: str) -> str:
    try:
        import feedparser
        feed = feedparser.parse(f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US")
        if feed.entries:
            return feed.entries[0].get('title', '') + ' [Yahoo]'
    except Exception:
        pass
    return ''


def industry_fallback(symbol: str) -> str:
    try:
        import yfinance as yf
        info = yf.Ticker(symbol).info
        return info.get('industry') or info.get('sector') or ''
    except Exception:
        return ''


# ── Stage 3: LLM Critique ───────────────────────────────────────────────────

def _call_ollama(prompt: str, timeout: int = 60) -> str:
    """Route through local_llm.generate() for audit + fallback."""
    try:
        from local_llm import generate
        return generate(prompt, timeout=timeout,
                        caller="scalp_critic_agent", process_type="STANDARD") or ""
    except Exception as e:
        log.warning(f"LLM error: {e}")
        return ""


def llm_critique(ticker: dict, flags: list, cat_valid: bool, cat_score: float, industry: str) -> dict:
    sym = ticker.get('symbol', '?')
    decision = ticker.get('decision', '?')
    score = ticker.get('score', 0)
    price = ticker.get('price', 0)
    rvol = ticker.get('relative_volume', ticker.get('rvol', 0))
    float_m = ticker.get('float_m', '?')
    catalyst = (ticker.get('top_catalyst') or {}).get('title', ticker.get('catalyst', 'None'))

    flags_txt = '\n'.join(f"  - {f}" for f in flags) if flags else "  None"
    cat_txt = f"VALID ({cat_score:.2f})" if cat_valid else f"INVALID ({cat_score:.2f})"

    prompt = f"""You are a professional scalp trade critic. Review this signal.
CONFIRM = signal is sound. DOWNGRADE = reduce decision. BLOCK = this is a trap.

{sym}: {decision} (Score {score}) | ${price} | RVOL {rvol}x | Float {float_m}M | Industry: {industry or 'Unknown'}
Catalyst: {catalyst}
Catalyst status: {cat_txt}
Danger flags:
{flags_txt}

Reply with ONLY JSON:
{{"verdict":"CONFIRM"|"DOWNGRADE"|"BLOCK","final_decision":"GO"|"WAIT"|"NO_GO","confidence":0.0-1.0,"reasoning":"1-2 sentences"}}"""

    raw = _call_ollama(prompt)
    if raw:
        # Strip thinking tags
        clean = raw.strip()
        if "<think>" in clean:
            idx = clean.find("</think>")
            if idx >= 0: clean = clean[idx + 8:].strip()
        m = re.search(r'\{.*\}', clean, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass

    # Fallback: auto-block only on hard danger flags, downgrade on warnings
    _hard_block_prefixes = ("MICRO_FLOAT_EXTREME_RVOL:", "LOW_PRICE_SPIKE:", "MICRO_FLOAT:")
    _rs_flags = [f for f in flags if f.startswith("REVERSE_SPLIT:")]
    _hard_flags = [f for f in flags if any(f.startswith(p) for p in _hard_block_prefixes)]
    _warn_flags = [f for f in flags if f not in _hard_flags and f not in _rs_flags]
    if _hard_flags:
        return {"verdict": "BLOCK", "final_decision": "NO_GO", "confidence": 0.9,
                "reasoning": f"Auto-blocked: {_hard_flags[0]}"}
    if _rs_flags:
        return {"verdict": "DOWNGRADE", "final_decision": "MANUAL_REVIEW", "confidence": 0.85,
                "reasoning": f"Squeeze manual review: {_rs_flags[0]}"}
    if _warn_flags:
        return {"verdict": "DOWNGRADE", "final_decision": "WAIT", "confidence": 0.6,
                "reasoning": f"Caution: {_warn_flags[0]}"}
    return {"verdict": "CONFIRM", "final_decision": decision, "confidence": 0.5,
            "reasoning": "LLM unavailable — original preserved"}


# ── Public API: critique a list of scored tickers ────────────────────────────

def critique_scored_tickers(scored: list, only_go_wait: bool = True, max_tickers: int = 10) -> dict:
    """Run the 3-stage critic on scored tickers. Modifies dicts in-place.

    Args:
        scored: list of scored ticker dicts from scoring.score_all()
        only_go_wait: if True, only critique GO and WAIT tickers (saves time)
        max_tickers: max tickers to review (prevents LLM bottleneck)

    Returns summary dict.
    """
    to_critique = scored if not only_go_wait else [t for t in scored if t.get('decision') in ('GO', 'WAIT')]
    if len(to_critique) > max_tickers:
        to_critique = sorted(to_critique, key=lambda t: t.get('score', 0), reverse=True)[:max_tickers]
    log.info(f"Scalp Critic: reviewing {len(to_critique)} of {len(scored)} tickers")

    summary = {'critiqued': 0, 'blocked': 0, 'downgraded': 0, 'confirmed': 0, 'changes': []}

    for ticker in to_critique:
        sym = ticker.get('symbol', '?')
        original = ticker.get('decision', 'AVOID')

        # Stage 1
        flags = check_danger_flags(sym, ticker)

        # Stage 2
        company = ticker.get('company', sym)
        top_cat = ticker.get('top_catalyst') or {}
        headline = top_cat.get('title', '')
        cat_valid, cat_score, cat_reason = validate_catalyst(sym, company, headline)

        if not cat_valid and headline:
            fallback = yahoo_headline_fallback(sym)
            if fallback:
                log.info(f"  [{sym}] Yahoo fallback: {fallback[:60]}")
                if top_cat:
                    top_cat['title'] = fallback
                    ticker['top_catalyst'] = top_cat
                cat_valid2, cat_score2, _ = validate_catalyst(sym, company, fallback)
                if cat_valid2:
                    cat_valid, cat_score = cat_valid2, cat_score2

        # Industry fallback
        ind = ticker.get('industry', ticker.get('sector', ''))
        if not ind or ind.lower() in ('', 'unknown', 'unclassified'):
            fb = industry_fallback(sym)
            if fb:
                ind = fb
                ticker['industry'] = fb

        # Stage 3
        critique = llm_critique(ticker, flags, cat_valid, cat_score, ind)

        verdict = critique.get('verdict', 'CONFIRM')
        final = critique.get('final_decision', original)
        confidence = critique.get('confidence', 0.5)
        reasoning = critique.get('reasoning', '')
        changed = final != original

        # Write critique fields into the ticker dict
        ticker['critic_verdict'] = verdict
        ticker['critic_confidence'] = confidence
        ticker['critic_reasoning'] = reasoning
        ticker['critic_flags'] = flags
        ticker['original_decision'] = original
        ticker['decision_changed'] = changed
        ticker['catalyst_verified'] = cat_valid
        ticker['catalyst_confidence'] = cat_score
        ticker['industry_resolved'] = ind

        if verdict == 'BLOCK':
            ticker['decision'] = 'NO_GO'
            ticker['disqualified'] = True
            ticker['disqualification_reason'] = reasoning
        elif verdict == 'DOWNGRADE' and final != original:
            ticker['decision'] = final

        log.info(f"  [{sym}] {verdict} conf={confidence:.2f} {original}→{ticker['decision']}{' CHANGED' if changed else ''}")

        summary['critiqued'] += 1
        if verdict == 'BLOCK': summary['blocked'] += 1
        elif verdict == 'DOWNGRADE': summary['downgraded'] += 1
        else: summary['confirmed'] += 1

        if changed:
            summary['changes'].append({'symbol': sym, 'from': original, 'to': ticker['decision'], 'reason': reasoning[:80]})

        time.sleep(0.3)

    return summary


def send_telegram_summary(summary: dict):
    """Send Telegram alert for blocked/downgraded tickers."""
    if summary.get('blocked', 0) == 0 and summary.get('downgraded', 0) == 0: return

    lines = [f"Trade AI Critique: {summary['critiqued']} reviewed"]
    lines.append(f"Confirmed: {summary['confirmed']} | Blocked: {summary['blocked']} | Downgraded: {summary['downgraded']}")
    for c in summary.get('changes', []):
        lines.append(f"  {c['symbol']}: {c['from']} -> {c['to']} -- {c['reason']}")
    msg = '\n'.join(lines)

    # Router suppresses generic critique summary on Telegram; always archived to Reports.
    try:
        from telegram_alert import send_telegram
        send_telegram(msg)
    except Exception:
        pass
    try:
        from report_capture import archive_message
        archive_message(msg, suppressed=False)
    except Exception:
        pass


# ── Standalone test mode ─────────────────────────────────────────────────────

def _test():
    """Test with synthetic TLIH and BOOM data."""
    test_tickers = [
        {
            'symbol': 'TLIH', 'company': 'Ten-League International Holdings',
            'score': 55, 'grade': 'A_plus', 'decision': 'GO',
            'price': 2.50, 'change_percent': 50.8, 'relative_volume': 16.6,
            'float_m': 0.5, 'industry': '', 'sector': '',
            'top_catalyst': {'title': 'Get insights into the top gainers and losers of Thursday after-hours session'},
        },
        {
            'symbol': 'BOOM', 'company': 'DMC Global Inc',
            'score': 51, 'grade': 'A_plus', 'decision': 'GO',
            'price': 18.0, 'change_percent': 15.0, 'relative_volume': 3.0,
            'float_m': 18.0, 'industry': '', 'sector': '',
            'top_catalyst': {'title': 'Western Digital and Sandisk crush Wall Street expectations on soaring AI demand'},
        },
    ]

    print("=== Scalp Critic Test ===\n")
    summary = critique_scored_tickers(test_tickers, only_go_wait=True)

    print(f"\n=== Results ===")
    for t in test_tickers:
        print(f"\n{t['symbol']}:")
        print(f"  Original: {t.get('original_decision')} → Final: {t['decision']}")
        print(f"  Verdict: {t.get('critic_verdict')} (conf={t.get('critic_confidence', 0):.2f})")
        print(f"  Flags: {t.get('critic_flags', [])}")
        print(f"  Catalyst verified: {t.get('catalyst_verified')}")
        print(f"  Industry: {t.get('industry_resolved', '?')}")
        print(f"  Reasoning: {t.get('critic_reasoning', '')[:100]}")

    print(f"\nSummary: {summary}")


if __name__ == '__main__':
    # Load env
    for line in (Path(__file__).parent.parent / '.env').read_text().splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ.setdefault(k.strip(), v.strip())

    if '--test' in sys.argv:
        _test()
    else:
        print("Usage: python3 scalp_critic_agent.py --test")
        print("In production, called by trade_ai_orchestrator.py after scoring.")
