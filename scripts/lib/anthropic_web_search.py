"""Anthropic hosted web_search as an Ask-the-CIO source.

The provider credential and the credit book live in the governed bridge; this module never sees a
key. It posts ONE tool-bearing call (server tool ``web_search_20260209``) under the registered
caller ``web_search`` and normalises the returned ``web_search_tool_result`` blocks into results.

Hermetic by construction: ``transport=`` is injectable, so tests never touch the network or the
bridge. A refused or unreachable bridge is a typed gap, never an exception into the caller.

**The tool version carries server-side code execution.** ``web_search_20260209`` uses Anthropic's
"dynamic filtering": Claude writes and runs code in Anthropic's own sandbox to call ``web_search`` and
filter the results before they reach the context window (provider docs, tool-use concepts). A real
response therefore also contains ``server_tool_use`` / ``code_execution_tool_result`` blocks, seen live
2026-11-01T23:5xZ, e.g. ``r = await web_search({"query": ...})`` followed by ``print(type(r), len(r))``.
Nothing of ours is executed: the sandbox is Anthropic-side, it never sees a credential, a file or a
broker path, and the only inputs are our query and public search results. The bridge's tool allowlist
(§23.10 P5) is an *outbound* gate and does not cover these blocks, so this module counts them instead of
hiding them: ``search()`` reports ``code_execution_blocks`` and the Ask source carries that count into its
run row. Choosing the older ``web_search_20250305`` is the way to have no code execution at all, at the
cost of the filtering that keeps result noise out of the context.
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

CALLER = "web_search"
TASK_TYPE = "web_search"
BRIDGE_URL_ENV = "TRADEAI_BRIDGE_URL"
DEFAULT_URL = "http://127.0.0.1:8766/v1/chat/completions"
#: Server tool: Anthropic runs the search and returns web_search_result blocks (title/url/page_age).
TOOL: dict[str, Any] = {"type": "web_search_20260209", "name": "web_search", "max_uses": 3}

# ── backoff (LQ-20261107-1592) ───────────────────────────────────────────────
# The paid web-search leg used to be re-attempted for every Ask subject on every run, even while the
# credit book was refusing every call: 2026-11-08/09 logged 91 ``CREDIT_PROCESS_CAP`` + 4
# ``UNAVAILABLE`` refusals and zero answers in 24 h. A refusal now opens a cooldown, and while it is
# open ``search()`` returns the refusal (with ``retry_at``) without posting to the bridge, so the
# ledger records one window rather than one row per subject per hour.
COOLDOWN_SCHEMA = "WebSearchCooldown@v1"
#: Refusals that mean "the paid credit book said no for now". The book paces a PROCESS's spend by the
#: UTC day (``CreditBook._counts_today``), so these cannot clear before the next UTC midnight: an hour
#: later is still the same utc day. Retrying sooner only adds another refused row.
DAY_PACED_REFUSALS = frozenset({
    "CREDIT_PROCESS_CAP", "PAUSED_TODAY", "EXHAUSTED", "TIER_CAP_REFUSAL",
    "CREDIT_PER_CALL_CAP", "EMERGENCY_TIER_REFUSED", "CALL_COST_CEILING",
})
#: A transient refusal (bridge down, provider 5xx, the book's own UNAVAILABLE cooldown) backs off
#: 15 min, then 30, 60, ... capped at 6 h; the first success closes the window.
BASE_BACKOFF_MINUTES = 15
MAX_BACKOFF_HOURS = 6
#: A transient streak older than this restarts at one step instead of compounding a stale count.
FAILURE_MEMORY = timedelta(days=1)
#: The bridge's own error codes are ours, not free text. Only a token of this shape is ever taken
#: from a refused response body; nothing else in the body is read (see the HTTPError branch below).
_TOKEN = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")
_LOCK = threading.Lock()


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def results_from_blocks(blocks: Any, count: int) -> tuple[list[dict[str, Any]], str | None]:
    """(results, error) from provider content blocks. A success ``content`` is a list; an error is an object."""
    out: list[dict[str, Any]] = []
    for block in blocks or []:
        if not isinstance(block, dict) or block.get("type") != "web_search_tool_result":
            continue
        content = block.get("content")
        if isinstance(content, dict):
            return out, str(content.get("error_code") or "WEB_SEARCH_ERROR")
        for row in content or []:
            if isinstance(row, dict) and row.get("type") == "web_search_result":
                out.append({
                    "title": row.get("title"),
                    "url": row.get("url"),
                    # The API returns encrypted_content, which is opaque - never readable page text.
                    # It is kept under its own key so no caller mistakes it for a snippet (2026-11-02: it
                    # reached a fact's claim text as base64 and landed in CIO memory that way).
                    "content": "",
                    "encrypted_content": row.get("encrypted_content") or "",
                    "published": row.get("page_age"),
                })
                if len(out) >= count:
                    return out, None
    return out, None


def code_execution_blocks(blocks: Any) -> int:
    """How many sandbox results the provider's dynamic filtering produced (see the module docstring).

    Counted, never consumed: the Ask source only reads ``web_search_tool_result`` rows. The count rides
    the run row so a receipt shows that code ran Anthropic-side, instead of the operator discovering it.
    """
    return sum(
        1 for b in (blocks or [])
        if isinstance(b, dict) and b.get("type") == "code_execution_tool_result"
    )


def _post(url: str, body: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "X-TradeAI-Agent": CALLER, "X-TradeAI-Task-Type": TASK_TYPE},
    )
    with build_opener(_NoRedirect).open(request, timeout=timeout_s) as response:
        return json.loads(response.read().decode("utf-8"))


# ── cooldown state ───────────────────────────────────────────────────────────
# One small JSON file, the same shape as scripts/lib/research_circuit.py: TRADEAI_CIO_DIR or
# ``data/cio``, the root the rest of the CIO runtime already uses. A closed record is written, never
# the file removed: the record is the audit trail of why the leg was silent, and "never delete" binds.
def _state_file(state_path: str | Path | None = None) -> Path:
    if state_path is not None:
        return Path(state_path)
    root = Path(os.environ.get("TRADEAI_CIO_DIR") or (Path(__file__).resolve().parents[2] / "data" / "cio"))
    return root / "web_search_cooldown.json"


def _utc(now: datetime | None = None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    return now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)


def _stamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _next_utc_midnight(now: datetime) -> datetime:
    return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def _read_state(path: Path) -> dict[str, Any] | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and doc.get("schema") == COOLDOWN_SCHEMA else None


def _write_state(record: dict[str, Any], path: Path) -> None:
    """Best effort: a cooldown that cannot be saved must never fail the search itself."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
        tmp.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        return


