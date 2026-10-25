"""Pure escalation text using the current Watch destination and central URL encoder."""
from __future__ import annotations

if __package__ and __package__.startswith("scripts."):
    from scripts.notification_url_builder import build_dashboard_url
else:  # scripts-only worker launch layout
    from notification_url_builder import build_dashboard_url


def build_escalation_message(symbol: str, recommendation: str, confidence: float, reasons: list[str]) -> str:
    review = build_dashboard_url("/v3/watch", {"tab": "my-watchlist", "symbol": symbol})
    return (
        f"\U0001F6A8 *Escalation: {symbol}*\n"
        f"Synthesis: {recommendation} ({confidence:.0%} confidence)\n"
        f"Reasons: {', '.join(reasons)}\n"
        f"Review at: {review}"
    )
