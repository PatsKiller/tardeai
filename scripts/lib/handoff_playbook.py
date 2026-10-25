"""Operating playbook + work-package handoff: one source for the rules, the board for the work.

Operator 2026-10-23: "this is what should be done inside of the board also. structure: problem, definition of done,
agent prompt, operator commands, and proof of completion." and "also add that the above should be part of the board."

* ``docs/ops/OPERATING_PLAYBOOK.md`` holds Section A (resume procedure, system map, rules, how a change goes live) and
  B0 (the standard agent preamble), copied verbatim from the v3 handoff. ``load_playbook`` parses it into anchored
  sections (cached by mtime and size; capped at ``MAX_PLAYBOOK_BYTES``).
* ``full_prompt`` prepends the B0 preamble to a task's short agent prompt, so per-task prompts stay short and the
  rules stay in one place (the Work pipeline's "Copy prompt", ``task show --full-prompt`` and the export use it).
* ``export_handoff`` regenerates the full markdown handoff (playbook + ordered work packages with status and proof
  evidence) from the task board, so the offline document is produced from the board rather than written by hand.
  ``scripts/import_handoff_workpackages.py`` parses that same format back, so export -> import is a fixed point.

Stdlib only. AUTHORITY: READ_ONLY_ADVISORY (reads the repo doc and the coordination task files; writes only the
``--out`` file the caller names).
"""

from __future__ import annotations

import hashlib
import re
import threading
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
PLAYBOOK_REL = "docs/ops/OPERATING_PLAYBOOK.md"
MAX_PLAYBOOK_BYTES = 512 * 1024
B0_HEADING = "## B0."
# the headings pinned by tests/test_operating_playbook_20261023.py (the B0 extractor and the UI anchors read them)
REQUIRED_HEADINGS = (
    "## A1. Resume procedure (any agent, every time)",
    "## A2. System map",
    "## A3. Rules (never skip)",
    "## A4. How a change goes from idea to live",
    "## B0. Standard agent preamble (every agent prompt below starts with this; paste it first)",
)
STATUS_BOX = {"done": "[x]", "in_progress": "[~]", "not_started": "[ ]", "repeating": "repeating"}
_WP_NUM = re.compile(r"WP-(\d+)")


def anchor(title: str) -> str:
    """GitHub-style heading anchor: lower case, punctuation dropped, spaces to dashes."""
    a = re.sub(r"[^\w\- ]+", "", title.strip().lower(), flags=re.UNICODE)
    return re.sub(r"\s+", "-", a).strip("-")


def parse_playbook(text: str) -> dict[str, Any]:
    """Split the playbook into sections at ``#``/``##`` headings and extract the B0 preamble."""
    sections: list[dict[str, Any]] = []
    cur: dict[str, Any] | None = None
    fence = False
    for line in text.split("\n"):
        if line.startswith("```"):
            fence = not fence
        m = None if fence else re.match(r"^(#{1,2}) (.+)$", line)
        if m:
            cur = {"level": len(m.group(1)), "title": m.group(2).strip(), "id": anchor(m.group(2)), "lines": []}
            sections.append(cur)
            continue
        if cur is not None:
            cur["lines"].append(line)
    out = []
    for s in sections:
        body = "\n".join(s.pop("lines")).strip("\n")
        out.append({**s, "markdown": body})
    b0 = next((s for s in out if s["title"].startswith(B0_HEADING[3:])), None)
    return {"sections": out, "b0_preamble": extract_preamble(b0["markdown"]) if b0 else None}


def extract_preamble(b0_markdown: str) -> str | None:
    """The first blockquote in the B0 section, with the ``> `` markers removed."""
    rows: list[str] = []
    started = False
    for line in b0_markdown.split("\n"):
        if line.startswith(">"):
            started = True
            rows.append(line[2:] if line.startswith("> ") else line[1:])
        elif started:
            break
    text = "\n".join(rows).strip()
    return text or None


_CACHE: dict[str, Any] = {}
_LOCK = threading.Lock()


