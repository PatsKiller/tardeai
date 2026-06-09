"""tg_chat_ids.py — operator Telegram alert chat IDs, sourced from env/.env. NEVER hardcoded.

Hard rule: no hardcoded names/values — config comes from a source (env, .env, DB). This is the single
place alert chat IDs are resolved, from TRADEAI_PROPOSAL_ALERT_CHAT_ID + TELEGRAM_CHAT_ID (comma-sep).
"""
import os
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def chat_ids():
    """Configured Telegram alert chat IDs (de-duped, in order). Empty if none configured."""
    out = []
    for k in ("TRADEAI_PROPOSAL_ALERT_CHAT_ID", "TELEGRAM_CHAT_ID"):
        v = os.environ.get(k, "")
        if not v:
            try:
                for line in (_ROOT / ".env").read_text().splitlines():
                    if line.startswith(k + "="):
                        v = line.split("=", 1)[1].strip()
                        break
            except Exception:
                pass
        for c in str(v).split(","):
            c = c.strip()
            if c and c not in out:
                out.append(c)
    return out
