#!/usr/bin/env python3
"""import_handoff_workpackages.py — put every work package of a handoff on the task board, with its structure.

Operator 2026-10-23: "this is what should be done inside of the board also. structure: problem, definition of done,
agent prompt, operator commands, and proof of completion." and "also add that the above should be part of the board."

    python3 scripts/import_handoff_workpackages.py --file <HANDOFF_v3_ORDERED_WORK.md> --dry-run
    python3 scripts/import_handoff_workpackages.py --file <HANDOFF_v3_ORDERED_WORK.md> --apply

Each ``### WP-NN <title>`` section becomes (or updates) one board task:

* header line ``**Owner:** … · **Depends:** … · **Status:** …`` -> ``owner_kind`` (AGENT | OPERATOR | BOTH, from the
  upper-case words), ``owner_label`` (the text), ``depends_on`` (every ``WP-NN`` named, except inside a parenthesis
  saying "optional") and ``wp_status`` (``[x]`` done, ``[~]`` in progress, ``[ ]`` not started; a multi-line status
  list is all-done only when every box is ``[x]``; "Repeating" is repeating), with the status text as the note;
* "Current issue" / "Current state" / "What happened" -> ``problem``; "Target state" -> ``definition_of_done``;
  "Agent prompt" (any "Agent … prompt") -> ``agent_prompt``, stored WITHOUT the ``(B0.)`` marker because the B0
  preamble is prepended at copy time from docs/ops/OPERATING_PLAYBOOK.md; "Operator command(s)" and other
  "Operator …" labels -> ``operator_commands``; "Verify" -> ``proof``; every other labelled block (Traps, Rollback,
  Limits, …) -> ``notes``. Unlabelled text before the first label goes to ``problem`` (or ``notes`` when a problem
  exists), and inline ``> (B0.)`` prompts inside numbered items are collected into ``agent_prompt``;
* ``## Stage N: title`` and the narrative above its first WP -> the board's stage descriptions (wp_stages.json).

Task id: an existing task with the same ``wp_id`` is updated in place (a task the importer did not create keeps its
title, status and dependencies; only its sections and labels are set). Otherwise a design-style id
``DSN-<date>-handoff-v3-P<stage>-T<wp>`` is created (the board's id format; ``wp_id`` carries ``WP-NN``) with the
pseudo-area ``handoff/WP-NN`` (an agent extends its claim with ``claim --add`` before touching files). Existing board
tasks that share a PR number or name the WP are linked as ``related_tasks`` and listed, never duplicated. A WP whose
status is ``[x]`` closes its free task with the status text as evidence. Re-running is idempotent.

--dry-run prints the plan and writes nothing. --apply writes the task files and history (coordination store only).
Exit: 0 ok · 2 usage / parse error. AUTHORITY: READ_ONLY_ADVISORY — coordination task files only; no broker, DB,
Telegram, scheduler or remote write.
"""

from __future__ import annotations

import argparse
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import agent_claim_board as B  # noqa: E402
from scripts.lib import agent_task_board as TB  # noqa: E402

DESIGN_PREFIX = "DSN-20261023-handoff-v3"
SOURCE = "handoff"
STAGE_PRIORITY = {1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 3, 7: 4}
_WP_HEAD = re.compile(r"^### (WP-\d{2,3})\s+(.*)$")
_STAGE_HEAD = re.compile(r"^## (Stage (\d+))\s*:?\s*(.*)$")
_LABEL = re.compile(r"^\*\*([^*]+?)\*\*(.*)$")
_BOX = re.compile(r"\[( |x|X|~)\]")
_PR = re.compile(r"#(\d{3,5})\b")


# --------------------------------------------------------------------------------------------- parse


