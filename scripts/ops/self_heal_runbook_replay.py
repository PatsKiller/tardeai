#!/usr/bin/env python3
"""Replay the self-heal runbook catalog over REAL failures: every signature in the window -> one catalog entry.

LQ-20261107-1259 (deliverable 1 and 4). The questions this answers, in the operator's words:

* every real failure signature seen in the n8n receipts and the dead-letter store over the last N days maps to a
  catalog entry, with its count;
* what only the K05 catch-all catches -- and, for each, either a real entry or a written reason (``GATE_REASONS``);
* the same 14-day failures replayed through ``plan_runbook`` (dry: this script calls no action, writes no receipt,
  touches no lane and makes no model call) with per-entry hit counts.

Sources, both read-only:

* ``<state root>/data/runtime/n8n_runs/d:<lane>:<mode>:<stamp>.json`` -- the executor's own run receipts. A failure
  is a receipt whose state is not ``RUN_DONE`` (the LQ-1237 taxonomy's rule; a legacy ``RUN_DONE`` with no verdict is
  a schema gap, not a failure, and is counted separately). The signature is the state plus the normalized last stderr
  line, or the receipt's ``reason`` when there is no stderr (the taxonomy's rule, re-implemented here so the replay
  does not depend on a coordination artifact).
* ``<state root>/data/governance/n8n_coordination_ledger.sqlite`` ``dead_letters`` (opened ``mode=ro``) -- the
  dispatch plane's own dead letters. Their signature is the state plus ``last_reason``; they carry no stderr.

The replay is deterministic for a given ``--as-of`` and window: no wall clock enters a plan, and the deferred /
cooldown / idempotency fields are functions of the as-of instant.

Usage::

    python3 scripts/ops/self_heal_runbook_replay.py --as-of 2026-11-08T22:00Z --window-days 14
    python3 scripts/ops/self_heal_runbook_replay.py --as-of ... --out docs/runbooks/self_heal/COVERAGE.json

Exit codes: 0 the replay ran; 2 usage; 3 a catch-all signature has no written reason (``--check-gate``).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.self_heal_runbooks import CATALOG_PATH, load_catalog, plan_runbook  # noqa: E402

SNAPSHOT_SCHEMA = "SelfHealRunbookCoverage@v1"
CATCH_ALL = "K05-unclassified-catch-all"
#: The states that make a receipt a failure. ``RUN_DONE`` is never a failure here (a legacy RUN_DONE with no verdict
#: is a schema gap; see ``legacy_no_verdict`` in the totals).
FAIL_STATES = frozenset({"RUN_FAILED", "RUN_TIMEOUT", "RUN_REFUSED", "RUN_SKIPPED_LOCK"})
RECEIPT_NAME = re.compile(r"^d:(?P<lane>[^:]+):(?P<mode>[^:]+):(?P<stamp>\d{8}T\d{4})\.json$")
RECEIPTS_REL = Path("data") / "runtime" / "n8n_runs"
LEDGER_REL = Path("data") / "governance" / "n8n_coordination_ledger.sqlite"
CATALOG_REL = Path("config") / "self_heal_runbook_catalog.json"

#: Catch-all signatures that deliberately have NO entry of their own, each with the reason. A signature that resolves
#: to K05 and is not listed here is a catalog gap: ``--check-gate`` exits 3. Keys are the normalized signature text.
#: Populated from the 2026-11-08 replay; see docs/runbooks/self_heal/COVERAGE.md.
GATE_REASONS: dict[str, str] = {}

#: (states, regex over the whole receipt text, failure_class). First rule wins; the last rule is the floor.
#: A class is what a fixer would have to derive anyway; the engine still matches on the receipt text, so a class the
#: catalog does not name is not a gap as long as a reason/exception regex matches.
FAILURE_CLASS_RULES: tuple[tuple[frozenset[str], str, str], ...] = (
    (frozenset({"RUN_SKIPPED_LOCK"}), r".", "lock_held"),
    (frozenset({"RUN_TIMEOUT"}), r"executor[_ ]lost|lost its executor", "executor_lost"),
    (frozenset({"RUN_TIMEOUT"}), r".", "wall_timeout"),
    (frozenset({"RUN_REFUSED"}), r"effect_no_owner", "effect_no_owner"),
    (frozenset({"RUN_REFUSED"}), r"effect_already_claimed", "effect_claimed"),
    (frozenset({"RUN_REFUSED"}), r"env_names_missing", "config_env"),
    (frozenset({"RUN_REFUSED"}), r".", "refused"),
    (FAIL_STATES, r"no space left on device|ENOSPC", "disk_full"),
    (FAIL_STATES, r"database is locked|SQLITE_BUSY", "sqlite_locked"),
    (FAIL_STATES, r"LockNotAvailable|55P03|could not obtain lock", "pg_lock"),
    (FAIL_STATES, r"log path component is not a real directory", "config_path"),
    (FAIL_STATES, r"\bempty_output\b|\bEMPTY_OUTPUT\b", "empty_output"),
    (FAIL_STATES, r"\boutput_unverifiable\b", "output_unverifiable"),
    (FAIL_STATES, r"effect_no_owner", "effect_no_owner"),
    (FAIL_STATES, r"effect_already_claimed", "effect_claimed"),
    (FAIL_STATES, r"env_names_missing", "config_env"),
    (FAIL_STATES, r"BRIDGE_ROUTE_REFUSED", "bridge_route_refused"),
    (FAIL_STATES, r"JSONDecodeError|json\.decoder", "parse_error"),
    (FAIL_STATES, r"connection already closed|SSL connection has been closed", "db_connection_closed"),
    (FAIL_STATES, r"while updating tuple|deadlock detected|serialization failure", "db_error"),
    (FAIL_STATES, r"\b(?:relation|column|table)\b.*does not exist", "schema"),
    (FAIL_STATES, r"dependency_unavailable", "data_defect"),
    (FAIL_STATES, r"verification_failed|failed verification|insufficient (?:ohlcv|data)", "upstream_verification"),
    (FAIL_STATES, r"DiscoveryInboxError|label normalizes", "data_defect"),
    (FAIL_STATES, r"\bflock\b", "lock_held"),
    (FAIL_STATES, r".", "code_error"),
)

_TS = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?")
_PATH = re.compile(r"(?:~|\.{0,2})?/(?:[\w.@+-]+/)+[\w.@+-]*")
_HEX = re.compile(r"\b[0-9a-f]{12,}\b", re.I)
_TOKEN = re.compile(r"\b[A-Za-z0-9_-]{24,}\b")
_NUM = re.compile(r"\d+(?:\.\d+)?")
_WS = re.compile(r"\s+")
#: A symbol can reach a signature through a URL query, an error prefix ("HD: model call failed"), a row payload or
#: "for CDT:". This repository is public: every symbol collapses to <SYM> exactly like a path collapses to <PATH>.
#: A placeholder inside angle brackets is never re-matched, and a protocol word stays readable.
_SYMBOLS_PARAM = re.compile(r"(?<=symbols=)[A-Za-z][A-Za-z,]*")
_SYMBOL_PREFIX = re.compile(r"^(?:(?:<TS>|,|<N>|\s)+)?\[?([A-Z]{1,7})\]?:(?=\s)")
_SYMBOL_FOR = re.compile(r"(?<=for )[A-Z]{1,5}(?=:)")
_CAPS = re.compile(r"(?<![<\w])[A-Z]{2,5}(?![\w>])")
#: A quoted single capital letter is a one-letter ticker ('A' is Agilent); the 2-5 rule does not reach it.
_QUOTED1 = re.compile(r"(?<![A-Za-z0-9_])[\'\"][A-Z][\'\"](?![A-Za-z0-9_])")
#: Words that stay readable: a protocol token, a status/level word, a grammar or domain word, an SQL keyword. Every
#: other 2-5 capitalised token is treated as a symbol and collapses to <SYM> (this repository is public, and a ticker
#: is a holding). The list is deliberately narrow: a US ticker can be any 1-5 capital letters, so a word is added
#: only when the alternative is an unreadable signature -- and "BE", "NOW" and "AI" are real tickers seen in the same
#: logs, so they are NOT here.
LOG_WORDS = frozenset({"ERROR", "FATAL", "WARN", "WARNING", "INFO", "DEBUG", "TRACE", "NOTICE", "HINT", "DETAIL",
                       "CONTEXT", "RUN", "SKIP", "DRY"})
PROTOCOL_WORDS = LOG_WORDS | frozenset({
    "HTTP", "HTTPS", "GET", "POST", "PUT", "HEAD", "DNS", "TCP", "UDP", "SSL", "TLS", "API", "URL", "JSON", "CSV",
    "XML", "SQL", "DB", "PID", "CPU", "RAM", "EOF", "OK", "TRUE", "FALSE", "NULL", "NONE", "UTF",
    # grammar and domain words: "IS"/"AND"/"INTO"/"WHERE" are ordinary English, "ALTER"/"TABLE"/"CAST" are SQL,
    # "OHLCV"/"ETF"/"FOMC" are this system's vocabulary
    "IS", "AND", "INTO", "WHERE", "ALTER", "TABLE", "CAST", "UPC", "MB", "FOMC", "ETF", "OHLCV", "ACTOR",
})
#: A word in front of a colon is either a log level/status word or a symbol ("BE: model call failed" is a ticker).
#: Only the log/status words may stay, so this is the narrower set -- never the grammar words above.
NON_SYMBOL_PREFIX = LOG_WORDS
TAIL_CHARS = 240


def state_root(environ: Mapping[str, str] | None = None) -> Path:
    """The state root, resolved exactly as the gateway resolves it (never a literal path in this file)."""
    source = environ if environ is not None else os.environ
    return Path(source.get("TRADEAI_STATE_ROOT") or (Path.home() / "trade-ai-releases" / "persistent-state"))


def catalog_version(catalog: Mapping[str, Any] | None = None) -> str:
    """The catalog's own version string, read from the file so a snapshot names the catalog it was replayed on."""
    if catalog is not None:
        version = catalog.get("version")
        if isinstance(version, str) and version:
            return version
    try:
        return str(json.loads(CATALOG_PATH.read_text(encoding="utf-8")).get("version") or "unknown")
    except (OSError, ValueError):
        return "unknown"


