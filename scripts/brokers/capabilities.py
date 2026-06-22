"""BrokerCapabilityRegistry (ADR-B1 §4): single source of truth for what each broker can express.

Levels: native | composed | degraded | blocked. The UI shows/hides controls from this; validation produces
operator-readable messages from it; translators consult it before emitting. Confidence annotations carry the
matrix labels (VERIFIED-LIVE / VERIFIED-SDK / UNVERIFIED) so the product never overstates support.
"""
from __future__ import annotations

CAPS: dict[str, dict] = {
    "alpaca": {
        "execution_mode_default": "PAPER_TRAINING",
        "environment": "paper",
        "features": {
            "entry.market":        {"level": "native"},
            "entry.limit":         {"level": "native"},
            "entry.stop":          {"level": "native"},
            "entry.stop_limit":    {"level": "native"},
            "entry.moc_loc":       {"level": "blocked", "msg": "MOC/LOC not supported on Alpaca paper"},
            "entry.price_link":    {"level": "blocked", "msg": "bid/ask-linked entries not representable on Alpaca"},
            "exit.bracket":        {"level": "native", "note": "order_class=bracket (1 target)"},
            "exit.oco":            {"level": "composed", "note": "monitor cancels sibling"},
            "exit.trailing":       {"level": "degraded", "note": "monitor-synthetic replace_stop (BE@1R, trail@2R)"},
            "exit.multi_target":   {"level": "composed", "note": "monitor partial closes"},
            "ladder":              {"level": "composed", "note": "N independent intents; our cancel coordination"},
            "tif.day":             {"level": "native"},
            "tif.gtc":             {"level": "native"},
            "tif.fok_ioc":         {"level": "blocked", "msg": "FOK/IOC not used on paper"},
            "session.extended":    {"level": "degraded", "note": "extended_hours flag; limit-only after hours"},
            "short":               {"level": "native", "note": "paper only"},
            "options":             {"level": "blocked", "msg": "options not supported in paper pipeline"},
            "fractional":          {"level": "blocked", "msg": "integer share qty only in our pipeline"},
            "replace":             {"level": "composed", "note": "cancel+repost"},
            "streaming_orders":    {"level": "blocked", "msg": "polling only"},
        },
    },
    "schwab": {
        # Stage 2b SB-1 (operator-approved 2026-06-12): mode is now LIVE_ENABLED_FUTURE — the guard's
        # gated branch is REACHABLE but fail-closed until ALL standing locks open (env flag + DB
        # control row + standing signed approval) AND per-order: canary gate + pilot caps + 2FA.
        # Disarmed state (any lock closed) behaves exactly like BROKER_DISABLED.
        "execution_mode_default": "LIVE_ENABLED_FUTURE",
        "environment": "live-only (NO paper environment exists)",
        "features": {
            "entry.market":        {"level": "native", "confidence": "VERIFIED-SDK"},
            "entry.limit":         {"level": "native", "confidence": "VERIFIED-SDK"},
            "entry.stop":          {"level": "native", "confidence": "VERIFIED-SDK"},
            "entry.stop_limit":    {"level": "native", "confidence": "VERIFIED-SDK"},
            "entry.moc_loc":       {"level": "native", "confidence": "VERIFIED-SDK"},
            "entry.price_link":    {"level": "native", "confidence": "VERIFIED-SDK",
                                    "note": "price_link_basis BID/ASK + StopType BID/ASK"},
            "exit.bracket":        {"level": "native", "confidence": "VERIFIED-SDK",
                                    "note": "TRIGGER -> child OCO (OTOCO)"},
            "exit.oco":            {"level": "native", "confidence": "VERIFIED-SDK"},
            "exit.trailing":       {"level": "native", "confidence": "VERIFIED-SDK",
                                    "note": "TRAILING_STOP basis x VALUE/PERCENT/TICK x offset"},
            "exit.multi_target":   {"level": "composed", "confidence": "UNVERIFIED",
                                    "note": "OCO of N limits w/ qty split — runtime acceptance unverified"},
            "ladder":              {"level": "composed", "confidence": "VERIFIED-SDK",
                                    "note": "N orders; rung cancel policy is ours"},
            "tif.day":             {"level": "native", "confidence": "VERIFIED-SDK"},
            "tif.gtc":             {"level": "native", "confidence": "VERIFIED-SDK"},
            "tif.fok_ioc":         {"level": "native", "confidence": "VERIFIED-SDK"},
            "session.extended":    {"level": "native", "confidence": "VERIFIED-SDK", "note": "AM/PM/SEAMLESS"},
            "short":               {"level": "native", "confidence": "VERIFIED-SDK",
                                    "note": "SELL_SHORT/BUY_TO_COVER — translation only this phase"},
            "options":             {"level": "native", "confidence": "VERIFIED-SDK(schema)",
                                    "note": "single-leg + NET_CREDIT vertical; requires options_pilot_arm --approve + 2FA"},
            "options.credit_spread": {"level": "native", "confidence": "VERIFIED-SDK(schema)",
                                      "note": "2-leg vertical NET_CREDIT; policy envelope + 2FA"},
            "fractional":          {"level": "blocked", "confidence": "UNVERIFIED",
                                    "msg": "API fractional support unverified — REQUIRES OFFICIAL DOC CONFIRMATION"},
            "replace":             {"level": "blocked", "confidence": "UNVERIFIED",
                                    "msg": "replace_order FENCED (NotProvenWrite); semantics unverified"},
            "streaming_orders":    {"level": "blocked", "confidence": "UNVERIFIED",
                                    "msg": "ACCT_ACTIVITY stream exists in schema; untested; Rule-9 fenced"},
        },
    },
    "fidelity": {
        "execution_mode_default": "LIVE_ENABLED_FUTURE",
        "environment": "live (monitored — no broker write API)",
        "features": {
            "entry.stop":          {"level": "degraded", "note": "monitored + 2FA + Active Trader ticket"},
            "entry.stop_limit":    {"level": "degraded", "note": "monitored + 2FA + Active Trader ticket"},
            "exit.trailing":       {"level": "degraded", "note": "monitored ratchet + 2FA on breach"},
            "tif.gtc":             {"level": "degraded", "note": "software-monitored GTC level"},
        },
    },
    "snaptrade": {
        "execution_mode_default": "LIVE_ENABLED_FUTURE",
        "environment": "live (broker-dependent; Fidelity read-only today)",
        "features": {
            "entry.stop":          {"level": "native", "confidence": "VERIFIED-SDK", "note": "Stop via get_order_impact"},
            "entry.stop_limit":    {"level": "native", "confidence": "VERIFIED-SDK", "note": "StopLimit"},
            "exit.trailing":       {"level": "blocked", "msg": "no TrailingStop in SnapTrade equity API"},
        },
    },
}