def _label(line: str) -> tuple[str, str] | None:
    """``**Label:** rest`` or ``**Label** (aside): rest`` -> (label, rest). Bold text without a colon is prose."""
    m = _LABEL.match(line)
    if not m:
        return None
    raw, rest = m.group(1).strip(), m.group(2)
    if raw.endswith(":"):
        return raw[:-1].strip(), rest.strip()
    m2 = re.match(r"^\s*(\([^)]*\))?\s*:(.*)$", rest)
    if m2:
        aside = (m2.group(1) or "").strip()
        tail = m2.group(2).strip()
        return raw, (aside + (" " + tail if tail else "")).strip()
    return None


def _field_for(label: str) -> str | None:
    low = label.lower()
    if low == "board":  # the export's own back-reference line
        return None
    if low in ("current issue", "current state", "what happened"):
        return "problem"
    if low.startswith("target state") or low.startswith("remaining"):
        return "definition_of_done"
    if low.startswith("agent") and "prompt" in low:
        return "agent_prompt"
    if low.startswith("operator"):
        return "operator_commands"
    if low == "verify" or low.startswith("verify"):
        return "proof"
    if low.startswith("proof evidence"):  # written by export-handoff for done work packages
        return "proof_evidence"
    return "notes"


PRIMARY = {
    "problem": ("current issue", "current state", "what happened"),
    "definition_of_done": ("target state",),
    "agent_prompt": ("agent prompt",),
    "operator_commands": ("operator commands", "operator command"),
    "proof": ("verify",),
    "proof_evidence": ("proof evidence",),
}


def _inline_ok(text: str) -> bool:
    """A one-line block reads ``**Label:** text``; lists, fences and quotes keep their own line."""
    return "\n" not in text and not text.lstrip().startswith(("-", "1.", "```", ">", "|"))


def _unquote(lines: list[str]) -> list[str]:
    out = []
    for ln in lines:
        if ln.startswith("> "):
            out.append(ln[2:])
        elif ln.startswith(">"):
            out.append(ln[1:])
        else:
            out.append(ln)
    return out


def _strip_b0(text: str) -> str:
    return re.sub(r"^\(B0(?: preamble)?\.?\)\.?\s*", "", text.lstrip())


def _trim(lines: list[str]) -> str:
    while lines and not lines[0].strip():
        lines = lines[1:]
    while lines and not lines[-1].strip():
        lines = lines[:-1]
    return "\n".join(lines)


def parse_header(line: str) -> dict[str, Any]:
    """``**Owner:** X · **Depends:** Y · **Status:** Z`` (any part may be missing; ``**Repeating**`` allowed)."""
    parts = {}
    for chunk in re.split(r"\s+·\s+", line.strip()):
        m = re.match(r"^\*\*([^*]+?):?\*\*:?\s*(.*)$", chunk.strip())
        if m:
            parts[m.group(1).strip().rstrip(":").lower()] = m.group(2).strip()
    owner = parts.get("owner") or ""
    has_a, has_o = bool(re.search(r"\bAGENT\b", owner)), bool(re.search(r"\bOPERATOR\b", owner))
    kind = "BOTH" if has_a and has_o else ("OPERATOR" if has_o else "AGENT")
    dep_text = parts.get("depends") or ""
    dep_scan = re.sub(r"\([^)]*optional[^)]*\)", "", dep_text, flags=re.I)
    dep_scan = re.sub(r"WP-\d+\s+optional", "", dep_scan, flags=re.I)
    deps = []
    for d in re.findall(r"WP-\d{2,3}", dep_scan):
        if d not in deps:
            deps.append(d)
    return {
        "owner_label": owner or None,
        "owner_kind": kind,
        "depends_text": dep_text or None,
        "depends": deps,
        "status_text": parts.get("status"),
        "repeating": "repeating" in parts,
    }


def status_of(status_lines: list[str], repeating: bool) -> tuple[str, str | None]:
    """(wp_status, note) from the status text (one line or a bullet list)."""
    if repeating:
        return "repeating", None
    text = "\n".join(ln for ln in status_lines if ln.strip()).strip()
    boxes = [b.lower() for b in _BOX.findall(text)]
    if not boxes:
        return "not_started", text or None
    if all(b == "x" for b in boxes):
        st = "done"
    elif any(b in ("~", "x") for b in boxes):
        st = "in_progress"
    else:
        st = "not_started"
    if "\n" not in text:
        note = _BOX.sub("", text, count=1).replace("``", "").strip(" `") or None
    else:
        note = text
    return st, note


