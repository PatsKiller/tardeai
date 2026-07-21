#!/usr/bin/env python3
"""Daily rotation nag/daemon (05:30 ET cron).

self_minted overdue → generate → SM → render → (caller restarts) → probe
vendor_manual overdue → Telegram nag with vendor_url every 3 days
Never prints values.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "secrets"))

STATE = ROOT / "data" / "runtime" / "rotation_daemon_state.json"


def main() -> int:
    try:
        import yaml
    except ImportError:
        print("pyyaml required", file=sys.stderr)
        return 1
    reg = yaml.safe_load((ROOT / "config" / "secret_registry.yaml").read_text())
    secrets = reg.get("secrets") or {}
    st = {}
    if STATE.exists():
        try:
            st = json.loads(STATE.read_text())
        except Exception:
            st = {}
    now = datetime.now(timezone.utc)
    nags = []
    for name, entry in secrets.items():
        if name.upper().startswith("BWS_"):
            continue
        cls = entry.get("class") or "vendor_manual"
        max_age = int(entry.get("max_age_days") or 90)
        last = st.get(name, {}).get("last_rotated_at")
        age_days = 999
        if last:
            try:
                age_days = (now - datetime.fromisoformat(last.replace("Z", "+00:00"))).days
            except Exception:
                age_days = 999
        if age_days < max_age:
            continue
        if cls == "vendor_manual" or cls == "oauth_managed":
            last_nag = st.setdefault(name, {}).get("last_nag_at")
            nag_ok = True
            if last_nag:
                try:
                    nag_age = (now - datetime.fromisoformat(last_nag.replace("Z", "+00:00"))).days
                    nag_ok = nag_age >= 3
                except Exception:
                    pass
            if nag_ok:
                url = entry.get("vendor_url") or ""
                nags.append(f"• `{name}` age≥{max_age}d {url}")
                st.setdefault(name, {})["last_nag_at"] = now.isoformat()
        # self_minted: do NOT auto-rotate DB without explicit flag (safety)
        elif cls == "self_minted":
            nags.append(f"• `{name}` self_minted overdue — run rotate.py --generate when window allows")
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, indent=2))
    if nags:
        msg = "🔐 Rotation due:\n" + "\n".join(nags[:20])
        try:
            from telegram_alert import send_telegram
            send_telegram(msg, bypass_router=True)
        except Exception as e:
            print("telegram", e)
        print(f"nagged={len(nags)}")
    else:
        print("nothing_due")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
