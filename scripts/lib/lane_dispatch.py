"""lane_dispatch.py — the optional `dispatch` and `watch` blocks on a lane-registry row.

N8N Maturity design 02 §2 (docs/implementation/n8n-maturity/02-six-workflow-architecture.md) and the schema
docs/implementation/n8n-maturity/schemas/registry-dispatch-block.schema.json. Consumers: compute_due (B5.3,
design §3.2) reads `DispatchBlock`; the heartbeat watcher (design §7) reads `WatchBlock`; the executor (B5.5)
and the gateway re-check `dispatch_eligible` before running anything.

Inert by default. A row with no `dispatch` block is mode "off": the dispatcher never emits it. A malformed
block is also "off" for `dispatch_mode` (fail closed) and is reported by `validate_dispatch_block` and by
scripts/check_lane_registry.py.

FORBIDDEN-TOKEN RULE (AGENTS.md §0 rails 1-2, §23.3, §23.14). Broker, order, stop, positions, secret, guard,
deploy and sender lanes are never dispatch-eligible, whatever their dispatch block says. The tokens are derived
from the existing sources of truth, not a parallel list: n8n_coordination_gateway.FORBIDDEN_ROUTE_TOKENS and
SECRET_KEYS, scripts/pipelines/pipeline_manifest.FORBIDDEN_COMMAND_TOKENS, and EXTRA_FORBIDDEN_WORDS below
(stop/positions, guard, deploy, sender, sm-render, submit and the broker/execution names neither list spells out).

WHOLE-WORD / PATH-SEGMENT MATCHING (operator ruling 2026-10-10 ~00:20 ET, n8n-maturity REMEDIATION_PLAN §7
ruling 2; tests/test_lane_dispatch_word_boundary_20261010.py). The text is split on every non-alphanumeric
(space, _ - / . = : and quotes), so argv words, path segments, flags and env assignments (NAME=value) are all
words. A forbidden word matches a text word that IS the word or an inflection of it (orders, stops, sizing,
promotion, deployment — _word_forms); a multi-word token (two_factor, place_order, api_key) matches as
contiguous words or as its joined form. Three rules keep the compound cases the substring matcher caught:
broker brand names and other DISTINCTIVE_SUBSTRINGS, and the pipeline_manifest script names, still match as
substrings of the separator-collapsed text; and a COMPOUND_PARTNERS word glued to a forbidden word
(liveorders, trailingstop, positionsync) matches. What no longer matches is a forbidden word buried inside an
unrelated word or across a separator: topic / hermes_top20 (stop), synthesizer (size), redeploy (deploy),
recorder (order), stoplights. The gateway's own HTTP route matcher (forbidden_route_token) is unchanged.
They are matched against the lane_id, every string in `scheduler` (or the whole string when `scheduler` is a
plain string), exec_start/service, command/script, and the lane's real argv in config/n8n_run_allowlist.json.
A row marked `stay_on_cron` or recommendation KEEP_ON_CRON (B1 reconcile, PR #1597), or with
watch.stay_behind=true, is never eligible either. dispatchable(row) = mode != off AND eligible.

POLICY EXCEPTIONS (config/lane_dispatch_policy_exceptions.json). trade-ai-scalp-live is governed by AGENTS.md
4.0.0 §23.3 through config/n8n_run_allowlist.json; its cron expression wraps `scripts/market_day_gate.sh`, a
pipeline_manifest FORBIDDEN_COMMAND_TOKENS entry. The exception file (operator approval 2026-10-09 ~18:05 ET)
exempts that lane from ONLY that token, and from the B1 stay_on_cron marker of class pipeline_excluded_gate
naming that token (plus the KEEP_ON_CRON recommendation the reconciler forces from it). Bounds, enforced here:
only EXEMPTIBLE_TOKENS can ever be exempted, and only for EXEMPTIBLE_LANES (an entry naming anything else is
dropped whole); only the top-level KEEP_ON_CRON is lifted, never the rationalization block's; every other
forbidden token, stay-behind, sender and broker rule still applies; a missing or malformed file = no exceptions.
An exception changes eligibility only — dispatch mode stays whatever the row's dispatch block says (off).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

try:
    from scripts.lib import cron_schedule as _cron
    from scripts.lib.n8n_coordination_gateway import FORBIDDEN_ROUTE_TOKENS as _ROUTE_TOKENS
    from scripts.lib.n8n_coordination_gateway import SECRET_KEYS as _SECRET_WORDS
    from scripts.pipelines.pipeline_manifest import FORBIDDEN_COMMAND_TOKENS as _COMMAND_TOKENS
except ImportError:                                        # imported as lib.lane_dispatch
    from lib import cron_schedule as _cron  # type: ignore
    from lib.n8n_coordination_gateway import FORBIDDEN_ROUTE_TOKENS as _ROUTE_TOKENS  # type: ignore
    from lib.n8n_coordination_gateway import SECRET_KEYS as _SECRET_WORDS  # type: ignore
    from pipelines.pipeline_manifest import FORBIDDEN_COMMAND_TOKENS as _COMMAND_TOKENS  # type: ignore

DISPATCH_MODES = ("off", "dry_run", "live")
DISPATCH_CLASSES = ("monitor", "report", "hygiene", "pipeline", "heavy", "llm", "ingest", "send", "learn")
#: Refused until AGENTS rules R1/R2 (E §3) are ratified (design 02 §2).
RATIFICATION_GATED_CLASSES = frozenset({"llm", "ingest", "send", "learn"})
#: The classes a dispatch block may carry before R1 (AGENTS 4.3.0) is ACTIVE; see permitted_classes_now().
PERMITTED_CLASSES_PRE_R1 = frozenset(DISPATCH_CLASSES) - RATIFICATION_GATED_CLASSES

# ── R1 (AGENTS.md 4.3.0 §23.18; operator rulings 2026-10-10 ~00:20 ET) ──────────────────────────
#: The classes R1 admits — ingest writers, governed LLM jobs, learning/memory writers. `send` stays gated (R2).
R1_ADMITTED_CLASSES = frozenset({"ingest", "llm", "learn"})
#: Policy status of R1. "PROPOSED" until the operator ratifies AGENTS.md 4.3.0; only the ratifying edit flips it,
#: and tests/test_agents_policy_4_3_0_r1_classes.py fails unless it matches the 4.3.0 version-history row.
R1_POLICY_VERSION = "4.3.0"
R1_STATUS = "PROPOSED"
#: Classes a dispatch block may carry once R1 is ACTIVE (each R1 class still needs r1_class_admission).
PERMITTED_CLASSES_R1 = PERMITTED_CLASSES_PRE_R1 | R1_ADMITTED_CLASSES
#: The ladder stages an R1 row may be at (AGENTS §23.11/§23.12 scheduler.stage). Anything else is refused.
R1_STAGES = frozenset({"shadow", "canary", "cutover"})
#: The only route a governed LLM job may use for model calls (AGENTS §23.4, §9.2, §12; `cio-governed-bridge`).
GOVERNED_LLM_ROUTE = "cio-governed-bridge"
#: Ruling 3: no broker credential in an admitted lane's environment. Name fragments, matched on env_names.
BROKER_CREDENTIAL_ENV_FRAGMENTS = ("SCHWAB", "ALPACA", "SNAPTRADE", "MOOMOO", "IBKR", "FUTU", "TRADIER", "BROKER")
#: argv tokens by which an LLM job would pick its own provider or model (§23.4: capability, never a provider).
LLM_PROVIDER_ARGV_TOKENS = ("--model", "--provider", "--lane", "anthropic", "openai", "api_key", "--api-key")
_RECEIPT_SIGNAL = re.compile(r"^data/runtime/[A-Za-z0-9._-]+_last\.json$")
#: Long-running flags: an R1 lane is a scheduled run, never a daemon (AGENTS §23.14 "not a daemon").
R1_DAEMON_ARGV_TOKENS = ("--daemon", "--loop", "--forever", "--watch", "--serve")
DISPATCH_WAVES = ("W0", "W1", "W2", "W3", "W4", "W5")
DISPATCH_TZ = "America/New_York"
TRIGGER_SOURCES = ("run_done", "receipt", "cio_bus", "ledger_event", "outbox")
DIGEST_ROLES = ("preparer", "sender")
WATCH_SEVERITIES = ("P1", "P2", "P3")

#: Issue codes. The first four align with due-response.schema.json errors[].code.
ISSUE_BAD_CRON = "bad_cron"
ISSUE_UNKNOWN_RETRY_POLICY = "unknown_retry_policy"
ISSUE_CLASS_NOT_PERMITTED = "class_not_permitted"
ISSUE_AFTER_UNKNOWN_LANE = "after_unknown_lane"
ISSUE_BAD_BLOCK = "bad_block"
ISSUE_FORBIDDEN_LANE = "forbidden_lane"

#: Words neither source list spells out: secret renderers, stops and positions, guard, deploy, senders, order
#: submission (submit — e.g. MOMENTUM_SCALP_VALIDATION_SUBMIT=1, --submit-validation), and the broker/execution
#: names (schwab, alpaca, snaptrade, moomoo, ibkr, paper, executor) that AGENTS §0 rails 1-2 and the allowlist's
#: `never` list keep off n8n.
EXTRA_FORBIDDEN_WORDS = (
    "secret", "stop", "position", "guard", "deploy", "sender", "sm-render", "sm_render", "smrender",
    "schwab", "alpaca", "snaptrade", "moomoo", "ibkr", "paper", "executor", "submit",
    # 4.3.0 (R1): secret renderers the 4.1.0 policy test names but this list missed (render_env.py was eligible).
    "render_env", "rotation_daemon", "bitwarden",
)
#: Name kept for callers of the first cut (it is now matched by word, not substring).
EXTRA_FORBIDDEN_SUBSTRINGS = EXTRA_FORBIDDEN_WORDS
#: The gateway's route tokens.
FORBIDDEN_LANE_TOKENS = frozenset(_ROUTE_TOKENS)
#: pipeline_manifest's excluded scripts, the gateway's secret words, and the extras.
FORBIDDEN_LANE_SUBSTRINGS = tuple(_COMMAND_TOKENS) + tuple(sorted(_SECRET_WORDS)) + EXTRA_FORBIDDEN_WORDS
#: Every forbidden token, in report order: route tokens, then script names / secret words / extras.
FORBIDDEN_TOKENS_ALL = tuple(sorted(_ROUTE_TOKENS)) + FORBIDDEN_LANE_SUBSTRINGS
#: Names no ordinary word contains: still matched as substrings of the separator-collapsed text, so
#: `schwabbrokers`, `placeorders`, `twofactor` and `brokerstop` keep blocking.
DISTINCTIVE_SUBSTRINGS = ("schwab", "alpaca", "snaptrade", "moomoo", "ibkr", "broker", "totp", "twofactor",
                          "placeorder", "smrender", "liveflag", "brokertruth")
#: Words that, glued directly to a forbidden word with no separator, still name the forbidden thing
#: (liveorders, trailingstop, positionsync, stopmanager). Explicit and small on purpose: `re`+deploy,
#: `rec`+order(er), stop+`lights` and synthe+`sizer` are not in it.
COMPOUND_PARTNERS = frozenset({
    "live", "place", "trail", "trailing", "sync", "cancel", "manager", "mgr", "limit", "hard", "auto", "smart",
    "worker", "runner", "daemon", "reconcile", "reconciler", "supervisor", "refresh", "replace", "modify",
    "bracket", "oco", "loss", "route", "router", "submit", "send", "write", "writer", "render", "sizer",
})
_WORD_SUFFIXES = ("", "s", "es", "ed", "d", "er", "ers", "r", "rs", "ing", "ion", "ions", "ment", "ments",
                  "or", "ors", "age", "ages")
_E_DROP_SUFFIXES = ("ing", "ion", "ions", "or", "ors", "ed", "er", "ers")
_DOUBLING = re.compile(r"[^aeiou][aeiou][bdgkmnprt]$")
_FILE_EXTS = frozenset({"py", "sh"})
#: Registry markers (B1 reconcile, PR #1597) that pin a lane to cron/systemd whatever its dispatch block says.
KEEP_ON_CRON = "KEEP_ON_CRON"
DEFAULT_RUN_ALLOWLIST = Path(__file__).resolve().parents[2] / "config" / "n8n_run_allowlist.json"
DEFAULT_POLICY_EXCEPTIONS = Path(__file__).resolve().parents[2] / "config" / "lane_dispatch_policy_exceptions.json"
DEFAULT_LLM_PROCESS_REGISTRY = Path(__file__).resolve().parents[2] / "config" / "llm_process_registry.json"
#: Safety ceiling on config/lane_dispatch_policy_exceptions.json: the only forbidden tokens a lane may ever be
#: exempted from. market_day_gate.sh is a market-calendar gate, not a broker/order/stop/secret authority.
EXEMPTIBLE_TOKENS = frozenset({"market_day_gate.sh"})
#: Safety ceiling on which lanes config may ever except (AGENTS 4.0.0 §23.3; operator 2026-10-09 ~18:05 ET).
#: An entry for any other lane is dropped; widening this needs a code change + review, not a config edit.
EXEMPTIBLE_LANES = frozenset({"trade-ai-scalp-live"})
#: The B1 reconciler's stay_on_cron class for a gate token (scripts/reconcile_lane_registry.py, PR #1597).
GATE_STAY_CLASS = "pipeline_excluded_gate"

_CRON_SHAPE = re.compile(r"^\S+ \S+ \S+ \S+ \S+$")
_RETRY_POLICY_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
_RECEIPT_REL = re.compile(r"^data/[A-Za-z0-9._/-]+$")
_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")

_DISPATCH_KEYS = frozenset({"mode", "cron", "tz", "wave", "class", "priority", "retry_policy", "catchup_min",
                            "min_interval_s", "after", "triggers", "sweep_cron", "digest_window", "digest_role"})
_DISPATCH_REQUIRED = ("mode", "cron", "class", "priority", "retry_policy", "wave")
_AFTER_KEYS = frozenset({"lane_id", "same_day", "deadline_min", "soft"})
_TRIGGER_KEYS = frozenset({"source", "lane_id", "receipt_rel", "event_type"})
_WATCH_KEYS = frozenset({"factor", "severity", "max_run_s", "stay_behind", "restart_safe"})


class DispatchBlockError(ValueError):
    """A dispatch or watch block that does not match the schema. `code` is an ISSUE_* value."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class AfterEdge:
    lane_id: str
    same_day: bool = True
    deadline_min: Optional[int] = None
    soft: bool = False