def load_playbook(path: Path | str | None = None) -> dict[str, Any]:
    """Parsed playbook, cached by (path, mtime, size). Never raises: ``{"ok": False, "error": ...}`` when unreadable."""
    p = Path(path) if path else ROOT / PLAYBOOK_REL
    try:
        st = p.stat()
    except OSError:
        return {"ok": False, "error": "playbook_missing", "path": str(p), "sections": [], "b0_preamble": None}
    if st.st_size > MAX_PLAYBOOK_BYTES:
        return {"ok": False, "error": "playbook_too_large", "path": str(p), "sections": [], "b0_preamble": None}
    key = (str(p), st.st_mtime_ns, st.st_size)
    with _LOCK:
        if _CACHE.get("key") == key:
            return _CACHE["value"]
    raw = p.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    m = re.search(r"^as_of:\s*(\S+)", text, re.M)
    value = {
        "ok": True,
        "schema": "OperatingPlaybook@v1",
        "path": PLAYBOOK_REL if p == ROOT / PLAYBOOK_REL else str(p),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "as_of": m.group(1) if m else None,
        "bytes": len(raw),
        **parse_playbook(text),
    }
    with _LOCK:
        _CACHE["key"] = key
        _CACHE["value"] = value
    return value


def full_prompt(agent_prompt: str | None, preamble: str | None) -> str | None:
    """B0 preamble + the task's own prompt (the "Copy prompt" text). None when the task has no prompt."""
    if not agent_prompt:
        return None
    if not preamble:
        return agent_prompt
    return f"{preamble}\n\n---\n\n{agent_prompt}"


# --------------------------------------------------------------------------------------------- export


def _wp_key(t: Mapping[str, Any]) -> tuple[int, str]:
    m = _WP_NUM.match(str(t.get("wp_id") or ""))
    return (int(m.group(1)) if m else 10**6, str(t.get("task_id")))


def wp_status(t: Mapping[str, Any]) -> str:
    """not_started | in_progress | done | repeating, from the board status first, then the imported marker."""
    if t.get("status") == "done":
        return "done"
    if t.get("wp_status") == "repeating":
        return "repeating"
    if t.get("status") in ("taken", "split") or t.get("wp_status") == "in_progress":
        return "in_progress"
    return t.get("wp_status") if t.get("wp_status") in STATUS_BOX else "not_started"


def _quote(text: str) -> str:
    return "\n".join(("> " + ln) if ln.strip() else ">" for ln in text.split("\n"))


def _owner_text(t: Mapping[str, Any]) -> str:
    return str(t.get("owner_label") or t.get("owner_kind") or "AGENT")


def _depends_text(t: Mapping[str, Any], wp_of: Mapping[str, str]) -> str:
    deps = [wp_of.get(d, d) for d in t.get("depends_on") or []]
    return ", ".join(deps) if deps else "none"


def render_wp(t: Mapping[str, Any], wp_of: Mapping[str, str]) -> str:
    st = wp_status(t)
    box = STATUS_BOX[st]
    status = box if st == "repeating" else f"`{box}`"
    note = t.get("wp_status_note")
    if st == "done" and not note and t.get("proof_evidence"):
        note = str(t["proof_evidence"]).split("\n")[0]
    head = f"**Owner:** {_owner_text(t)} · **Depends:** {_depends_text(t, wp_of)} · **Status:**"
    multi = bool(note and "\n" in note and st != "done")
    if st == "repeating":
        head = f"**Owner:** {_owner_text(t)} · **Depends:** {_depends_text(t, wp_of)} · **Repeating**"
    elif multi:
        head += "\n" + str(note)  # the per-item status list, verbatim (each item carries its own box)
    else:
        head += f" {status}" + (f" {note}" if note else "")
    title = re.sub(r"^WP-\d+\s+", "", str(t.get("title") or ""))
    out = [f"### {t.get('wp_id')} {title}", head, ""]

    def sec(label: str, body: str | None, *, quote: bool = False) -> None:
        if not body:
            return
        if "\n" in body or body.lstrip().startswith(("-", "1.", "```", ">", "|")):
            out.extend([f"**{label}:**", _quote(body) if quote else body, ""])
        else:
            out.extend([f"**{label}:** {body}", ""])

    sec("Current issue", t.get("problem"))
    sec("Target state", t.get("definition_of_done"))
    if t.get("agent_prompt"):
        out.extend(["**Agent prompt:**", _quote("(B0.) " + str(t["agent_prompt"])), ""])
    sec("Operator commands", t.get("operator_commands"))
    sec("Verify", t.get("proof"))
    sec("Proof evidence", t.get("proof_evidence"))
    if t.get("notes"):
        out.extend([str(t["notes"]), ""])
    rel = "; related " + ", ".join(t["related_tasks"]) if t.get("related_tasks") else ""
    out.extend([f"**Board:** `{t['task_id']}`{rel}", ""])
    return "\n".join(out).rstrip() + "\n"