def parse_wp(wp_id: str, title: str, body: list[str], stage: dict[str, Any] | None) -> dict[str, Any]:
    head_i = next((i for i, ln in enumerate(body) if ln.startswith("**Owner:**")), None)
    hdr = parse_header(body[head_i]) if head_i is not None else parse_header("")
    rest = body[head_i + 1 :] if head_i is not None else body
    status_lines: list[str] = []
    if hdr["status_text"] is not None:
        status_lines = [hdr["status_text"]]
        if not hdr["status_text"]:
            i = 0
            while i < len(rest) and rest[i].lstrip().startswith("- "):
                status_lines.append(rest[i].strip())
                i += 1
            rest = rest[i:]
    wp_status, note = status_of(status_lines, hdr["repeating"])

    # split into labelled blocks; text before the first label is the "lead"
    blocks: list[tuple[str | None, str, list[str]]] = [(None, "", [])]
    fence = False
    for ln in rest:
        if ln.startswith("```"):
            fence = not fence
        lab = None if fence else _label(ln)
        if lab:
            blocks.append((lab[0], lab[1], []))
        else:
            blocks[-1][2].append(ln)
    fields: dict[str, list[str]] = {}

    def put(field: str, text: str) -> None:
        if text.strip():
            fields.setdefault(field, []).append(text)

    lead = _trim(blocks[0][2])
    inline_prompts: list[str] = []
    for label, aside, lines in blocks[1:]:
        f = _field_for(label)
        if f is None:
            continue
        if f == "agent_prompt":
            text = _trim(_unquote(lines))
            if aside:
                text = (aside + "\n" + text).strip() if text else aside
            text = _strip_b0(text)
            primary = label.lower() in PRIMARY["agent_prompt"] and not aside
            put(
                f,
                text
                if primary and not fields.get(f)
                else f"**{label}{' ' + aside if aside and not text.startswith(aside) else ''}:**\n{text}",
            )
            continue
        body_text = _trim(lines)
        if aside:
            body_text = (aside + ("\n" + body_text if body_text else "")).strip()
        primary = label.lower() in PRIMARY.get(f, ())
        if f == "notes" or not primary or fields.get(f):
            put(f, f"**{label}:** {body_text}" if body_text and _inline_ok(body_text) else f"**{label}:**\n{body_text}")
        else:
            put(f, body_text)
    # inline (B0.) prompts inside numbered items (e.g. "1. **Rebase #1976** …\n   > (B0.) …"), anywhere but a prompt
    item = None
    scan = [ln for label, _a, lines in blocks if label is None or _field_for(label) != "agent_prompt" for ln in lines]
    for ln in scan:
        m = re.match(r"^\s*(\d+)\.\s+\*\*([^*]+)\*\*", ln)
        if m:
            item = f"{m.group(1)}. {m.group(2).rstrip(':.')}"
        q = re.match(r"^\s*>\s?(.*)$", ln)
        if q and q.group(1).lstrip().startswith("(B0"):
            inline_prompts.append((f"**Item {item}:** " if item else "") + _strip_b0(q.group(1)))
    if lead:
        put("problem" if "problem" not in fields else "notes", lead)
        if "problem" in fields and len(fields["problem"]) > 1:  # keep the labelled problem first
            fields["problem"] = fields["problem"][1:] + fields["problem"][:1]
    if inline_prompts and "agent_prompt" not in fields:
        fields["agent_prompt"] = ["\n\n".join(inline_prompts)]
    out = {k: "\n\n".join(v).strip() for k, v in fields.items() if "".join(v).strip()}
    return {
        "wp_id": wp_id,
        "title": title.strip(),
        "stage": (stage or {}).get("stage"),
        "stage_num": (stage or {}).get("num"),
        **hdr,
        "wp_status": wp_status,
        "wp_status_note": note,
        "sections": out,
        "prs": sorted({int(n) for n in _PR.findall(" ".join([title, hdr.get("status_text") or "", note or ""]))}),
    }