@dataclass(frozen=True)
class Trigger:
    source: str
    lane_id: Optional[str] = None
    receipt_rel: Optional[str] = None
    event_type: Optional[str] = None


@dataclass(frozen=True)
class DispatchBlock:
    mode: str
    cron: tuple[str, ...]
    tz: str
    wave: str
    klass: str
    priority: int
    retry_policy: str
    catchup_min: Optional[int]
    min_interval_s: int
    after: tuple[AfterEdge, ...]
    triggers: tuple[Trigger, ...]
    sweep_cron: tuple[str, ...]
    digest_window: Optional[str]
    digest_role: Optional[str]


@dataclass(frozen=True)
class WatchBlock:
    factor: float = 2.0
    severity: Optional[str] = None
    max_run_s: Optional[int] = None
    stay_behind: bool = False
    restart_safe: bool = False


@dataclass(frozen=True)
class DispatchIssue:
    lane_id: str
    code: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"lane_id": self.lane_id, "code": self.code, "detail": self.detail[:160]}


# ── parsing ──────────────────────────────────────────────────────────────────────────────────────

def _bad(detail: str) -> DispatchBlockError:
    return DispatchBlockError(ISSUE_BAD_BLOCK, detail)


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _int_in(obj: Mapping[str, Any], key: str, lo: int, hi: int, where: str) -> Optional[int]:
    if key not in obj:
        return None
    v = obj[key]
    if not _is_int(v) or not lo <= v <= hi:
        raise _bad(f"{where}.{key} must be an integer {lo}..{hi}, got {v!r}")
    return v