def open_cooldown(*, state_path: str | Path | None = None,
                  now: datetime | None = None) -> dict[str, Any] | None:
    """The refusal record still in force at ``now``, or None when the leg may be attempted."""
    record = _read_state(_state_file(state_path))
    if not record or record.get("state") not in {"cap", "transient"}:
        return None
    retry_at = _stamp(record.get("retry_at"))
    if retry_at is None or _utc(now) >= retry_at:
        return None
    return record


def record_success(*, state_path: str | Path | None = None, now: datetime | None = None) -> None:
    path = _state_file(state_path)
    with _LOCK:
        _write_state(
            {"schema": COOLDOWN_SCHEMA, "state": "closed", "reason": None, "failures": 0,
             "opened_at": _utc(now).isoformat(), "retry_at": None},
            path,
        )


def record_failure(reason: str, *, state_path: str | Path | None = None,
                   now: datetime | None = None) -> dict[str, Any]:
    """Open (or keep) the cooldown window for ``reason`` and return the record.

    A burst of subjects is ONE window: a concurrent second subject that is refused while a window is
    already open keeps that window instead of doubling its delay, so five subjects cannot turn a
    15-minute backoff into two hours.
    """
    token = str(reason or "WEB_SEARCH_UNAVAILABLE").strip()[:120]
    moment = _utc(now)
    path = _state_file(state_path)
    with _LOCK:
        prior = _read_state(path)
        retry_at = _stamp((prior or {}).get("retry_at"))
        if prior and prior.get("state") in {"cap", "transient"} and retry_at is not None and moment < retry_at:
            return prior
        # Only a transient streak compounds; a cap refusal or an old streak restarts at one step.
        streak = 0
        opened = _stamp((prior or {}).get("opened_at"))
        if (prior or {}).get("state") == "transient" and opened is not None and moment - opened <= FAILURE_MEMORY:
            try:
                streak = int(prior["failures"])  # an unreadable count restarts the streak, never widens it
            except (KeyError, TypeError, ValueError):
                streak = 0
        failures = streak + 1
        code = token.split()[0] if token.split() else token
        if code in DAY_PACED_REFUSALS:
            state, until = "cap", _next_utc_midnight(moment)
        else:
            state = "transient"
            minutes = min(BASE_BACKOFF_MINUTES * (2 ** (failures - 1)), MAX_BACKOFF_HOURS * 60)
            until = moment + timedelta(minutes=minutes)
        record = {"schema": COOLDOWN_SCHEMA, "state": state, "reason": token, "failures": failures,
                  "opened_at": moment.isoformat(), "retry_at": until.isoformat()}
        _write_state(record, path)
        return record


