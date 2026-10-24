"""Per-claim worklog: the hand-off file another agent can pick up from.

Operator 2026-10-23, verbatim: "put their complete changes and what are they planning to do into a file, and then
annotate when it is actually done or complete … just in case I need another agent to pick up anything".

One markdown file next to each claim, ``<claims_dir>/<claim_id>.worklog.md``, created by ``agent_claim.py claim``.
Fixed sections, in this order (AGENTS.md 20.0.0 §28.3 names them; keep the names exact)::

    ## Goal          the task, the operator request quoted
    ## Plan          checkbox steps: "- [ ] step" / "- [x] step"            (plan, done)
    ## Changes made  files, commits, PR, each with a time                   (note --change, stage, observed merge)
    ## Decisions     decisions and why                                       (note)
    ## Blockers      what is blocking and what is needed from whom           (blocker)
    ## Status        stage changes with times (declared and observed), the final summary at release
    ## Handoff       exact next step, branch / worktree path, how to verify  (handoff)

Every entry starts with a backticked UTC time. Entries written by the board itself (observed stage changes) end
with ``(auto)``; they do not count as the agent's own activity for the pre-commit freshness check.

Writes are read-modify-replace (temp + ``os.replace``) under an flock on ``<claims_dir>/.worklog.lock``, because the
owner and an observer (``sync --apply``) may both append. Compaction moves the file to
``<claims_dir>/worklog_archive/`` (never deleted). Stdlib only. AUTHORITY: READ_ONLY_ADVISORY (coordination files).
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SECTIONS = ("Goal", "Plan", "Changes made", "Decisions", "Blockers", "Status", "Handoff")
SUFFIX = ".worklog.md"
ARCHIVE_DIRNAME = "worklog_archive"
LOCK_NAME = ".worklog.lock"
FRESH_HOURS = 2.0
MAX_TEXT = 1000
MAX_API_BYTES = 64 * 1024
_TS_RE = re.compile(r"`(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)`")
_STEP_RE = re.compile(r"^- \[( |x)\] (.*?)(?:  _\(added [^)]*\)_)?(?:  _\(done [^)]*\)_)?$")
_HANDOFF_KEYS = ("Next step", "Branch", "Worktree", "Verify")


class WorklogError(Exception):
    """A refused worklog operation (missing file, empty text, ambiguous step)."""


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _clean(text: Any, n: int = MAX_TEXT) -> str:
    s = re.sub(r"[\x00-\x1f\x7f]", " ", str(text or "")).strip()
    return s[:n]


def path_for(claims_dir: Path, claim_id: str) -> Path:
    return Path(claims_dir) / f"{claim_id}{SUFFIX}"


def archive_dir(claims_dir: Path) -> Path:
    return Path(claims_dir) / ARCHIVE_DIRNAME


# --------------------------------------------------------------------------------------------- parse / render


def parse(text: str) -> tuple[str, dict[str, list[str]]]:
    """(header, {section: lines}). Unknown ``##`` headings are kept under the preceding section."""
    header: list[str] = []
    out: dict[str, list[str]] = {s: [] for s in SECTIONS}
    cur: str | None = None
    for line in text.splitlines():
        m = re.match(r"^## (.+?)\s*$", line)
        if m and m.group(1) in SECTIONS:
            cur = m.group(1)
            continue
        if cur is None:
            header.append(line)
        else:
            out[cur].append(line)
    for s in SECTIONS:
        while out[s] and not out[s][-1].strip():
            out[s].pop()
        while out[s] and not out[s][0].strip():
            out[s].pop(0)
    return "\n".join(header).rstrip(), out


def render(header: str, sections: Mapping[str, list[str]]) -> str:
    parts = [header.rstrip(), ""]
    for s in SECTIONS:
        parts.append(f"## {s}")
        parts.append("")
        lines = list(sections.get(s) or [])
        parts.extend(lines if lines else ["_(none yet)_"])
        parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def _strip_placeholder(lines: list[str]) -> list[str]:
    return [ln for ln in lines if ln.strip() != "_(none yet)_"]


# --------------------------------------------------------------------------------------------- store