def _bool(obj: Mapping[str, Any], key: str, default: bool, where: str) -> bool:
    v = obj.get(key, default)
    if not isinstance(v, bool):
        raise _bad(f"{where}.{key} must be a boolean, got {v!r}")
    return v


def _str_or_none(obj: Mapping[str, Any], key: str, where: str) -> Optional[str]:
    v = obj.get(key)
    if v is not None and not isinstance(v, str):
        raise _bad(f"{where}.{key} must be a string, got {v!r}")
    return v


def _closed(obj: Any, allowed: frozenset[str], where: str) -> Mapping[str, Any]:
    if not isinstance(obj, dict):
        raise _bad(f"{where} must be an object")
    extra = sorted(set(obj) - allowed)
    if extra:
        raise _bad(f"{where} has unknown key(s) {extra}")
    return obj


def _cron_list(v: Any, max_items: int, where: str) -> tuple[str, ...]:
    if not isinstance(v, list) or len(v) > max_items:
        raise _bad(f"{where} must be a list of at most {max_items} cron strings")
    out = []
    for i, expr in enumerate(v):
        if not isinstance(expr, str) or not _CRON_SHAPE.match(expr):
            raise DispatchBlockError(ISSUE_BAD_CRON, f"{where}[{i}] is not a 5-field cron: {expr!r}")
        try:
            _cron.parse(expr)
        except ValueError as e:
            raise DispatchBlockError(ISSUE_BAD_CRON, f"{where}[{i}] {expr!r}: {e}") from None
        out.append(expr)
    return tuple(out)


