#!/usr/bin/env python3
"""Static transitive-capability audit of every n8n-allowlisted lane (DR/boundary audit finding B / DD01, 2026-10-15).

Third-party finding: "An allowlisted scalp lane can reach direct Slack/Twilio transports, contradicting the
unqualified 'only sender' boundary. Transitive capabilities need review alongside route permissions." The
allowlist test checks argv tokens and the gateway checks route names; neither looks at what the lane's code
can reach. This walks it.

For every lane in config/n8n_run_allowlist.json:
  1. take the lane's entry script from its argv (the first ``*.py`` token, ``$CODE_ROOT/`` stripped; a
     ``bash -c`` lane is a shell lane and gets ``subprocess`` with no Python closure);
  2. resolve its repo-local import closure by AST: every ``import`` / ``from ... import`` at any depth
     (function-level lazy imports included, because a lazy import is still reachable), ``__import__("x")`` and
     ``importlib.import_module("x")`` with a literal name. Resolution follows how these scripts run: the
     script's own directory, the repo root, ``scripts/`` and ``scripts/lib/`` (the sys.path inserts they do);
  3. traversal STOPS at an approved delivery chokepoint (CHOKEPOINTS, the outbound/delivery set of
     scripts/check_telegram_chokepoint.py, plus the scripts/lib/comms/ gateway package): reaching it is
     ``chokepoint_send``, the sanctioned path;
  4. flags each module in the closure by AST (strings in docstrings are ignored):

  FORBIDDEN (CI fails on a new lane/capability pair not in config/n8n_lane_capability_baseline.json)
    direct_sender     smtplib / twilio / slack_sdk / python-telegram-bot import; a literal Bot API, Slack
                      webhook/API or Twilio API host; a SLACK_WEBHOOK* / TWILIO_* name next to an HTTP/Twilio
                      client; a telegram_transport send name (not escape_markdown/smart_split/MAX_MSG_LEN)
                      imported outside the chokepoint set; tooling in SENDER_EXEMPT is not a sender
    broker_module     a module whose file name starts schwab/alpaca/moomoo/futu/ibkr, or an import of the
                      schwab / alpaca / alpaca_trade_api / moomoo / futu / ib_insync / tda packages
    order_placement   defines or calls place_order / submit_order / cancel_order / replace_order /
                      place_*_order
  REVIEW (reported, never fails CI)
    db_write          an INSERT/UPDATE/DELETE/TRUNCATE/ALTER/DROP/CREATE/UPSERT SQL literal in a module that
                      imports db_adapter / psycopg2 / psycopg / sqlalchemy (the trade_ai write paths)
    subprocess        subprocess / os.system / os.popen / os.exec* / os.spawn* / pty
    network_http      requests / httpx / urllib.request / http.client / aiohttp / socket
    chokepoint_send   reaches an approved delivery chokepoint (traversal stops there)

Each flag carries the SHORTEST import chain from the lane script to the first module that has it (BFS), so
"which path" is a citation, not a guess. Static limits (stated on the output): a subprocess-launched script is
not followed (that is what ``subprocess`` flags), dynamic imports with computed names are not resolved, and a
module name that resolves to more than one file takes the first search root.

    python3 scripts/audit_lane_transitive_capabilities.py                # print totals
    python3 scripts/audit_lane_transitive_capabilities.py --write        # write the dated JSON + MD
    python3 scripts/audit_lane_transitive_capabilities.py --check        # exit 1 on an unbaselined forbidden pair
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST = ROOT / "config" / "n8n_run_allowlist.json"
BASELINE = ROOT / "config" / "n8n_lane_capability_baseline.json"
OUT_DIR = ROOT / "docs" / "implementation" / "n8n-maturity"
OUT_STEM = "LANE_TRANSITIVE_CAPABILITIES_20261015"
SCHEMA = "LaneTransitiveCapabilities@v1"

FORBIDDEN = ("direct_sender", "broker_module", "order_placement")
REVIEW = ("db_write", "subprocess", "network_http", "chokepoint_send")
CAPABILITIES = FORBIDDEN + REVIEW

# Approved outbound/delivery boundaries (scripts/check_telegram_chokepoint.py APPROVED_OUTBOUND | APPROVED_DELIVERY).
CHOKEPOINTS = frozenset(
    {
        "scripts/telegram_alert.py",
        "scripts/alert_outbox.py",
        "scripts/telegram_transport.py",
        "scripts/lib/cio_telegram_transport.py",
        "scripts/lib/autonomy_watchdog/telegram_system.py",
    }
)
# The comms gateway package is the governed host sender (N8N_REFERENCE_ARCHITECTURE.md B4): its channel adapters
# send only when deliver=True and COMMS_GATEWAY_MODE is CANARY/ACTIVE, behind its own route policy.
CHOKEPOINT_PREFIXES = ("scripts/lib/comms/",)


def is_chokepoint(rel: str) -> bool:
    return rel in CHOKEPOINTS or rel.startswith(CHOKEPOINT_PREFIXES)


# Tooling that names or probes a provider and never delivers a message (check_telegram_chokepoint.py APPROVED_TOOLING
# and the comms inventory/authority checkers). secret_validators calls Bot API getMe only, and lists TWILIO_AUTH_TOKEN
# as "not_validatable"; it sends nothing.
SENDER_EXEMPT = {
    "scripts/secret_validators.py": "tooling: validates keys (Telegram getMe); sends no message",
    "scripts/secrets/rotation_probes.py": "tooling: rotation probes; sends no message",
    "scripts/audit_direct_telegram_senders.py": "tooling: sender inventory",
    "scripts/check_telegram_chokepoint.py": "tooling: chokepoint ratchet",
    "scripts/comms_phase0_sender_inventory.py": "tooling: sender inventory",
    "scripts/check_data_source_authority.py": "tooling: authority checker",
    "scripts/check_provider_chokepoint.py": "tooling: provider chokepoint checker",
}

SEARCH_SUBDIRS = ("", "scripts", "scripts/lib")
SKIP_PARTS = frozenset({"tests", ".venv", "node_modules", ".git", "worktrees", ".claude"})

SENDER_PKGS = ("smtplib", "twilio", "slack_sdk", "slack", "telegram", "aiosmtplib", "sendgrid")
SENDER_HOST_RE = re.compile(r"(api\.telegram\.org/bot|hooks\.slack\.com|slack\.com/api|api\.twilio\.com)", re.I)
SENDER_NAME_RE = re.compile(r"^(SLACK_WEBHOOK\w*|TWILIO_\w+)$")
BROKER_PKGS = ("schwab", "alpaca", "alpaca_trade_api", "moomoo", "futu", "ib_insync", "tda", "ibapi")
BROKER_FILE_RE = re.compile(r"^(schwab|alpaca|moomoo|futu|ibkr)", re.I)
ORDER_FN_RE = re.compile(r"^(place_order|submit_order|cancel_order|replace_order|place_\w*_order)$")
SQL_WRITE_RE = re.compile(r"^\s*(INSERT|UPDATE|DELETE|TRUNCATE|ALTER|DROP|CREATE|UPSERT)\s", re.I)
DB_PKGS = ("db_adapter", "psycopg2", "psycopg", "sqlalchemy")
NET_PKGS = ("requests", "httpx", "urllib.request", "http.client", "aiohttp", "socket", "urllib3")
OS_EXEC_RE = re.compile(r"^(system|popen|exec\w*|spawn\w*|posix_spawn\w*)$")


def _rel(p: Path) -> str:
    return p.resolve().relative_to(ROOT.resolve()).as_posix()


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            for stmt in body:
                if (
                    isinstance(stmt, ast.Expr)
                    and isinstance(stmt.value, ast.Constant)
                    and isinstance(stmt.value.value, str)
                ):
                    ids.add(id(stmt.value))
    return ids


# Names of telegram_transport that do not deliver (formatting helpers). Importing the module itself or any other
# name (send_message, send_document, _http_post, TELEGRAM_*_API ...) is a chokepoint bypass.
TRANSPORT_HELPERS = frozenset({"escape_markdown", "smart_split", "MAX_MSG_LEN"})


def _transport_send_import(name: str) -> bool:
    parts = name.split(".")
    if "telegram_transport" not in parts:
        return False
    tail = parts[parts.index("telegram_transport") + 1 :]
    return not (tail and tail[0] in TRANSPORT_HELPERS)


def _top(name: str) -> str:
    return name.split(".", 1)[0]


class ModuleInfo:
    __slots__ = ("path", "imports", "caps", "evidence", "all_evidence")

    def __init__(self, path: str):
        self.path = path
        self.imports: list[tuple[str, int, str | None, bool]] = []  # (module, relative level, from-name, eager)
        self.caps: set[str] = set()
        self.evidence: dict[str, str] = {}
        self.all_evidence: dict[str, list[str]] = {}

    def flag(self, cap: str, why: str) -> None:
        self.all_evidence.setdefault(cap, []).append(why)
        if cap not in self.caps:
            self.caps.add(cap)
            self.evidence[cap] = why


def analyse(path: Path) -> ModuleInfo:
    rel = _rel(path)
    info = ModuleInfo(rel)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=rel)
    except SyntaxError as exc:
        info.evidence["parse_error"] = str(exc)[:120]
        return info
    if BROKER_FILE_RE.match(path.name):
        info.flag("broker_module", f"file name {path.name}")
    docs = _docstring_nodes(tree)
    lazy: set[int] = set()  # nodes inside a function body run only when called, not at import time
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            for sub in ast.walk(fn):
                if sub is not fn:
                    lazy.add(id(sub))
    imported: set[str] = set()
    has_sql_write = None
    sender_name_hit = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                info.imports.append((a.name, 0, None, id(node) not in lazy))
                imported.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for a in node.names:
                info.imports.append((mod, node.level, a.name, id(node) not in lazy))
                if node.level == 0:
                    imported.add(f"{mod}.{a.name}" if mod else a.name)
        elif isinstance(node, ast.Call):
            fn = node.func
            fname = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else None)
            if (
                fname in ("__import__", "import_module")
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                info.imports.append((node.args[0].value, 0, None, id(node) not in lazy))
                imported.add(node.args[0].value)
            if fname and ORDER_FN_RE.match(fname):
                info.flag("order_placement", f"calls {fname}() line {node.lineno}")
            if (
                isinstance(fn, ast.Attribute)
                and isinstance(fn.value, ast.Name)
                and fn.value.id == "os"
                and OS_EXEC_RE.match(fn.attr)
            ):
                info.flag("subprocess", f"os.{fn.attr}() line {node.lineno}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if ORDER_FN_RE.match(node.name):
                info.flag("order_placement", f"defines {node.name}() line {node.lineno}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            s = node.value
            m = SENDER_HOST_RE.search(s)
            if m:
                info.flag("direct_sender", f"literal {m.group(1)} line {node.lineno}")
            elif SENDER_NAME_RE.match(s) and sender_name_hit is None:
                sender_name_hit = f"reads {s} line {node.lineno}"
            if has_sql_write is None and SQL_WRITE_RE.match(s):
                has_sql_write = f"SQL {SQL_WRITE_RE.match(s).group(1).upper()} line {node.lineno}"
    for name in sorted(imported):
        top = _top(name)
        if top in SENDER_PKGS or name in SENDER_PKGS:
            info.flag("direct_sender", f"imports {name}")
        if _transport_send_import(name):
            info.flag("direct_sender", f"imports {name} outside the chokepoint set")
        if top in BROKER_PKGS:
            info.flag("broker_module", f"imports {name}")
        if top == "subprocess" or top == "pty" or name == "asyncio.subprocess":
            info.flag("subprocess", f"imports {name}")
        if (
            name in NET_PKGS
            or top in ("requests", "httpx", "aiohttp", "socket", "urllib3")
            or name.startswith(("urllib.request", "http.client"))
        ):
            info.flag("network_http", f"imports {name}")
    # A SLACK_WEBHOOK* / TWILIO_* name is a sender only next to an HTTP/Twilio client in the same module.
    if sender_name_hit and any(
        _top(n) in ("requests", "httpx", "twilio", "aiohttp", "urllib3") or n.startswith("urllib.request")
        for n in imported
    ):
        info.flag("direct_sender", sender_name_hit)
    if rel in SENDER_EXEMPT:
        info.caps.discard("direct_sender")
        info.evidence.pop("direct_sender", None)
        info.all_evidence.pop("direct_sender", None)
        info.evidence["direct_sender_exempt"] = SENDER_EXEMPT[rel]
    if has_sql_write and any(_top(n) in DB_PKGS or n.endswith(".db_adapter") for n in imported):
        info.flag("db_write", has_sql_write)
    if is_chokepoint(rel):
        info.caps = {"chokepoint_send"}
        info.evidence = {"chokepoint_send": "approved delivery chokepoint (check_telegram_chokepoint.py)"}
        info.all_evidence = {"chokepoint_send": [info.evidence["chokepoint_send"]]}
    return info


class Resolver:
    def __init__(self, root: Path = ROOT):
        self.root = root
        self.cache: dict[Path, ModuleInfo] = {}
        self.edges: dict[tuple[Path, bool], list[Path]] = {}
        self._cand: dict[tuple[str, tuple[Path, ...]], Path | None] = {}

    def _candidates(self, dotted: str, base_dirs: list[Path]) -> Path | None:
        key = (dotted, tuple(base_dirs))
        if key not in self._cand:
            self._cand[key] = self._candidates_uncached(dotted, base_dirs)
        return self._cand[key]

    def _candidates_uncached(self, dotted: str, base_dirs: list[Path]) -> Path | None:
        parts = dotted.split(".")
        for base in base_dirs:
            p = base.joinpath(*parts)
            for cand in (p.with_suffix(".py"), p / "__init__.py"):
                if cand.is_file() and not (SKIP_PARTS & set(cand.relative_to(self.root).parts)):
                    return cand
        return None

    def resolve(self, importer: Path, name: str, level: int, from_name: str | None) -> list[Path]:
        out: list[Path] = []
        if level:
            base = importer.parent
            for _ in range(level - 1):
                base = base.parent
            dirs = [base]
            dotted = name
        else:
            dirs = [importer.parent] + [self.root / s if s else self.root for s in SEARCH_SUBDIRS]
            dotted = name
        if dotted:
            segs = dotted.split(".")
            for i in range(1, len(segs) + 1):  # importing a.b.c executes a/__init__, a/b/__init__, a/b/c
                hit = self._candidates(".".join(segs[:i]), dirs)
                if hit is not None:
                    out.append(hit)
        if from_name and from_name != "*":
            sub = f"{dotted}.{from_name}" if dotted else from_name
            hit = self._candidates(sub, dirs)
            if hit is not None:
                out.append(hit)
        return out

    def info(self, path: Path) -> ModuleInfo:
        if path not in self.cache:
            self.cache[path] = analyse(path)
        return self.cache[path]

    def closure(self, entry: Path, eager_only: bool = False) -> tuple[list[Path], dict[Path, Path | None]]:
        """BFS over the import graph; returns (order, parent) so chains are shortest. Stops at chokepoints.
        ``eager_only`` follows module-level imports only: what loads when the lane starts."""
        parent: dict[Path, Path | None] = {entry: None}
        order: list[Path] = []
        q = deque([entry])
        while q:
            cur = q.popleft()
            order.append(cur)
            inf = self.info(cur)
            if is_chokepoint(inf.path):
                continue
            key = (cur, eager_only)
            if key not in self.edges:
                nexts: list[Path] = []
                for name, level, from_name, eager in inf.imports:
                    if eager_only and not eager:
                        continue
                    for nxt in self.resolve(cur, name, level, from_name):
                        if nxt not in nexts:
                            nexts.append(nxt)
                self.edges[key] = nexts
            for nxt in self.edges[key]:
                if nxt not in parent:
                    parent[nxt] = cur
                    q.append(nxt)
        return order, parent


def lane_entry(command: list[str]) -> tuple[str | None, str]:
    """(entry script relative path or None, kind) from an allowlist argv."""
    if command and command[0] == "bash":
        return None, "shell"
    for tok in command:
        if tok.endswith(".py"):
            return tok.replace("$CODE_ROOT/", ""), "python"
    return None, "unknown"


def _chain(path: Path, parent: dict[Path, Path | None]) -> list[str]:
    out = []
    cur: Path | None = path
    while cur is not None:
        out.append(_rel(cur))
        cur = parent[cur]
    return list(reversed(out))


def audit(allowlist_path: Path = ALLOWLIST, resolver: Resolver | None = None) -> dict[str, Any]:
    res = resolver or Resolver()
    lanes = json.loads(allowlist_path.read_text(encoding="utf-8"))["lanes"]
    out: dict[str, Any] = {}
    for lane in lanes:
        lid = str(lane["lane_id"])
        entry, kind = lane_entry([str(x) for x in lane.get("command") or []])
        row: dict[str, Any] = {"entry": entry, "kind": kind, "capabilities": {}}
        if kind == "shell":
            row["capabilities"]["subprocess"] = {"module": None, "evidence": "bash -c argv", "chain": []}
            row["modules_in_closure"] = 0
            out[lid] = row
            continue
        p = (res.root / entry) if entry else None
        if p is None or not p.is_file():
            row["error"] = f"entry script not found: {entry}"
            out[lid] = row
            continue
        order, parent = res.closure(p)
        row["modules_in_closure"] = len(order)
        counts: dict[str, int] = {}
        for mod in order:
            inf = res.info(mod)
            for cap in sorted(inf.caps):
                counts[cap] = counts.get(cap, 0) + 1
                if cap not in row["capabilities"]:
                    row["capabilities"][cap] = {
                        "module": inf.path,
                        "evidence": inf.evidence.get(cap),
                        "module_evidence": sorted(set(inf.all_evidence.get(cap, [])))[:8],
                        "chain": _chain(mod, parent),
                    }
        for cap, n in counts.items():
            row["capabilities"][cap]["modules_with_capability"] = n
        # Import-time reach: the same walk over module-level imports only (loaded when the lane starts).
        e_order, e_parent = res.closure(p, eager_only=True)
        row["modules_at_import"] = len(e_order)
        seen: set[str] = set()
        for mod in e_order:
            for cap in sorted(res.info(mod).caps):
                if cap not in seen:
                    seen.add(cap)
                    row["capabilities"][cap]["at_import"] = True
                    row["capabilities"][cap]["import_chain"] = _chain(mod, e_parent)
        for cap, info in row["capabilities"].items():
            info.setdefault("at_import", False)
        out[lid] = row
    return out


def load_baseline(path: Path = BASELINE) -> dict[str, dict[str, str]]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): {str(c): str(r) for c, r in (v or {}).items()} for k, v in (doc.get("lanes") or {}).items()}


def violations(result: dict[str, Any], baseline: dict[str, dict[str, str]]) -> dict[str, list]:
    """new: forbidden (lane, cap) reached but not baselined with a reason. stale: baselined but no longer reached
    (shrink the baseline). Both fail --check."""
    new, stale = [], []
    for lid, row in sorted(result.items()):
        for cap in FORBIDDEN:
            if cap in row.get("capabilities", {}) and not (baseline.get(lid, {}).get(cap) or "").strip():
                new.append([lid, cap, row["capabilities"][cap]["chain"]])
    for lid, caps in sorted(baseline.items()):
        for cap in caps:
            if cap not in (result.get(lid) or {}).get("capabilities", {}):
                stale.append([lid, cap])
    return {"new": new, "stale": stale}


def totals(result: dict[str, Any]) -> dict[str, int]:
    return {cap: sum(1 for r in result.values() if cap in r.get("capabilities", {})) for cap in CAPABILITIES}


SCALP_SECTION = """## trade-ai-scalp-live: the direct Slack / Twilio path (DD01)

