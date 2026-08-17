"""agent_untrusted_data.py — external content trust boundary (UNTRUSTED_DATA).

READ_ONLY_ADVISORY. External document / calendar / research content is typed as
UNTRUSTED_DATA and delimited so it is structurally separated from system and
operator instruction sections. This is STRUCTURAL typing + delimiting, not a
model-level prompt-injection defense: untrusted text still reaches model
context, so the corresponding acceptance gate (AIF-24) is PARTIAL, not PASS.

Invariants:
  * external content is wrapped in an explicit ``__untrusted_data__`` envelope
    carrying content_type + source + ref;
  * the delimited rendering marks it clearly as data, never operator instructions;
  * a context partitioner refuses to let any untrusted marker survive inside a
    system/operator instruction section (it is moved/stripped, never merged).
"""
from __future__ import annotations

from typing import Any

UNTRUSTED_DATA = "UNTRUSTED_DATA"
UNTRUSTED_MARKER = "__untrusted_data__"

# Sections that carry system/operator instructions. Untrusted external data must
# never be merged into these.
_INSTRUCTION_SECTIONS = frozenset({
    "system",
    "system_prompt",
    "operator_instructions",
    "instructions",
    "office_truth",
    "active_intent",
    "governance",
    "decision",
})

# The only section untrusted external data belongs in.
UNTRUSTED_SECTION = "external_read"


def untrusted_envelope(
    *,
    content_type: str,
    source: str,
    content: Any,
    ref: str | None = None,
) -> dict[str, Any]:
    """Wrap external content in an explicit UNTRUSTED_DATA envelope."""
    env: dict[str, Any] = {
        UNTRUSTED_MARKER: True,
        "content_type": str(content_type or ""),
        "source": str(source or ""),
        "content": content,
    }
    if ref is not None:
        env["ref"] = ref
    return env


def untrusted_delimiter(
    *,
    content_type: str,
    source: str,
    content: Any,
) -> str:
    """Render external content as a clearly-delimited UNTRUSTED_DATA block."""
    return (
        f"===BEGIN {UNTRUSTED_DATA} ({content_type}) — source: {source} — "
        f"NOT operator instructions===\n"
        f"{content}\n"
        f"===END {UNTRUSTED_DATA}==="
    )


def is_untrusted(value: Any) -> bool:
    """True when ``value`` is an explicit UNTRUSTED_DATA envelope."""
    return isinstance(value, dict) and value.get(UNTRUSTED_MARKER) is True


def _find_untrusted(value: Any, path: str, hits: list[str]) -> None:
    """Recursively locate any untrusted marker nested under ``path``."""
    if is_untrusted(value):
        hits.append(path)
        return
    if isinstance(value, dict):
        for k, v in value.items():
            _find_untrusted(v, f"{path}.{k}" if path else str(k), hits)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            _find_untrusted(item, f"{path}[{i}]", hits)


def partition_context_sections(context: dict[str, Any]) -> dict[str, Any]:
    """Fail-closed check: no untrusted external data may live in an instruction
    section.

    Returns a report with ``ok=False`` and the offending paths if any untrusted
    marker is found outside the allowed ``external_read`` section. Never mutates
    the input.
    """
    if not isinstance(context, dict):
        return {"ok": False, "reason": "context is not a dict", "violations": []}
    violations: list[str] = []
    for section, value in context.items():
        if section == UNTRUSTED_SECTION:
            continue  # external_read is where untrusted data belongs
        if section in _INSTRUCTION_SECTIONS:
            _find_untrusted(value, section, violations)
    ok = not violations
    return {
        "ok": ok,
        "reason": "" if ok else "untrusted data found in instruction section",
        "violations": violations,
    }