def _after(v: Any) -> tuple[AfterEdge, ...]:
    if not isinstance(v, list) or len(v) > 8:
        raise _bad("dispatch.after must be a list of at most 8 edges")
    edges = []
    for i, e in enumerate(v):
        where = f"dispatch.after[{i}]"
        e = _closed(e, _AFTER_KEYS, where)
        lane = e.get("lane_id")
        if not isinstance(lane, str) or not lane:
            raise _bad(f"{where}.lane_id is required")
        edges.append(AfterEdge(lane_id=lane, same_day=_bool(e, "same_day", True, where),
                               deadline_min=_int_in(e, "deadline_min", 1, 720, where),
                               soft=_bool(e, "soft", False, where)))
    return tuple(edges)


def _triggers(v: Any) -> tuple[Trigger, ...]:
    if not isinstance(v, list) or len(v) > 8:
        raise _bad("dispatch.triggers must be a list of at most 8 triggers")
    out = []
    for i, t in enumerate(v):
        where = f"dispatch.triggers[{i}]"
        t = _closed(t, _TRIGGER_KEYS, where)
        if t.get("source") not in TRIGGER_SOURCES:
            raise _bad(f"{where}.source must be one of {TRIGGER_SOURCES}, got {t.get('source')!r}")
        rel = _str_or_none(t, "receipt_rel", where)
        if rel is not None and not _RECEIPT_REL.match(rel):
            raise _bad(f"{where}.receipt_rel must be data/<relative path>, got {rel!r}")
        ev = _str_or_none(t, "event_type", where)
        if ev is not None and len(ev) > 80:
            raise _bad(f"{where}.event_type longer than 80")
        out.append(Trigger(source=t["source"], lane_id=_str_or_none(t, "lane_id", where),
                           receipt_rel=rel, event_type=ev))
    return tuple(out)


def parse_dispatch_block(row: Mapping[str, Any]) -> Optional[DispatchBlock]:
    """The row's dispatch block, None when absent. Raises DispatchBlockError when malformed."""
    if "dispatch" not in row or row.get("dispatch") is None:
        return None
    d = _closed(row["dispatch"], _DISPATCH_KEYS, "dispatch")
    missing = [k for k in _DISPATCH_REQUIRED if k not in d]
    if missing:
        raise _bad(f"dispatch missing required key(s) {missing}")
    if d["mode"] not in DISPATCH_MODES:
        raise _bad(f"dispatch.mode must be one of {DISPATCH_MODES}, got {d['mode']!r}")
    tz = d.get("tz", DISPATCH_TZ)
    if tz != DISPATCH_TZ:
        raise _bad(f"dispatch.tz must be {DISPATCH_TZ}, got {tz!r}")
    if d["wave"] not in DISPATCH_WAVES:
        raise _bad(f"dispatch.wave must be one of {DISPATCH_WAVES}, got {d['wave']!r}")
    if d["class"] not in DISPATCH_CLASSES:
        raise _bad(f"dispatch.class must be one of {DISPATCH_CLASSES}, got {d['class']!r}")
    priority = _int_in(d, "priority", 0, 9, "dispatch")
    rp = d["retry_policy"]
    if not isinstance(rp, str) or not _RETRY_POLICY_NAME.match(rp):
        raise _bad(f"dispatch.retry_policy is not a policy name: {rp!r}")
    role = d.get("digest_role")
    if role is not None and role not in DIGEST_ROLES:
        raise _bad(f"dispatch.digest_role must be one of {DIGEST_ROLES}, got {role!r}")
    return DispatchBlock(
        mode=d["mode"],
        cron=_cron_list(d["cron"], 8, "dispatch.cron"),
        tz=tz,
        wave=d["wave"],
        klass=d["class"],
        priority=priority,  # type: ignore[arg-type]  # required, so never None here
        retry_policy=rp,
        catchup_min=_int_in(d, "catchup_min", 1, 1440, "dispatch"),
        min_interval_s=_int_in(d, "min_interval_s", 0, 86400, "dispatch") or 0,
        after=_after(d.get("after", [])),
        triggers=_triggers(d.get("triggers", [])),
        sweep_cron=_cron_list(d.get("sweep_cron", []), 4, "dispatch.sweep_cron"),
        digest_window=_str_or_none(d, "digest_window", "dispatch"),
        digest_role=role,
    )


def parse_watch_block(row: Mapping[str, Any]) -> WatchBlock:
    """The row's watch block; schema defaults when absent. Raises DispatchBlockError when malformed."""
    if row.get("watch") is None:
        return WatchBlock()
    w = _closed(row["watch"], _WATCH_KEYS, "watch")
    factor = w.get("factor", 2.0)
    if isinstance(factor, bool) or not isinstance(factor, (int, float)) or not 1.0 <= float(factor) <= 6.0:
        raise _bad(f"watch.factor must be a number 1.0..6.0, got {factor!r}")
    sev = w.get("severity")
    if sev is not None and sev not in WATCH_SEVERITIES:
        raise _bad(f"watch.severity must be one of {WATCH_SEVERITIES}, got {sev!r}")
    return WatchBlock(factor=float(factor), severity=sev,
                      max_run_s=_int_in(w, "max_run_s", 1, 86400, "watch"),
                      stay_behind=_bool(w, "stay_behind", False, "watch"),
                      restart_safe=_bool(w, "restart_safe", False, "watch"))


