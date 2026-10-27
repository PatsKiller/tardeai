"""PrReview@v1 — the independent, head-bound PR review behind Approvals → Merges (Design approvals-pr-review/v001).

Operator 2026-10-27: "we really need to build something that actually has a review that I can review in the same
modal of the command center." Decisions D1–D7 as recommended (operator 2026-10-27, relayed by the coordinator;
docs/ops/PR_REVIEW_MODAL_SPEC.md §12, config/pr_independent_review.json).

The deterministic harness here owns every field except the ones the model writes (summary, risk, one note per hunk,
findings, verdict), and it re-rules those: the risk floor (shared-infra → MEDIUM, held → HIGH), findings outside a
changed hunk are dropped and counted, more than 10% unexplained hunks → CANNOT_REVIEW, any BLOCKER → HOLD. Whether a
PR is held is never the model's call (config/merge_hold_paths.json).

Store (domain ``pr_reviews``, single writer scripts/pr_independent_review.py; host persistent-state, never git):
  <store>/<pr>/<head_sha>.json    PrReview@v1, one per (PR, head); a newer head never overwrites an older review
  <store>/index.jsonl             append-only (pr, head, verdict, document_sha, at)
  <store>/status/<pr>.json        PrReviewQueueStatus@v1: the latest head's queue state (settling, waiting for
                                  credit, cannot review) when no review exists for it
  <store>/open_prs.json           PrReviewOpenPrs@v1: the runner's snapshot of open PRs (a GET never calls GitHub)
  <store>/spend.jsonl             PrReviewSpend@v1: every model call, its process, provider and cost
  <store>/answers.jsonl           PrReviewAnswer@v1: the reviewer's answer to an operator QUESTION ledger row
Nothing is deleted (AGENTS.md §0 rule 6). Writes refuse with STORE_APPROVAL_PENDING until the operator-approved
``pr_reviews`` row is in config/data_source_authority.json (D5; §26.6).

Advisory only: nothing here merges, labels, approves, pushes or comments on GitHub. ``MBI_BEHAVIOR = 0``.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "pr_independent_review.json"
SCHEMA = "PrReview@v1"
STATUS_SCHEMA = "PrReviewQueueStatus@v1"
SNAPSHOT_SCHEMA = "PrReviewOpenPrs@v1"
SPEND_SCHEMA = "PrReviewSpend@v1"
ANSWER_SCHEMA = "PrReviewAnswer@v1"
VERDICTS = ("MERGE", "MERGE_WITH_NOTES", "HOLD", "CANNOT_REVIEW")
SEVERITIES = ("BLOCKER", "MAJOR", "MINOR", "NOTE")
RISK = ("LOW", "MEDIUM", "HIGH")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
#: Fields that change at read time or after publication; never part of what the ledger binds.
RUNTIME_FIELDS = ("stale", "status_post", "document_sha", "current_head")
INDEPENDENCE_RULE = "AGENTS.md §28.15 item 10"


class StoreRefused(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def load_config(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or CONFIG).read_text(encoding="utf-8"))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def parse_iso(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else None


def digest(value: Any) -> str:
    """Same canonical form as scripts/lib/operator_approvals.digest (the ledger binds this)."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode()).hexdigest()


# ── the store and its approval (D5) ──────────────────────────────────────────


def store_approved(registry: Mapping[str, Any], cfg: Mapping[str, Any] | None = None) -> bool:
    """True only for an operator-approved ``pr_reviews`` row naming this store and writer. No env flag replaces it."""
    cfg = cfg or load_config()
    domains = registry.get("domains") or []
    rows = domains.values() if isinstance(domains, dict) else domains
    want_dir = str(cfg.get("store_rel", "")).removeprefix("data/")
    for row in rows:
        if not isinstance(row, dict) or row.get("domain", row.get("id")) != cfg.get("store_domain", "pr_reviews"):
            continue
        store, approval = row.get("store") or {}, row.get("approval") or {}
        if (isinstance(store, dict) and store.get("dir") == want_dir and row.get("writer") == cfg.get("store_writer")
                and approval.get("approved_by") == "operator" and approval.get("approved_on") and approval.get("reference")):
            return True
    return False


def registry_store_approved(root: Path = ROOT, cfg: Mapping[str, Any] | None = None) -> bool:
    try:
        return store_approved(json.loads((root / "config/data_source_authority.json").read_text(encoding="utf-8")), cfg)
    except (OSError, ValueError):
        return False


def store_dir(state_root: Path, cfg: Mapping[str, Any] | None = None) -> Path:
    return Path(state_root) / (cfg or load_config()).get("store_rel", "data/coordination/pr_reviews")


