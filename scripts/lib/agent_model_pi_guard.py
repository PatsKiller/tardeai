"""agent_model_pi_guard.py — post-generation prompt-injection / exfil scan.

READ_ONLY_ADVISORY. Complements ingress UNTRUSTED_DATA + router refuse.
Scans model *output* for system-prompt / secret exfiltration patterns and
instruction-override echoes. Fail-soft: returns a report; callers decide refuse.
"""
from __future__ import annotations

import re
from typing import Any

SCHEMA = "ModelPiGuard@v1"

_EXFIL_OUT_RE = re.compile(
    r"(?is)("
    r"here\s+is\s+(?:my\s+)?(?:system\s+)?(?:prompt|instructions)"
    r"|system\s+prompt\s*:"
    r"|ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions"
    r"|api[_\s-]?key\s*[:=]\s*[A-Za-z0-9_\-]{8,}"
    r"|sk-[A-Za-z0-9]{8,}"
    r"|BEGIN\s+PRIVATE\s+KEY"
    r"|you\s+are\s+now\s+jailbroken"
    r")"
)


def scan_model_output(text: Any) -> dict[str, Any]:
    """Return {ok, refuse, matches, schema}. Never raises."""
    s = str(text or "")
    if not s.strip():
        return {"schema": SCHEMA, "ok": True, "refuse": False, "matches": []}
    hits = [m.group(0)[:80] for m in _EXFIL_OUT_RE.finditer(s)]
    refuse = bool(hits)
    return {
        "schema": SCHEMA,
        "ok": not refuse,
        "refuse": refuse,
        "matches": hits[:5],
        "authority": "READ_ONLY_ADVISORY",
    }


def refuse_text(report: dict[str, Any] | None = None) -> str:
    """Operator-facing refusal when model output fails the PI guard."""
    return (
        "Refused: model output looked like a prompt/secret exfiltration or "
        "instruction-override echo. READ_ONLY_ADVISORY — try a narrower question."
    )