Static chain: `scripts/run_trade_ai_scalp_live.py` -> `scripts/continuous_runner.py` -> `scripts/alerting.py`.
Call path (source lines on the train branch, 2026-10-15):

1. `scripts/run_trade_ai_scalp_live.py` ~304: `from continuous_runner import run_live_cycle`, then calls it.
2. `scripts/continuous_runner.py` `run_live_cycle` -> `_deliver_live_alert` for the cycle's GO / HALT / RVOL /
   SCORE_JUMP triggers.
3. `scripts/continuous_runner.py` 636-637, inside `_deliver_live_alert`, BEFORE the chokepoint at 643-644:
   `from alerting import send_whatsapp, send_slack` / `send_whatsapp(msg); send_slack(msg)` (errors swallowed).
4. `scripts/alerting.py` 221-232 `send_slack`: `requests.post(SLACK_WEBHOOK_URL, ...)`; 235-252 `send_whatsapp`:
   `twilio.rest.Client(TWILIO_SID, TWILIO_AUTH_TOKEN).messages.create(...)`. `_enabled()` (line 23) defaults
   to "true", so the only gates are the credential names being set and ENABLE_SLACK / ENABLE_WHATSAPP not "false".

Consequence measured hermetically (`tests/test_scalp_go_delivery_transports_20261015.py`): with credentials set,
every delivery ATTEMPT sends one Slack webhook POST and one Twilio WhatsApp message before `send_telegram`, so a GO
whose Telegram send fails twice and succeeds on the third attempt reaches Slack and WhatsApp three times while the
delivery owner delivers it once. Without credentials (or with both switches "false") the lane makes zero raw sends
and exactly one chokepoint call per attempt across delivered / disabled / partial / failed / retried outcomes.

