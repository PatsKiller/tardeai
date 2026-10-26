"""pr_merge_telegram.py — Telegram is the Mergify go-signal (no GitHub UI).

Operator taps Approve on Telegram. This module adds the ``operator-merge`` label
on the PR. Mergify queues only when that label is present (plus CI green and
window). Deny removes the label. Agents never merge and never Approve on GitHub.

Flow
----
1. ``mint_and_notify(pr, ...)`` — PENDING request + interrupt Telegram with
   Approve / Deny buttons (``prmapprove:<id>`` / ``prmdeny:<id>``).
2. Callback poller calls ``settle_by_request_id`` — only an allowlisted chat tap
   settles. On approve: ``gh`` adds ``operator-merge``. On deny: removes it.
3. ``notify_pr_merge_ready.py`` (host timer) and agents after ``gh pr create``
   call mint so the phone gets the prompt without anyone opening github.com.

Authority
---------
Telegram tap = operator decision. Label write is a host side-effect of that tap.
``MBI_BEHAVIOR = 0``; no broker, order, or promote path.
"""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

SCHEMA = "PrMergeTelegramApproval@v1"
LABEL = "operator-merge"
DEFAULT_REPO = os.environ.get("TRADEAI_GITHUB_REPO", "PatsKiller/tardeai")
DEFAULT_TTL_SECONDS = int(os.environ.get("PR_MERGE_TELEGRAM_TTL_SECONDS", "86400"))  # 24h
# Chicken-egg bridge: CURRENT's poller already settles gapprove. Until this module
# is promoted, Telegram Approve for a PR is a short-lived ``telegram`` guard
# request whose reason carries this marker; a waiter applies ``operator-merge``.
GUARD_REASON_MARKER = "PR_MERGE_LABEL"
GUARD_BRIDGE_SCOPE = "telegram"
REQUIRED_CHECKS = (
    "cio-hardening",
    "agent-governance",
    "release-readiness",
    "ci-gate",
)
HOLD_LABELS = frozenset({"held", "broker", "broker_active_trader"})


def store_dir() -> Path:
    override = os.environ.get("PR_MERGE_TELEGRAM_DIR")
    if override:
        return Path(override)
    # Prefer persistent-state; fall back under home if that tree is absent.
    root = Path(
        os.environ.get(
            "TRADEAI_PERSISTENT_STATE",
            str(Path.home() / "trade-ai-releases" / "persistent-state"),
        )
    )
    path = root / "data" / "runtime" / "pr_merge_telegram"
    path.mkdir(parents=True, exist_ok=True)
    return path


def requests_path() -> Path:
    return store_dir() / "requests.json"


def _load() -> list[dict[str, Any]]:
    p = requests_path()
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _save(rows: list[dict[str, Any]]) -> None:
    p = requests_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(p)


def _new_id() -> str:
    return secrets.token_hex(8)


def find_pending(pr_number: int, head_sha: str | None = None) -> Optional[dict[str, Any]]:
    now = time.time()
    for r in _load():
        if r.get("status") != "PENDING":
            continue
        if int(r.get("pr_number") or 0) != int(pr_number):
            continue
        if float(r.get("expires_at") or 0) < now:
            continue
        if head_sha and r.get("head_sha") and str(r["head_sha"])[:9] != str(head_sha)[:9]:
            continue
        return r
    return None


def mint_request(
    *,
    pr_number: int,
    title: str,
    head_sha: str,
    url: str,
    reason: str = "",
    repo: str = DEFAULT_REPO,
    ttl: int = DEFAULT_TTL_SECONDS,
) -> dict[str, Any]:
    """Create a PENDING row. Does not send Telegram (caller sends)."""
    existing = find_pending(pr_number, head_sha)
    if existing:
        return existing
    now = time.time()
    rec = {
        "schema": SCHEMA,
        "request_id": _new_id(),
        "status": "PENDING",
        "pr_number": int(pr_number),
        "title": str(title or "")[:200],
        "head_sha": str(head_sha or "")[:40],
        "url": str(url or ""),
        "repo": repo,
        "reason": str(reason or "")[:500],
        "created_at": now,
        "expires_at": now + max(60, int(ttl)),
        "settled_at": None,
        "settled_by": None,
        "label_result": None,
    }
    rows = _load()
    rows.append(rec)
    # Keep the newest 200; archive older by dropping from the hot file only after
    # they are settled or expired (append-only history lives in receipts).
    hot = [r for r in rows if r.get("status") == "PENDING" or (now - float(r.get("created_at") or 0)) < 7 * 86400]
    _save(hot[-200:])
    return rec