class Store:
    """Single-writer store. Reads never create anything; every write needs the approved row."""

    def __init__(self, root: Path, *, approved: Callable[[], bool]):
        self.root, self.approved = Path(root), approved

    # reads
    def _json(self, path: Path, default: Any) -> Any:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    def _jsonl(self, name: str) -> list[dict]:
        path = self.root / name
        if not path.is_file():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                out.append(row)
        return out

    def review(self, pr: int, head: str) -> Optional[dict]:
        if not SHA40.fullmatch(str(head)):
            return None
        rec = self._json(self.root / str(int(pr)) / f"{head}.json", None)
        return rec if isinstance(rec, dict) and rec.get("schema") == SCHEMA else None

    def reviews_for(self, pr: int) -> list[dict]:
        d = self.root / str(int(pr))
        if not d.is_dir():
            return []
        out = [r for p in d.glob("*.json") if isinstance(r := self._json(p, None), dict) and r.get("schema") == SCHEMA]
        return sorted(out, key=lambda r: str(r.get("created_at") or ""))

    def latest(self, pr: int) -> Optional[dict]:
        rows = self.reviews_for(pr)
        return rows[-1] if rows else None

    def status(self, pr: int) -> Optional[dict]:
        row = self._json(self.root / "status" / f"{int(pr)}.json", None)
        return row if isinstance(row, dict) else None

    def snapshot(self) -> Optional[dict]:
        row = self._json(self.root / "open_prs.json", None)
        return row if isinstance(row, dict) and row.get("schema") == SNAPSHOT_SCHEMA else None

    def spend(self) -> list[dict]:
        return self._jsonl("spend.jsonl")

    def answers(self) -> list[dict]:
        return self._jsonl("answers.jsonl")

    def index(self) -> list[dict]:
        return self._jsonl("index.jsonl")

    # writes
    def _guard(self) -> None:
        if not self.approved():
            raise StoreRefused("STORE_APPROVAL_PENDING")

    def _atomic(self, path: Path, obj: Any) -> None:
        self._guard()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
        tmp.write_text(json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)

    def _append(self, name: str, row: dict) -> None:
        self._guard()
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / name).open("a", encoding="utf-8") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            fh.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def write_review(self, rec: dict) -> Path:
        path = self.root / str(int(rec["pr"])) / f"{rec['head_sha']}.json"
        if path.exists():
            raise StoreRefused("REVIEW_EXISTS")  # one review per (PR, head); never overwritten
        self._atomic(path, rec)
        self._append("index.jsonl", {"pr": rec["pr"], "head_sha": rec["head_sha"], "verdict": rec["verdict"],
                                     "document_sha": rec["document_sha"], "at": rec["created_at"]})
        return path

    def update_status_post(self, rec: dict, post: dict) -> None:
        """The commit-status outcome is a runtime field (outside document_sha); recorded on the same file."""
        path = self.root / str(int(rec["pr"])) / f"{rec['head_sha']}.json"
        current = self._json(path, None)
        if isinstance(current, dict) and current.get("document_sha") == rec["document_sha"]:
            self._atomic(path, {**current, "status_post": post})

    def write_status(self, row: dict) -> None:
        self._atomic(self.root / "status" / f"{int(row['pr'])}.json", {"schema": STATUS_SCHEMA, **row})

    def write_snapshot(self, row: dict) -> None:
        self._atomic(self.root / "open_prs.json", {"schema": SNAPSHOT_SCHEMA, **row})

    def add_spend(self, row: dict) -> None:
        self._append("spend.jsonl", {"schema": SPEND_SCHEMA, **row})

    def add_answer(self, row: dict) -> None:
        self._append("answers.jsonl", {"schema": ANSWER_SCHEMA, **row})


# ── the diff: files, areas, hunks ────────────────────────────────────────────


_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")


def area_of(path: str, cfg: Mapping[str, Any]) -> str:
    for area in cfg.get("areas") or []:
        if any(path.startswith(p) for p in area.get("prefixes") or []):
            return str(area["name"])
    return str(cfg.get("default_area") or "Other")


