#!/usr/bin/env python3
"""email_notifier.py — Send trade notification emails via gog Gmail CLI.

Uses gog (Google CLI) to send emails. No SMTP config needed.
Paper mode only. No trades, no orders.
"""
import logging, os, shutil, subprocess, sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
log = logging.getLogger(__name__)

OPERATOR_EMAIL = "john@jwwhiting.com"
GOG_ACCOUNT = "john@jwwhiting.com"

# gog lives in ~/.local/bin, which is on an interactive PATH but NOT on the minimal PATH
# cron hands a job (the crontab sets SHELL but no PATH). Every cron-launched email therefore
# died with "[Errno 2] No such file or directory: 'gog'" while Telegram still worked, so the
# operator silently lost the second channel. Resolve the binary explicitly (2026-07-29).
_GOG_FALLBACKS = (
    Path.home() / ".local" / "bin" / "gog",
    Path("/usr/local/bin/gog"),
    Path("/usr/bin/gog"),
)


def _gog_bin():
    """Absolute path to the gog CLI, or None when it genuinely is not installed."""
    found = shutil.which("gog")
    if found:
        return found
    for cand in _GOG_FALLBACKS:
        if cand.is_file() and os.access(cand, os.X_OK):
            return str(cand)
    return None


def _get_keyring_password():
    kp = Path(os.path.expanduser("~/.openclaw/credentials/gog_keyring_password"))
    if kp.exists():
        return kp.read_text().strip()
    return os.environ.get("GOG_KEYRING_PASSWORD", "")


def send_email(subject, body, to=None):
    """Send a plain-text email via gog gmail send."""
    to = to or OPERATOR_EMAIL
    try:  # FQDN/v3 normalization chokepoint (rewrite internal IPs + legacy /v2/ dashboard links)
        from notification_url_builder import publicize_message
        body = publicize_message(body)
    except Exception:
        pass
    pw = _get_keyring_password()
    if not pw:
        log.warning("No GOG_KEYRING_PASSWORD — skipping email")
        return False

    gog = _gog_bin()
    if not gog:
        log.error("gog CLI not found (checked PATH, ~/.local/bin, /usr/local/bin) — skipping email")
        return False

    # Put gog's own directory on PATH too, so anything it shells out to resolves under cron.
    env = {**os.environ, "GOG_KEYRING_PASSWORD": pw,
           "PATH": os.pathsep.join([str(Path(gog).parent), os.environ.get("PATH", "/usr/bin:/bin")])}
    try:
        r = subprocess.run(
            [gog, "gmail", "send",
             "--to", to,
             "-a", GOG_ACCOUNT,
             "--subject", subject,
             "--body", body],
            env=env, capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            log.info(f"Email sent: {subject[:50]}")
            return True
        else:
            log.error(f"Email failed: {r.stderr[:200]}")
            return False
    except Exception as e:
        log.error(f"Email error: {e}")
        return False


def notify_fill(symbol, shares, fill_price, broker_order_id, trade_id,
                stop_price=0, target_price=0, strategy=""):
    """Send fill confirmation email."""
    position_value = shares * fill_price
    body = (
        f"ORDER FILLED — {symbol}\n\n"
        f"Filled: {shares:.0f} shares @ ${fill_price:.2f}\n"
        f"Position value: ${position_value:,.0f}\n"
        f"Stop: ${stop_price:.2f}  |  Target: ${target_price:.2f}\n"
        f"Strategy: {strategy}\n"
        f"Order ID: {broker_order_id}\n"
        f"Trade #{trade_id}\n\n"
        f"Paper mode — no live money.\n"
        f"Dashboard: https://ms01-openclaw.tail163d14.ts.net/v3/trading"
    )
    return send_email(f"Trade AI Fill: {symbol} {shares:.0f}sh @ ${fill_price:.2f}", body)


def notify_stop_triggered(symbol, current_price, stop_price, pnl_dollars,
                           pnl_pct, regime="", triggered_count=0):
    """Send stop triggered decision email."""
    body = (
        f"STOP TRIGGERED — {symbol}\n\n"
        f"Current: ${current_price:.2f}  |  Stop: ${stop_price:.2f}\n"
        f"P&L if exit now: ${pnl_dollars:+,.0f} ({pnl_pct:+.1f}%)\n"
        f"Market regime: {regime}\n"
        f"Total stops triggered: {triggered_count}\n\n"
        f"Action required in Telegram or dashboard.\n"
        f"Dashboard: https://ms01-openclaw.tail163d14.ts.net/v3/risk"
    )
    return send_email(f"Trade AI Stop: {symbol} @ ${current_price:.2f} — decision required", body)


def notify_proposal(symbol, strategy, entry, stop, target, shares, proposal_id):
    """Send new proposal email."""
    rr = (target - entry) / (entry - stop) if (entry - stop) > 0 else 0
    risk = abs(entry - stop) * shares
    body = (
        f"NEW PROPOSAL — {symbol}\n\n"
        f"Strategy: {strategy}\n"
        f"Entry: ${entry:.2f}  |  Stop: ${stop:.2f}  |  Target: ${target:.2f}\n"
        f"R:R: {rr:.1f}x  |  Shares: {shares}  |  Risk: ${risk:,.0f}\n"
        f"Proposal #{proposal_id}\n\n"
        f"Approve/reject in Telegram or dashboard.\n"
        f"Dashboard: https://ms01-openclaw.tail163d14.ts.net/v3/trading"
    )
    return send_email(f"Trade AI Proposal: {symbol} — {strategy}", body)


def notify_approval_result(symbol, shares, entry, stop, target,
                            risk_gate, alpaca_status, broker_order_id=""):
    """Send approval confirmation email."""
    body = (
        f"PROPOSAL APPROVED — {symbol}\n\n"
        f"Shares: {shares}  |  Entry: ${entry:.2f}\n"
        f"Stop: ${stop:.2f}  |  Target: ${target:.2f}\n"
        f"Risk gate: {risk_gate}\n"
        f"Alpaca: {alpaca_status}\n"
    )
    if broker_order_id:
        body += f"Order ID: {broker_order_id}\n"
    body += (
        f"\nPaper mode — no live money.\n"
        f"Dashboard: https://ms01-openclaw.tail163d14.ts.net/v3/trading"
    )
    return send_email(f"Trade AI Approved: {symbol} {shares}sh submitted", body)