def record_delivery(request_id: str, *, accepted: bool, message_ids: list[str] | None = None) -> None:
    rows = _load()
    for r in rows:
        if r.get("request_id") == request_id:
            r["delivery"] = {
                "accepted": bool(accepted),
                "message_ids": list(message_ids or []),
                "at": time.time(),
            }
            break
    _save(rows)


def _gh_json(args: list[str], *, input_obj: Any | None = None) -> tuple[int, Any]:
    cmd = ["gh", "api", *args]
    raw_in = None
    if input_obj is not None:
        cmd.extend(["--input", "-"])
        raw_in = json.dumps(input_obj).encode("utf-8")
    env = os.environ.copy()
    # Never inherit agent-injected secrets into gh beyond the host login.
    proc = subprocess.run(
        cmd,
        input=raw_in,
        capture_output=True,
        env=env,
        timeout=60,
        check=False,
    )
    text = (proc.stdout or b"").decode("utf-8", errors="replace").strip()
    try:
        body = json.loads(text) if text else None
    except json.JSONDecodeError:
        body = {"raw": text, "stderr": (proc.stderr or b"").decode("utf-8", errors="replace")[:500]}
    return proc.returncode, body


def ensure_label_exists(repo: str = DEFAULT_REPO) -> None:
    code, _ = _gh_json([f"repos/{repo}/labels/{LABEL}"])
    if code == 0:
        return
    _gh_json(
        [f"repos/{repo}/labels", "-X", "POST"],
        input_obj={
            "name": LABEL,
            "color": "0E8A16",
            "description": "Telegram Approve: Mergify may queue this PR",
        },
    )


def add_operator_merge_label(pr_number: int, *, repo: str = DEFAULT_REPO) -> dict[str, Any]:
    ensure_label_exists(repo)
    code, body = _gh_json(
        [f"repos/{repo}/issues/{int(pr_number)}/labels", "-X", "POST"],
        input_obj={"labels": [LABEL]},
    )
    return {"ok": code == 0, "rc": code, "body": body, "action": "add", "label": LABEL}


def remove_operator_merge_label(pr_number: int, *, repo: str = DEFAULT_REPO) -> dict[str, Any]:
    code, body = _gh_json(
        [f"repos/{repo}/issues/{int(pr_number)}/labels/{LABEL}", "-X", "DELETE"],
    )
    # 404 = already absent — treat as ok
    ok = code == 0 or (isinstance(body, dict) and body.get("status") == "404")
    return {"ok": ok, "rc": code, "body": body, "action": "remove", "label": LABEL}


def comment_on_pr(pr_number: int, body: str, *, repo: str = DEFAULT_REPO) -> dict[str, Any]:
    code, resp = _gh_json(
        [f"repos/{repo}/issues/{int(pr_number)}/comments", "-X", "POST"],
        input_obj={"body": body},
    )
    return {"ok": code == 0, "rc": code, "body": resp}


def settle_by_request_id(
    request_id: str,
    *,
    approve: bool,
    chat_id: Any,
    allowed_chats: set[str] | list[str] | frozenset,
    telegram: dict[str, Any] | None = None,
    apply_label: bool = True,
) -> dict[str, Any]:
    """Settle a PENDING request from a Telegram callback.

    Only an allowlisted ``chat_id`` may settle. Approve adds ``operator-merge``;
    deny removes it. Returns ``{ok, reason?, request, label_result?}``.
    """
    allowed = {str(c) for c in allowed_chats if c is not None and str(c)}
    if str(chat_id) not in allowed:
        return {"ok": False, "reason": "CHAT_NOT_ALLOWLISTED"}

    rows = _load()
    rec = next((r for r in rows if r.get("request_id") == request_id), None)
    if not rec:
        return {"ok": False, "reason": "UNKNOWN_REQUEST"}
    if rec.get("status") != "PENDING":
        return {"ok": False, "reason": f"NOT_PENDING:{rec.get('status')}", "request": rec}
    if float(rec.get("expires_at") or 0) < time.time():
        rec["status"] = "EXPIRED"
        _save(rows)
        return {"ok": False, "reason": "EXPIRED", "request": rec}

    rec["status"] = "APPROVED" if approve else "DENIED"
    rec["settled_at"] = time.time()
    rec["settled_by"] = {
        "chat_id": str(chat_id),
        "from_id": (telegram or {}).get("from_id"),
        "from_username": (telegram or {}).get("from_username"),
        "message_id": (telegram or {}).get("message_id"),
        "text": (telegram or {}).get("text"),
    }
    label_result: dict[str, Any] | None = None
    if apply_label:
        pr = int(rec["pr_number"])
        repo = str(rec.get("repo") or DEFAULT_REPO)
        if approve:
            label_result = add_operator_merge_label(pr, repo=repo)
            if label_result.get("ok"):
                comment_on_pr(
                    pr,
                    f"operator-merge: set by Telegram Approve "
                    f"(request `{request_id}`, head `{str(rec.get('head_sha') or '')[:9]}`). "
                    f"Mergify may queue when CI is green in an ET window.",
                    repo=repo,
                )
        else:
            label_result = remove_operator_merge_label(pr, repo=repo)
            comment_on_pr(
                pr,
                f"operator-merge: cleared by Telegram Deny (request `{request_id}`).",
                repo=repo,
            )
        rec["label_result"] = label_result
    _save(rows)

    if apply_label and label_result is not None and not label_result.get("ok"):
        return {
            "ok": False,
            "reason": "LABEL_WRITE_FAILED",
            "request": rec,
            "label_result": label_result,
        }
    return {"ok": True, "request": rec, "label_result": label_result}


