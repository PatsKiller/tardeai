"""pr_merge_digest.py — one Telegram tap approves a digest of ready PRs (Mergify go-signal).

Operator 2026-10-27, verbatim: "I only want to be able to approve something once in Telegram.
It could be a digest of work and then it gets pushed and merged and on a timer it's approved."

Flow
----
1. ``run_digest`` (host timer, weekdays 08:00 / 12:00 / 16:30 ET, weekends every 3h; ``--now``
   for the coordinator) lists open PRs to ``main`` that are READY: not draft, the four required
   checks ``SUCCESS`` on the current head, no hold label, no path in ``config/merge_hold_paths.json``,
   no ``operator-merge`` yet. It sends one card group through ``telegram_alert`` with
   "Approve all (N)" / "Hold all" and per-item hold toggles (``prdall:`` / ``prdhold:`` /
   ``prdx:<id>:<pr>``); "hold #N" typed in the chat does the same. Held-path PRs are listed as
   "needs operator merge" with a per-PR "Approve #N" tap (``prdheld:<id>:<pr>``) — never in
   "Approve all" — so a broker/secret/policy/guard change still needs an explicit per-PR tap.
   Nothing ready and nothing new → no message.
2. ``settle_approve_all`` (callback poller) re-reads each PR's head, writes ONE
   ``PrMergeDigestApproval@v1`` record (digest id, chat, operator id, time, [(PR, head SHA)]) —
   provenance per AGENTS.md §28.4 — then adds ``operator-merge`` to each PR. A held PR is approved
   the same way, one tap at a time (``settle_approve_held_pr``): re-read head, write one
   ``PrMergeDigestApproval@v1`` record, add ``operator-merge`` — never bulk.
3. ``reconcile`` (host timer, every 3 min): a labelled PR whose head moved off the approved SHA
   loses ``operator-merge`` and returns to the next digest; approved PRs that merged get one
   "Merged N, deploying" note; a ``DeployOnMainReceipt@v1`` that carries them gets one
   "Live: <sha> — PRs …, post-release tester ok/failed" note (failure → P1).

Authority: the tap is the operator's approval; the label write is the host side-effect of it.
No merge, no promote, no broker path. ``MBI_BEHAVIOR = 0``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

try:
    from scripts import check_pr_plain_english as plain
    from scripts.lib import merge_hold_paths as mhp
    from scripts.lib import pr_merge_telegram as pmt
except ImportError:  # pragma: no cover — run from scripts/
    import check_pr_plain_english as plain  # type: ignore
    from lib import merge_hold_paths as mhp  # type: ignore
    from lib import pr_merge_telegram as pmt  # type: ignore

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "pr_merge_digest.json"
DIGEST_SCHEMA = "PrMergeDigest@v1"
APPROVAL_SCHEMA = "PrMergeDigestApproval@v1"
BINDING_SCHEMA = "PrMergeHeadBinding@v1"
PRODUCER = "pr_merge_digest"
ET_NAME = "America/New_York"


# ── config + store ────────────────────────────────────────────────────────────


def load_config(path: Path | None = None) -> dict[str, Any]:
    return json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))


def _store() -> Path:
    return pmt.store_dir()


def digests_path() -> Path:
    return _store() / "digests.json"


def approvals_path() -> Path:
    return _store() / "digest_approvals.jsonl"


def bindings_path() -> Path:
    return _store() / "digest_head_bindings.jsonl"


def notes_state_path() -> Path:
    return _store() / "digest_notes_state.json"


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _append_jsonl(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def load_digests() -> list[dict[str, Any]]:
    rows = _read_json(digests_path(), [])
    return rows if isinstance(rows, list) else []


def save_digests(rows: list[dict[str, Any]]) -> None:
    now = time.time()
    keep = [r for r in rows if r.get("status") == "PENDING" or now - float(r.get("created_at") or 0) < 14 * 86400]
    _write_json(digests_path(), keep[-100:])


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── gh (stubbed in tests) ─────────────────────────────────────────────────────


def _gh(args: list[str], *, timeout: int = 90) -> tuple[int, str]:
    proc = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=timeout, check=False)
    return proc.returncode, (proc.stdout or "") if proc.returncode == 0 else (proc.stderr or proc.stdout or "")


def _gh_json(args: list[str], default: Any) -> Any:
    rc, out = _gh(args)
    if rc != 0:
        raise RuntimeError(f"gh {' '.join(args[:3])} failed: {out.strip()[:300]}")
    try:
        return json.loads(out) if out.strip() else default
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"gh {' '.join(args[:3])} returned non-JSON: {exc}") from exc


PR_FIELDS = "number,title,url,headRefOid,isDraft,labels,body,files,changedFiles,statusCheckRollup,baseRefName"


def list_open_prs(repo: str, limit: int) -> list[dict[str, Any]]:
    return _gh_json(
        ["pr", "list", "--repo", repo, "--base", "main", "--state", "open",
         "--limit", str(int(limit)), "--json", PR_FIELDS],
        [],
    )


def pr_all_files(repo: str, number: int) -> list[str]:
    rc, out = _gh(["api", "--paginate", f"repos/{repo}/pulls/{int(number)}/files?per_page=100",
                   "--jq", ".[].filename"])
    if rc != 0:
        raise RuntimeError(f"gh api pulls/{number}/files failed: {out.strip()[:300]}")
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def pr_view(repo: str, number: int) -> dict[str, Any]:
    return _gh_json(["pr", "view", str(int(number)), "--repo", repo,
                     "--json", "number,state,headRefOid,isDraft,labels"], {})


def list_merged_prs(repo: str, limit: int = 50) -> list[dict[str, Any]]:
    return _gh_json(["pr", "list", "--repo", repo, "--base", "main", "--state", "merged",
                     "--limit", str(int(limit)), "--json", "number,title,mergeCommit,mergedAt"], [])


def commit_included(repo: str, commit_sha: str, main_sha: str) -> bool:
    """True when ``commit_sha`` is ``main_sha`` or an ancestor of it."""
    if not commit_sha or not main_sha:
        return False
    if main_sha.startswith(commit_sha[:12]) or commit_sha.startswith(main_sha[:12]):
        return True
    rc, out = _gh(["api", f"repos/{repo}/compare/{commit_sha}...{main_sha}", "--jq", ".status"])
    return rc == 0 and out.strip() in ("ahead", "identical")


# ── classification ───────────────────────────────────────────────────────────


def label_set(pr: dict[str, Any]) -> set[str]:
    return pmt.label_names(pr)


def checks_green(rollup: Iterable[dict[str, Any]] | None) -> tuple[bool, dict[str, str]]:
    """Every required check present and every run of it ``SUCCESS`` on this head."""
    seen: dict[str, set[str]] = {}
    for row in rollup or []:
        name = str(row.get("name") or row.get("context") or "")
        if name not in pmt.REQUIRED_CHECKS:
            continue
        concl = str(row.get("conclusion") or row.get("state") or row.get("status") or "").upper()
        seen.setdefault(name, set()).add(concl or "PENDING")
    statuses = {c: ("SUCCESS" if seen.get(c) == {"SUCCESS"} else ",".join(sorted(seen.get(c) or {"MISSING"})))
                for c in pmt.REQUIRED_CHECKS}
    return all(v == "SUCCESS" for v in statuses.values()), statuses


def pr_class(pr: dict[str, Any]) -> str:
    labels = label_set(pr)
    if "solo" in labels:
        return "solo"
    if "shared-infra" in labels or "[shared-infra]" in str(pr.get("title") or "").lower():
        return "shared-infra"
    return "normal"


def _glob_hit(paths: list[str], globs: list[str]) -> bool:
    rxs = [re.compile(mhp.glob_to_regex(g)) for g in globs]
    return any(rx.search(p) for p in paths for rx in rxs)


def risk_notes(paths: list[str], cfg: dict[str, Any]) -> list[str]:
    notes = [name for name, globs in (cfg.get("risk_globs") or {}).items() if _glob_hit(paths, list(globs))]
    notes += [f"risk:{f}" for f in mhp.risk_flags(paths)]
    return notes


_SKIP_PREFIX = ("#", "<!--", "|", "```", "---", ">", "!", "[!")


def summary_line(body: str | None, limit: int = 140) -> str:
    text = str(body or "")
    m = re.search(r"^#+\s*summary\s*$", text, flags=re.I | re.M)
    if m:
        text = text[m.end():]
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(_SKIP_PREFIX):
            continue
        line = re.sub(r"^[-*+]\s+", "", line)
        line = line.replace("**", "").replace("`", "").strip()
        if not line:
            continue
        return line if len(line) <= limit else line[: limit - 1] + "…"
    return ""


def classify_pr(pr: dict[str, Any], *, repo: str, cfg: dict[str, Any]) -> dict[str, Any]:
    number = int(pr["number"])
    head = str(pr.get("headRefOid") or "")
    labels = label_set(pr)
    files = [str(f.get("path") if isinstance(f, dict) else f) for f in (pr.get("files") or [])]
    changed = int(pr.get("changedFiles") or len(files))
    if changed > len(files):
        try:
            files = pr_all_files(repo, number) or files
        except RuntimeError:
            pass
    answers = plain.fields(str(pr.get("body") or ""))
    item: dict[str, Any] = {
        "pr": number,
        "title": str(pr.get("title") or ""),
        "url": str(pr.get("url") or ""),
        "head_sha": head,
        "class": pr_class(pr),
        "files_count": changed,
        "risk": risk_notes(files, cfg),
        "plain_english": answers,
        "summary": answers.get("What changes", ""),
        "body_excerpt": _trim(str(pr.get("body") or ""), 140),
    }
    if str(pr.get("baseRefName") or "main") != "main":
        return {**item, "status": "skip", "reason": "base_not_main"}
    if pr.get("isDraft"):
        return {**item, "status": "skip", "reason": "draft"}
    if pmt.LABEL in labels:
        return {**item, "status": "skip", "reason": "already_approved"}
    green, statuses = checks_green(pr.get("statusCheckRollup"))
    item["checks"] = statuses
    held_labels = sorted(labels & mhp.hold_labels())
    held_paths = mhp.held_classes(files)
    errors = plain.check(item["title"], str(pr.get("body") or ""))
    if not errors and any(not item["plain_english"].get(label) or (
        item["plain_english"][label].startswith("<") and item["plain_english"][label].endswith(">")
    ) for label in plain.LABELS):
        errors = ["plain-English answers are empty or still placeholders"]
    if errors:
        return {**item, "status": "not_described", "reason": "plain_english_required", "description_errors": errors}
    if held_labels or held_paths:
        item["hold"] = {"labels": held_labels, "classes": sorted(held_paths)}
        return {**item, "status": "needs_operator", "reason": "held"}
    if len(files) < changed:
        # Could not see every changed path: never offer Approve on a partial view.
        item["hold"] = {"labels": [], "classes": ["files_unverified"]}
        return {**item, "status": "needs_operator", "reason": "files_unverified"}
    if not green:
        return {**item, "status": "skip", "reason": "checks_not_green"}
    return {**item, "status": "ready"}


def build_digest(repo: str, cfg: dict[str, Any]) -> dict[str, Any]:
    prs = list_open_prs(repo, int(cfg.get("pr_list_limit") or 100))
    ready, needs, skipped, undescribed = [], [], [], []
    for pr in sorted(prs, key=lambda p: int(p["number"])):
        it = classify_pr(pr, repo=repo, cfg=cfg)
        {"ready": ready, "needs_operator": needs, "not_described": undescribed}.get(it["status"], skipped).append(it)
    cap = max(1, int(cfg.get("max_ready_per_digest") or 8))
    return {"ready": ready[:cap], "overflow": ready[cap:], "needs_operator": needs, "skipped": skipped,
            "not_described": undescribed, "scanned": len(prs)}


# ── message ──────────────────────────────────────────────────────────────────


def _esc(text: str) -> str:
    """Telegram legacy Markdown: neutralise the four control characters."""
    return re.sub(r"([_*`\[])", r"\\\1", str(text or ""))


MAX_MESSAGE_CHARS = 3800  # headroom below Telegram's 4096 UTF-16-unit limit


def _units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _trim(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    prefix = text[: max(0, limit - 1)]
    if " " in prefix:
        prefix = prefix.rsplit(" ", 1)[0]
    return prefix.rstrip() + "…"


def headline(title: str) -> str:
    text = " ".join(str(title or "").split())
    pattern = r"^(?:\[(?:shared-infra|held)\]\s*|(?:feat|fix|chore|ci|docs|refactor|test|perf|build|style)(?:\([^)]*\))?!?\s*:\s*|DSN-\d{8}-[^:]+:\s*)"
    while True:
        stripped = re.sub(pattern, "", text, count=1, flags=re.I)
        if stripped == text:
            return text
        text = stripped


def _card(item: dict[str, Any], cfg: dict[str, Any], excluded: set[int]) -> str:
    values = item.get("plain_english") or {}
    limit = max(1, int(cfg.get("plain_field_chars") or 160))
    mark = "⏸ HELD " if int(item["pr"]) in excluded else ""
    lines = [f"{mark}*#{item['pr']}* — {_esc(headline(item['title']))}"]
    for label, field in (("What", "What changes"), ("Why", "Why"), ("Affects", "Who / what it affects"),
                         ("When", "When it takes effect"), ("Fallback", "Risk and fallback")):
        lines.append(f"{label}: {_esc(_trim(values[field], limit))}")
    hold = item.get("hold") or {}
    if "files_unverified" in (hold.get("classes") or []):
        approval = "unavailable until all changed files are verified"
    elif hold:
        approval = "individual operator approval required; never Approve all"
    else:
        approval = _trim(values["Approval"], limit)
    lines.append(f"Approval: {_esc(approval)}")
    words = cfg.get("hold_class_words") or {}
    risk = list(item.get("risk") or [])
    for hold in (item.get("hold") or {}).get("classes") or []:
        risk.append(words.get(hold) or ("changed files could not be verified" if hold == "files_unverified" else "requires operator review"))
    if (item.get("hold") or {}).get("labels") and not (item.get("hold") or {}).get("classes"):
        risk.append("requires individual operator approval")
    risk_text = "; ".join(dict.fromkeys(risk)) or "no specific risks flagged"
    lines.append(f"Risk: {_esc(risk_text)} · {item['files_count']} files · head `{str(item['head_sha'])[:9]}`")
    return "\n".join(lines)


def format_digest_messages(d: dict[str, Any], cfg: dict[str, Any] | None = None) -> list[str]:
    """Pack complete cards; never suppress their descriptions to fit a message."""
    cfg = cfg or load_config()
    ready = d.get("ready") or []
    excluded = {int(x) for x in d.get("excluded") or []}
    did = str(d.get("digest_id") or "preview")
    header = f"📦 *PR merge digest* — {len(ready)} ready (`{_esc(did)}`)"
    pages = []

    def pack(blocks, heading, card_limit=3):
        prefix = header + "\n\n" + heading
        page, count = prefix, 0
        for block in blocks:
            if _units(prefix + "\n\n" + block) > MAX_MESSAGE_CHARS:
                raise ValueError("PR card exceeds Telegram limit; reduce plain_field_chars")
            candidate = page + "\n\n" + block
            if count and (_units(candidate) > MAX_MESSAGE_CHARS or (card_limit is not None and count >= card_limit)):
                pages.append(page)
                page, count = prefix, 0
            page += "\n\n" + block
            count += 1
        pages.append(page)

    if d.get("not_described"):
        info = []
        for item in d["not_described"]:
            info.append(f"*#{item['pr']}* — {_esc(headline(item['title']))}\n{_esc(item['body_excerpt'])}")
        pack(info, "⚠️ *Not described — cannot approve until rewritten*", card_limit=None)
    if d.get("needs_operator"):
        pack([_card(item, cfg, excluded) for item in d["needs_operator"]],
             "🔒 *Needs operator merge* — individual approval only; never Approve all")
    if not pages:
        pack([], "Review the described ready cards in the following messages.")
    if ready:
        cards = [_card(item, cfg, excluded) for item in ready]
        if d.get("overflow"):
            cards[-1] += f"\n\n+{len(d['overflow'])} more ready — next digest."
        cards[-1] += "\n\nApprove all → label `operator-merge` on each described ready PR; Mergify merges in its ET window and the host deploys. Hold one with its button or reply `hold #N`. A changed head needs a new approval."
        pack(cards, "*Ready for your approval*")
    return pages


def format_digest(d: dict[str, Any]) -> str:
    """Complete text preview; sending uses the bounded messages individually."""
    return "\n\n".join(format_digest_messages(d))


def _preview(d: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    parts = format_digest_messages(d, cfg)
    markup = keyboard(d, cfg)
    return {
        "message": "\n\n".join(parts), "reply_markup": markup,
        "messages": [{"digest_id": d["digest_id"], "message": text,
                      "reply_markup": markup if i == len(parts) - 1 else None} for i, text in enumerate(parts)],
    }


def keyboard(d: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any] | None:
    ready = d.get("ready") or []
    needs = [
        it for it in (d.get("needs_operator") or [])
        if "files_unverified" not in (it.get("hold") or {}).get("classes", [])
    ]
    if not ready and not needs:
        return None
    did = d["digest_id"]
    excluded = set(int(x) for x in d.get("excluded") or [])
    rows: list[list[dict[str, str]]] = []
    if ready:
        n = len([it for it in ready if int(it["pr"]) not in excluded])
        rows.append([
            {"text": f"✅ Approve all ({n})", "callback_data": f"prdall:{did}"},
            {"text": "\U0001f6d1 Hold all", "callback_data": f"prdhold:{did}"},
        ])
        per = []
        for it in ready[: int(cfg.get("max_item_buttons") or 8)]:
            pr = int(it["pr"])
            label = f"↩ Include #{pr}" if pr in excluded else f"⏸ Hold #{pr}"
            per.append({"text": label, "callback_data": f"prdx:{did}:{pr}"})
        for i in range(0, len(per), 2):
            rows.append(per[i:i + 2])
    # Held PRs are per-PR only, never in "Approve all": each gets its own "Approve #N" tap so a
    # broker/secret/policy/guard/merge-tooling change still needs explicit per-PR operator intent.
    for it in needs[: int(cfg.get("max_item_buttons") or 8)]:
        pr = int(it["pr"])
        rows.append([{"text": f"🔐 Approve #{pr} (held)", "callback_data": f"prdheld:{did}:{pr}"}])
    return {"inline_keyboard": rows}


# ── Telegram (the one chokepoint; stubbed in tests) ──────────────────────────


def _send(message: str, *, priority: str, reply_markup: dict[str, Any] | None = None) -> tuple[bool, list[str], str]:
    try:
        import telegram_alert as ta  # type: ignore
    except ImportError:
        try:
            from scripts import telegram_alert as ta  # type: ignore
        except ImportError as exc:
            return False, [], f"telegram_alert unavailable: {exc}"
    try:
        ta.reset_last_message_ids()
        ok = ta.send_telegram(message, priority=priority, dedupe_minutes=0, producer=PRODUCER,
                              reply_markup=reply_markup or None)
        ids = [str(i) for i in (ta.last_message_ids() or []) if i is not None]
    except Exception as exc:  # noqa: BLE001
        return False, [], f"{type(exc).__name__}: {exc}"
    return bool(ok), ids, "accepted" if ok else "send_telegram returned falsey"


# ── digest send ──────────────────────────────────────────────────────────────


def _signature(d: dict[str, Any]) -> list[list[Any]]:
    return sorted([["r", int(i["pr"]), str(i["head_sha"])] for i in d.get("ready") or []]
                  + [["n", int(i["pr"]), str(i["head_sha"])] for i in d.get("needs_operator") or []])


def latest_pending(rows: list[dict[str, Any]] | None = None) -> Optional[dict[str, Any]]:
    now = time.time()
    for r in reversed(rows if rows is not None else load_digests()):
        if r.get("status") == "PENDING" and float(r.get("expires_at") or 0) >= now:
            return r
    return None


def run_digest(*, repo: str = pmt.DEFAULT_REPO, apply: bool = False, force: bool = False,
               cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    out = _run_digest(repo=repo, apply=apply, force=force, cfg=cfg or load_config())
    if apply:  # durable per-run receipt (lane output_signal), even when nothing was sent
        _write_json(_store() / "digest_last_run.json",
                    {k: v for k, v in out.items() if k not in ("message", "messages", "reply_markup")} | {"at": _now_iso()})
    return out


def _run_digest(*, repo: str, apply: bool, force: bool, cfg: dict[str, Any]) -> dict[str, Any]:
    d = build_digest(repo, cfg)
    out: dict[str, Any] = {
        "ok": True, "apply": apply, "scanned": d["scanned"],
        "ready": [i["pr"] for i in d["ready"]], "needs_operator": [i["pr"] for i in d["needs_operator"]],
        "overflow": [i["pr"] for i in d["overflow"]],
        "not_described": [i["pr"] for i in d["not_described"]],
        "skipped": [{"pr": i["pr"], "reason": i.get("reason")} for i in d["skipped"]],
    }
    if not d["ready"] and not d["needs_operator"] and not d["not_described"]:
        out["action"] = "empty_no_message"
        return out
    rows = load_digests()
    prev = latest_pending(rows)
    sig = _signature(d)
    # Rendering changes replace old prompts without changing approval SHA binding.
    display = hashlib.sha256("\n".join(format_digest_messages({**d, "digest_id": "preview"}, cfg)).encode()).hexdigest()
    last_sent = rows[-1] if rows else None
    if not force:
        if prev and prev.get("signature") == sig and prev.get("display_fingerprint") == display:
            out["action"] = "unchanged_pending_digest"
            out["digest_id"] = prev["digest_id"]
            if not apply:
                out.update(_preview({**d, "digest_id": prev["digest_id"], "excluded": prev.get("excluded") or []}, cfg))
            return out
        if not d["ready"] and last_sent and last_sent.get("delivery", {}).get("accepted") is True and last_sent.get("display_fingerprint") == display and [s for s in (last_sent.get("signature") or []) if s[0] == "n"] == sig:
            out["action"] = "needs_operator_unchanged"
            if not apply:
                out.update(_preview({**d, "digest_id": last_sent["digest_id"], "excluded": []}, cfg))
            return out
    digest_id = secrets.token_hex(6)
    now = time.time()
    rec = {
        "schema": DIGEST_SCHEMA, "digest_id": digest_id, "repo": repo, "status": "PENDING",
        "created_at": now, "expires_at": now + int(cfg.get("ttl_seconds") or 43200),
        "ready": d["ready"], "needs_operator": d["needs_operator"], "overflow": d["overflow"],
        "not_described": d["not_described"],
        "excluded": [], "signature": sig, "display_fingerprint": display, "message_ids": [],
    }
    preview = _preview(rec, cfg)
    markup, messages = preview["reply_markup"], preview["messages"]
    out.update({"digest_id": digest_id, **preview})
    if not apply:
        out["action"] = "would_send"
        return out
    ids, details, ok = [], [], True
    for message in messages:
        accepted, delivered, detail = _send(message["message"], priority=str(cfg.get("digest_priority") or "P1"),
                                            reply_markup=message["reply_markup"])
        ids.extend(delivered)
        details.append(detail)
        if not accepted or not delivered:
            ok = False  # Never offer approval after a missing/queued detail page.
            break
    detail = "; ".join(details)
    for r in rows:
        if r.get("status") == "PENDING":
            r["status"] = "SUPERSEDED"
            r["superseded_by"] = digest_id
    rec["message_ids"] = ids
    rec["delivery"] = {"accepted": ok, "detail": detail, "at": now}
    if not ok:
        rec["status"] = "DELIVERY_FAILED"
    elif not markup:
        rec["status"] = "INFO"  # no described ready or verified held PR has an approval button
    rows.append(rec)
    save_digests(rows)
    out.update({"action": "sent" if ok else "send_failed", "ok": ok, "telegram": detail, "message_ids": ids})
    return out


# ── settle (callback poller) ─────────────────────────────────────────────────


def _find(rows: list[dict[str, Any]], digest_id: str) -> Optional[dict[str, Any]]:
    return next((r for r in rows if r.get("digest_id") == digest_id), None)


def _check_settleable(digest_id: str, chat_id: Any, allowed_chats: Iterable[Any]) -> tuple[Optional[str], list, Optional[dict]]:
    allowed = {str(c) for c in allowed_chats if c is not None and str(c)}
    if str(chat_id) not in allowed:
        return "CHAT_NOT_ALLOWLISTED", [], None
    rows = load_digests()
    rec = _find(rows, digest_id)
    if not rec:
        return "UNKNOWN_DIGEST", rows, None
    if rec.get("status") != "PENDING":
        return f"NOT_PENDING:{rec.get('status')}", rows, rec
    if float(rec.get("expires_at") or 0) < time.time():
        rec["status"] = "EXPIRED"
        save_digests(rows)
        return "EXPIRED", rows, rec
    return None, rows, rec


def toggle_item(digest_id: str, pr_number: int, *, chat_id: Any, allowed_chats: Iterable[Any],
                hold: Optional[bool] = None) -> dict[str, Any]:
    """Exclude (hold) or re-include one PR. ``hold=None`` toggles."""
    err, rows, rec = _check_settleable(digest_id, chat_id, allowed_chats)
    if err:
        return {"ok": False, "reason": err}
    assert rec is not None
    prs = {int(i["pr"]) for i in rec.get("ready") or []}
    pr = int(pr_number)
    if pr not in prs:
        return {"ok": False, "reason": "PR_NOT_IN_DIGEST", "digest": rec}
    excluded = {int(x) for x in rec.get("excluded") or []}
    now_held = (pr not in excluded) if hold is None else bool(hold)
    excluded.add(pr) if now_held else excluded.discard(pr)
    rec["excluded"] = sorted(excluded)
    rec.setdefault("events", []).append({"at": _now_iso(), "chat_id": str(chat_id), "pr": pr,
                                         "action": "hold" if now_held else "include"})
    save_digests(rows)
    return {"ok": True, "held": now_held, "pr": pr, "digest": rec,
            "remaining": len(prs - excluded)}


def settle_hold_all(digest_id: str, *, chat_id: Any, allowed_chats: Iterable[Any],
                    telegram: dict[str, Any] | None = None) -> dict[str, Any]:
    err, rows, rec = _check_settleable(digest_id, chat_id, allowed_chats)
    if err:
        return {"ok": False, "reason": err}
    assert rec is not None
    rec["status"] = "HELD"
    rec["settled_at"] = time.time()
    rec["settled_by"] = {"chat_id": str(chat_id), **{k: (telegram or {}).get(k) for k in ("from_id", "from_username", "message_id")}}
    save_digests(rows)
    return {"ok": True, "digest": rec, "held": [int(i["pr"]) for i in rec.get("ready") or []]}


def settle_approve_all(digest_id: str, *, chat_id: Any, allowed_chats: Iterable[Any],
                       telegram: dict[str, Any] | None = None, apply_label: bool = True) -> dict[str, Any]:
    """Approve every non-excluded ready PR in the digest, bound to its digest head SHA."""
    err, rows, rec = _check_settleable(digest_id, chat_id, allowed_chats)
    if err:
        return {"ok": False, "reason": err}
    assert rec is not None
    repo = str(rec.get("repo") or pmt.DEFAULT_REPO)
    # Claim the digest first so a double tap cannot settle it twice.
    rec["status"] = "SETTLING"
    save_digests(rows)

    excluded = {int(x) for x in rec.get("excluded") or []}
    hold_lbls = mhp.hold_labels()
    approved: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    for it in rec.get("ready") or []:
        pr = int(it["pr"])
        bound = str(it["head_sha"])
        if pr in excluded:
            outcomes.append({"pr": pr, "outcome": "held_by_operator"})
            continue
        try:
            view = pr_view(repo, pr)
        except RuntimeError as exc:
            outcomes.append({"pr": pr, "outcome": "view_failed", "detail": str(exc)[:200]})
            continue
        if str(view.get("state") or "").upper() != "OPEN":
            outcomes.append({"pr": pr, "outcome": "not_open", "state": view.get("state")})
            continue
        if str(view.get("headRefOid") or "") != bound:
            outcomes.append({"pr": pr, "outcome": "head_changed", "bound": bound[:9],
                             "now": str(view.get("headRefOid") or "")[:9]})
            continue
        if view.get("isDraft") or (pmt.label_names(view) & hold_lbls):
            outcomes.append({"pr": pr, "outcome": "now_draft_or_held"})
            continue
        approved.append({"pr": pr, "head_sha": bound})

    tg = telegram or {}
    approval = {
        "schema": APPROVAL_SCHEMA,
        "approval_id": f"{digest_id}-{secrets.token_hex(3)}",
        "digest_id": digest_id,
        "repo": repo,
        "operator_chat_id": str(chat_id),
        "operator_from_id": tg.get("from_id"),
        "operator_from_username": tg.get("from_username"),
        "telegram_message_id": tg.get("message_id"),
        "callback_data": tg.get("text"),
        "approved_at": _now_iso(),
        "items": approved,
        "provenance": "operator Telegram tap 'Approve all' in an allowlisted chat (AGENTS.md §28.4); "
                      "the label is the host side-effect of that tap",
    }
    _append_jsonl(approvals_path(), approval)

    if apply_label and approved:
        for a in approved:
            res = pmt.add_operator_merge_label(a["pr"], repo=repo)
            a["label_ok"] = bool(res.get("ok"))
            outcomes.append({"pr": a["pr"], "outcome": "labeled" if res.get("ok") else "label_failed",
                             "head_sha": a["head_sha"][:9]})
            if res.get("ok"):
                pmt.comment_on_pr(
                    a["pr"],
                    f"operator-merge: set by Telegram digest Approve all (digest `{digest_id}`, "
                    f"approval `{approval['approval_id']}`, bound head `{a['head_sha'][:9]}`). "
                    f"If the head changes the host removes the label and the PR returns to the next digest.",
                    repo=repo,
                )

    rows = load_digests()
    rec = _find(rows, digest_id) or rec
    rec["status"] = "APPROVED"
    rec["settled_at"] = time.time()
    rec["approval_id"] = approval["approval_id"]
    rec["outcomes"] = outcomes
    save_digests(rows)
    failed = [o for o in outcomes if o["outcome"] in ("label_failed", "view_failed")]
    return {"ok": not failed, "digest": rec, "approval": approval, "outcomes": outcomes,
            "labeled": [o["pr"] for o in outcomes if o["outcome"] == "labeled"],
            "returned": [o["pr"] for o in outcomes if o["outcome"] in ("head_changed", "not_open", "now_draft_or_held", "view_failed", "label_failed")],
            "reason": "LABEL_OR_VIEW_FAILED" if failed else None}


def settle_approve_held_pr(digest_id: str, pr_number: int, *, chat_id: Any, allowed_chats: Iterable[Any],
                           telegram: dict[str, Any] | None = None, apply_label: bool = True) -> dict[str, Any]:
    """Approve ONE held (needs-operator) PR, bound to its digest head SHA.

    Held PRs are per-PR only and are never in "Approve all", so a broker/secret/policy/guard/
    merge-tooling change still needs an explicit per-PR operator tap (AGENTS.md §25.10, §28.15
    item 3; reviews stay required, the tap is what merges). Same ``PrMergeDigestApproval@v1``
    provenance as ``settle_approve_all``: chat, operator id, time, PR + head SHA.
    """
    err, rows, rec = _check_settleable(digest_id, chat_id, allowed_chats)
    if err:
        return {"ok": False, "reason": err}
    assert rec is not None
    pr = int(pr_number)
    needs = {int(i["pr"]): i for i in rec.get("needs_operator") or []}
    item = needs.get(pr)
    if item is None:
        return {"ok": False, "reason": "PR_NOT_HELD_IN_DIGEST", "digest": rec}
    if "files_unverified" in (item.get("hold") or {}).get("classes", []):
        return {"ok": False, "reason": "FILES_UNVERIFIED", "digest": rec}
    if pr in {int(x) for x in rec.get("held_approved") or []}:
        return {"ok": False, "reason": "ALREADY_APPROVED", "digest": rec}
    bound = str(item["head_sha"])
    repo = str(rec.get("repo") or pmt.DEFAULT_REPO)

    # SHA-bound: re-read the head now; a moved head / closed PR / draft refuses and returns to the
    # next digest. No hold-label check here — held PRs legitimately carry hold labels.
    try:
        view = pr_view(repo, pr)
    except RuntimeError as exc:
        return {"ok": False, "reason": "VIEW_FAILED", "detail": str(exc)[:200], "digest": rec}
    if str(view.get("state") or "").upper() != "OPEN":
        return {"ok": False, "reason": "NOT_OPEN", "state": view.get("state"), "digest": rec}
    if str(view.get("headRefOid") or "") != bound:
        return {"ok": False, "reason": "HEAD_CHANGED", "bound": bound[:9],
                "now": str(view.get("headRefOid") or "")[:9], "digest": rec}
    if view.get("isDraft"):
        return {"ok": False, "reason": "NOW_DRAFT", "digest": rec}

    # Mark in-flight first so a double tap cannot approve twice.
    rec.setdefault("held_approved", []).append(pr)
    save_digests(rows)

    tg = telegram or {}
    approval = {
        "schema": APPROVAL_SCHEMA,
        "approval_id": f"{digest_id}-{secrets.token_hex(3)}",
        "digest_id": digest_id,
        "repo": repo,
        "operator_chat_id": str(chat_id),
        "operator_from_id": tg.get("from_id"),
        "operator_from_username": tg.get("from_username"),
        "telegram_message_id": tg.get("message_id"),
        "callback_data": tg.get("text"),
        "approved_at": _now_iso(),
        "items": [{"pr": pr, "head_sha": bound}],
        "held": True,
        "provenance": "operator Telegram tap 'Approve #N (held)' in an allowlisted chat (AGENTS.md §28.4, §25.10); "
                      "per-PR only, never bulk; the label is the host side-effect of that tap",
    }
    _append_jsonl(approvals_path(), approval)

    outcome = {"pr": pr, "outcome": "held_approved", "head_sha": bound[:9]}
    if apply_label:
        res = pmt.add_operator_merge_label(pr, repo=repo)
        approval["items"][0]["label_ok"] = bool(res.get("ok"))
        outcome["outcome"] = "labeled" if res.get("ok") else "label_failed"
        if res.get("ok"):
            pmt.comment_on_pr(
                pr,
                f"operator-merge: set by Telegram per-PR held Approve (digest `{digest_id}`, "
                f"approval `{approval['approval_id']}`, bound head `{bound[:9]}`). "
                f"If the head changes the host removes the label and the PR returns to the next digest.",
                repo=repo,
            )

    rows = load_digests()
    rec2 = _find(rows, digest_id) or rec
    rec2.setdefault("events", []).append({"at": _now_iso(), "chat_id": str(chat_id), "pr": pr,
                                          "action": "held_approve"})
    rec2.setdefault("outcomes", []).append(outcome)
    save_digests(rows)
    failed = outcome["outcome"] == "label_failed"
    return {"ok": not failed, "digest": rec2, "approval": approval, "outcome": outcome, "pr": pr,
            "labeled": [pr] if not failed else [],
            "returned": [pr] if failed else [],
            "reason": "LABEL_WRITE_FAILED" if failed else None}


def format_settle_reply(out: dict[str, Any]) -> str:
    if not out.get("ok") and not out.get("outcomes"):
        return f"Digest not settled: {out.get('reason')}"
    lab = out.get("labeled") or []
    ret = out.get("returned") or []
    held = [o["pr"] for o in out.get("outcomes") or [] if o["outcome"] == "held_by_operator"]
    parts = [f"✅ Approved {len(lab)}: " + (", ".join(f"#{p}" for p in lab) or "none")]
    if held:
        parts.append("Held by you: " + ", ".join(f"#{p}" for p in held))
    if ret:
        parts.append("Back to next digest (head moved / closed / failed): " + ", ".join(f"#{p}" for p in ret))
    parts.append("Mergify merges in its ET window; you will get one Merged note and one Live note.")
    return "\n".join(parts)


_TEXT_RE = re.compile(r"^\s*(hold|unhold|include)\s+((?:#?\d+[\s,]*)+)\s*$", re.I)


def handle_text_command(text: str, *, chat_id: Any, allowed_chats: Iterable[Any],
                        reply_to_message_id: Any = None) -> Optional[str]:
    """``hold #N`` / ``unhold #N`` (several numbers allowed). Returns the reply, or None if not ours."""
    m = _TEXT_RE.match(str(text or ""))
    if not m:
        return None
    rows = load_digests()
    target = None
    if reply_to_message_id is not None:
        target = next((r for r in reversed(rows) if str(reply_to_message_id) in [str(x) for x in r.get("message_ids") or []]), None)
    target = target or latest_pending(rows)
    if not target:
        return "No open PR digest to change."
    hold = m.group(1).lower() == "hold"
    replies = []
    for num in re.findall(r"\d+", m.group(2)):
        out = toggle_item(target["digest_id"], int(num), chat_id=chat_id, allowed_chats=allowed_chats, hold=hold)
        if out.get("ok"):
            replies.append(f"#{num} {'held' if hold else 'included'}")
        else:
            replies.append(f"#{num}: {out.get('reason')}")
    after = _find(load_digests(), target["digest_id"]) or target
    n = len({int(i['pr']) for i in after.get('ready') or []} - {int(x) for x in after.get('excluded') or []})
    return f"Digest `{target['digest_id']}`: " + "; ".join(replies) + f". Approve all now covers {n}."