def split_hunks(diff: str) -> list[dict]:
    """Unified diff → hunks {id, file, header, start_line, end_line, old_start, old_end, added, removed, lines}.

    ``id`` is stable for (file, header, body), so a note keyed by it cannot attach to a different hunk.
    """
    hunks: list[dict] = []
    file = None
    current: Optional[dict] = None

    def close():
        nonlocal current
        if current is not None:
            body = "\n".join(current["lines"])
            current["id"] = "h_" + hashlib.sha256(f"{current['file']}\0{current['header']}\0{body}".encode()).hexdigest()[:16]
            hunks.append(current)
        current = None

    for line in diff.splitlines():
        if line.startswith("diff --git "):
            close()
            m = re.match(r"^diff --git a/(.+?) b/(.+)$", line)
            file = m.group(2) if m else None
            continue
        if line.startswith("+++ "):
            target = line[4:].strip()
            if target != "/dev/null":
                file = target[2:] if target.startswith("b/") else target
            continue
        if line.startswith("--- ") and current is None:
            source = line[4:].strip()
            if file is None and source != "/dev/null":
                file = source[2:] if source.startswith("a/") else source
            continue
        m = _HUNK.match(line)
        if m and file:
            close()
            old_start, old_len = int(m.group(1)), int(m.group(2) or 1)
            new_start, new_len = int(m.group(3)), int(m.group(4) or 1)
            current = {"file": file, "header": line[: line.index("@@", 2) + 2] + (m.group(5) or ""),
                       "start_line": new_start, "end_line": new_start + max(new_len, 1) - 1,
                       "old_start": old_start, "old_end": old_start + max(old_len, 1) - 1,
                       "added": 0, "removed": 0, "lines": []}
            continue
        if current is not None:
            if line.startswith("+"):
                current["added"] += 1
            elif line.startswith("-"):
                current["removed"] += 1
            elif not line.startswith((" ", "\\")) and line != "":
                close()
                continue
            current["lines"].append(line)
    close()
    return hunks


def diff_files(hunks: Iterable[dict]) -> set[str]:
    return {h["file"] for h in hunks}


# ── author and independence ──────────────────────────────────────────────────


_SESSION = re.compile(r"^Claude-Session:\s*(\S+)", re.M | re.I)
_COAUTHOR = re.compile(r"^Co-Authored-By:\s*(.+?)\s*<", re.M | re.I)
_BODY_AGENT = re.compile(r"^(?:Agent|Session|Author-Agent|Agent-Session):\s*(\S.{0,120})$", re.M | re.I)
_VENDORS = (("claude", "Claude Code"), ("codex", "Codex"), ("cursor", "Cursor"), ("gemini", "Gemini"), ("grok", "Grok"))


def author_identity(commit_messages: Iterable[str], body: str = "", login: str = "") -> dict:
    """Author ids from commit trailers (Claude-Session:, Co-Authored-By:) and the PR body (Agent:/Session: lines)."""
    sessions, models, agents = [], [], []
    for msg in commit_messages:
        sessions += _SESSION.findall(msg or "")
        models += [m for m in _COAUTHOR.findall(msg or "") if not re.match(r"^john\b", m, re.I)]
    agents += [a.strip() for a in _BODY_AGENT.findall(body or "")]
    text = " ".join(sessions + models + agents).lower()
    vendor = next((name for key, name in _VENDORS if key in text), None)
    session = sessions[-1] if sessions else (agents[0] if agents else None)
    short = session.rstrip("/").rsplit("/", 1)[-1] if session else None
    ids = sorted({*sessions, *agents, *([f"login:{login}"] if login else [])})
    return {"vendor": vendor or "unknown", "agent": agents[0] if agents else None, "session": short,
            "model": models[-1] if models else None, "ids": ids}


def reviewer_id(run_id: str) -> str:
    return f"host:pr_independent_review:{run_id}"


def independence(author: Mapping[str, Any], reviewer: Mapping[str, Any]) -> dict:
    """The reviewer is a host process with a fresh context. It is independent unless an author id names it."""
    rid = str(reviewer.get("id") or "")
    compared = list(author.get("ids") or [])
    clash = [a for a in compared if a == rid or "pr_independent_review" in str(a)]
    family = lambda s: (re.search(r"(opus|sonnet|haiku|fable|gpt|grok)", str(s or "").lower()) or [None])[0]  # noqa: E731
    return {"ok": not clash and bool(rid), "rule": INDEPENDENCE_RULE, "compared": compared, "reviewer": rid,
            "same_model_family": bool(family(author.get("model")) and family(author.get("model")) == family(reviewer.get("model"))),
            "reason": "reviewer id matches an author id" if clash else None}


# ── eligibility, classes and evidence (GitHub facts, never the model's word) ─


def held_classes(paths: list[str], labels: Iterable[str]) -> list[str]:
    try:
        from scripts.lib import merge_hold_paths as mhp
    except ImportError:  # pragma: no cover
        from lib import merge_hold_paths as mhp  # type: ignore
    out = sorted(mhp.held_classes(paths))
    if set(labels) & mhp.hold_labels():
        out.append("held_label")
    return out


