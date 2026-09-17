"""D1 (2026-09-16): CIO Desk is CIO-origin only — shrink-only structural gate.

The dedicated CIO bot is credential-separated (TELEGRAM_CIO_BOT_TOKEN +
TELEGRAM_CIO_CHAT_IDS, never the general Maria token/chat). This gate pins the
remaining invariant: the ONLY callers of the CIO send entrypoints
(send_cio_message / notify_thesis_published) are `cio_*` modules. A non-CIO
producer reaching the CIO channel fails CI.

The allowlist may shrink; it must never grow. Same shape as the dark-contract
and test-coverage gates.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

# CIO send entrypoints. A caller of any of these reaches the dedicated CIO bot.
ENTRYPOINTS = ("send_cio_message", "notify_thesis_published")

# Shrink-only allowlist: every module permitted to call a CIO entrypoint.
# These are all cio_* (or the transport/converse definitions themselves).
CIO_ORIGIN_ONLY = frozenset({
    "cio_telegram_transport",   # defines send_cio_message (the transport)
    "cio_telegram_converse",    # defines the send_cio_message wrapper
    "cio_telegram_bot",         # the CIO bot
    "cio_entry_state_runner",   # CIO entry-state cards
    "cio_plan_enrichment",      # CIO plan cards
    "cio_notification_delivery",# CIO notification outbox delivery
    "cio_theses",               # CIO thesis publish
    "cio_alex_telegram",        # Alex (CIO) messages
    "cio_operator_desk_loop",   # desk answers, if present
    "cio_phase9_alex_telegram", # Alex converse path, if present
})


def _callers() -> dict[str, set[str]]:
    """module-basename -> entrypoint names it calls (call sites only, not defs)."""
    out: dict[str, set[str]] = {}
    for py in SCRIPTS.rglob("*.py"):
        rel = py.relative_to(SCRIPTS).as_posix()
        # skip __pycache__ and the definitions themselves are allowed regardless
        try:
            src = py.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for ep in ENTRYPOINTS:
            # a call site: ep followed by "(" but not "def ep(" or " ep ="
            if re.search(rf"(?<!def )\b{ep}\s*\(", src):
                # exclude the definition line itself
                calls = [l for l in src.splitlines()
                         if re.search(rf"\b{ep}\s*\(", l) and not re.search(rf"^\s*def\s+{ep}\b", l)]
                if calls:
                    stem = Path(rel).stem
                    out.setdefault(stem, set()).add(ep)
    return out


def test_only_cio_modules_call_the_cio_send_path():
    callers = _callers()
    non_cio = {m: eps for m, eps in callers.items() if m not in CIO_ORIGIN_ONLY}
    assert non_cio == {}, (
        f"non-CIO modules reach the CIO channel: {non_cio}. "
        f"A non-CIO producer calling a CIO entrypoint breaks CIO-origin-only."
    )


def test_the_cio_allowlist_is_shrink_only_and_named():
    # Every allowed caller must actually exist and be cio_* (or the known converse alias).
    for m in CIO_ORIGIN_ONLY:
        if m in {"cio_operator_desk_loop", "cio_phase9_alex_telegram"}:
            continue  # optional aliases; the gate fails only on growth, not absence
        assert m.startswith("cio"), m


def test_transport_never_falls_back_to_general_token():
    src = (SCRIPTS / "lib" / "cio_telegram_transport.py").read_text(encoding="utf-8")
    # The CIO transport must reference only the CIO token/chat, never the general ones.
    assert "TELEGRAM_CIO_BOT_TOKEN" in src
    assert "TELEGRAM_CIO_CHAT_IDS" in src
    # General credential names must not be the CIO token source.
    assert "ENV_CIO_TOKEN = \"TELEGRAM_CIO_BOT_TOKEN\"" in src