def get(broker: str) -> dict:
    return CAPS.get(broker, {"execution_mode_default": "BROKER_DISABLED", "features": {}})


def feature(broker: str, key: str) -> dict:
    return get(broker).get("features", {}).get(key,
            {"level": "blocked", "msg": f"unknown capability '{key}' — fail closed"})


def annotate_intent(broker: str, intent) -> list[dict]:
    """Capability annotations for an OrderIntent — drives UI hints + validation messages."""
    from .order_intent import EntryMethod
    out = []

    def add(key):
        f = feature(broker, key)
        out.append({"capability": key, **f})

    m = intent.entry.method
    add({"MARKET": "entry.market", "LIMIT": "entry.limit", "STOP": "entry.stop",
         "STOP_LIMIT": "entry.stop_limit", "MARKET_ON_CLOSE": "entry.moc_loc",
         "LIMIT_ON_CLOSE": "entry.moc_loc"}[m.value])
    if intent.entry.price_link:
        add("entry.price_link")
    if intent.exit_policy.stop and intent.exit_policy.targets and intent.exit_policy.oco:
        add("exit.bracket")
    if intent.exit_policy.stop and intent.exit_policy.stop.trail:
        add("exit.trailing")
    if len(intent.exit_policy.targets) > 1:
        add("exit.multi_target")
    if intent.ladder:
        add("ladder")
    if intent.session.value != "NORMAL":
        add("session.extended")
    if intent.direction.value == "SHORT":
        add("short")
    if intent.instrument.asset_type.value == "OPTION" or intent.instrument.option_legs:
        add("options")
        if getattr(intent.instrument, "spread_type", None) and intent.instrument.spread_type.value == "CREDIT_SPREAD":
            add("options.credit_spread")
    if intent.quantity.notional:
        add("fractional")
    add({"DAY": "tif.day", "GTC": "tif.gtc"}.get(intent.tif.value, "tif.fok_ioc"))
    return out