def dispatch_mode(row: Mapping[str, Any]) -> str:
    """"off" when the block is absent or unparseable (fail closed); otherwise the declared mode.

    This does NOT apply the forbidden-token rule: callers that run anything use dispatchable(row)."""
    try:
        block = parse_dispatch_block(row)
    except DispatchBlockError:
        return "off"
    return block.mode if block else "off"


# ── forbidden-token rule ─────────────────────────────────────────────────────────────────────────

_ALLOWLIST_CACHE: dict[str, dict[str, str]] = {}


def load_run_allowlist_argv(path: Optional[Path] = None) -> dict[str, str]:
    """lane_id -> the argv the n8n executor would run for that lane (command + dry_run_arg + live_arg, with
    scripts/market_day_gate.sh prepended when market_gate is set), as one string. Read from
    config/n8n_run_allowlist.json; a missing or malformed file yields {} (eligibility then rests on the
    registry fields alone, which are never relaxed by this)."""
    p = Path(path) if path is not None else DEFAULT_RUN_ALLOWLIST
    key = str(p)
    if key in _ALLOWLIST_CACHE:
        return _ALLOWLIST_CACHE[key]
    out: dict[str, str] = {}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    for entry in (doc.get("lanes") or []) if isinstance(doc, dict) else []:
        if not isinstance(entry, dict) or not isinstance(entry.get("lane_id"), str):
            continue
        argv: list[str] = ["scripts/market_day_gate.sh"] if entry.get("market_gate") else []
        for k in ("command", "dry_run_arg", "live_arg"):
            v = entry.get(k)
            if isinstance(v, list):
                argv.extend(str(t) for t in v)
        out[entry["lane_id"]] = " ".join(argv)
    _ALLOWLIST_CACHE[key] = out
    return out


def _command_fields(row: Mapping[str, Any], allowlist_argv: Optional[Mapping[str, str]] = None
                    ) -> list[tuple[str, str]]:
    """Every command-bearing field of the row, lowercased. A string `scheduler` is checked whole; a dict
    scheduler contributes every string value. exec_start/service (systemd rows), command/script, and the lane's
    real argv from the run allowlist are included."""
    sched = row.get("scheduler")
    fields: list[tuple[str, Any]] = [("lane_id", row.get("lane_id"))]
    if isinstance(sched, dict):
        fields.extend((f"scheduler.{k}", v) for k, v in sorted(sched.items()) if isinstance(v, str))
    elif sched is not None:
        fields.append(("scheduler", sched))
    for name in ("exec_start", "service", "command", "script"):
        v = row.get(name)
        fields.append((name, " ".join(map(str, v)) if isinstance(v, (list, tuple)) else v))
    argv_map = load_run_allowlist_argv() if allowlist_argv is None else allowlist_argv
    lane = row.get("lane_id")
    if isinstance(lane, str) and lane in argv_map:
        fields.append(("allowlist.argv", argv_map[lane]))
    return [(name, str(v).lower()) for name, v in fields if v]


def _words(text: str) -> list[str]:
    return [w for w in _TOKEN_SPLIT.split(text.lower()) if w]


def _word_forms(word: str) -> frozenset[str]:
    """`word` and its inflections: orders, stops/stopped, positions, sizing, promotion, deployment."""
    out = {word + s for s in _WORD_SUFFIXES}
    if word.endswith("e"):
        out |= {word[:-1] + s for s in _E_DROP_SUFFIXES}
    if _DOUBLING.search(word):
        out |= {word + word[-1] + s for s in ("ed", "er", "ers", "ing")}
    return frozenset(out)


def _phrase(token: str) -> tuple[str, ...]:
    """A forbidden token as words, a trailing file extension dropped (positions_sync.py -> positions, sync)."""
    words = _words(token)
    while len(words) > 1 and words[-1] in _FILE_EXTS:
        words = words[:-1]
    return tuple(words)


#: (reported token, its words) for every forbidden token.
_PHRASES = tuple((tok, _phrase(tok)) for tok in FORBIDDEN_TOKENS_ALL if _phrase(tok))
#: pipeline_manifest script names, collapsed (schwab_position_sync.py -> schwabpositionsync): substrings.
_SCRIPT_SUBSTRINGS = tuple((tok, "".join(_phrase(tok))) for tok in _COMMAND_TOKENS if _phrase(tok))


def _compound_hit(word: str, forms: frozenset[str]) -> bool:
    """`word` is a forbidden form glued to a COMPOUND_PARTNERS word, either way round (liveorders, positionsync)."""
    for f in forms:
        if len(f) < 3 or len(word) <= len(f):
            continue
        if word.startswith(f) and word[len(f):] in COMPOUND_PARTNERS:
            return True
        if word.endswith(f) and word[: -len(f)] in COMPOUND_PARTNERS:
            return True
    return False


def forbidden_text_hits(text: str) -> list[str]:
    """Every forbidden token in `text` under whole-word / path-segment matching (module docstring), in
    FORBIDDEN_TOKENS_ALL order then the substring rules. [] when clean. The one matcher behind
    forbidden_hits / dispatch_eligible and the §23.14 test mirror."""
    words = _words(text or "")
    if not words:
        return []
    squashed = "".join(words)
    hits: list[str] = []
    for tok, phrase in _PHRASES:
        last = _word_forms(phrase[-1])
        joined = _word_forms("".join(phrase))
        n = len(phrase)
        found = any(w in joined or _compound_hit(w, joined) for w in words)
        if not found and n > 1:
            found = any(tuple(words[i:i + n - 1]) == phrase[:-1] and words[i + n - 1] in last
                        for i in range(len(words) - n + 1))
        if found and tok not in hits:
            hits.append(tok)
    for tok, sub in _SCRIPT_SUBSTRINGS:
        if sub in squashed and tok not in hits:
            hits.append(tok)
    for sub in DISTINCTIVE_SUBSTRINGS:
        if sub in squashed and sub not in hits:
            hits.append(sub)
    return hits