def held_paths(paths: list[str]) -> dict[str, list[str]]:
    """Held class → the changed paths that put the PR in it (shown in the sheet's held banner)."""
    try:
        from scripts.lib import merge_hold_paths as mhp
    except ImportError:  # pragma: no cover
        from lib import merge_hold_paths as mhp  # type: ignore
    return {k: sorted(v)[:5] for k, v in mhp.held_classes(paths).items()}


def required_checks() -> tuple[str, ...]:
    try:
        from scripts.lib import pr_merge_telegram as pmt
    except ImportError:  # pragma: no cover
        from lib import pr_merge_telegram as pmt  # type: ignore
    return tuple(pmt.REQUIRED_CHECKS)


def check_states(rollup: Iterable[Mapping[str, Any]] | None) -> tuple[bool, dict[str, str]]:
    seen: dict[str, set[str]] = {}
    req = required_checks()
    for row in rollup or []:
        name = str(row.get("name") or row.get("context") or "")
        if name in req:
            seen.setdefault(name, set()).add(str(row.get("conclusion") or row.get("state") or row.get("status") or "PENDING").upper())
    states = {c: ("SUCCESS" if seen.get(c) == {"SUCCESS"} else ",".join(sorted(seen.get(c) or {"MISSING"}))) for c in req}
    return all(v == "SUCCESS" for v in states.values()), states


def is_shared_infra(labels: Iterable[str], title: str) -> bool:
    return "shared-infra" in set(labels) or "[shared-infra]" in (title or "").lower()


def evidence_from(pr: Mapping[str, Any], files: list[dict], checks: dict[str, str]) -> dict:
    body = str(pr.get("body") or "")
    tests = [f for f in files if f["path"].startswith("tests/") or "/e2e/" in f["path"] or re.search(r"\.test\.(ts|tsx|mjs)$", f["path"])]
    return {"checks": checks,
            "tests_changed": sum(1 for f in tests if f.get("status") != "added"),
            "tests_added": sum(1 for f in tests if f.get("status") == "added"),
            "dry_run_quoted": bool(re.search(r"dry[- ]run", body, re.I)),
            "real_layout_proof": bool(re.search(r"^Real-layout proof:", body, re.I | re.M)),
            "adversarial_receipts": re.findall(r"Adversarial-review:\s*(MERGE|HOLD)\b[^\n]*", body)[:5]}


# ── data-quality gate (AGENTS.md §29) ────────────────────────────────────────


def data_quality_gate(*, files: list[dict], changed_files: int, hunks: list[dict], head_now: str, head: str,
                      diff_text: str) -> Optional[str]:
    """None when the inputs are whole and bound to ``head``; otherwise the defect. No model call follows a defect."""
    if not SHA40.fullmatch(head or ""):
        return "head SHA unavailable"
    if head_now != head:
        return "the PR head moved while the diff was read"
    if len(files) < int(changed_files or 0):
        return f"partial file list ({len(files)} of {changed_files})"
    if not diff_text.strip():
        return "empty diff"
    textual = {f["path"] for f in files if (f.get("additions") or 0) + (f.get("deletions") or 0) > 0}
    missing = sorted(textual - diff_files(hunks))
    if missing:
        return f"the diff is missing {len(missing)} changed file(s), e.g. {missing[0]}"
    return None


# ── prompt, model output, harness rules ──────────────────────────────────────


def policy_excerpts(agents_text: str, cfg: Mapping[str, Any], *, shared_infra: bool, ui: bool) -> str:
    ps = cfg.get("policy_sections") or {}
    wanted = list(ps.get("always") or []) + (list(ps.get("shared_infra") or []) if shared_infra else []) \
        + (list(ps.get("ui") or []) if ui else [])
    cap = int(ps.get("max_chars_per_section") or 12000)
    out = []
    lines = agents_text.splitlines()
    for head in wanted:
        start = next((i for i, ln in enumerate(lines) if ln.startswith(head)), None)
        if start is None:
            continue
        level = len(head) - len(head.lstrip("#"))
        end = next((j for j in range(start + 1, len(lines)) if re.match(r"^#{1,%d} " % level, lines[j])), len(lines))
        out.append("\n".join(lines[start:end])[:cap])
    return "\n\n".join(out)


OUTPUT_CONTRACT = {
    "summary": "2-5 plain sentences for a non-programmer: what the change does for the operator, and what it does not touch",
    "risk": {"level": "LOW | MEDIUM | HIGH", "why": "one sentence"},
    "hunk_notes": {"<hunk id>": "one line: what this hunk does"},
    "findings": [{"severity": "BLOCKER | MAJOR | MINOR | NOTE", "title": "short", "file": "path of a changed file",
                  "line": "integer line number inside a changed hunk (new side)", "detail": "what is wrong and why",
                  "suggestion": "what to change"}],
    "verdict": "MERGE | MERGE_WITH_NOTES | HOLD | CANNOT_REVIEW",
}