### Recommendation: route via the chokepoint (do not just remove the lane from the allowlist)

Removing the lane from `config/n8n_run_allowlist.json` only stops n8n from starting it; the cron fallback
(`*/5 9-15 * * 1-5 ... run_trade_ai_scalp_live.py`) runs the same `_deliver_live_alert`, so the raw sends remain.
The fix that closes DD01 is in the lane code. Proposed diff (NOT applied; operator/owner decision, scalp code):

```diff
--- a/scripts/continuous_runner.py
+++ b/scripts/continuous_runner.py
@@ def _deliver_live_alert(...):
     _set_trigger_marks(state, good, alerted=True)
     _save_state_quietly(state_saver, state, cs, "pre_send")
-    try:
-        from alerting import send_whatsapp, send_slack
-        send_whatsapp(msg); send_slack(msg)
-    except Exception:
-        pass
     accepted = False
     _reset_telegram_message_ids()
```

If Slack / WhatsApp copies are still wanted, publish them through the comms gateway
(`scripts/lib/comms` `send_via_gateway`, mode-gated, one ChannelDelivery per event) after the chokepoint accepts,
never per attempt. When the diff lands: remove `trade-ai-scalp-live.direct_sender` from
`config/n8n_lane_capability_baseline.json` and from the frozen set in
`tests/test_lane_transitive_capabilities_20261015.py`, drop the `xfail` on
`test_dd01_closure_no_raw_sends_even_with_credentials_configured` and delete
`test_dd01_open_gap_raw_transports_fire_per_attempt_today`.