def forbidden_hits(row: Mapping[str, Any], *, allowlist_argv: Optional[Mapping[str, str]] = None
                   ) -> list[tuple[str, str]]:
    """Every (token, field) of the forbidden-token rule that this row trips, in a stable order.

    Whole-word / path-segment matching (forbidden_text_hits): argv words, path segments, flags and env
    assignments are each compared, so `topic_curator` no longer trips `stop` while `positions_sync.py`,
    `placeorders`, `two_factor`, `MOMENTUM_SCALP_VALIDATION_SUBMIT=1` and `bash -c '...'` wrappers all match."""
    hits: list[tuple[str, str]] = []
    for field, text in _command_fields(row, allowlist_argv):
        for tok in forbidden_text_hits(text):
            if (tok, field) not in hits:
                hits.append((tok, field))
    return hits


_EXCEPTIONS_CACHE: dict[str, dict[str, frozenset[str]]] = {}


def load_policy_exceptions(path: Optional[Path] = None) -> dict[str, frozenset[str]]:
    """lane_id -> the forbidden tokens that lane is exempted from (config/lane_dispatch_policy_exceptions.json).

    Fail closed: a missing/unreadable/malformed file yields {}; an entry without a string lane_id, without a
    non-empty exempt_tokens list, naming any token outside EXEMPTIBLE_TOKENS, or for a lane outside
    EXEMPTIBLE_LANES is dropped whole; a lane listed twice is dropped (ambiguous). Shared by the dispatcher and, after PR #1597, the registry reconciler."""
    p = Path(path) if path is not None else DEFAULT_POLICY_EXCEPTIONS
    key = str(p)
    if key in _EXCEPTIONS_CACHE:
        return _EXCEPTIONS_CACHE[key]
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    entries = doc.get("exceptions") if isinstance(doc, dict) else None
    out: dict[str, frozenset[str]] = {}
    seen: set[str] = set()
    for entry in entries if isinstance(entries, list) else []:
        if not isinstance(entry, dict) or not isinstance(entry.get("lane_id"), str) or not entry["lane_id"]:
            continue
        lane = entry["lane_id"]
        toks = entry.get("exempt_tokens")
        if lane in seen:
            out.pop(lane, None)
            continue
        seen.add(lane)
        if not isinstance(toks, list) or not toks or not all(isinstance(t, str) for t in toks):
            continue
        if not set(toks) <= EXEMPTIBLE_TOKENS:
            continue
        if lane not in EXEMPTIBLE_LANES:
            continue
        out[lane] = frozenset(toks)
    _EXCEPTIONS_CACHE[key] = out
    return out


def _exempt_tokens(row: Mapping[str, Any], exceptions: Optional[Mapping[str, frozenset[str]]]) -> frozenset[str]:
    lane = row.get("lane_id")
    table = load_policy_exceptions() if exceptions is None else exceptions
    if not isinstance(lane, str) or lane not in EXEMPTIBLE_LANES:
        return frozenset()
    return frozenset(table.get(lane) or ()) & EXEMPTIBLE_TOKENS


def _gate_marker_exempt(row: Mapping[str, Any], exempt: frozenset[str]) -> bool:
    """True only when the row's stay_on_cron marker is the B1 gate class naming an exempted token."""
    mark = row.get("stay_on_cron")
    return (bool(exempt) and isinstance(mark, dict) and mark.get("class") == GATE_STAY_CLASS
            and mark.get("token") in exempt)


def _keep_on_cron(row: Mapping[str, Any], *, lift_top_level: bool = False) -> bool:
    """KEEP_ON_CRON at the row's top level (B1-forced) or in its rationalization block. The policy exception may
    lift only the top-level one (the reconciler forces it from the gate marker); a KEEP_ON_CRON inside the
    rationalization block is an independent F-review verdict and always blocks."""
    rat = row.get("rationalization")
    top = row.get("recommendation") == KEEP_ON_CRON and not lift_top_level
    return top or (isinstance(rat, dict) and rat.get("recommendation") == KEEP_ON_CRON)


def dispatch_eligible(row: Mapping[str, Any], *, allowlist_argv: Optional[Mapping[str, str]] = None,
                      exceptions: Optional[Mapping[str, frozenset[str]]] = None) -> tuple[bool, str]:
    """(eligible, reason). Never eligible: a stay_on_cron or KEEP_ON_CRON row (B1 reconcile markers), a
    stay-behind row, or any forbidden token in the lane id, scheduler, exec_start/service, command/script or
    the lane's run-allowlist argv.

    Independent of the dispatch block: a block saying `live` cannot make a forbidden lane eligible. Callers
    that RUN anything use dispatchable(row), which also requires mode != off.

    `exceptions` (default: config/lane_dispatch_policy_exceptions.json) lifts ONLY the listed EXEMPTIBLE_TOKENS
    hits for a lane in EXEMPTIBLE_LANES, and the B1 gate-class stay_on_cron marker (with the top-level KEEP_ON_CRON
    it forces; never the rationalization block's) naming one of them. Any other hit or marker still blocks; the reason then names it."""
    exempt = _exempt_tokens(row, exceptions)
    gate_exempt = _gate_marker_exempt(row, exempt)
    if row.get("stay_on_cron") not in (None, False, {}, "") and not gate_exempt:
        return False, "stay_on_cron"
    if _keep_on_cron(row, lift_top_level=gate_exempt):
        return False, "keep_on_cron"
    try:
        watch = parse_watch_block(row)
    except DispatchBlockError as e:
        return False, f"bad_watch_block:{e.detail}"
    if watch.stay_behind:
        return False, "stay_behind"
    all_hits = forbidden_hits(row, allowlist_argv=allowlist_argv)
    hits = [h for h in all_hits if h[0] not in exempt]
    if hits:
        tok, field = hits[0]
        return False, f"forbidden_token:{tok}@{field}"
    used = sorted({h[0] for h in all_hits} | ({row["stay_on_cron"]["token"]} if gate_exempt else set()))
    if used:
        return True, "eligible:policy_exception:" + ",".join(used)
    return True, "eligible"