def build_prompt(*, pr: Mapping[str, Any], files: list[dict], hunks: list[dict], policy: str, part: tuple[int, int] = (1, 1)) -> str:
    listing = "\n".join(f"- {f['path']} ({f.get('status')}, +{f.get('additions', 0)} -{f.get('deletions', 0)})" for f in files)
    body = "\n\n".join(f"### hunk {h['id']} · {h['file']}\n{h['header']}\n" + "\n".join(h["lines"]) for h in hunks)
    return (
        "You are an independent code reviewer for a public trading-tools repository. You did not write this PR and "
        "you have no access to its author. Review the EXACT diff below.\n"
        "Rules:\n"
        "1. Report what the diff does, not what the PR description claims. Where the two disagree, raise a finding.\n"
        "2. Every finding must name a changed file and a line inside one of the hunks shown (new-side line number).\n"
        "3. Write one plain one-line note for EVERY hunk id shown, keyed by its id.\n"
        "4. BLOCKER = would break production, lose data, weaken a safety rail or touch broker/order/secret paths "
        "without authority. Never say a PR may merge itself; you only advise.\n"
        "5. Reply with ONE JSON object and nothing else, matching this shape:\n"
        + json.dumps(OUTPUT_CONTRACT, ensure_ascii=False) + "\n\n"
        f"PR #{int(pr['pr'])}: {pr.get('title', '')}\nBase {pr.get('base_sha', '')} · head {pr.get('head_sha', '')}"
        + (f" · part {part[0]} of {part[1]} (other parts are reviewed separately)" if part[1] > 1 else "") + "\n\n"
        f"PR description (claims, not facts):\n{str(pr.get('body') or '')[:6000]}\n\n"
        f"All changed files:\n{listing}\n\n"
        f"Repository rules that apply to these paths (AGENTS.md excerpts):\n{policy}\n\n"
        f"Diff hunks:\n{body}\n"
    )


def parse_model(text: str) -> Optional[dict]:
    """Strict JSON (one object), tolerating a fenced block. Shape-checked; None on any defect."""
    raw = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.S)
    if fenced:
        raw = fenced.group(1)
    try:
        doc = json.loads(raw)
    except ValueError:
        start, end = raw.find("{"), raw.rfind("}")
        try:
            doc = json.loads(raw[start:end + 1]) if start >= 0 and end > start else None
        except ValueError:
            return None
    if not isinstance(doc, dict) or not isinstance(doc.get("summary"), str) or doc.get("verdict") not in VERDICTS:
        return None
    risk = doc.get("risk") if isinstance(doc.get("risk"), dict) else {}
    notes = doc.get("hunk_notes") if isinstance(doc.get("hunk_notes"), dict) else {}
    findings = []
    for f in doc.get("findings") if isinstance(doc.get("findings"), list) else []:
        if not isinstance(f, dict) or f.get("severity") not in SEVERITIES or not isinstance(f.get("title"), str):
            continue
        try:
            line = int(f.get("line")) if f.get("line") is not None else None
        except (TypeError, ValueError):
            line = None
        findings.append({"severity": f["severity"], "title": f["title"][:200], "file": str(f.get("file") or "")[:300],
                         "line": line, "detail": str(f.get("detail") or "")[:2000],
                         "suggestion": str(f.get("suggestion") or "")[:1000]})
    return {"summary": doc["summary"][:1500],
            "risk": {"level": risk.get("level") if risk.get("level") in RISK else "MEDIUM", "why": str(risk.get("why") or "")[:400]},
            "hunk_notes": {str(k): str(v)[:300] for k, v in notes.items() if isinstance(v, str) and v.strip()},
            "findings": findings, "verdict": doc["verdict"]}


def chunk_hunks(hunks: list[dict], budget_chars: int, max_parts: int) -> Optional[list[list[dict]]]:
    """Group hunks by file into at most ``max_parts`` calls under the input budget; None if they cannot fit."""
    parts: list[list[dict]] = [[]]
    size = 0
    for h in hunks:
        cost = len(h["header"]) + sum(len(x) + 1 for x in h["lines"]) + 80
        if cost > budget_chars:
            return None
        if size + cost > budget_chars and parts[-1]:
            parts.append([])
            size = 0
        parts[-1].append(h)
        size += cost
    return parts if len(parts) <= max_parts else None


