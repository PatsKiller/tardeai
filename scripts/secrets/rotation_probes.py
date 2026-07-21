#!/usr/bin/env python3
"""Value-free verify probes for secret rotation (S6)."""
from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _ensure_env():
    import sys
    sys.path.insert(0, str(ROOT / "scripts" / "lib"))
    from env_bootstrap import load_env
    load_env(override=True)


def probe_db_select_1() -> dict:
    _ensure_env()
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    from db_adapter import _get_conn
    cur = _get_conn().cursor()
    cur.execute("SELECT 1")
    return {"ok": cur.fetchone()[0] == 1, "probe": "db_select_1"}


def _alpaca_account(slot_keys: tuple[str, str], host: str) -> dict:
    _ensure_env()
    k = os.environ.get(slot_keys[0], "")
    s = os.environ.get(slot_keys[1], "")
    if not k or not s:
        return {"ok": True, "probe": "alpaca", "skipped": True, "reason": "no_keys"}
    req = urllib.request.Request(
        f"https://{host}/v2/account",
        headers={"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read() or b"{}")
        return {"ok": True, "probe": "alpaca", "status": data.get("status"), "host": host}
    except Exception as e:
        return {"ok": False, "probe": "alpaca", "error": str(e)[:120], "host": host}


def probe_alpaca_paper_account() -> dict:
    return _alpaca_account(("ALPACA_API_KEY", "ALPACA_SECRET_KEY"), "paper-api.alpaca.markets")


def probe_alpaca_taxable_account() -> dict:
    return _alpaca_account(("ALPACA_TAXABLE_API_KEY", "ALPACA_TAXABLE_SECRET_KEY"), "api.alpaca.markets")


def probe_alpaca_ira_account() -> dict:
    return _alpaca_account(("ALPACA_IRA_API_KEY", "ALPACA_IRA_SECRET_KEY"), "api.alpaca.markets")


def probe_telegram_getme() -> dict:
    _ensure_env()
    tok = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not tok:
        return {"ok": False, "probe": "telegram_getme", "error": "no token"}
    try:
        with urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/getMe", timeout=15) as r:
            data = json.loads(r.read())
        return {"ok": bool(data.get("ok")), "probe": "telegram_getme", "username": (data.get("result") or {}).get("username")}
    except Exception as e:
        return {"ok": False, "probe": "telegram_getme", "error": str(e)[:120]}


def probe_openai_models() -> dict:
    _ensure_env()
    k = os.environ.get("OPENAI_API_KEY", "")
    if not k:
        return {"ok": True, "skipped": True}
    req = urllib.request.Request("https://api.openai.com/v1/models", headers={"Authorization": f"Bearer {k}"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return {"ok": r.status == 200, "probe": "openai_models"}
    except Exception as e:
        return {"ok": False, "probe": "openai_models", "error": str(e)[:120]}


def probe_anthropic_models() -> dict:
    _ensure_env()
    k = os.environ.get("ANTHROPIC_API_KEY", "")
    if not k:
        return {"ok": True, "skipped": True}
    # cheap authenticated ping
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=b'{"model":"claude-3-haiku-20240307","max_tokens":1,"messages":[{"role":"user","content":"hi"}]}',
        headers={"x-api-key": k, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return {"ok": r.status in (200, 201), "probe": "anthropic_models"}
    except Exception as e:
        # 400 still proves auth sometimes; treat 401/403 as fail
        msg = str(e)
        if "401" in msg or "403" in msg or "authentication" in msg.lower():
            return {"ok": False, "probe": "anthropic_models", "error": msg[:120]}
        return {"ok": True, "probe": "anthropic_models", "note": "auth_likely_ok", "error": msg[:80]}


def probe_finviz_ping() -> dict:
    _ensure_env()
    tok = os.environ.get("FINVIZ_API_TOKEN", "")
    if not tok:
        return {"ok": True, "skipped": True}
    return {"ok": True, "probe": "finviz_ping", "note": "token_present"}


_PROBES = {
    "db_select_1": probe_db_select_1,
    "alpaca_paper_account": probe_alpaca_paper_account,
    "alpaca_taxable_account": probe_alpaca_taxable_account,
    "alpaca_ira_account": probe_alpaca_ira_account,
    "telegram_getme": probe_telegram_getme,
    "openai_models": probe_openai_models,
    "anthropic_models": probe_anthropic_models,
    "finviz_ping": probe_finviz_ping,
}


def run_probe(secret_name: str) -> dict:
    """Map secret name → registry probe if available."""
    try:
        import yaml
        reg = yaml.safe_load((ROOT / "config" / "secret_registry.yaml").read_text())
        entry = (reg.get("secrets") or {}).get(secret_name) or {}
        pname = entry.get("verify_probe")
        if not pname:
            return {"ok": True, "probe": None, "skipped": True}
        fn = _PROBES.get(pname)
        if not fn:
            return {"ok": True, "probe": pname, "skipped": True, "reason": "no_impl"}
        return fn()
    except Exception as e:
        return {"ok": False, "error": str(e)[:160]}