def dispatchable(row: Mapping[str, Any], *, allowlist_argv: Optional[Mapping[str, str]] = None,
                 exceptions: Optional[Mapping[str, frozenset[str]]] = None) -> bool:
    """The one check a dispatcher/executor needs: dispatch mode is not off (block present and well-formed)
    AND the row is dispatch-eligible."""
    return dispatch_mode(row) != "off" and dispatch_eligible(
        row, allowlist_argv=allowlist_argv, exceptions=exceptions)[0]


# ── R1 class admission (AGENTS.md 4.3.0 §23.18) ──────────────────────────────────────────────────

def permitted_classes_now(status: Optional[str] = None) -> frozenset[str]:
    """PERMITTED_CLASSES_PRE_R1 until R1 is ACTIVE, then PERMITTED_CLASSES_R1. `status` overrides R1_STATUS
    (tests only)."""
    return PERMITTED_CLASSES_R1 if (status or R1_STATUS) == "ACTIVE" else PERMITTED_CLASSES_PRE_R1


_ENTRIES_CACHE: dict[str, dict[str, dict[str, Any]]] = {}


def load_run_allowlist_entries(path: Optional[Path] = None) -> dict[str, dict[str, Any]]:
    """lane_id -> the whole config/n8n_run_allowlist.json entry. Missing/malformed file -> {} (fail closed: an R1
    row with no entry is refused)."""
    p = Path(path) if path is not None else DEFAULT_RUN_ALLOWLIST
    key = str(p)
    if key not in _ENTRIES_CACHE:
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = {}
        lanes = doc.get("lanes") if isinstance(doc, dict) else None
        _ENTRIES_CACHE[key] = {e["lane_id"]: e for e in (lanes if isinstance(lanes, list) else [])
                               if isinstance(e, dict) and isinstance(e.get("lane_id"), str)}
    return _ENTRIES_CACHE[key]


def load_llm_process_ids(path: Optional[Path] = None) -> frozenset[str]:
    """Registered process ids in config/llm_process_registry.json. Missing/malformed -> empty (fail closed)."""
    p = Path(path) if path is not None else DEFAULT_LLM_PROCESS_REGISTRY
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    procs = doc.get("processes") if isinstance(doc, dict) else None
    return frozenset(str(x["id"]) for x in (procs if isinstance(procs, list) else [])
                     if isinstance(x, dict) and x.get("id"))


def receipt_signal_path(row: Mapping[str, Any]) -> Optional[str]:
    """The LaneRunReceipt@v1 path when the row's output_signal is that receipt (scripts/lib/lane_last_receipt.py:
    json_key `ok_at` on data/runtime/<lane>_last.json), else None. A log-file mtime is not a receipt (§0 rail 8)."""
    sig = row.get("output_signal")
    if not isinstance(sig, dict) or sig.get("kind") != "json_key" or sig.get("key") != "ok_at":
        return None
    path = sig.get("path")
    return path if isinstance(path, str) and _RECEIPT_SIGNAL.match(path) else None


def r1_class_admission(row: Mapping[str, Any], entry: Optional[Mapping[str, Any]] = None, *,
                       status: Optional[str] = None, process_ids: Optional[Iterable[str]] = None,
                       allowlist_argv: Optional[Mapping[str, str]] = None,
                       exceptions: Optional[Mapping[str, frozenset[str]]] = None) -> tuple[bool, str]:
    """AGENTS.md 4.3.0 §23.18: may this row's dispatch class run from the dispatcher? (ok, reason).

    Classes outside R1_ADMITTED_CLASSES are answered by PERMITTED_CLASSES_PRE_R1 alone (`send` stays refused).
    An R1 class (ingest / llm / learn) is admitted only when ALL hold:
      * R1 is ACTIVE (R1_STATUS, flipped only by the ratifying edit);
      * dispatch_eligible(row): the forbidden-token rule, stay-behind and KEEP_ON_CRON are never relaxed by a class;
      * not a daemon: no R1_DAEMON_ARGV_TOKENS flag in the allowlist argv, no systemd service (non-timer) scheduler;
      * scheduler.expression == "dispatcher" and scheduler.stage in {shadow, canary, cutover};
      * an allowlist entry with a non-empty dry_run_arg (the shadow step needs a real dry run);
      * output_signal is the LaneRunReceipt@v1 (json_key ok_at on data/runtime/<x>_last.json) and the allowlist
        entry's output_signal is the same path;
      * no broker credential name in the entry's env_names (ruling 3);
      * llm only: entry.llm_route == {"via": "cio-governed-bridge", "process_id": <registered process>} and no argv
        token that picks a provider or model (§23.4). The spend cap (§12) and deferral ride the bridge."""
    lane = str(row.get("lane_id") or "?")
    try:
        block = parse_dispatch_block(row)
    except DispatchBlockError as e:
        return False, f"bad_block:{e.detail}"
    if block is None:
        return False, "no_dispatch_block"
    klass = block.klass
    if klass not in R1_ADMITTED_CLASSES:
        return (True, "pre_r1_class") if klass in PERMITTED_CLASSES_PRE_R1 else (False, f"class_gated:{klass}")
    if (status or R1_STATUS) != "ACTIVE":
        return False, f"r1_not_ratified:{klass} (AGENTS {R1_POLICY_VERSION} is {status or R1_STATUS})"
    ok, why = dispatch_eligible(row, allowlist_argv=allowlist_argv, exceptions=exceptions)
    if not ok:
        return False, f"ineligible:{why}"
    sched = row.get("scheduler") if isinstance(row.get("scheduler"), dict) else {}
    if sched.get("expression") != "dispatcher":
        return False, "not_a_dispatcher_row"
    if sched.get("stage") not in R1_STAGES:
        return False, f"stage:{sched.get('stage')!r} not in shadow/canary/cutover"
    if entry is None:
        entry = load_run_allowlist_entries().get(lane)
    if not isinstance(entry, Mapping):
        return False, "not_allowlisted"
    for key in ("command", "dry_run_arg", "live_arg"):
        for tok in entry.get(key) or []:
            if any(str(tok) == d or str(tok).startswith(d + "=") for d in R1_DAEMON_ARGV_TOKENS):
                return False, f"daemon_flag:{tok}"
    if any((".service" in str(v) and ".timer" not in str(v)) or "Restart=always" in str(v) for v in sched.values()):
        return False, "systemd_service_lane"
    dry = entry.get("dry_run_arg")
    if not isinstance(dry, list) or not dry or not all(isinstance(t, str) and t for t in dry):
        return False, "no_dry_run_arg"
    receipt = receipt_signal_path(row)
    if receipt is None:
        return False, "output_signal_not_a_lane_receipt"
    if entry.get("output_signal") != receipt:
        return False, f"allowlist_output_signal_mismatch:{entry.get('output_signal')!r}"
    for name in entry.get("env_names") or []:
        up = str(name).upper()
        if any(frag in up for frag in BROKER_CREDENTIAL_ENV_FRAGMENTS):
            return False, f"broker_credential_env:{name}"
    if klass == "llm":
        route = entry.get("llm_route")
        if not isinstance(route, Mapping) or route.get("via") != GOVERNED_LLM_ROUTE:
            return False, f"llm_route_not_governed_bridge:{route!r}"
        pid = route.get("process_id")
        known = frozenset(process_ids) if process_ids is not None else load_llm_process_ids()
        if not isinstance(pid, str) or pid not in known:
            return False, f"llm_process_unregistered:{pid!r}"
        for key in ("command", "dry_run_arg", "live_arg"):
            for tok in entry.get(key) or []:
                low = str(tok).lower()
                hit = next((p for p in LLM_PROVIDER_ARGV_TOKENS if p in low), None)
                if hit:
                    return False, f"llm_argv_selects_provider:{hit}"
    return True, f"r1_admitted:{klass}"