def normalize(text: Any) -> str:
    """A signature tail with no volatile token: timestamps, paths, hex, long tokens and digits collapse.

    A signature is a *failure shape*, not a payload; the collapse is what makes two occurrences of one defect one
    row. It is also what keeps an operator path out of a public document.
    """
    out = str(text or "")
    out = _TS.sub("<TS>", out)
    out = _SYMBOLS_PARAM.sub("<SYM>", out)
    out = _PATH.sub("<PATH>", out)
    out = _HEX.sub("<HEX>", out)
    out = _TOKEN.sub("<TOKEN>", out)
    out = _NUM.sub("<N>", out)
    out = _SYMBOL_PREFIX.sub(lambda m: m.group(0) if m.group(1) in NON_SYMBOL_PREFIX else "<SYM>:", out)
    out = _SYMBOL_FOR.sub("<SYM>", out)
    out = _QUOTED1.sub("<SYM>", out)
    out = _CAPS.sub(lambda m: m.group(0) if m.group(0) in PROTOCOL_WORDS else "<SYM>", out)
    out = _WS.sub(" ", out).strip()
    return out[-TAIL_CHARS:]


def failure_class(state: str, text: str) -> str:
    for states, pattern, cls in FAILURE_CLASS_RULES:
        if state in states and re.search(pattern, text):
            return cls
    return "code_error"