# ── reconcile (host timer) ───────────────────────────────────────────────────


def approved_bindings() -> dict[int, dict[str, Any]]:
    """Latest approved head per PR, from digest approvals and the per-PR Telegram path."""
    out: dict[int, dict[str, Any]] = {}

    def put(pr: int, head: str, at: float, source: str) -> None:
        if not head:
            return
        cur = out.get(pr)
        if cur is None or at >= cur["at"]:
            out[pr] = {"head_sha": head, "at": at, "source": source}

    for a in _read_jsonl(approvals_path()):
        try:
            at = datetime.strptime(a["approved_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
        except (KeyError, ValueError):
            at = 0.0
        for it in a.get("items") or []:
            put(int(it["pr"]), str(it.get("head_sha") or ""), at, f"digest:{a.get('digest_id')}")
    for r in pmt._load():  # noqa: SLF001 — read-only
        if r.get("status") == "APPROVED":
            put(int(r.get("pr_number") or 0), str(r.get("head_sha") or ""), float(r.get("settled_at") or 0),
                f"per_pr:{r.get('request_id')}")
    return out


def _heads_match(a: str, b: str) -> bool:
    a, b = str(a or ""), str(b or "")
    if not a or not b:
        return False
    n = min(len(a), len(b), 40)
    return n >= 7 and a[:n] == b[:n]


def reconcile_head_binding(repo: str, *, apply: bool, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    prs = list_open_prs(repo, int(cfg.get("pr_list_limit") or 100))
    binds = approved_bindings()
    results = []
    for pr in prs:
        if pmt.LABEL not in label_set(pr):
            continue
        n = int(pr["number"])
        head = str(pr.get("headRefOid") or "")
        b = binds.get(n)
        if b is None:
            results.append({"pr": n, "action": "unbound_label", "policy": cfg.get("unbound_label_action", "report")})
            if cfg.get("unbound_label_action") != "remove":
                continue
        elif _heads_match(b["head_sha"], head):
            results.append({"pr": n, "action": "bound_ok", "head": head[:9]})
            continue
        row = {"schema": BINDING_SCHEMA, "at": _now_iso(), "pr": n, "approved_head": (b or {}).get("head_sha", ""),
               "current_head": head, "source": (b or {}).get("source"), "action": "remove_label"}
        if apply:
            res = pmt.remove_operator_merge_label(n, repo=repo)
            row["label_removed"] = bool(res.get("ok"))
            if res.get("ok"):
                pmt.comment_on_pr(
                    n,
                    f"operator-merge removed: head moved from `{str(row['approved_head'])[:9] or 'unbound'}` to "
                    f"`{head[:9]}` after approval. The PR returns to the next Telegram digest.",
                    repo=repo,
                )
            _append_jsonl(bindings_path(), row)
        results.append({"pr": n, "action": "label_removed" if apply else "would_remove_label",
                        "approved_head": str(row["approved_head"])[:9], "head": head[:9]})
    return results


def _deploy_receipts_dir() -> Path:
    try:
        from scripts.lib import deploy_on_main as dom  # read-only: receipts location only
        return dom.receipts_dir()
    except Exception:  # noqa: BLE001
        root = Path(os.environ.get("TRADEAI_STATE_ROOT") or Path.home() / "trade-ai-releases" / "persistent-state")
        return root / "data" / "runtime" / "deploy_on_main"


def reconcile_notes(repo: str, *, apply: bool, cfg: dict[str, Any]) -> dict[str, Any]:
    state = _read_json(notes_state_path(), {})
    tracked: dict[str, Any] = state.setdefault("tracked", {})
    approved_prs = set()
    for a in _read_jsonl(approvals_path()):
        for it in a.get("items") or []:
            approved_prs.add(int(it["pr"]))
    out: dict[str, Any] = {"merged_note": None, "live_notes": []}

    # Merged
    fresh = []
    if approved_prs:
        for m in list_merged_prs(repo):
            n = int(m["number"])
            if n in approved_prs and str(n) not in tracked:
                fresh.append({"pr": n, "title": str(m.get("title") or "")[:80],
                              "merge_sha": str((m.get("mergeCommit") or {}).get("oid") or ""),
                              "merged_at": m.get("mergedAt")})
    if fresh:
        text = (f"\U0001f500 *Merged {len(fresh)}, deploying*\n"
                + "\n".join(f"• #{f['pr']} {_esc(f['title'])} `{f['merge_sha'][:9]}`" for f in fresh)
                + "\nHost deploy\\_on\\_main promotes the new main; a Live note follows.")
        out["merged_note"] = {"prs": [f["pr"] for f in fresh], "message": text}
        if apply:
            ok, _ids, detail = _send(text, priority=str(cfg.get("notes_priority") or "P2"))
            out["merged_note"]["telegram"] = detail
            for f in fresh:
                tracked[str(f["pr"])] = {**f, "merged_noted_at": _now_iso(), "live": None}

    # Live / failed
    rdir = _deploy_receipts_dir()
    files = sorted(p.name for p in rdir.glob("*.json") if p.name != "latest.json") if rdir.is_dir() else []
    cursor = state.get("receipt_cursor")
    if cursor is None:
        # First run: never replay history.
        state["receipt_cursor"] = files[-1] if files else ""
        files = []
    else:
        files = [f for f in files if f > cursor]
    notify = set(cfg.get("receipt_outcomes_notify") or [])
    failed_set = set(cfg.get("receipt_outcomes_failed") or [])
    for name in files:
        rec = _read_json(rdir / name, {})
        outcome = str(rec.get("outcome") or "")
        if outcome in notify:
            main_sha = str(rec.get("main_sha") or "")
            pending = [t for t in tracked.values() if not t.get("live")]
            incl = [t for t in pending if commit_included(repo, t.get("merge_sha", ""), main_sha)]
            if incl:
                failed = outcome in failed_set
                verdict = {"verified": "post-release tester ok", "verify_failed": "post-release tester FAILED",
                           "deploy_failed": "deploy FAILED (CURRENT not moved)"}.get(outcome, outcome)
                head = "\U0001f6a8 *Deploy problem*" if failed else "\U0001f7e2 *Live*"
                text = (f"{head}: `{main_sha[:9]}` — PRs " + ", ".join(f"#{t['pr']}" for t in incl)
                        + f"\n{verdict} (receipt `{name}`, path {rec.get('path')})")
                note = {"receipt": name, "outcome": outcome, "prs": [t["pr"] for t in incl], "message": text}
                if apply:
                    _ok, _ids, detail = _send(text, priority=str(cfg.get("failure_priority" if failed else "notes_priority") or "P1"))
                    note["telegram"] = detail
                    if not failed:
                        for t in incl:
                            t["live"] = {"sha": main_sha, "receipt": name, "at": _now_iso()}
                out["live_notes"].append(note)
        if apply:
            state["receipt_cursor"] = name
    if apply:
        # Bound the tracked map.
        if len(tracked) > 300:
            for k in sorted(tracked, key=lambda k: str(tracked[k].get("merged_noted_at")))[:-300]:
                tracked.pop(k, None)
        _write_json(notes_state_path(), state)
    elif cursor is None:
        out["first_run"] = True
    return out


def reconcile(*, repo: str = pmt.DEFAULT_REPO, apply: bool = False, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = cfg or load_config()
    out = {"ok": True, "apply": apply,
           "head_binding": reconcile_head_binding(repo, apply=apply, cfg=cfg),
           "notes": reconcile_notes(repo, apply=apply, cfg=cfg)}
    if apply:
        _write_json(_store() / "digest_reconcile_last_run.json", {"at": _now_iso(), **out})
    return out


# ── next digest time (request_pr_merge_approve.py) ───────────────────────────


def next_digest_at(now: datetime | None = None, cfg: dict[str, Any] | None = None) -> str:
    from zoneinfo import ZoneInfo

    cfg = cfg or load_config()
    tz = ZoneInfo(ET_NAME)
    now = (now or datetime.now(timezone.utc)).astimezone(tz)
    times = cfg.get("next_digest_times") or {}
    for day in range(0, 8):
        d = (now + timedelta(days=day)).date()
        slots = times.get("weekend" if d.weekday() >= 5 else "weekday") or []
        for hhmm in sorted(slots):
            h, m = (int(x) for x in hhmm.split(":"))
            at = datetime(d.year, d.month, d.day, h, m, tzinfo=tz)
            if at > now:
                return at.strftime("%a %Y-%m-%d %H:%M ET")
    return "unknown"


def nominate(pr_number: int, *, head_sha: str, title: str, reason: str = "") -> dict[str, Any]:
    """Record that the coordinator asked for this PR; the next digest lists it if READY."""
    row = {"at": _now_iso(), "pr": int(pr_number), "head_sha": head_sha, "title": title[:200], "reason": reason[:300]}
    _append_jsonl(_store() / "digest_nominations.jsonl", row)
    return row