class Worklog:
    def __init__(self, claims_dir: Path | str, claim_id: str, *, now=None):
        self.dir = Path(claims_dir)
        self.claim_id = claim_id
        self.path = path_for(self.dir, claim_id)
        self._now = now or (lambda: datetime.now(timezone.utc))

    def exists(self) -> bool:
        return self.path.is_file()

    def ts(self) -> str:
        return _iso(self._now())

    def read(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise WorklogError(f"no worklog for claim {self.claim_id} ({self.path}): {type(exc).__name__}") from exc

    def _write(self, text: str) -> None:
        tmp = self.dir / f".{self.path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp"
        fd = os.open(str(tmp), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            os.write(fd, text.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(str(tmp), str(self.path))

    def _edit(self, fn) -> dict[str, list[str]]:
        self.dir.mkdir(parents=True, exist_ok=True)
        with open(self.dir / LOCK_NAME, "a", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                header, sections = parse(self.read())
                sections = {k: _strip_placeholder(v) for k, v in sections.items()}
                fn(sections)
                self._write(render(header, sections))
                return sections
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    # -- create -------------------------------------------------------------------------------------

    def create(
        self,
        doc: Mapping[str, Any],
        *,
        goal: str | None = None,
        request: str | None = None,
        plan: list[str] | None = None,
        worktree: str | None = None,
    ) -> Path:
        """Write the initial worklog. Never overwrites an existing one."""
        t = self.ts()
        header = (
            f"# Worklog — {_clean(doc.get('task'), 200)}\n\n"
            f"- Claim: `{self.claim_id}` · {doc.get('vendor')}/{doc.get('agent') or '-'} · session `{doc.get('session')}`\n"
            f"- Created: `{t}`\n"
            f"- Paths: {', '.join(f'`{p}`' for p in doc.get('paths') or [])}\n"
            f"- Board: `python3 scripts/agent_claim.py takeover {self.claim_id}` prints the Handoff section first."
        )
        sections: dict[str, list[str]] = {s: [] for s in SECTIONS}
        sections["Goal"].append(_clean(goal or doc.get("task")))
        if request:
            sections["Goal"].extend(["", *[f"> {ln}" for ln in _clean(request, 4000).splitlines() or [""]]])
        sections["Plan"] = [f"- [ ] {_clean(p, 300)}  _(added {t})_" for p in (plan or []) if _clean(p)]
        sections["Status"].append(f"- `{t}` claimed")
        sections["Handoff"] = [
            "- Next step: (not set — `agent_claim.py handoff <id> --next ...`)",
            f"- Branch: `{doc.get('branch') or '?'}`",
            f"- Worktree: `{worktree or '?'}`",
            "- Verify: (not set)",
        ]
        self.dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            os.write(fd, render(header, sections).encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        return self.path

    def carry_forward(self, old_text: str, doc: Mapping[str, Any], line: str) -> Path:
        """Takeover: a new worklog that keeps every section of the old one, plus the 'taken over by' line in Status."""
        _h, old = parse(old_text)
        t = self.ts()
        header = (
            f"# Worklog — {_clean(doc.get('task'), 200)}\n\n"
            f"- Claim: `{self.claim_id}` · {doc.get('vendor')}/{doc.get('agent') or '-'} · session `{doc.get('session')}`\n"
            f"- Created: `{t}` (carried forward)\n"
            f"- Paths: {', '.join(f'`{p}`' for p in doc.get('paths') or [])}"
        )
        sections = {k: _strip_placeholder(v) for k, v in old.items()}
        sections["Status"].append(f"- `{t}` {_clean(line)}")
        self.dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            os.write(fd, render(header, sections).encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        return self.path

    # -- entries ------------------------------------------------------------------------------------

    def plan(self, step: str) -> None:
        step = _clean(step, 300)
        if not step:
            raise WorklogError("empty plan step")
        t = self.ts()
        self._edit(lambda s: s["Plan"].append(f"- [ ] {step}  _(added {t})_"))

    def done(self, step: str) -> str:
        """Check off the plan step matching ``step`` (exact, else a unique case-insensitive substring). An unknown step
        is added already checked. Returns the step text checked."""
        want = _clean(step, 300)
        if not want:
            raise WorklogError("empty step")
        t = self.ts()
        result: list[str] = []

        def fn(s: dict[str, list[str]]) -> None:
            open_steps = [(i, _STEP_RE.match(ln)) for i, ln in enumerate(s["Plan"])]
            open_steps = [(i, m) for i, m in open_steps if m and m.group(1) == " "]
            exact = [(i, m) for i, m in open_steps if m.group(2).strip() == want]
            hits = exact or [(i, m) for i, m in open_steps if want.lower() in m.group(2).lower()]
            if len(hits) > 1:
                raise WorklogError(f"{len(hits)} open plan steps match {want!r}; use the exact step text")
            if hits:
                i, m = hits[0]
                line = s["Plan"][i].replace("- [ ] ", "- [x] ", 1)
                s["Plan"][i] = f"{line}  _(done {t})_"
                result.append(m.group(2).strip())
            else:
                s["Plan"].append(f"- [x] {want}  _(added {t})_  _(done {t})_")
                result.append(want)

        self._edit(fn)
        return result[0]

    def note(self, text: str, *, change: bool = False) -> None:
        text = _clean(text)
        if not text:
            raise WorklogError("empty note")
        t = self.ts()
        self._edit(lambda s: s["Changes made" if change else "Decisions"].append(f"- `{t}` {text}"))

    def blocker(self, text: str) -> None:
        text = _clean(text)
        if not text:
            raise WorklogError("empty blocker")
        t = self.ts()
        self._edit(lambda s: s["Blockers"].append(f"- `{t}` {text}"))

    def handoff(self, **fields: str | None) -> None:
        t = self.ts()
        keymap = {"next_step": "Next step", "branch": "Branch", "worktree": "Worktree", "verify": "Verify"}

        def fn(s: dict[str, list[str]]) -> None:
            lines = s["Handoff"]
            for k, v in fields.items():
                if v is None:
                    continue
                label = keymap[k]
                val = _clean(v)
                new = f"- {label}: {val}  _(`{t}`)_"
                idx = next((i for i, ln in enumerate(lines) if ln.startswith(f"- {label}:")), None)
                if idx is None:
                    lines.append(new)
                else:
                    lines[idx] = new

        self._edit(fn)

    def status(self, text: str, *, auto: bool = False, at: str | None = None) -> None:
        t = at or self.ts()
        line = f"- `{t}` {_clean(text)}" + ("  (auto)" if auto else "")
        self._edit(lambda s: s["Status"].append(line))

    def change(self, text: str, *, auto: bool = False) -> None:
        t = self.ts()
        line = f"- `{t}` {_clean(text)}" + ("  (auto)" if auto else "")
        self._edit(lambda s: s["Changes made"].append(line))

    def final_summary(self, summary: str, status: str) -> None:
        summary = _clean(summary)
        if not summary:
            raise WorklogError("release needs a final summary line (--summary)")
        t = self.ts()
        self._edit(lambda s: s["Status"].append(f"- `{t}` released by its agent ({status}). Final summary: {summary}"))


# --------------------------------------------------------------------------------------------- read model


def summarize(text: str) -> dict[str, Any]:
    """Plan progress, last agent entry, open blockers, next step, final summary -- for the board and the gate."""
    _h, s = parse(text)
    steps = [m for m in (_STEP_RE.match(ln) for ln in s["Plan"]) if m]
    agent_ts: list[str] = []
    for sec in ("Plan", "Changes made", "Decisions", "Blockers", "Status", "Handoff"):
        for ln in s[sec]:
            if ln.rstrip().endswith("(auto)"):
                continue
            agent_ts.extend(_TS_RE.findall(ln))
            agent_ts.extend(re.findall(r"_\((?:added|done) (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)\)_", ln))
    nxt = next((ln.split(":", 1)[1].strip() for ln in s["Handoff"] if ln.startswith("- Next step:")), None)
    final = next((ln for ln in reversed(s["Status"]) if "Final summary:" in ln), None)
    return {
        "plan_total": len(steps),
        "plan_done": sum(1 for m in steps if m.group(1) == "x"),
        "last_entry_at": max(agent_ts) if agent_ts else None,
        "blockers": len(_strip_placeholder(s["Blockers"])),
        "next_step": nxt,
        "final_summary": final.split("Final summary:", 1)[1].strip() if final else None,
    }


def handoff_text(text: str) -> str:
    """The Handoff section first, then open plan steps and blockers: what ``takeover`` prints."""
    _h, s = parse(text)
    open_steps = [ln for ln in s["Plan"] if ln.startswith("- [ ]")]
    out = ["## Handoff", *(_strip_placeholder(s["Handoff"]) or ["(empty)"]), "", "## Open plan steps"]
    out += open_steps or ["(none)"]
    out += ["", "## Blockers", *(_strip_placeholder(s["Blockers"]) or ["(none)"])]
    return "\n".join(out) + "\n"


def board_summary(claims_dir: Path, claim_id: str, now: datetime) -> dict[str, Any]:
    p = path_for(claims_dir, claim_id)
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return {"exists": False, "path": str(p)}
    summ = summarize(text)
    last = summ.get("last_entry_at")
    age = None
    if last:
        try:
            age = round((now - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds() / 60, 1)
        except ValueError:
            age = None
    return {"exists": True, "path": str(p), "last_entry_age_minutes": age, **summ}


def archive(claims_dir: Path, claim_id: str) -> dict[str, Any] | None:
    """Move the worklog to worklog_archive/ (never delete). Returns {path, sha256} or None if there is none."""
    src = path_for(claims_dir, claim_id)
    if not src.is_file():
        return None
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    dst_dir = archive_dir(claims_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    if dst.exists():  # never clobber an earlier archive
        dst = dst_dir / f"{claim_id}.{digest[:12]}{SUFFIX}"
    os.replace(str(src), str(dst))
    return {"path": str(dst), "sha256": digest}


def read_any(claims_dir: Path, claim_id: str) -> tuple[str, str] | None:
    """(path, text) from the live file, else the archive. Text capped at MAX_API_BYTES."""
    for p in [path_for(claims_dir, claim_id), *sorted(archive_dir(claims_dir).glob(f"{claim_id}*{SUFFIX}"))]:
        try:
            raw = p.read_bytes()[:MAX_API_BYTES]
        except OSError:
            continue
        return str(p), raw.decode("utf-8", "replace")
    return None
