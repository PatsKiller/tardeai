"""The four preconditions for the CIO persistent spine, checked not asserted.

Slice A minted InstrumentRecord@v1. Slice B rehydrated it into the gate. This
slice answers the only question that matters before anything is built on top:
**is the spine actually load-bearing right now?**

Four preconditions, and each one is a claim about the LIVE tree, not a wish:

  S0_ATTACH_REHYDRATE   an operator turn lands on the RECORD, carries its
                        plan_id, and a later wake reads it back
  CC_NARRATIVE_NO_PING  the Command Center shows a non-SCHD held narrative and
                        the cash letter, and sends no Telegram doing it
  CRITIQUE_PERSISTED    a Grok critique attach OR reject is written to a record
  DUST_CASH_REFUSED     dust and cash-as-a-ticker cannot mint or fire

Three verdicts, not two. A board that reports RED when it was simply pointed at
the wrong tree is worse than no board, because the next agent spends an hour
fixing something that was never broken. Many CIO stores use RELATIVE paths
(`data/cio/...`) and therefore follow the CWD; four separate bugs in one day came
from that. So every record-dependent check is gated behind `probe_root`, and a
root that carries no CIO data yields CANNOT_VERIFY with the resolved path
printed, never RED.

The board also PRINTS the live notify rails rather than asserting them. The
original spine spec said "notify is off, do not lift INTERDICT"; the operator has
since turned Telegram on (CIO_SITUATION_NOTIFY=1, CIO_TELEGRAM_INTERDICT=0,
`situation_notify_telegram: true`, bar narrowed to S6 only). A board that
restates the stale pin instead of reading /proc and the policy file would be
lying about its own rails. It reads. It never writes.

READ_ONLY_ADVISORY. MBI_BEHAVIOR=0: this module inspects records, plans, config
and one HTTP payload. It mints nothing, persists nothing, sends nothing.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Iterable, Optional

from scripts.lib.cio_instrument_record import (
    DUST_MAX_MARKET_VALUE_USD,
    NON_INSTRUMENT_SYMBOLS,
    InstrumentRecordStore,
    is_mintable,
    parse_subject_key,
)
from scripts.lib.cio_rehydrate import gate_input_from_record

SCHEMA = "CIOPreconditionsBoard@v1"
AUTHORITY = "READ_ONLY_ADVISORY"
MBI_BEHAVIOR = 0
MBI_COGNITION = 0

GREEN = "GREEN"
RED = "RED"
CANNOT_VERIFY = "CANNOT_VERIFY"

# Root probe verdicts. Only ROOT_OK lets a record check reach GREEN or RED.
ROOT_OK = "ROOT_OK"
ROOT_NO_CIO_DIR = "ROOT_NO_CIO_DIR"
ROOT_NO_RECORD_STORE = "ROOT_NO_RECORD_STORE"
ROOT_EMPTY_STORE = "ROOT_EMPTY_STORE"

RECORDS_REL = Path("data/cio/cio_instrument_records.jsonl")
POLICY_REL = Path("config/cio_llm_policy.yaml")

CHECK_IDS = (
    "S0_ATTACH_REHYDRATE",
    "CC_NARRATIVE_NO_PING",
    "CRITIQUE_PERSISTED",
    "DUST_CASH_REFUSED",
)

# Outcomes cio_rehydrate writes when an artifact (a Grok critique among them)
# lands on a record. Their presence is the persist; their absence is the RED.
ATTACH_OUTCOMES = {"attached", "valid", "accepted", "ok", "pass", "passed"}
REJECT_OUTCOMES = {"rejected", "reject", "failed", "execution_language"}

# Substrings that identify a critique artifact regardless of which desk wrote it.
CRITIQUE_MARKERS = ("grok", "critique", "criticism", "devils_advocate", "red_team")

# Enough of a narrative to be a fingerprint, short enough to survive the
# reformatting a surface legitimately does (truncation, prefixing, escaping).
NARRATIVE_FINGERPRINT_CHARS = 48

# Modules that touch the spine but are NOT a live wake reading a record back:
# the libraries themselves, the one-shot migrator, the store registry, this
# board, and tests.
_NON_WAKE_CONSUMERS = {
    "scripts/lib/cio_instrument_record.py",
    "scripts/lib/cio_rehydrate.py",
    "scripts/lib/cio_preconditions_board.py",
    "scripts/lib/canonical_store_registry.py",
    "scripts/cio_migrate_instrument_records.py",
    "scripts/cio_preconditions_board.py",
}


# ── root probe ─────────────────────────────────────────────────────────────

def probe_root(root: Path | str) -> dict[str, Any]:
    """Is this tree one where the record store can be read at all?

    Returns the RESOLVED store path in every branch. When a check comes back
    CANNOT_VERIFY the next question is always "which file did you look at?",
    and answering it in the same breath is the difference between a two-minute
    correction and an hour chasing a store that was never missing.
    """
    root_path = Path(root).resolve()
    cio_dir = root_path / "data" / "cio"
    store_path = root_path / RECORDS_REL
    resolved = str(store_path.resolve()) if store_path.exists() else str(store_path)

    out: dict[str, Any] = {
        "root": str(root_path),
        "cwd": os.getcwd(),
        "store_path": str(store_path),
        "store_path_resolved": resolved,
        "cio_dir_exists": cio_dir.is_dir(),
        "store_exists": store_path.is_file(),
        "rows": 0,
        "subjects": 0,
    }

    if not cio_dir.is_dir():
        out["verdict"] = ROOT_NO_CIO_DIR
        out["reason"] = (
            f"no data/cio under {root_path} — this tree carries no CIO state. "
            f"Re-run with --root pointing at the live release "
            f"(/home/johnclaw/trade-ai-releases/portfolio-server/CURRENT).")
        return out

    if not store_path.is_file():
        out["verdict"] = ROOT_NO_RECORD_STORE
        out["reason"] = (
            f"data/cio exists but {RECORDS_REL} does not, at {resolved}. Either "
            f"the root is wrong or the store was never migrated.")
        return out

    rows = 0
    subjects: set[str] = set()
    try:
        with open(store_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rows += 1
                try:
                    key = json.loads(line).get("subject_key")
                except Exception:                                # noqa: BLE001
                    continue
                if key:
                    subjects.add(str(key))
    except OSError as exc:
        out["verdict"] = ROOT_NO_RECORD_STORE
        out["reason"] = f"{resolved} unreadable: {exc}"
        return out

    out["rows"] = rows
    out["subjects"] = len(subjects)
    if not subjects:
        out["verdict"] = ROOT_EMPTY_STORE
        out["reason"] = (
            f"{resolved} holds {rows} row(s) and 0 subjects — an empty store "
            f"reads the same as a wrong root, so this is not a RED.")
        return out

    out["verdict"] = ROOT_OK
    out["reason"] = f"{len(subjects)} subject(s) from {resolved}"
    return out


def load_records(root: Path | str) -> list[dict[str, Any]]:
    """Read-only projection of the record store under an explicit root.

    The store's DEFAULT_PATH is relative, so it follows the CWD. Passing the
    root in explicitly is the whole reason this board can be trusted from a
    worktree that has no data/ of its own.
    """
    return InstrumentRecordStore(Path(root) / RECORDS_REL).all()


def _cannot_verify(check_id: str, title: str, probe: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": check_id,
        "title": title,
        "status": CANNOT_VERIFY,
        "reason": probe.get("reason") or "root probe failed",
        "root_verdict": probe.get("verdict"),
        "store_path_resolved": probe.get("store_path_resolved"),
        "facts": {},
    }


# ── check 1: S0 attach + rehydrate ─────────────────────────────────────────

def check_s0_attach_rehydrate(
    records: Iterable[dict[str, Any]],
    *,
    probe: Optional[dict[str, Any]] = None,
    wake_consumers: Optional[list[str]] = None,
) -> dict[str, Any]:
    """An operator turn on the RECORD, carrying plan_id, readable by a later wake.

    Attaching a turn to the PLAN alone is what lost the SCHD defer: the plan
    closed and the disposition went with it. So three things must hold, and all
    three are checked separately because they fail for different reasons:

      1. the turn is on the record and carries a plan_id
      2. the turn moved cognition (a stored turn that changed no question is a
         log line, not a memory)
      3. `gate_input_from_record` hands that plan_id and eligibility back — the
         read-back a later wake performs
    """
    title = "S0 attach + rehydrate (operator turn on the record, read back)"
    if probe and probe.get("verdict") != ROOT_OK:
        return _cannot_verify("S0_ATTACH_REHYDRATE", title, probe)

    with_turn: list[str] = []
    with_plan_id: list[str] = []
    moved_cognition: list[str] = []
    read_back_ok: list[dict[str, Any]] = []

    for rec in records:
        turn = rec.get("last_operator_turn") or {}
        if not turn:
            continue
        key = str(rec.get("subject_key") or "?")
        with_turn.append(key)
        plan_id = turn.get("plan_id")
        if not plan_id:
            continue
        with_plan_id.append(key)

        if rec.get("next_research_question") or rec.get("next_eligible_at") or (
                rec.get("cc_narrative") or {}).get("what"):
            moved_cognition.append(key)
        else:
            continue

        # The read-back. A plan supplies this wake's facts; the record must
        # supply the memory, and where they disagree the record wins.
        gate_input = gate_input_from_record(rec, plan={"material": True})
        if (gate_input.get("plan_id") == plan_id
                and gate_input.get("next_eligible_at") == rec.get("next_eligible_at")):
            read_back_ok.append({
                "subject_key": key,
                "plan_id": plan_id,
                "intent": turn.get("intent"),
                "note": turn.get("note"),
                "next_eligible_at": rec.get("next_eligible_at"),
                "next_research_question": rec.get("next_research_question"),
            })

    facts = {
        "records_with_operator_turn": len(with_turn),
        "records_with_plan_id": len(with_plan_id),
        "records_whose_turn_moved_cognition": len(moved_cognition),
        "read_back_ok_n": len(read_back_ok),
        "read_back_examples": read_back_ok[:3],
        "subjects_with_turn": with_turn[:10],
        "product_wake_consumers": list(wake_consumers or []),
    }

    if read_back_ok:
        caveat = None
        if wake_consumers is not None and not wake_consumers:
            caveat = (
                "read-back verified through cio_rehydrate.gate_input_from_record; "
                "NO scheduled product wake imports it yet, so this is a working "
                "mechanism, not yet a working loop")
        return {
            "id": "S0_ATTACH_REHYDRATE", "title": title, "status": GREEN,
            "reason": (f"{len(read_back_ok)} record(s) carry an operator turn with a "
                       f"plan_id and hand it back through the gate input"),
            "caveat": caveat, "facts": facts,
        }

    if not with_turn:
        reason = "no record carries last_operator_turn — S0 never attached"
    elif not with_plan_id:
        reason = (f"{len(with_turn)} record(s) carry a turn but none carries a "
                  f"plan_id — the turn cannot be traced to the plan that raised it")
    elif not moved_cognition:
        reason = (f"{len(with_plan_id)} turn(s) carry a plan_id but moved no "
                  f"cognition — stored, not remembered")
    else:
        reason = ("the turn is on the record but gate_input_from_record does not "
                  "return its plan_id/eligibility — the read-back is broken")
    return {"id": "S0_ATTACH_REHYDRATE", "title": title, "status": RED,
            "reason": reason, "caveat": None, "facts": facts}


# ── check 2: CC narrative without a ping ───────────────────────────────────

def _fingerprint(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()[:NARRATIVE_FINGERPRINT_CHARS]


def _payload_text(payload: Any) -> str:
    try:
        return re.sub(r"\s+", " ", json.dumps(payload, default=str))
    except Exception:                                            # noqa: BLE001
        return re.sub(r"\s+", " ", str(payload))


def check_cc_narrative_without_ping(
    records: Iterable[dict[str, Any]],
    home: Optional[dict[str, Any]],
    *,
    probe: Optional[dict[str, Any]] = None,
    home_error: Optional[str] = None,
) -> dict[str, Any]:
    """A non-SCHD held narrative AND the cash letter reach the CC, silently.

    "Silently" is half the precondition and the easy half to lose: the whole
    point of the record is that the desk can say something in the Command
    Center without paying for it with a Telegram push. So the ping facts are
    read from the same payload, not assumed.

    SCHD is excluded deliberately. It is the one subject with an operator defer
    and a hand-built narrative; proving the pipe with SCHD would prove only that
    the exception works.
    """
    title = "CC shows a non-SCHD held narrative + the cash letter, no ping"
    if probe and probe.get("verdict") != ROOT_OK:
        return _cannot_verify("CC_NARRATIVE_NO_PING", title, probe)
    if home is None:
        return {
            "id": "CC_NARRATIVE_NO_PING", "title": title, "status": CANNOT_VERIFY,
            "reason": (f"the live CIO home payload could not be read "
                       f"({home_error or 'no payload'}) — a surface that cannot be "
                       f"fetched is unverified, not broken"),
            "facts": {},
        }

    blob = _payload_text(home)

    held_candidates: list[dict[str, Any]] = []
    held_surfaced: list[dict[str, Any]] = []
    for rec in records:
        kind, name = parse_subject_key(str(rec.get("subject_key") or ""))
        if kind != "HELD" or name.upper() == "SCHD":
            continue
        what = (rec.get("cc_narrative") or {}).get("what") or ""
        fp = _fingerprint(what)
        if not fp:
            continue
        item = {"subject_key": rec.get("subject_key"), "fingerprint": fp}
        held_candidates.append(item)
        if fp in blob:
            held_surfaced.append(item)

    cash_rec = next(
        (r for r in records if str(r.get("subject_key") or "").upper() == "SLEEVE:CASH"),
        None)
    cash_fp = _fingerprint((cash_rec or {}).get("cc_narrative", {}).get("what") or "")
    cash_surfaced = bool(cash_fp) and cash_fp in blob

    notif = home.get("notifications") or {}
    telegram_sent = bool(home.get("telegram_sent") or notif.get("telegram_sent"))
    would_send_any = bool(notif.get("would_send_any"))
    no_ping = (not telegram_sent) and (not would_send_any)

    facts = {
        "held_narrative_candidates_n": len(held_candidates),
        "held_narrative_surfaced_n": len(held_surfaced),
        "held_narrative_surfaced": held_surfaced[:3],
        "held_narrative_candidates": held_candidates[:3],
        "cash_record_present": cash_rec is not None,
        "cash_fingerprint": cash_fp or None,
        "cash_letter_surfaced": cash_surfaced,
        "telegram_sent": telegram_sent,
        "would_send_any": would_send_any,
        "no_ping": no_ping,
        "delivery": home.get("delivery"),
    }

    if held_surfaced and cash_surfaced and no_ping:
        return {"id": "CC_NARRATIVE_NO_PING", "title": title, "status": GREEN,
                "reason": (f"{len(held_surfaced)} non-SCHD held narrative(s) and the "
                           f"cash letter are in the payload; nothing was pushed"),
                "caveat": None, "facts": facts}

    missing: list[str] = []
    if not held_candidates:
        missing.append("no non-SCHD HELD record carries a narrative at all")
    elif not held_surfaced:
        missing.append(
            f"{len(held_candidates)} non-SCHD held narrative(s) exist on records but "
            f"none appears in the CC payload")
    if cash_rec is None:
        missing.append("no SLEEVE:CASH record")
    elif not cash_fp:
        missing.append("SLEEVE:CASH carries no narrative text")
    elif not cash_surfaced:
        missing.append("the cash letter is on the record but not in the CC payload")
    if not no_ping:
        missing.append(
            f"a ping is implicated (telegram_sent={telegram_sent}, "
            f"would_send_any={would_send_any})")
    return {"id": "CC_NARRATIVE_NO_PING", "title": title, "status": RED,
            "reason": "; ".join(missing), "caveat": None, "facts": facts}


# ── check 3: a critique persisted on a record ──────────────────────────────

def _is_critique_shaped(rec: dict[str, Any]) -> bool:
    """Does the evidence on this record come from a CRITIQUE?

    The check used to accept a bare `last_artifact_id`, so ANY artifact
    satisfied a check named for a critique. On 2026-08-30 a residual_web hop
    (artifact rw_8893dcc5aad5be6c, lane residual_web, zero grok lessons) turned
    it GREEN while the grok critique lane was still POLICY_NOT_ALLOWED — the
    board reported the thing it exists to detect as present when it was absent.

    A green obtained by the wrong artifact type is worse than a red, because a
    red gets investigated.
    """
    for field in ("last_artifact_id", "last_outcome", "last_lane",
                  "last_provider", "critique_verdict"):
        if any(m in str(rec.get(field) or "").lower() for m in CRITIQUE_MARKERS):
            return True
    for les in rec.get("lessons") or []:
        if any(m in json.dumps(les, default=str).lower() for m in CRITIQUE_MARKERS):
            return True
    return False


def _critique_evidence(rec: dict[str, Any]) -> Optional[dict[str, Any]]:
    outcome = str(rec.get("last_outcome") or "").strip().lower()
    artifact_id = rec.get("last_artifact_id")
    blocked = rec.get("research_blocked")

    lesson_hit = None
    for les in rec.get("lessons") or []:
        text = json.dumps(les, default=str).lower()
        if any(m in text for m in CRITIQUE_MARKERS):
            lesson_hit = les.get("lesson_id") or les.get("claim")
            break

    # The evidence must come from a critique. A research attach of any other
    # kind is real work and still not what this check is named for.
    if not _is_critique_shaped(rec):
        return None

    kind = None
    if outcome in REJECT_OUTCOMES or blocked is True:
        kind = "reject"
    elif outcome in ATTACH_OUTCOMES or artifact_id:
        kind = "attach"
    elif lesson_hit:
        kind = "attach"

    if not kind:
        return None
    return {
        "subject_key": rec.get("subject_key"),
        "kind": kind,
        "last_outcome": rec.get("last_outcome"),
        "last_artifact_id": artifact_id,
        "research_blocked": blocked,
        "lesson": lesson_hit,
        "next_research_question": rec.get("next_research_question"),
    }


def check_critique_persisted(
    records: Iterable[dict[str, Any]],
    *,
    probe: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """A Grok critique — attached OR rejected — written to a record.

    Either outcome counts, and a reject counts for MORE, because a reject is the
    branch that exercises rule 2: the next question must not be the prompt that
    already failed closed. An attach-only spine has never proved it can learn
    from a refusal.
    """
    title = "Grok critique attach OR reject persisted on a record"
    if probe and probe.get("verdict") != ROOT_OK:
        return _cannot_verify("CRITIQUE_PERSISTED", title, probe)

    hits = [e for e in (_critique_evidence(r) for r in records) if e]
    attaches = [h for h in hits if h["kind"] == "attach"]
    rejects = [h for h in hits if h["kind"] == "reject"]
    facts = {
        "records_with_critique_n": len(hits),
        "attach_n": len(attaches),
        "reject_n": len(rejects),
        "examples": hits[:3],
    }
    if hits:
        return {"id": "CRITIQUE_PERSISTED", "title": title, "status": GREEN,
                "reason": (f"{len(attaches)} attach + {len(rejects)} reject "
                           f"persisted on records"),
                "caveat": None, "facts": facts}
    return {"id": "CRITIQUE_PERSISTED", "title": title, "status": RED,
            "reason": ("no record carries last_artifact_id, a critique lesson, or a "
                       "reject outcome — no critique has ever been written back"),
            "caveat": None, "facts": facts}


# ── check 4: dust and cash-as-a-ticker cannot fire ─────────────────────────

DUST_PROBES = (
    ("HELD", "CASH", None, "cash_or_test_ticker"),
    ("HELD", "USD", None, "cash_or_test_ticker"),
    ("HELD", "SPAXX", None, "cash_or_test_ticker"),
    ("HELD", "TEST", None, "cash_or_test_ticker"),
    ("HELD", "DUSTY", 0.0, "dust_residual"),
    ("HELD", "DUSTY", 12.34, "dust_residual"),
    ("HELD", "DUSTY", -12.34, "dust_residual"),
    ("EXIT", "CASH", None, "cash_or_test_ticker"),
    ("HELD", "", None, "empty_symbol"),
)


def check_dust_cash_refused(
    records: Iterable[dict[str, Any]],
    *,
    probe: Optional[dict[str, Any]] = None,
    dust_tickers: Optional[Iterable[str]] = None,
) -> dict[str, Any]:
    """Refusal must hold at the gate AND be true of what is already stored.

    Two halves, because they fail independently. `is_mintable` can refuse
    perfectly while a record minted before the rule existed still sits in the
    store, and a leaked SLEEVE-as-a-holding is exactly the $630k cash question
    reappearing as a fake position.
    """
    title = "dust / CASH-as-a-ticker cannot mint or fire"
    if probe and probe.get("verdict") != ROOT_OK:
        return _cannot_verify("DUST_CASH_REFUSED", title, probe)

    gate_failures: list[dict[str, Any]] = []
    for kind, name, mv, expected in DUST_PROBES:
        ok, reason = is_mintable(kind, name, market_value=mv)
        if ok or reason != expected:
            gate_failures.append({"kind": kind, "name": name, "market_value": mv,
                                  "expected": expected, "got": reason,
                                  "mintable": ok})

    # A real ticker with real size must still pass, or "refuses everything" would
    # score as a healthy gate.
    control_ok, control_reason = is_mintable("HELD", "NOC", market_value=127.67)

    dust_set = {str(t).strip().upper() for t in (dust_tickers or []) if str(t).strip()}
    leaks: list[dict[str, Any]] = []
    for rec in records:
        kind, name = parse_subject_key(str(rec.get("subject_key") or ""))
        upper = name.strip().upper()
        if kind in ("HELD", "EXIT", "WATCH"):
            if upper in NON_INSTRUMENT_SYMBOLS:
                leaks.append({"subject_key": rec.get("subject_key"),
                              "why": "cash_or_test_ticker_as_instrument"})
            elif upper in dust_set:
                leaks.append({"subject_key": rec.get("subject_key"),
                              "why": "live_dust_ticker_has_a_record"})

    facts = {
        "gate_probes_n": len(DUST_PROBES),
        "gate_failures": gate_failures,
        "control_symbol_mintable": control_ok,
        "control_reason": control_reason,
        "dust_threshold_usd": DUST_MAX_MARKET_VALUE_USD,
        "live_dust_tickers": sorted(dust_set),
        "stored_leaks": leaks,
    }
    if not gate_failures and control_ok and not leaks:
        return {"id": "DUST_CASH_REFUSED", "title": title, "status": GREEN,
                "reason": (f"{len(DUST_PROBES)} refusal probes held, a real ticker "
                           f"still mints, and no stored record is dust or cash"),
                "caveat": None, "facts": facts}
    bits = []
    if gate_failures:
        bits.append(f"{len(gate_failures)} refusal probe(s) did not refuse as expected")
    if not control_ok:
        bits.append(f"a real ticker was also refused ({control_reason}) — over-refusal")
    if leaks:
        bits.append(f"{len(leaks)} stored record(s) are dust or cash-as-a-ticker")
    return {"id": "DUST_CASH_REFUSED", "title": title, "status": RED,
            "reason": "; ".join(bits), "caveat": None, "facts": facts}


# ── the live rails, read rather than asserted ──────────────────────────────

_YAML_BOOL = re.compile(r"^\s*situation_notify_telegram\s*:\s*(\S+)")
_YAML_LIST_HEAD = re.compile(r"^\s*notify_situation_types\s*:")
_YAML_LIST_ITEM = re.compile(r"^\s*-\s*(\S+)")

NOTIFY_ENV_KEYS = (
    "CIO_SITUATION_NOTIFY",
    "CIO_SITUATIONS_NOTIFY",
    "CIO_TELEGRAM_INTERDICT",
    "CIO_SITUATION_NOTIFY_FORCE",
    "CIO_MATERIAL_FINANCIAL_NOTIFY_CANARY",
    "ENABLE_TELEGRAM",
)


def read_policy_notify(root: Path | str) -> dict[str, Any]:
    """Parse the two notify rails out of cio_llm_policy.yaml, line-wise.

    Line-wise on purpose: the board must be able to report the rails even in a
    tree where PyYAML is not importable, and the two fields it needs are flat.
    """
    path = Path(root) / POLICY_REL
    out: dict[str, Any] = {"policy_path": str(path), "policy_readable": False,
                           "situation_notify_telegram": None,
                           "notify_situation_types": []}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    out["policy_readable"] = True
    in_list = False
    for line in lines:
        if line.lstrip().startswith("#"):
            continue
        m = _YAML_BOOL.match(line)
        if m:
            out["situation_notify_telegram"] = m.group(1).strip().lower() in (
                "true", "yes", "1", "on")
            continue
        if _YAML_LIST_HEAD.match(line):
            in_list = True
            continue
        if in_list:
            item = _YAML_LIST_ITEM.match(line)
            if item:
                out["notify_situation_types"].append(item.group(1))
            elif line.strip():
                in_list = False
    return out


def read_server_env(pid: Optional[int] = None) -> dict[str, Any]:
    """The flags the RUNNING server actually holds, from /proc/<pid>/environ.

    A shell's environment is not the server's. The rails that matter are the
    ones the live process was started with, and this is the only place they can
    be read without restarting it. Secrets are never returned — only the
    boolean-ish notify keys.
    """
    out: dict[str, Any] = {"pid": pid, "env_readable": False, "env": {}}
    if pid is None:
        return out
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes().decode("utf-8", "replace")
    except OSError as exc:
        out["error"] = str(exc)
        return out
    out["env_readable"] = True
    for entry in raw.split("\0"):
        key, _, value = entry.partition("=")
        if key in NOTIFY_ENV_KEYS:
            out["env"][key] = value
    return out


def find_server_pid(cmdline_match: str = "portfolio_server.py") -> Optional[int]:
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            cmd = (proc / "cmdline").read_bytes().decode("utf-8", "replace")
        except OSError:
            continue
        if cmdline_match in cmd:
            return int(proc.name)
    return None


def notify_rails(root: Path | str, *, pid: Optional[int] = None) -> dict[str, Any]:
    """What the rails ARE, right now. Never what a spec once said they were."""
    policy = read_policy_notify(root)
    env = read_server_env(pid if pid is not None else find_server_pid())
    values = env.get("env") or {}
    notify_on = values.get("CIO_SITUATION_NOTIFY") == "1" or values.get(
        "CIO_SITUATIONS_NOTIFY") == "1"
    interdict = values.get("CIO_TELEGRAM_INTERDICT")
    return {
        "read_at": "live",
        "server_pid": env.get("pid"),
        "env_readable": env.get("env_readable"),
        "env": values,
        "policy_path": policy["policy_path"],
        "policy_readable": policy["policy_readable"],
        "situation_notify_telegram": policy["situation_notify_telegram"],
        "notify_situation_types": policy["notify_situation_types"],
        "notify_enabled": bool(notify_on and policy["situation_notify_telegram"]),
        "interdict_raised": interdict not in (None, "", "0"),
        "note": ("read from the running process and the policy file; this board "
                 "never sets, clears or asserts a flag"),
    }


# ── spine wiring ───────────────────────────────────────────────────────────

def scan_wake_consumers(repo: Path | str) -> list[str]:
    """Product modules that import the spine — i.e. would read a record on a wake.

    Tests, the libraries themselves, the store registry and the one-shot
    migrator are excluded: none of them is a wake. An empty list means the
    record is written but never consulted, which is a fact the board must print
    rather than let a GREEN imply otherwise.
    """
    repo_path = Path(repo)
    found: list[str] = []
    for path in (repo_path / "scripts").rglob("*.py"):
        rel = str(path.relative_to(repo_path))
        if rel in _NON_WAKE_CONSUMERS or "__pycache__" in rel:
            continue
        if path.name.startswith("test_"):
            continue
        try:
            src = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "cio_rehydrate" in src or "cio_instrument_record" in src:
            found.append(rel)
    return sorted(found)


# ── the board ──────────────────────────────────────────────────────────────

def build_board(
    root: Path | str,
    *,
    home: Optional[dict[str, Any]] = None,
    home_error: Optional[str] = None,
    repo: Optional[Path | str] = None,
    pid: Optional[int] = None,
    dust_tickers: Optional[Iterable[str]] = None,
) -> dict[str, Any]:
    """Assemble the four-item board. Reads only; writes and sends nothing."""
    probe = probe_root(root)
    records = load_records(root) if probe["verdict"] == ROOT_OK else []
    wake_consumers = scan_wake_consumers(repo) if repo else None

    if dust_tickers is None and home:
        dust_tickers = (home.get("holdings_thesis_coverage") or {}).get("dust_tickers")

    checks = [
        check_s0_attach_rehydrate(records, probe=probe, wake_consumers=wake_consumers),
        check_cc_narrative_without_ping(records, home, probe=probe,
                                        home_error=home_error),
        check_critique_persisted(records, probe=probe),
        check_dust_cash_refused(records, probe=probe, dust_tickers=dust_tickers),
    ]

    counts = {GREEN: 0, RED: 0, CANNOT_VERIFY: 0}
    for chk in checks:
        counts[chk["status"]] = counts.get(chk["status"], 0) + 1

    return {
        "schema": SCHEMA,
        "authority": AUTHORITY,
        "memory_behavior_influence": MBI_BEHAVIOR,
        "memory_cognition_influence": MBI_COGNITION,
        "root_probe": probe,
        "record_counts_by_kind": _counts_by_kind(records),
        "checks": checks,
        "counts": counts,
        "all_green": counts[GREEN] == len(CHECK_IDS),
        "notify_rails": notify_rails(root, pid=pid),
        "spine_wake_consumers": wake_consumers,
    }


def _counts_by_kind(records: Iterable[dict[str, Any]]) -> dict[str, int]:
    out: dict[str, int] = {}
    for rec in records:
        kind = str(rec.get("kind") or "?").upper()
        out[kind] = out.get(kind, 0) + 1
    return dict(sorted(out.items()))


def render(board: dict[str, Any]) -> str:
    """Human board. Every RED states WHY, and CANNOT_VERIFY names the path."""
    mark = {GREEN: "GREEN        ", RED: "RED          ",
            CANNOT_VERIFY: "CANNOT_VERIFY"}
    lines: list[str] = []
    probe = board["root_probe"]
    lines.append(f"{SCHEMA}  authority={AUTHORITY}  MBI_BEHAVIOR={MBI_BEHAVIOR}")
    lines.append(f"root      : {probe['root']}")
    lines.append(f"store     : {probe['store_path_resolved']}")
    lines.append(f"root probe: {probe['verdict']} — {probe['reason']}")
    counts = board["record_counts_by_kind"]
    if counts:
        lines.append("records   : " + ", ".join(
            f"{k}={v}" for k, v in counts.items()) + f"  (total {sum(counts.values())})")

    rails = board["notify_rails"]
    lines.append("")
    lines.append("LIVE NOTIFY RAILS (read, not asserted; unchanged by this board)")
    lines.append(f"  server pid                 : {rails['server_pid']}")
    for key in NOTIFY_ENV_KEYS:
        if key in (rails.get("env") or {}):
            lines.append(f"  {key:<27}: {rails['env'][key]}")
    lines.append(f"  situation_notify_telegram  : {rails['situation_notify_telegram']}")
    lines.append(f"  notify_situation_types     : "
                 f"{', '.join(rails['notify_situation_types']) or '(none)'}")
    lines.append(f"  notify enabled             : {rails['notify_enabled']}")
    lines.append(f"  interdict raised           : {rails['interdict_raised']}")

    lines.append("")
    lines.append("PRECONDITIONS")
    for i, chk in enumerate(board["checks"], 1):
        lines.append(f"  {i}. [{mark.get(chk['status'], chk['status'])}] {chk['title']}")
        lines.append(f"        {chk['reason']}")
        if chk.get("caveat"):
            lines.append(f"        CAVEAT: {chk['caveat']}")

    consumers = board.get("spine_wake_consumers")
    if consumers is not None:
        lines.append("")
        lines.append(f"spine wake consumers: {', '.join(consumers) or 'NONE'}")

    c = board["counts"]
    lines.append("")
    lines.append(f"TOTAL green={c[GREEN]} red={c[RED]} cannot_verify={c[CANNOT_VERIFY]}")
    return "\n".join(lines)
