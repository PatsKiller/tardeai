#!/usr/bin/env python3
"""options_lifecycle_digest.py — optional daily options-management digest (cron 08:05).
Sends to Telegram only when the policy enables it AND there is something to say;
an empty book prints locally and stays silent on the phone."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from db_adapter import _get_conn
from options_lifecycle_alerts import daily_digest, _telegram
from options_lifecycle_engine import policy

text = daily_digest(_get_conn().cursor())
print(text)
if policy()["alerts"]["daily_digest"] and "no open option strategies" not in text:
    _telegram(text)