def parse_handoff(text: str) -> dict[str, Any]:
    """Every stage (with its intro) and every work package, in document order."""
    lines = text.replace("\r\n", "\n").split("\n")
    stages: list[dict[str, Any]] = []
    wps: list[dict[str, Any]] = []
    stage: dict[str, Any] | None = None
    cur: tuple[str, str, list[str]] | None = None
    stage_intro: list[str] | None = None
    fence = False

    def flush() -> None:
        nonlocal cur
        if cur is not None:
            wps.append(parse_wp(cur[0], cur[1], cur[2], stage))
            cur = None

    for ln in lines:
        if ln.startswith("```"):
            fence = not fence
        if not fence:
            sm = _STAGE_HEAD.match(ln)
            wm = _WP_HEAD.match(ln)
            if sm:
                flush()
                stage = {"stage": sm.group(1), "num": int(sm.group(2)), "title": sm.group(3).strip() or None}
                stages.append(stage)
                stage_intro = []
                continue
            if wm:
                flush()
                if stage is not None and stage_intro is not None:
                    stage["description"] = _trim(_unquote(stage_intro)) or None
                    stage_intro = None
                cur = (wm.group(1), wm.group(2), [])
                continue
            if ln.startswith("## ") or ln.startswith("# "):
                flush()
                if stage is not None and stage_intro is not None:
                    stage["description"] = _trim(_unquote(stage_intro)) or None
                stage_intro = None
                stage = None if ln.startswith("# ") or not ln.startswith("## Stage") else stage
                continue
        if cur is not None:
            cur[2].append(ln)
        elif stage_intro is not None:
            stage_intro.append(ln)
    flush()
    for s in stages:
        s.setdefault("description", None)
    return {"stages": stages, "wps": wps}


# --------------------------------------------------------------------------------------------- plan


def task_id_for(wp: dict[str, Any]) -> str:
    num = int(wp["wp_id"].split("-")[1])
    return f"{DESIGN_PREFIX}-P{wp.get('stage_num') or 0}-T{num:02d}"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", re.sub(r"^(OPERATOR|WP-\d+)\s*:?\s*", "", s, flags=re.I).lower()).strip()


def related(wp: dict[str, Any], tasks: list[dict[str, Any]], own_id: str | None) -> list[str]:
    """Existing tasks with the same subject: they name the WP, share a PR number, or have a near-identical title."""
    out = []
    want = set(wp["prs"])
    for t in tasks:
        if t["task_id"] == own_id or t.get("wp_id") or t.get("source") == SOURCE:
            continue
        title = str(t.get("title") or "")
        prs = {int(n) for n in _PR.findall(title)}
        same = (
            re.search(rf"\b{re.escape(wp['wp_id'])}\b", title)
            or (want and want & prs)
            or SequenceMatcher(None, _norm(title), _norm(wp["title"])).ratio() >= 0.8
        )
        if same:
            out.append(t["task_id"])
    return out[:8]


def structure_of(wp: dict[str, Any], source_ref: str) -> dict[str, Any]:
    sec = wp["sections"]
    return {
        "problem": sec.get("problem"),
        "definition_of_done": sec.get("definition_of_done"),
        "agent_prompt": sec.get("agent_prompt"),
        "operator_commands": sec.get("operator_commands"),
        "proof": sec.get("proof"),
        **({"proof_evidence": sec["proof_evidence"]} if sec.get("proof_evidence") else {}),
        "notes": sec.get("notes"),
        "wp_id": wp["wp_id"],
        "stage": wp.get("stage"),
        "owner_kind": wp["owner_kind"],
        "owner_label": wp.get("owner_label"),
        "wp_status": wp["wp_status"],
        "wp_status_note": wp.get("wp_status_note"),
        "source_ref": source_ref,
    }