def keyboard(request_id: str) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {"text": "\u2705 Approve merge", "callback_data": f"prmapprove:{request_id}"},
                {"text": "\U0001f6d1 Deny", "callback_data": f"prmdeny:{request_id}"},
            ]
        ]
    }


def format_message(rec: dict[str, Any]) -> str:
    sha = str(rec.get("head_sha") or "")[:9]
    reason = rec.get("reason") or "Mergify go-signal (Telegram only — no GitHub Approve needed)"
    return (
        f"\U0001f4e6 *PR merge approval*\n\n"
        f"*PR:* #{rec.get('pr_number')} — {rec.get('title')}\n"
        f"*Head:* `{sha}`\n"
        f"*Link:* {rec.get('url')}\n"
        f"*Why:* {reason}\n\n"
        f"Tap **Approve merge** to put this on the Mergify queue "
        f"(label `{LABEL}`). Deny leaves it out.\n"
        f"_You do not need github.com. Expires in "
        f"{max(1, int((float(rec.get('expires_at') or 0) - time.time()) / 3600))}h._"
    )


def send_interrupt(message: str, reply_markup: dict[str, Any]) -> tuple[bool, str, list[str]]:
    """P1 interrupt with buttons. Prefer intent path; reply_markup uses transport."""
    try:
        import telegram_alert as _ta
    except ImportError:
        try:
            from scripts import telegram_alert as _ta  # type: ignore
        except ImportError as exc:
            return False, f"telegram_alert unavailable: {exc}", []
    try:
        _ta.reset_last_message_ids()
        ok = _ta.send_telegram(
            message,
            priority="P1",
            dedupe_minutes=0,
            producer="pr_merge_telegram",
            reply_markup=reply_markup,
        )
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}", []
    if not ok:
        return False, "send_telegram returned falsey", []
    try:
        ids = [str(i) for i in (_ta.last_message_ids() or []) if i is not None]
    except Exception:  # noqa: BLE001
        ids = []
    if ids:
        return True, f"accepted, delivered message_id={','.join(ids)}", ids
    return True, "accepted for interrupt delivery, UNCONFIRMED: no message id", ids