# ── validation ───────────────────────────────────────────────────────────────────────────────────

def validate_dispatch_block(row: Mapping[str, Any], *, known_lane_ids: Optional[Iterable[str]] = None,
                            retry_policy_names: Optional[Iterable[str]] = None,
                            permitted_classes: Optional[Iterable[str]] = None) -> list[DispatchIssue]:
    """Every issue with the row's dispatch/watch blocks. [] when both are absent or clean.

    known_lane_ids / retry_policy_names: None skips that cross-check (no policy file exists yet).
    permitted_classes: None = permitted_classes_now() (PRE_R1 until AGENTS 4.3.0 is ACTIVE). A wider set passed by
    a caller never waives R1: an ingest/llm/learn block must also pass r1_class_admission (R1 ACTIVE included)."""
    if permitted_classes is None:
        permitted_classes = permitted_classes_now()
    lane = str(row.get("lane_id") or "?")
    issues: list[DispatchIssue] = []
    try:
        parse_watch_block(row)
    except DispatchBlockError as e:
        issues.append(DispatchIssue(lane, e.code, e.detail))
    try:
        block = parse_dispatch_block(row)
    except DispatchBlockError as e:
        return issues + [DispatchIssue(lane, e.code, e.detail)]
    if block is None:
        return issues
    if retry_policy_names is not None and block.retry_policy not in set(retry_policy_names):
        issues.append(DispatchIssue(lane, ISSUE_UNKNOWN_RETRY_POLICY, f"retry_policy {block.retry_policy!r}"))
    if block.klass not in set(permitted_classes):
        issues.append(DispatchIssue(lane, ISSUE_CLASS_NOT_PERMITTED,
                                    f"class {block.klass!r} is refused until AGENTS R1/R2 are ratified"
                                    if block.klass in RATIFICATION_GATED_CLASSES else f"class {block.klass!r}"))
    elif block.klass in R1_ADMITTED_CLASSES:
        ok, why = r1_class_admission(row)
        if not ok:
            issues.append(DispatchIssue(lane, ISSUE_CLASS_NOT_PERMITTED, f"class {block.klass!r} (R1): {why}"))
    if known_lane_ids is not None:
        known = set(known_lane_ids)
        for i, edge in enumerate(block.after):
            if edge.lane_id not in known or edge.lane_id == lane:
                issues.append(DispatchIssue(lane, ISSUE_AFTER_UNKNOWN_LANE, f"after[{i}].lane_id {edge.lane_id!r}"))
        for i, trig in enumerate(block.triggers):
            if trig.source == "run_done" and (trig.lane_id not in known or trig.lane_id == lane):
                issues.append(DispatchIssue(lane, ISSUE_AFTER_UNKNOWN_LANE,
                                            f"triggers[{i}] run_done lane_id {trig.lane_id!r}"))
    if block.mode != "off":
        ok, why = dispatch_eligible(row)
        if not ok:
            issues.append(DispatchIssue(lane, ISSUE_FORBIDDEN_LANE, f"mode {block.mode} on an ineligible lane: {why}"))
    return issues


def registry_dispatch_errors(reg: Mapping[str, Any], *,
                             retry_policy_names: Optional[Iterable[str]] = None) -> list[str]:
    """check_lane_registry hook: one line per dispatch/watch issue across the registry."""
    rows = [r for r in (reg.get("lanes") or []) if isinstance(r, dict)]
    known = {str(r.get("lane_id")) for r in rows}
    out = []
    for r in rows:
        for issue in validate_dispatch_block(r, known_lane_ids=known, retry_policy_names=retry_policy_names):
            out.append(f"{issue.lane_id}: dispatch {issue.code}: {issue.detail}")
    return out