def merge_parts(outs: list[dict]) -> dict:
    rank = {v: i for i, v in enumerate(VERDICTS)}
    rrank = {v: i for i, v in enumerate(RISK)}
    worst = max(outs, key=lambda o: rrank[o["risk"]["level"]])
    return {"summary": " ".join(o["summary"] for o in outs)[:1500], "risk": worst["risk"],
            "hunk_notes": {k: v for o in outs for k, v in o["hunk_notes"].items()},
            "findings": [f for o in outs for f in o["findings"]],
            "verdict": max((o["verdict"] for o in outs), key=lambda v: rank[v])}


def _in_hunk(f: Mapping[str, Any], hunks: list[dict]) -> Optional[dict]:
    if f.get("line") is None:
        return None
    for h in hunks:
        if h["file"] == f.get("file") and (h["start_line"] <= f["line"] <= h["end_line"]
                                           or (h["added"] == 0 and h["old_start"] <= f["line"] <= h["old_end"])):
            return h
    return None


def apply_rules(model: Optional[dict], *, hunks: list[dict], held: list[str], shared_infra: bool,
                gate_defect: Optional[str], unexplained_max: float) -> dict:
    """The harness's ruling over the model's words. Returns summary/risk/notes/findings/verdict/verdict_reason."""
    if gate_defect:
        return {"summary": "", "risk": {"level": "HIGH" if held else "MEDIUM", "why": ""}, "hunk_notes": {},
                "findings": [], "dropped_findings": 0, "unexplained_hunks": len(hunks), "verdict": "CANNOT_REVIEW",
                "verdict_reason": gate_defect}
    if model is None:
        return {"summary": "", "risk": {"level": "HIGH" if held else "MEDIUM", "why": ""}, "hunk_notes": {},
                "findings": [], "dropped_findings": 0, "unexplained_hunks": len(hunks), "verdict": "CANNOT_REVIEW",
                "verdict_reason": "the reviewer's answer was not valid JSON (after one retry)"}
    ids = {h["id"] for h in hunks}
    notes = {k: v for k, v in model["hunk_notes"].items() if k in ids}
    kept, dropped = [], 0
    for n, f in enumerate(model["findings"], 1):
        if _in_hunk(f, hunks) is None:
            dropped += 1
            continue
        kept.append({"id": f"F{n}", **f})
    order = {s: i for i, s in enumerate(SEVERITIES)}
    kept.sort(key=lambda f: (order[f["severity"]], f["id"]))
    unexplained = len(ids - set(notes))
    level = model["risk"]["level"]
    floor = "HIGH" if held else "MEDIUM" if shared_infra else "LOW"
    if RISK.index(floor) > RISK.index(level):
        level = floor
    verdict, reason = model["verdict"], "the reviewer's verdict"
    if hunks and unexplained / len(hunks) > unexplained_max:
        verdict, reason = "CANNOT_REVIEW", f"{unexplained} of {len(hunks)} changes were not explained by the reviewer"
    elif any(f["severity"] == "BLOCKER" for f in kept):
        verdict, reason = "HOLD", "a blocker finding"
    elif verdict == "MERGE" and any(f["severity"] in ("MAJOR", "MINOR") for f in kept):
        verdict, reason = "MERGE_WITH_NOTES", "follow-up findings"
    return {"summary": model["summary"], "risk": {"level": level, "why": model["risk"]["why"], "floor": floor},
            "hunk_notes": notes, "findings": kept, "dropped_findings": dropped, "unexplained_hunks": unexplained,
            "verdict": verdict, "verdict_reason": reason}


def document_sha(rec: Mapping[str, Any]) -> str:
    return digest({k: v for k, v in rec.items() if k not in RUNTIME_FIELDS})


def build_areas(files: list[dict], hunks: list[dict], notes: Mapping[str, str], cfg: Mapping[str, Any],
                max_lines: int = 400) -> list[dict]:
    by_area: dict[str, list[dict]] = {}
    for f in files:
        fh = [{"id": h["id"], "file": h["file"], "header": h["header"], "start_line": h["start_line"],
               "end_line": h["end_line"], "added": h["added"], "removed": h["removed"],
               "lines": h["lines"][:max_lines], "truncated": len(h["lines"]) > max_lines,
               "note": notes.get(h["id"])} for h in hunks if h["file"] == f["path"]]
        by_area.setdefault(area_of(f["path"], cfg), []).append({**f, "hunks": fh})
    return [{"name": name, "files": rows, "additions": sum(r.get("additions", 0) for r in rows),
             "deletions": sum(r.get("deletions", 0) for r in rows)} for name, rows in by_area.items()]


# ── commit status (D4) ───────────────────────────────────────────────────────