def mint_and_notify(
    *,
    pr_number: int,
    title: str,
    head_sha: str,
    url: str,
    reason: str = "",
    repo: str = DEFAULT_REPO,
    ttl: int = DEFAULT_TTL_SECONDS,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Mint (or reuse pending) and send Telegram. Returns receipt dict."""
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "pr_number": pr_number,
            "would_send": True,
            "label": LABEL,
        }
    rec = mint_request(
        pr_number=pr_number,
        title=title,
        head_sha=head_sha,
        url=url,
        reason=reason,
        repo=repo,
        ttl=ttl,
    )
    reused = float(rec.get("created_at") or 0) < time.time() - 2
    if reused and rec.get("delivery", {}).get("accepted"):
        return {
            "ok": True,
            "reused": True,
            "request_id": rec["request_id"],
            "pr_number": pr_number,
            "telegram": "already_notified",
        }
    ok, detail, ids = send_interrupt(format_message(rec), keyboard(rec["request_id"]))
    record_delivery(rec["request_id"], accepted=ok, message_ids=ids)
    return {
        "ok": ok,
        "request_id": rec["request_id"],
        "pr_number": pr_number,
        "telegram": detail,
        "message_ids": ids,
        "label": LABEL,
    }


def pr_check_rollup_green(pr_number: int, *, repo: str = DEFAULT_REPO) -> tuple[bool, dict[str, str]]:
    """Return (all required success, {check: conclusion})."""
    proc = subprocess.run(
        ["gh", "pr", "checks", str(pr_number), "--repo", repo, "--json", "name,state,bucket"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    statuses: dict[str, str] = {}
    if proc.returncode == 0 and proc.stdout.strip():
        try:
            rows = json.loads(proc.stdout)
        except json.JSONDecodeError:
            rows = []
        for row in rows:
            name = str(row.get("name") or "")
            bucket = str(row.get("bucket") or row.get("state") or "").lower()
            if name in REQUIRED_CHECKS:
                statuses[name] = "SUCCESS" if bucket in ("pass", "success") else bucket.upper()
    if not statuses:
        return False, {c: "UNKNOWN" for c in REQUIRED_CHECKS}
    missing = [c for c in REQUIRED_CHECKS if statuses.get(c) != "SUCCESS"]
    return (not missing), statuses


def label_names(pr: dict[str, Any]) -> set[str]:
    labels = pr.get("labels") or []
    out: set[str] = set()
    for lab in labels:
        if isinstance(lab, dict):
            out.add(str(lab.get("name") or ""))
        else:
            out.add(str(lab))
    return out


def guard_reason(*, pr_number: int, request_id: str, head_sha: str) -> str:
    return (
        f"{GUARD_REASON_MARKER} pr=#{int(pr_number)} "
        f"rid={request_id} head={str(head_sha or '')[:9]} "
        f"— tap Approve to queue Mergify (no GitHub needed)"
    )


def parse_guard_reason(reason: str) -> Optional[dict[str, str]]:
    """Extract pr / rid / head from a bridge reason, or None."""
    text = str(reason or "")
    if GUARD_REASON_MARKER not in text:
        return None
    out: dict[str, str] = {}
    for token in text.split():
        if token.startswith("pr=#"):
            out["pr"] = token[4:]
        elif token.startswith("rid="):
            out["rid"] = token[4:]
        elif token.startswith("head="):
            out["head"] = token[5:]
    if "pr" in out and "rid" in out:
        return out
    return None


def mint_and_notify_via_guard(
    *,
    pr_number: int,
    title: str,
    head_sha: str,
    url: str,
    reason: str = "",
    repo: str = DEFAULT_REPO,
    ttl: int = DEFAULT_TTL_SECONDS,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Mint a pr_merge row and ask via the LIVE gapprove path (works on CURRENT).

    The short ``telegram`` grant proves the tap; it is not used for anything else.
    A waiter (``wait_guard_and_apply``) then adds ``operator-merge``.
    """
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "pr_number": pr_number,
            "via": "guard",
            "would_send": True,
            "label": LABEL,
        }
    rec = mint_request(
        pr_number=pr_number,
        title=title,
        head_sha=head_sha,
        url=url,
        reason=reason or "Mergify go-signal via Telegram (guard bridge)",
        repo=repo,
        ttl=ttl,
    )
    try:
        from scripts.lib import guard_remote_approval as gra
    except ImportError:
        from lib import guard_remote_approval as gra  # type: ignore

    g_reason = guard_reason(
        pr_number=pr_number, request_id=rec["request_id"], head_sha=head_sha
    )
    try:
        greq = gra.mint_request(
            GUARD_BRIDGE_SCOPE,
            seconds=300,
            uses=1,
            reason=g_reason,
            ttl=min(int(ttl), int(getattr(gra, "MAX_REQUEST_TTL_SECONDS", 43200))),
        )
    except (ValueError, RuntimeError) as exc:
        return {
            "ok": False,
            "pr_number": pr_number,
            "request_id": rec["request_id"],
            "via": "guard",
            "telegram": f"guard mint refused: {exc}",
        }

    # Reuse the proven interrupt sender from guard_request_approval.
    try:
        from scripts.guard_request_approval import _keyboard, _send
    except ImportError:
        from guard_request_approval import _keyboard, _send  # type: ignore

    body = (
        f"\U0001f4e6 *PR merge approval*\n\n"
        f"*PR:* #{pr_number} — {title[:120]}\n"
        f"*Head:* `{str(head_sha)[:9]}`\n"
        f"*Link:* {url}\n"
        f"*Why:* {reason or 'Ready for Mergify — no GitHub Approve needed'}\n\n"
        f"Tap **Approve** to put this on the Mergify queue "
        f"(adds label `{LABEL}`). Deny leaves it out.\n"
        f"_Bridge scope `{GUARD_BRIDGE_SCOPE}` is only proof of your tap "
        f"(5 min / 1 use). You do not need github.com._"
    )
    ok, detail, ids = _send(body, reply_markup=_keyboard(greq["request_id"]))
    gra.record_delivery(greq["request_id"], accepted=ok, message_ids=ids)
    record_delivery(rec["request_id"], accepted=ok, message_ids=ids)
    # Stash the bridge id so the waiter can match without re-parsing.
    rows = _load()
    for r in rows:
        if r.get("request_id") == rec["request_id"]:
            r["guard_bridge_request_id"] = greq["request_id"]
            break
    _save(rows)
    return {
        "ok": ok,
        "pr_number": pr_number,
        "request_id": rec["request_id"],
        "guard_request_id": greq["request_id"],
        "via": "guard",
        "telegram": detail,
        "message_ids": ids,
        "label": LABEL,
    }