def export_handoff(
    tasks: Iterable[Mapping[str, Any]],
    stages: Mapping[str, Any] | None,
    playbook: Mapping[str, Any],
    *,
    as_of: str,
    playbook_text: str | None = None,
) -> str:
    """The full handoff markdown: title, the playbook (Section A + B0), the ordered index, then each stage with its
    intro and each work package with every structure section, its status and its proof evidence."""
    wps = sorted([t for t in tasks if t.get("wp_id")], key=_wp_key)
    wp_of = {str(t["task_id"]): str(t["wp_id"]) for t in wps}
    stage_rows = list((stages or {}).get("stages") or [])
    stage_names = [s["stage"] for s in stage_rows]
    for t in wps:  # stages known only from the tasks, in WP order
        if t.get("stage") and t["stage"] not in stage_names:
            stage_names.append(t["stage"])
            stage_rows.append({"stage": t["stage"], "title": None, "description": None})
    lines = [
        "# Trade AI: complete ordered work plan (generated from the board)",
        "",
        "```",
        "Status:      GENERATED (do not hand-edit: change the board or docs/ops/OPERATING_PLAYBOOK.md, then re-export)",
        f"as_of:       {as_of}",
        f"Measured at: task board ({len(wps)} work packages) + {playbook.get('path')} sha256 {str(playbook.get('sha256') or '')[:16]}",
        "Generator:   python3 scripts/agent_claim.py export-handoff --out <file>",
        "```",
        "",
    ]
    if playbook_text is not None:
        body = playbook_text
        m = re.search(r"^# Section A", body, re.M)
        lines.append((body[m.start() :] if m else body).rstrip() + "\n")
    lines.extend(["---", "", "# Section B: the work, in order", "", "## Ordered index of work packages", ""])
    lines.extend(["| # | Work package | Owner | Status |", "|---|---|---|---|"])
    for name in stage_names:
        row = next((s for s in stage_rows if s["stage"] == name), {})
        lines.append(f"| **{name}{': ' + row['title'] if row.get('title') else ''}** | | | |")
        for t in [t for t in wps if t.get("stage") == name]:
            title = re.sub(r"^WP-\d+\s+", "", str(t.get("title") or ""))
            lines.append(f"| {t['wp_id']} | {title} | {_owner_text(t)} | {STATUS_BOX[wp_status(t)]} |")
    loose = [t for t in wps if not t.get("stage")]
    for t in loose:
        lines.append(f"| {t['wp_id']} | {t.get('title')} | {_owner_text(t)} | {STATUS_BOX[wp_status(t)]} |")
    lines.append("")
    for name in stage_names:
        row = next((s for s in stage_rows if s["stage"] == name), {})
        lines.append(f"## {name}{': ' + row['title'] if row.get('title') else ''}")
        lines.append("")
        if row.get("description"):
            lines.extend([_quote(row["description"]), ""])
        for t in [t for t in wps if t.get("stage") == name]:
            lines.append(render_wp(t, wp_of))
    for t in loose:
        lines.append(render_wp(t, wp_of))
    return "\n".join(lines).rstrip() + "\n"