def plan(parsed: dict[str, Any], tasks: list[dict[str, Any]], source_name: str) -> list[dict[str, Any]]:
    by_wp = {t["wp_id"]: t for t in tasks if t.get("wp_id")}
    by_id = {t["task_id"]: t for t in tasks}
    rows = []
    for wp in parsed["wps"]:
        existing = by_wp.get(wp["wp_id"])
        tid = existing["task_id"] if existing else task_id_for(wp)
        if not existing and tid in by_id:
            existing = by_id[tid]
        owned = existing is None or existing.get("source") == SOURCE
        struct = structure_of(wp, f"{source_name}#{wp['wp_id'].lower()}")
        rel = related(wp, tasks, tid)
        if existing:
            diff = [
                k
                for k, v in struct.items()
                if k != "source_ref"
                and (owned or v is not None)
                and (existing.get(k) or None) != (TB.normalize_structure({k: v})[k] or None)
            ]
            if owned and existing.get("title") != f"{wp['wp_id']} {wp['title']}"[:200]:
                diff.append("title")
            if existing.get("related_tasks") != rel and rel:
                diff.append("related_tasks")
            action = "UPDATE" if diff else "UNCHANGED"
        else:
            diff, action = list(struct), "CREATE"
        close = wp["wp_status"] == "done" and (existing or {}).get("status", "free") == "free"
        rows.append(
            {
                "wp": wp,
                "task_id": tid,
                "action": action,
                "owned": owned,
                "changed": diff,
                "structure": struct,
                "related": rel,
                "close": close,
                "existing_status": (existing or {}).get("status"),
            }
        )
    for r in rows:
        if r["action"] != "CREATE" and r["owned"]:
            cur = list((by_id.get(r["task_id"]) or {}).get("depends_on") or [])
            if cur != deps_for(r, rows):
                r["changed"].append("depends_on")
                r["action"] = "UPDATE"
    return rows


def deps_for(row: dict[str, Any], rows: list[dict[str, Any]]) -> list[str]:
    ids = {r["wp"]["wp_id"]: r["task_id"] for r in rows}
    return [ids[d] for d in row["wp"]["depends"] if d in ids and ids[d] != row["task_id"]]


def print_plan(rows: list[dict[str, Any]], parsed: dict[str, Any], *, stream=None) -> None:
    out = stream or sys.stdout
    for s in parsed["stages"]:
        n = sum(1 for r in rows if r["wp"].get("stage") == s["stage"])
        intro = "intro " + str(len(s.get("description") or "")) + " chars" if s.get("description") else "no intro"
        print(f"{s['stage']}: {s.get('title')} — {n} WPs, {intro}", file=out)
    print("", file=out)
    for r in rows:
        wp = r["wp"]
        secs = ",".join(
            k
            for k in ("problem", "definition_of_done", "agent_prompt", "operator_commands", "proof", "notes")
            if wp["sections"].get(k)
        )
        wp_of = {x["task_id"]: x["wp"]["wp_id"] for x in rows}
        deps = [wp_of[d] for d in deps_for(r, rows)] if r["owned"] else []
        print(
            f"{r['action']:<9} {wp['wp_id']} -> {r['task_id']}  [{wp['owner_kind']}, {wp.get('stage') or '-'}, "
            f"{wp['wp_status']}] {wp['title'][:70]}",
            file=out,
        )
        print(f"          sections: {secs or '(none)'}"
              + (f" · depends: {', '.join(deps)}" if deps else "")
              + (f" · related: {', '.join(r['related'])}" if r["related"] else "")
              + ("" if r["owned"] else f" · adopts existing task ({r['existing_status']}): sections only")
              + (" · CLOSE with status evidence" if r["close"] else "")
              + (f" · changes: {', '.join(r['changed'])}" if r["action"] == "UPDATE" else ""),
              file=out)  # fmt: skip
    counts = {a: sum(1 for r in rows if r["action"] == a) for a in ("CREATE", "UPDATE", "UNCHANGED")}
    print(
        f"\nplan: {len(rows)} work packages · create {counts['CREATE']} · update {counts['UPDATE']} · unchanged "
        f"{counts['UNCHANGED']} · close {sum(1 for r in rows if r['close'])} · with related tasks "
        f"{sum(1 for r in rows if r['related'])} · stages {len(parsed['stages'])}",
        file=out,
    )