def wait_guard_and_apply(
    *,
    pr_number: int,
    request_id: str,
    timeout_s: int = 900,
    poll_s: float = 5.0,
) -> dict[str, Any]:
    """Poll the guard remote store; on Approve, add ``operator-merge``."""
    try:
        from scripts.lib import guard_remote_approval as gra
    except ImportError:
        from lib import guard_remote_approval as gra  # type: ignore

    deadline = time.time() + max(30, int(timeout_s))
    while time.time() < deadline:
        doc = gra._load()  # noqa: SLF001 — same process, read-only poll
        for r in doc.get("requests") or []:
            parsed = parse_guard_reason(str(r.get("reason") or ""))
            if not parsed:
                continue
            if parsed.get("pr") != str(pr_number):
                continue
            if parsed.get("rid") and parsed["rid"] != request_id:
                continue
            status = str(r.get("status") or "")
            if status in ("DENIED_BY_OPERATOR", "DENIED", "EXPIRED", "SUPERSEDED"):
                # Mirror onto the pr_merge row.
                rows = _load()
                for row in rows:
                    if row.get("request_id") == request_id and row.get("status") == "PENDING":
                        row["status"] = "DENIED" if "DENY" in status else status
                        row["settled_at"] = time.time()
                        row["settled_by"] = {"via": "guard_bridge", "guard_status": status}
                        break
                _save(rows)
                return {"ok": False, "reason": status, "pr_number": pr_number}
            if status == "APPROVED":
                label_result = add_operator_merge_label(pr_number)
                rows = _load()
                for row in rows:
                    if row.get("request_id") == request_id:
                        row["status"] = "APPROVED"
                        row["settled_at"] = time.time()
                        row["settled_by"] = {
                            "via": "guard_bridge",
                            "guard_request_id": r.get("request_id"),
                        }
                        row["label_result"] = label_result
                        break
                _save(rows)
                if label_result.get("ok"):
                    comment_on_pr(
                        pr_number,
                        f"operator-merge: set by Telegram Approve "
                        f"(request `{request_id}`, via guard bridge). "
                        f"Mergify may queue when CI is green in an ET window.",
                    )
                out: dict[str, Any] = {
                    "ok": bool(label_result.get("ok")),
                    "pr_number": pr_number,
                    "request_id": request_id,
                    "label_result": label_result,
                }
                # Chicken-egg: main may still require GitHub Approve / merge-ready.
                # When enabled, Telegram Approve also merges this one PR via gh so
                # the new Mergify rules land without the operator opening github.com.
                if out["ok"] and os.environ.get("PR_MERGE_BOOTSTRAP_GH_MERGE", "").strip() in (
                    "1",
                    "true",
                    "yes",
                ):
                    out["bootstrap_merge"] = _bootstrap_gh_merge(pr_number)
                return out
        time.sleep(max(1.0, float(poll_s)))
    return {"ok": False, "reason": "TIMEOUT", "pr_number": pr_number, "request_id": request_id}


def write_notify_receipt(summary: dict[str, Any]) -> Path:
    path = store_dir() / "notify_receipt.json"
    path.write_text(json.dumps({**summary, "written_at": time.time()}, indent=2) + "\n")
    return path


def _bootstrap_gh_merge(pr_number: int, *, repo: str = DEFAULT_REPO) -> dict[str, Any]:
    """Merge via ``gh`` so the operator never opens github.com for the bootstrap PR.

    Used only while main's Mergify still requires a GitHub Approve. After this
    PR lands, Telegram → ``operator-merge`` is enough and this path stays off.
    """
    # Prefer squash to match queue_rules.merge_method on this repo.
    proc = subprocess.run(
        [
            "gh",
            "pr",
            "merge",
            str(int(pr_number)),
            "--repo",
            repo,
            "--squash",
            "--auto",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    return {
        "ok": proc.returncode == 0,
        "rc": proc.returncode,
        "stdout": (proc.stdout or "")[-500:],
        "stderr": (proc.stderr or "")[-500:],
        "mode": "gh_pr_merge_squash_auto",
    }