def commit_status_payload(rec: Mapping[str, Any], cfg: Mapping[str, Any], target_url: Optional[str]) -> dict:
    v = rec.get("verdict")
    follow = sum(1 for f in rec.get("findings") or [] if f.get("severity") in ("MAJOR", "MINOR"))
    state, text = {"MERGE": ("success", "Independent review: safe to merge"),
                   "MERGE_WITH_NOTES": ("success", f"Independent review: merge with {follow} follow-up(s)"),
                   "HOLD": ("failure", "Independent review: hold (blocker found)"),
                   "CANNOT_REVIEW": ("error", "Independent review: cannot review")}[v]
    if (rec.get("classes") or {}).get("held"):
        text += " · held: operator's own merge"
    out = {"state": state, "context": (cfg.get("commit_status") or {}).get("context", "tradeai/independent-review"),
           "description": text[:140]}
    if target_url:
        out["target_url"] = target_url
    return out


def review_url(pr: int, head: str) -> Optional[str]:
    try:
        from scripts.lib.agent_gateway_adapter import command_center_url_for
        return command_center_url_for(f"/v3/approvals/pr:{int(pr)}?head={head[:9]}")
    except Exception:  # noqa: BLE001 - the link is optional on the status
        return None


# ── spend and preflight (AGENTS.md §29, D3) ─────────────────────────────────


def _today(rows: list[dict], now: datetime) -> list[dict]:
    day = now.astimezone(timezone.utc).date()
    return [r for r in rows if (t := parse_iso(r.get("at"))) and t.astimezone(timezone.utc).date() == day]


def spend_today(rows: list[dict], now: datetime) -> dict:
    today = _today(rows, now)
    paid = [r for r in today if r.get("provider") == "anthropic"]
    return {"usd": float(sum(Decimal(str(r.get("cost_usd") or 0)) for r in paid)),
            "reviews": sum(1 for r in paid if r.get("kind") == "review" and r.get("call") == 1),
            "questions": sum(1 for r in paid if r.get("kind") == "question"),
            "by_process": {p: float(sum(Decimal(str(r.get("cost_usd") or 0)) for r in paid if r.get("process_id") == p))
                           for p in {r.get("process_id") for r in paid}}}


def reviews_of_pr_today(rows: list[dict], pr: int, now: datetime) -> int:
    return sum(1 for r in _today(rows, now) if r.get("kind") == "review" and r.get("call") == 1 and r.get("pr") == pr
               and r.get("provider") == "anthropic")


def credit_snapshot(state_root: Path, now: datetime) -> dict:
    try:
        from scripts.lib.anthropic_credit import CreditBook
        from scripts.lib.anthropic_transport import load_policy
        return CreditBook(Path(state_root), load_policy()).snapshot(now=now)
    except Exception as exc:  # noqa: BLE001 - an unreadable credit book is a wait, never a spend
        return {"status": "UNAVAILABLE", "error": type(exc).__name__}


def process_cap(process_id: str) -> Optional[float]:
    try:
        reg = json.loads((ROOT / "config/llm_process_registry.json").read_text(encoding="utf-8"))
        row = next(p for p in reg["processes"] if p["id"] == process_id)
        return float(row["daily_cost_cap_usd"])
    except (OSError, ValueError, StopIteration, KeyError, TypeError):
        return None


def next_utc_midnight(now: datetime) -> datetime:
    d = now.astimezone(timezone.utc)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc) + timedelta(days=1)