def apply(rows: list[dict[str, Any]], parsed: dict[str, Any], tb: TB.TaskBoard, *, by: str, source: str) -> dict:
    created = updated = closed = 0
    for r in rows:
        wp, struct = r["wp"], dict(r["structure"])
        title = f"{wp['wp_id']} {wp['title']}"
        if r["action"] == "CREATE":
            tb.add(
                task_id=r["task_id"],
                title=title,
                kind="review" if wp["owner_kind"] == "OPERATOR" else "build",
                areas=[f"handoff/{wp['wp_id']}"],
                priority=STAGE_PRIORITY.get(wp.get("stage_num") or 0, 3),
                source=SOURCE,
                created_by=by,
                structure={k: v for k, v in struct.items() if v is not None},
            )
            created += 1
        elif r["action"] == "UPDATE":
            if not r["owned"]:  # an adopted task keeps whatever the handoff does not say
                struct = {k: v for k, v in struct.items() if v is not None}
            tb.edit(r["task_id"], by=by, title=title if r["owned"] else None, **struct)
            updated += 1
    for r in rows:  # second pass: dependencies (every WP task exists now) and related links
        extra: dict[str, Any] = {}
        if r["owned"]:
            extra["depends_on"] = deps_for(r, rows)
        if r["related"]:
            extra["related_tasks"] = r["related"]
        if extra:
            tb.edit(r["task_id"], by=by, **extra)
        if r["close"]:
            note = r["wp"].get("wp_status_note") or "marked [x] in the handoff"
            links = re.findall(r"#\d{3,5}|\b[0-9a-f]{9,40}\b|\S+/\S+\.json", note) or [
                f"{source}#{r['wp']['wp_id'].lower()}"
            ]
            tb.evidence_done(
                r["task_id"],
                actor={"vendor": "import", "session": by, "agent": "import_handoff_workpackages"},
                summary=f"{r['wp']['wp_id']} marked [x] in the handoff: {note}",
                evidence=links,
                mode="handoff_import",
            )
            closed += 1
    tb.set_stages(
        [{"stage": s["stage"], "title": s.get("title"), "description": s.get("description")} for s in parsed["stages"]],
        source=source,
        by=by,
    )
    return {"created": created, "updated": updated, "closed": closed, "stages": len(parsed["stages"])}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--file", required=True, help="the handoff markdown (e.g. HANDOFF_v3_ORDERED_WORK.md)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--claims-dir", default=None, help="default: TRADEAI_AGENT_CLAIMS_DIR or persistent-state")
    ap.add_argument("--session", default=None, help="actor recorded on the task history (default AGENT_CLAIM_SESSION)")
    a = ap.parse_args(argv)
    path = Path(a.file).expanduser()
    try:
        parsed = parse_handoff(path.read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not parsed["wps"]:
        print(f"error: no '### WP-NN' sections in {path}", file=sys.stderr)
        return 2
    tb = TB.TaskBoard(B.ClaimBoard(a.claims_dir))
    rows = plan(parsed, tb.read_all(), path.name)
    print(f"{'DRY RUN' if a.dry_run else 'APPLY'}: {path} -> {tb.dir}")
    print_plan(rows, parsed)
    if a.dry_run:
        print("dry run: nothing written")
        return 0
    by = a.session or B.detect_session() or "import"
    try:
        res = apply(rows, parsed, tb, by=f"import/{by}", source=path.name)
    except (TB.TaskError, B.ClaimError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(
        f"applied: created {res['created']} · updated {res['updated']} · closed {res['closed']} · stages {res['stages']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