def _receipt_text(doc: Mapping[str, Any]) -> str:
    return "\n".join(str(doc.get(k) or "") for k in ("reason", "stderr_tail", "stdout_tail"))


def _signature_text(state: str, doc: Mapping[str, Any]) -> str:
    """State + the normalized last stderr line, or the receipt's reason when there is no stderr (LQ-1237's rule)."""
    stderr = str(doc.get("stderr_tail") or "")
    lines = [ln for ln in stderr.splitlines() if ln.strip()]
    tail = lines[-1] if lines else str(doc.get("reason") or "")
    return f"{state}: {normalize(tail)}"


def _receipts(runs_dir: Path, since: datetime, until: datetime) -> tuple[list[dict[str, Any]], Counter]:
    """Every receipt in the window whose state is a failure, plus the scan's own totals."""
    totals: Counter = Counter()
    out: list[dict[str, Any]] = []
    if not runs_dir.is_dir():
        raise SystemExit(f"receipts directory not found: {runs_dir}")
    for ent in os.scandir(runs_dir):
        m = RECEIPT_NAME.match(ent.name)
        if not m:
            continue
        try:
            stamp = datetime.strptime(m.group("stamp"), "%Y%m%dT%H%M").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if not (since <= stamp <= until):
            continue
        totals["receipts_scanned"] += 1
        try:
            with open(ent.path, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            totals["receipts_unreadable"] += 1
            continue
        state = str(doc.get("state") or "")
        if state == "RUN_DONE":
            if not doc.get("verdict"):
                totals["legacy_no_verdict"] += 1
            continue
        if state not in FAIL_STATES:
            totals[f"state_other:{state or 'missing'}"] += 1
            continue
        out.append({"lane": m.group("lane"), "mode": m.group("mode"), "slot": m.group("stamp"),
                    "state": state, "doc": doc})
    return out, totals


def _dead_letters(ledger: Path, since: datetime, until: datetime) -> tuple[list[dict[str, Any]], Counter]:
    """Unreleased-and-released dead letters in the window, read through a read-only connection (never created)."""
    totals: Counter = Counter()
    if not ledger.is_file():
        totals["ledger_missing"] += 1
        return [], totals
    conn = sqlite3.connect(f"file:{ledger}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT slot_key, lane_id, mode, last_state, COALESCE(last_reason,'') AS last_reason, class, policy,"
            " dead_at, released_at FROM dead_letters WHERE dead_at >= ? AND dead_at <= ?",
            (since.isoformat(), until.isoformat()),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        totals["dead_letters"] += 1
        if r["released_at"]:
            totals["dead_letters_released"] += 1
        out.append({"lane": r["lane_id"] or "", "mode": r["mode"] or "", "slot": r["slot_key"] or "",
                    "state": str(r["last_state"] or ""), "last_reason": r["last_reason"],
                    "class": r["class"] or "", "policy": r["policy"] or ""})
    return out, totals


def _lane_timeouts() -> dict[str, float]:
    """Each lane's declared wall limit, from the n8n entry list the executor runs from (a missing lane is absent)."""
    path = ROOT / "config" / "n8n_run_allowlist.json"
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    lanes = doc.get("lanes") if isinstance(doc, dict) else doc
    lanes = lanes.values() if isinstance(lanes, dict) else lanes or []
    out: dict[str, float] = {}
    for lane in lanes:
        if not isinstance(lane, Mapping):
            continue
        lid, timeout = lane.get("lane_id"), lane.get("timeout_s")
        if isinstance(lid, str) and isinstance(timeout, (int, float)) and not isinstance(timeout, bool):
            out[lid] = float(timeout)
    return out


def replay(*, as_of: datetime, window_days: int, runs_dir: Path, ledger: Path,
           catalog: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Plan every failure in the window. Pure apart from the two read-only sources."""
    cat = catalog if catalog is not None else load_catalog()
    since = as_of - timedelta(days=window_days)
    receipts, rtot = _receipts(runs_dir, since, as_of)
    letters, ltot = _dead_letters(ledger, since, as_of)
    timeouts = _lane_timeouts()
    sig_rows: dict[str, dict[str, Any]] = {}
    per_entry: dict[str, dict[str, Any]] = defaultdict(lambda: {"hits": 0, "lanes": Counter(),
                                                               "signatures": Counter()})
    totals: Counter = Counter(rtot)
    totals.update(ltot)
    totals["window_failures"] = 0

    def _record(source: str, lane: str, state: str, signature: str, evidence: dict[str, Any],
                cls: str) -> None:
        totals["window_failures"] += 1
        row = sig_rows.setdefault(signature, {"signature": signature, "state": state, "failure_class": cls,
                                              "hits": 0, "sources": Counter(), "lanes": Counter(),
                                              "entry": None, "action": None, "tier": None, "reason": None,
                                              "plans": Counter(), "example": None})
        row["hits"] += 1
        row["sources"][source] += 1
        row["lanes"][lane] += 1
        if row["example"] is None:
            row["example"] = {"lane": lane, "source": source}
        contract = {"lane": lane, "baseline": {"timeout_s": 1800}} if lane not in timeouts else {
            "lane": lane, "baseline": {"timeout_s": timeouts[lane]}}
        plan = plan_runbook(cls, evidence, contract, as_of, catalog=cat)
        # One signature must plan to ONE action: lane-dependent preconditions (a per-lane timeout) could otherwise
        # make the row's printed action an arbitrary last-hit sample. Record the first plan and every variant; the
        # report prints a warning when a signature has more than one.
        row["plans"][(plan["entry"], plan["action"], plan["tier"])] += 1
        if row["entry"] is None:
            row["entry"], row["action"], row["tier"], row["reason"] = (
                plan["entry"], plan["action"], plan["tier"], plan["reason"])
        agg = per_entry[plan["entry"]]
        agg["hits"] += 1
        agg["lanes"][lane] += 1
        agg["signatures"][signature] += 1

    for r in receipts:
        doc = r["doc"]
        text = _receipt_text(doc)
        cls = failure_class(r["state"], text)
        signature = _signature_text(r["state"], doc)
        evidence = {
            "lane": r["lane"], "signature": signature, "reason": str(doc.get("reason") or ""),
            "detail": signature.split(": ", 1)[-1], "stderr_tail": str(doc.get("stderr_tail") or "")[-2000:],
            "stdout_tail": str(doc.get("stdout_tail") or "")[-1000:], "slot": r["slot"],
        }
        if r["lane"] in timeouts:
            evidence["lane_timeout_s"] = timeouts[r["lane"]]
        _record("receipts", r["lane"], r["state"], signature, evidence, cls)
    for d in letters:
        text = d["last_reason"]
        cls = failure_class(d["state"], text)
        signature = f"{d['state']}: {normalize(text)}" if text else f"{d['state']}: <no reason recorded>"
        evidence = {"lane": d["lane"], "signature": signature, "reason": text, "detail": normalize(text),
                    "slot": d["slot"]}
        _record("dead_letters", d["lane"], d["state"], signature, evidence, cls)

    sigs = sorted(sig_rows.values(), key=lambda r: (-r["hits"], r["signature"]))
    catch_all = [r for r in sigs if r["entry"] == CATCH_ALL]
    gate_missing = [r["signature"] for r in catch_all if r["signature"] not in GATE_REASONS]
    return {
        "schema": SNAPSHOT_SCHEMA,
        "as_of": as_of.isoformat(),
        "window_days": window_days,
        "window_start": since.isoformat(),
        "sources": {
            "receipts": str(RECEIPTS_REL),
            "dead_letters": str(LEDGER_REL) + " (dead_letters, mode=ro)",
        },
        "rule": ("failure = a receipt whose state is not RUN_DONE (RUN_FAILED/RUN_TIMEOUT/RUN_REFUSED/"
                 "RUN_SKIPPED_LOCK) or a dead letter; signature = state + normalized last stderr line (shortest "
                 "reader: the receipt reason when there is no stderr); a legacy RUN_DONE with no verdict is a schema "
                 "gap, not a failure; replay = plan_runbook(dry, fixed as-of, catalog on this commit)."),
        "totals": dict(sorted(totals.items())),
        "catalog": {"path": str(CATALOG_REL), "version": catalog_version(), "entries": len(cat)},
        "entries": {eid: {"hits": agg["hits"], "lanes": sorted(agg["lanes"]),
                          "signatures": [s for s, _ in agg["signatures"].most_common()]}
                    for eid, agg in sorted(per_entry.items())},
        "signatures": [{"signature": r["signature"], "state": r["state"], "failure_class": r["failure_class"],
                        "hits": r["hits"], "sources": dict(sorted(r["sources"].items())),
                        "lanes": [ln for ln, _ in r["lanes"].most_common()], "entry": r["entry"],
                        "action": r["action"], "tier": r["tier"], "reason": r["reason"],
                        "plan_variants": len(r["plans"]),
                        "plans": [{"entry": k[0], "action": k[1], "tier": k[2], "hits": v}
                                  for k, v in sorted(r["plans"].items(), key=lambda kv: (-kv[1], kv[0]))],
                        "example": r["example"]} for r in sigs],
        "catch_all": {"hits": sum(r["hits"] for r in catch_all),
                      "signatures": [{"signature": r["signature"], "hits": r["hits"],
                                      "reason_written": GATE_REASONS.get(r["signature"])} for r in catch_all],
                      "missing_reason": gate_missing},
    }


def _print_report(snap: Mapping[str, Any], top: int) -> None:
    tot = snap["totals"]
    print(f"window {snap['window_start']} .. {snap['as_of']} ({snap['window_days']} d)")
    print(f"receipts scanned {tot.get('receipts_scanned', 0)} · failures {tot.get('window_failures', 0)}"
          f" · dead letters {tot.get('dead_letters', 0)} · signatures {len(snap['signatures'])}")
    print(f"{'hits':>6}  {'class':<20} {'entry':<38} {'action':<28} {'tier':<12} signature")
    for row in snap["signatures"][:top]:
        print(f"{row['hits']:>6}  {row['failure_class']:<20} {str(row['entry']):<38} {str(row['action']):<28}"
              f" {str(row['tier']):<12} {row['signature'][:96]}")
    print(f"\nper entry: {len(snap['entries'])} entries hit")
    ca = snap["catch_all"]
    print(f"catch-all: {ca['hits']} hit(s), {len(ca['missing_reason'])} without a written reason"
          + (f": {ca['missing_reason']}" if ca["missing_reason"] else ""))
    variants = [r["signature"] for r in snap["signatures"] if r.get("plan_variants", 1) > 1]
    if variants:
        print(f"plan variants: {len(variants)} signature(s) plan to more than one entry/action "
              f"(the class is derived from other receipt fields): {variants[:3]}")


def _parse_as_of(value: str) -> datetime:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit(f"bad --as-of: {value}") from exc
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--as-of", default=None, help="replay clock (ISO 8601, UTC); default: now")
    ap.add_argument("--window-days", type=int, default=14)
    ap.add_argument("--receipts", default=None, help="override the receipts directory")
    ap.add_argument("--ledger", default=None, help="override the coordination ledger file")
    ap.add_argument("--out", default=None, help="write the coverage snapshot JSON here")
    ap.add_argument("--top", type=int, default=40, help="signature rows printed")
    ap.add_argument("--check-gate", action="store_true",
                    help="exit 3 when a catch-all signature has no written reason in GATE_REASONS")
    args = ap.parse_args(list(argv) if argv is not None else None)

    as_of = _parse_as_of(args.as_of) if args.as_of else datetime.now(timezone.utc)
    root = state_root()
    snap = replay(as_of=as_of, window_days=args.window_days,
                  runs_dir=Path(args.receipts) if args.receipts else root / RECEIPTS_REL,
                  ledger=Path(args.ledger) if args.ledger else root / LEDGER_REL)
    _print_report(snap, args.top)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(snap, indent=2, sort_keys=False) + "\n", encoding="utf-8")
        print(f"\nwrote {out}")
    if args.check_gate and snap["catch_all"]["missing_reason"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