def preflight(*, kind: str, tier: str, pr: Optional[int], cfg: Mapping[str, Any], spend_rows: list[dict],
              credit: Mapping[str, Any], now: datetime, env: Mapping[str, str] | None = None) -> dict:
    """Quote every limit that can stop the call and size it under the lowest (§29). ``ok`` False → the call waits."""
    env = os.environ if env is None else env
    b = cfg.get("budget") or {}
    procs = cfg.get("processes") or {}
    process_id = procs.get("question" if kind == "question" else tier)
    projected = float((b.get("projected_cost_usd") or {}).get("question" if kind == "question" else tier, 0.5))
    mine = spend_today(spend_rows, now)
    combined_cap = float(b.get("combined_daily_cost_cap_usd", 2.0))
    pcap = process_cap(process_id) if process_id else None
    pspent = mine["by_process"].get(process_id, 0.0)
    gcap_raw = env.get("LLM_GLOBAL_DAILY_USD_CAP")
    try:
        daily_left = float(Decimal(str(credit.get("daily_cap_usd"))) - Decimal(str(credit.get("today_used_usd"))) - Decimal(str(credit.get("reserved_today_usd") or 0)))
    except Exception:  # noqa: BLE001
        daily_left = 0.0
    try:
        total_left = float(credit.get("remaining_budget_usd"))
    except (TypeError, ValueError):
        total_left = 0.0
    headroom = {"credit_daily_remaining_usd": round(daily_left, 4), "credit_total_remaining_usd": round(total_left, 4),
                "combined_review_cap_remaining_usd": round(combined_cap - mine["usd"], 4),
                "process_cap_remaining_usd": round((pcap - pspent) if pcap is not None else 0.0, 4)}
    limits = {"credit": {k: credit.get(k) for k in ("status", "today_used_usd", "daily_cap_usd", "remaining_budget_usd",
                                                     "expiry", "unavailable_until")},
              "process": {"id": process_id, "daily_cost_cap_usd": pcap, "spent_today_usd": round(pspent, 4)},
              "combined": {"daily_cost_cap_usd": combined_cap, "spent_today_usd": round(mine["usd"], 4)},
              "global_daily_usd_cap": gcap_raw or "not set (the governed gate enforces it at call time)",
              "reviews_today": mine["reviews"], "max_reviews_per_day": b.get("max_reviews_per_day"),
              "questions_today": mine["questions"], "max_questions_per_day": b.get("max_questions_per_day"),
              "projected_call_usd": projected, "headroom_usd": headroom}
    reason, next_try = None, None
    status = credit.get("status")
    if status != "OK":
        reason = f"credit {status or 'UNAVAILABLE'}"
        until = parse_iso(credit.get("unavailable_until"))
        next_try = until if until else (None if status in ("EXPIRED", "EXHAUSTED", "DISABLED") else next_utc_midnight(now))
    elif pcap is None:
        reason = "process not registered"
    elif min(headroom.values()) < projected:
        lowest = min(headroom, key=headroom.get)
        reason, next_try = f"daily limit reached ({lowest.replace('_', ' ')})", next_utc_midnight(now)
    elif kind == "review" and mine["reviews"] >= int(b.get("max_reviews_per_day", 20)):
        reason, next_try = "20 reviews today", next_utc_midnight(now)
    elif kind == "review" and pr is not None and reviews_of_pr_today(spend_rows, pr, now) >= int(b.get("max_reviews_per_pr_per_day", 3)):
        reason, next_try = "3 reviews of this PR today", next_utc_midnight(now)
    elif kind == "question" and mine["questions"] >= int(b.get("max_questions_per_day", 10)):
        reason, next_try = "question limit today", next_utc_midnight(now)
    if gcap_raw:
        try:
            if float(gcap_raw) <= 0:
                reason = reason or "global daily provider cap is 0"
        except ValueError:
            pass
    return {"ok": reason is None, "reason": reason, "next_try_at": iso(next_try) if next_try else None,
            "process_id": process_id, "limits": limits}


# ── read model for the API (no GitHub, no model, no writes) ─────────────────


PILL = {"ready": ("Safe to merge", "success"), "notes": ("Merge · {n} follow-up{s}", "warning"),
        "held": ("Held · your own merge", "danger"), "hold": ("Review says hold", "danger"),
        "stale": ("New push · re-reviewing", "neutral"), "credit": ("Review waiting for credit", "warning"),
        "cannot": ("Cannot review", "danger")}


def row_state(rec: Optional[dict], status: Optional[dict], head: str) -> str:
    if rec is None or rec.get("head_sha") != head:
        if status and status.get("head_sha") == head and status.get("state") == "WAITING_FOR_CREDIT":
            return "credit"
        if status and status.get("head_sha") == head and status.get("state") == "CANNOT_REVIEW":
            return "cannot"
        return "stale"
    if rec.get("verdict") == "CANNOT_REVIEW":
        return "cannot"
    if (rec.get("classes") or {}).get("held"):
        return "held"
    if rec.get("verdict") == "HOLD":
        return "hold"
    return "notes" if rec.get("verdict") == "MERGE_WITH_NOTES" else "ready"


def pill(state: str, rec: Optional[dict]) -> dict:
    label, tone = PILL[state]
    n = sum(1 for f in (rec or {}).get("findings") or [] if f.get("severity") in ("MAJOR", "MINOR"))
    return {"state": state, "label": label.format(n=n, s="" if n == 1 else "s"), "tone": tone}


def approve_all_eligible(rec: Optional[dict], head: str) -> tuple[bool, str]:
    """D1: "Approve all" leaves out a PR whose review is missing or stale, says HOLD or CANNOT_REVIEW, or has a BLOCKER."""
    if rec is None or rec.get("head_sha") != head:
        return False, "no review of this head"
    if rec.get("verdict") in ("HOLD", "CANNOT_REVIEW"):
        return False, f"review says {rec['verdict'].replace('_', ' ').lower()}"
    if any(f.get("severity") == "BLOCKER" for f in rec.get("findings") or []):
        return False, "blocker finding"
    return True, "reviewed"