Accompanying allowlist diff (text only: makes the exception truthful until the code fix lands; NOT applied):

```diff
--- a/config/n8n_run_allowlist.json
+++ b/config/n8n_run_allowlist.json
@@ lane trade-ai-scalp-live, "source" (line 562)
-... writes trade_ai_scans + the scalp projection and sends a new GO through send_telegram; it is the only allowlisted lane that may. ...
+... writes trade_ai_scans + the scalp projection and sends a new GO through send_telegram; until DD01 closes it ALSO sends each delivery attempt directly to Slack (alerting.send_slack, SLACK_WEBHOOK_URL) and WhatsApp (alerting.send_whatsapp, TWILIO_*) unless ENABLE_SLACK / ENABLE_WHATSAPP are "false" (docs/implementation/n8n-maturity/LANE_TRANSITIVE_CAPABILITIES_20261015.md); it is the only allowlisted lane that may. ...
```

Alternative only if the code fix cannot land before the next live activation of the n8n workflow: delete the
whole `trade-ai-scalp-live` object (allowlist lines 556-577) so the gateway refuses n8n live runs (cron keeps
running it, with the same raw sends). Interim mitigation without code change: set ENABLE_SLACK=false and
ENABLE_WHATSAPP=false in the scalp lane's environment (config-write grant; this audit did not read the env file,
so their current values are unknown).
"""


def render_md(doc: dict[str, Any]) -> str:
    res = doc["lanes"]
    t = doc["totals"]
    lines = [
        "# Lane transitive capabilities (2026-10-15)",
        "",
        "Generated by `scripts/audit_lane_transitive_capabilities.py --write` from `config/n8n_run_allowlist.json`.",
        "Static AST import closure per allowlisted lane; traversal stops at the approved delivery chokepoints.",
        "CI (`tests/test_lane_transitive_capabilities_20261015.py`) fails when a lane reaches a FORBIDDEN capability",
        "that `config/n8n_lane_capability_baseline.json` does not list with a reason, and when a baseline entry is",
        "no longer reached (the baseline only shrinks). This file is a dated snapshot, not a live gate.",
        "",
        f"Lanes: **{len(res)}**. Allowlist `as_of` {doc['allowlist_as_of']}.",
        "",
        "## Totals (lanes reaching each capability)",
        "",
        "`reachable` follows every import, function-level (lazy) ones included: code the lane can run.",
        "`at import` follows module-level imports only: what is loaded the moment the lane starts.",
        "",
        "| Capability | Class | Lanes (reachable) | Lanes (at import) |",
        "|---|---|---|---|",
    ]
    ti = doc.get("totals_at_import", {})
    for cap in CAPABILITIES:
        lines.append(f"| `{cap}` | {'FORBIDDEN' if cap in FORBIDDEN else 'review'} | {t[cap]} | {ti.get(cap, 0)} |")
    lines += [
        "",
        "Why broker/order reach is so wide: one lazy chain is shared by most DB lanes. `scripts/db_adapter.py`",
        "imports `holdings_guard` inside its holdings write function; `holdings_guard` imports",
        "`schwab_position_sync` at module level; that lazily imports `schwab_transport` (defines `place_order`),",
        "which lazily reaches `brokers/options_order_pilot` -> `lib/options_workflow_service` -> `api_v2`. No lane",
        "reaches a FORBIDDEN capability at import time. Static reach is not a call: the broker modules still need",
        "a broker credential, which `env_names` / the executor env policy are meant to keep out (DD02).",
    ]
    lines += [
        "",
        "## Lane x capability",
        "",
        "`S` direct_sender, `B` broker_module, `O` order_placement, `W` db_write, `X` subprocess, `N` network_http, `C` chokepoint_send.",
        "",
        "| Lane | Closure | S | B | O | W | X | N | C |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for lid, row in sorted(res.items()):
        caps = row.get("capabilities", {})
        cells = ["x" if c in caps else "" for c in CAPABILITIES]
        lines.append(f"| `{lid}` | {row.get('modules_in_closure', row.get('error', ''))} | " + " | ".join(cells) + " |")
    lines += ["", "## Forbidden reach: shortest import chain per lane", ""]
    for lid, row in sorted(res.items()):
        caps = row.get("capabilities", {})
        hits = [c for c in FORBIDDEN if c in caps]
        if not hits:
            continue
        lines.append(f"### `{lid}`")
        lines.append("")
        for c in hits:
            info = caps[c]
            lines.append(
                f"- **{c}** at `{info['module']}` ({info['evidence']}); chain: "
                + " -> ".join(f"`{x}`" for x in info["chain"])
            )
        lines.append("")
    lines += SCALP_SECTION.splitlines() + [""]
    lines += [
        "## Static limits",
        "",
        "- A script launched through `subprocess` is not followed; `subprocess` marks that hole.",
        "- Dynamic imports with computed names are not resolved; literal `__import__` / `import_module` are.",
        "- Resolution order is the script directory, repo root, `scripts/`, `scripts/lib/`; the first hit wins.",
        "- A flag means reachable code holds the capability, not that a run exercises it (env switches,",
        "  credentials and stage still gate it at runtime).",
        "",
    ]
    return "\n".join(lines)


def build_doc(result: dict[str, Any]) -> dict[str, Any]:
    allow = json.loads(ALLOWLIST.read_text(encoding="utf-8"))
    return {
        "schema": SCHEMA,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "allowlist_as_of": allow.get("as_of"),
        "forbidden": list(FORBIDDEN),
        "review": list(REVIEW),
        "chokepoints": sorted(CHOKEPOINTS) + [p + "*" for p in CHOKEPOINT_PREFIXES],
        "totals": totals(result),
        "totals_at_import": {
            cap: sum(1 for r in result.values() if (r.get("capabilities", {}).get(cap) or {}).get("at_import"))
            for cap in CAPABILITIES
        },
        "lanes": result,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--write", action="store_true", help="write the dated JSON + MD under docs/implementation/n8n-maturity"
    )
    ap.add_argument(
        "--check", action="store_true", help="exit 1 on an unbaselined forbidden pair or a stale baseline entry"
    )
    a = ap.parse_args(argv)
    result = audit()
    doc = build_doc(result)
    if a.write:
        (OUT_DIR / f"{OUT_STEM}.json").write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        (OUT_DIR / f"{OUT_STEM}.md").write_text(render_md(doc), encoding="utf-8")
    v = violations(result, load_baseline())
    print(json.dumps({"lanes": len(result), "totals": doc["totals"], "new": len(v["new"]), "stale": len(v["stale"])}))
    if a.check and (v["new"] or v["stale"]):
        for row in v["new"]:
            print(f"NEW forbidden capability: lane {row[0]} -> {row[1]} via {' -> '.join(row[2])}", file=sys.stderr)
        for row in v["stale"]:
            print(f"STALE baseline entry (shrink it): lane {row[0]} {row[1]}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