def _refused(reason: str, *, state_path: str | Path | None, now: datetime | None,
             **extra: Any) -> dict[str, Any]:
    """A refused call: record the window and hand the caller the reason with its retry time."""
    record = record_failure(reason, state_path=state_path, now=now)
    return {"ok": False, "provider": "anthropic", "results": [], "error": reason, "reason": reason,
            "backoff": False, "skipped": False, "retry_at": record.get("retry_at"),
            "cooldown_state": record.get("state"), **extra}


def _http_error_body(exc: HTTPError) -> bytes:
    """At most 8 KiB of a refused response, or b"" — reading it must never turn into a second failure."""
    try:
        return exc.read(8192) or b""
    except (OSError, ValueError, AttributeError):
        return b""


def _body_error_code(raw: Any) -> str | None:
    """The bridge's typed error code from a refused response body, and nothing else from it.

    The body is never read into a row: it can quote the question or an auth page (see the HTTPError
    branch). Only a bare ``error.code`` token is taken, and only if it is shaped like one of ours.
    """
    try:
        code = (json.loads(raw or b"") or {}).get("error", {}).get("code")
    except (ValueError, AttributeError, TypeError):
        return None
    return code if isinstance(code, str) and _TOKEN.match(code) else None


def search(query: str, *, count: int = 5, timeout_s: float = 60.0,
           transport: Callable[[str, dict, float], dict] | None = None,
           state_path: str | Path | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Search the web through the governed bridge. Never raises; a failure is a typed gap."""
    held = open_cooldown(state_path=state_path, now=now)
    if held:
        # Nothing is posted and nothing is logged at the bridge: the reason and its retry time are the
        # honest state, and the caller records them once instead of once per subject per hour.
        return {"ok": False, "provider": "anthropic", "results": [],
                "error": held.get("reason") or "WEB_SEARCH_UNAVAILABLE",
                "reason": held.get("reason") or "WEB_SEARCH_UNAVAILABLE",
                "backoff": True, "skipped": True, "retry_at": held.get("retry_at"),
                "cooldown_state": held.get("state")}
    url = os.environ.get(BRIDGE_URL_ENV) or DEFAULT_URL
    body = {
        "model": "tradeai_governed",
        "messages": [{"role": "user", "content": f"Search the web for: {query}"}],
        "tools": [TOOL],
        "max_tokens": 1024,
    }
    try:
        document = (transport or _post)(url, body, timeout_s)
    except HTTPError as exc:
        # 2026-11-07 (LQ-20261107-212): the status used to be thrown away — the run row said only
        # "HTTPError", so a lane degraded for a day with no nameable cause. The code and the reason
        # line are what let an operator tell unauthorized (401) from misrouted (404), throttled (429)
        # and broken (5xx). 2026-11-09 (LQ-20261107-1592): a credit refusal reaches us as HTTP 500,
        # so the status alone named a server fault; its typed ``error.code`` (CREDIT_PROCESS_CAP,
        # UNAVAILABLE, ...) is now taken from the body and nothing else in the body is read — it can
        # quote the question or an auth error page, and this row is written to the ledger.
        token = _body_error_code(_http_error_body(exc))
        reason = token or f"HTTP {exc.code} {exc.reason}".strip()
        return _refused(reason, state_path=state_path, now=now, status=int(exc.code))
    except URLError as exc:
        # urllib's reason is usually the socket error (e.g. "Connection refused"), which is the one
        # fact that separates "the bridge is down" from "the bridge said no". The class name stays
        # first so an existing "URLError" match keeps working.
        reason = str(getattr(exc, "reason", None) or "").strip()
        return _refused(f"URLError: {reason}" if reason else "URLError", state_path=state_path, now=now)
    except (OSError, ValueError) as exc:
        return _refused(type(exc).__name__, state_path=state_path, now=now)
    if not isinstance(document, dict) or document.get("error"):
        reason = "BRIDGE_REFUSED"
        if isinstance(document, dict):
            reason = str((document.get("error") or {}).get("code") or reason)
        return _refused(reason, state_path=state_path, now=now)
    blocks = document.get("content_blocks") or (document.get("_tradeai") or {}).get("content_blocks") or []
    results, error = results_from_blocks(blocks, count)
    if results and not error:
        record_success(state_path=state_path, now=now)
    return {
        "ok": bool(results) and not error,
        "provider": "anthropic",
        "results": results,
        "error": error,
        # Dynamic filtering ran Anthropic-side code to answer this call (module docstring). Reported so the
        # run row says so, rather than leaving it to a provider-side detail nobody reads.
        "code_execution_blocks": code_execution_blocks(blocks),
    }
