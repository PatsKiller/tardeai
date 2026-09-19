#!/usr/bin/env python3
"""report_maturity_bar_m1_m5.py — thin §15 five-proof status (honest, not a percentage).

Reads local artifacts only. Default verdict is NOT_OBSERVED unless evidence is present.
Does not claim OBSERVED from hermetic tests alone.

USAGE
  python3 scripts/report_maturity_bar_m1_m5.py
  python3 scripts/report_maturity_bar_m1_m5.py --json

AUTHORITY: READ_ONLY_ADVISORY
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "MaturityBarM1M5Report@v1"
NO_CONSUMER_REASON = (
    "operator maturity report; stdout/JSON is the consumer until a CC surface "
    "or scheduled digest imports it"
)
ROOT = Path(__file__).resolve().parents[1]


def _pin() -> str:
    try:
        return str((Path.home() / "trade-ai-releases/portfolio-server/CURRENT").resolve())
    except OSError:
        return "UNKNOWN"


def _exists_nonempty(p: Path) -> bool:
    return p.is_file() and p.stat().st_size > 0


def _load_json(p: Path) -> dict | None:
    if not _exists_nonempty(p):
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


# Cognition fields MBI_COGNITION may move (AGENTS.md §2). Behaviour fields never.
_M1_COGNITION_FIELDS = frozenset({
    "next_research_question",
    "next_eligible_at",
    "notify_priority",
    "cc_narrative",
})


def _named_cognition_fields(persist: dict) -> list[str]:
    """Collect named cognition field diffs from current.persist and retained hits."""
    named: list[str] = []
    seen: set[str] = set()

    def _add(values) -> None:
        for raw in values or []:
            key = str(raw).strip()
            if key in _M1_COGNITION_FIELDS and key not in seen:
                seen.add(key)
                named.append(key)

    current = persist.get("current") if isinstance(persist.get("current"), dict) else {}
    for row in current.get("persist") or []:
        if isinstance(row, dict) and row.get("persisted"):
            _add(row.get("changed"))
    for hit in persist.get("hits") or []:
        if not isinstance(hit, dict):
            continue
        if int(hit.get("persisted") or 0) < 1:
            continue
        _add(hit.get("field_changes") or hit.get("changed_fields"))
    return named


def _field_changes_from_wake_log(
    subjects: list[str],
    *,
    log_path: Path | None = None,
) -> list[str]:
    """Corroborate M1 from the durable entrypoint log when hits omit field_changes.

    `cognition_persist ... changed=a,b` lines are written by the scheduled
    entrypoint into persistent-state/logs. Hits retained before field_changes
    was added to hit_from_cycle still prove persist; the log names the fields.
    """
    if not subjects:
        return []
    path = log_path or (
        Path.home()
        / "trade-ai-releases"
        / "persistent-state"
        / "logs"
        / "cio_wake_dispatcher.log"
    )
    if not _exists_nonempty(path):
        return []
    wanted = {str(s) for s in subjects if s}
    found: list[str] = []
    seen: set[str] = set()
    try:
        # Bound the scan: last ~2 MiB covers recent unattended cycles.
        size = path.stat().st_size
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            if size > 2_000_000:
                fh.seek(size - 2_000_000)
                fh.readline()
            for line in fh:
                if "cognition_persist" not in line or "changed=" not in line:
                    continue
                if "persisted=True" not in line and "persisted=true" not in line:
                    continue
                # subject=<key> ... changed=a,b
                subj = None
                if "subject=" in line:
                    try:
                        subj = line.split("subject=", 1)[1].split()[0].strip()
                    except IndexError:
                        subj = None
                if subj not in wanted:
                    continue
                try:
                    raw = line.split("changed=", 1)[1].strip()
                except IndexError:
                    continue
                # Rest of the line may continue; fields are comma-separated tokens.
                raw = raw.split()[0] if raw.split() else raw
                for part in raw.split(","):
                    key = part.strip()
                    if key in _M1_COGNITION_FIELDS and key not in seen:
                        seen.add(key)
                        found.append(key)
    except OSError:
        return []
    return found


def _m5_from_consult(consult: dict | None) -> tuple[str, str]:
    """M5: unattended load-by-subject + days-later disposition still honored."""
    if not consult:
        return (
            "NOT_OBSERVED",
            "needs unattended scheduled load-by-subject + days-later disposition honor",
        )
    unattended = bool(consult.get("unattended"))
    found = int(consult.get("record_found") or 0)
    resolved = int(consult.get("subject_resolved") or 0)
    changed = int(consult.get("decisions_changed_by_record") or 0)
    skipped = int(consult.get("skipped_cadence_not_due") or 0)
    ie = consult.get("instrument_enqueue") if isinstance(consult.get("instrument_enqueue"), dict) else {}
    ie_skipped = int(
        consult.get("instrument_enqueue_skipped_cadence")
        or ie.get("skipped_cadence_count")
        or 0
    )
    as_of = consult.get("as_of")
    entry = consult.get("entrypoint")
    base = (
        f"consult as_of={as_of} entry={entry} unattended={unattended} "
        f"subject_resolved={resolved} record_found={found} "
        f"changed_by_record={changed} skipped_cadence={skipped} "
        f"instrument_enqueue_skipped_cadence={ie_skipped}"
    )
    disposition = changed >= 1 or skipped >= 1 or ie_skipped >= 1
    if unattended and found >= 1 and disposition:
        return (
            "OBSERVED",
            f"{base} — load-by-subject ran on schedule and honored a prior disposition",
        )
    if unattended and found >= 1 and resolved >= 1:
        return (
            "CANDIDATE",
            f"{base} — load works; waiting for a cycle that skips on cadence/disposition",
        )
    return ("NOT_OBSERVED", base)




def _m5_from_consult_history(hist: Path) -> tuple[str, str] | None:
    """Scan append-only consult history for a recent OBSERVED-qualifying cycle."""
    if not _exists_nonempty(hist):
        return None
    last_obs = None
    try:
        size = hist.stat().st_size
        with hist.open("r", encoding="utf-8", errors="replace") as fh:
            if size > 2_000_000:
                fh.seek(size - 2_000_000)
                fh.readline()
            for line in fh:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                v, note = _m5_from_consult(row)
                if v == "OBSERVED":
                    last_obs = (v, note + " via=consult_history")
    except OSError:
        return None
    return last_obs


def _m5_from_wake_log(*, log_path: Path | None = None) -> tuple[str, str] | None:
    """Corroborate M5 from dispatcher log when the latest consult json was overwritten."""
    path = log_path or (
        Path.home()
        / "trade-ai-releases"
        / "persistent-state"
        / "logs"
        / "cio_wake_dispatcher.log"
    )
    if not _exists_nonempty(path):
        return None
    last = None
    try:
        size = path.stat().st_size
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            if size > 2_000_000:
                fh.seek(size - 2_000_000)
                fh.readline()
            for line in fh:
                if "record_consult:" not in line:
                    continue
                try:
                    changed = int(line.split("changed_by_record=", 1)[1].split()[0])
                    skipped = int(line.split("skipped_cadence_not_due=", 1)[1].split()[0])
                    found = int(line.split("record_found=", 1)[1].split()[0])
                except (IndexError, ValueError):
                    continue
                if found >= 1 and (changed >= 1 or skipped >= 1):
                    ts = line.split(" [", 1)[0].strip() if " [" in line else None
                    last = (
                        "OBSERVED",
                        "log record_consult as_of=%s record_found=%s "
                        "changed_by_record=%s skipped_cadence=%s "
                        "via=wake_dispatcher_log — disposition honored on schedule"
                        % (ts, found, changed, skipped),
                    )
    except OSError:
        return None
    return last


def _m5_evaluate(cio: Path) -> tuple[str, str]:
    consult = _load_json(cio / "wake_record_consult.json")
    v, note = _m5_from_consult(consult)
    if v == "OBSERVED":
        return v, note
    hist = _m5_from_consult_history(cio / "wake_record_consult.jsonl")
    if hist and hist[0] == "OBSERVED":
        return hist
    logged = _m5_from_wake_log()
    if logged and logged[0] == "OBSERVED":
        return logged
    return v, note


def _m1_from_persist(
    persist: dict | None,
    *,
    log_path: Path | None = None,
) -> tuple[str, str]:
    """M1: self-raised research that persisted onto a named InstrumentRecord field."""
    if not persist:
        return (
            "NOT_OBSERVED",
            "needs self-raised research → InstrumentRecord field diff from served release",
        )
    current = persist.get("current") if isinstance(persist.get("current"), dict) else {}
    hits = persist.get("hits") if isinstance(persist.get("hits"), list) else []
    recent = [h for h in hits if isinstance(h, dict) and int(h.get("persisted") or 0) >= 1]
    cur_persisted = int(current.get("persisted") or 0)
    named = _named_cognition_fields(persist)
    evidence_src = "persist_artifact"
    if not named and recent:
        last = recent[-1]
        subjects = [str(s) for s in (last.get("subjects") or []) if s]
        named = _field_changes_from_wake_log(subjects, log_path=log_path)
        if named:
            evidence_src = "wake_dispatcher_log"
    unattended = bool(current.get("unattended")) or any(
        bool(h.get("unattended", True)) for h in recent
    )
    if named and unattended and (cur_persisted >= 1 or recent):
        as_of = current.get("as_of") if cur_persisted >= 1 else (
            recent[-1].get("as_of") if recent else None
        )
        persisted_n = cur_persisted or (recent[-1].get("persisted") if recent else 0)
        return (
            "OBSERVED",
            f"unattended persist as_of={as_of} persisted={persisted_n} "
            f"field_changes={named} via={evidence_src}",
        )
    if cur_persisted >= 1 and current.get("unattended"):
        return (
            "CANDIDATE",
            f"current wake_research_persist persisted={cur_persisted} unattended "
            f"as_of={current.get('as_of')} — name the field diff to promote to OBSERVED",
        )
    if recent:
        last = recent[-1]
        return (
            "CANDIDATE",
            f"historical unattended persist hit as_of={last.get('as_of')} "
            f"subjects={last.get('subjects')} — need named field diff on served pin",
        )
    return (
        "NOT_OBSERVED",
        "needs self-raised research → InstrumentRecord field diff from served release",
    )


def _m4_from_soak(root: Path) -> tuple[str, str]:
    """M4 partial: pin soak readiness is one consistency signal, not the full census."""
    soak = (
        Path.home()
        / "trade-ai-releases/persistent-state/data/runtime/bridge_pin_soak.jsonl"
    )
    if not _exists_nonempty(soak):
        return (
            "PARTIAL",
            "bridge pin soak ledger absent; full operator-number census not run",
        )
    streak = 0
    last = None
    try:
        for line in soak.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            last = row
            if row.get("pins_match"):
                streak += 1
            else:
                streak = 0
    except (OSError, ValueError):
        return ("PARTIAL", "bridge pin soak ledger unreadable")
    ready = streak >= 3 and bool((last or {}).get("pins_match"))
    note = (
        f"bridge pin soak streak={streak} soak_ready={'YES' if ready else 'NO'} "
        f"last_as_of={(last or {}).get('as_of')}; full operator-number census not run"
    )
    return ("PARTIAL", note)


def _m2_from_writeback(cio: Path) -> tuple[str, str]:
    """M2: critique verdict changed next_research_question on a live record."""
    try:
        # Path-load so `python scripts/report_maturity_bar_m1_m5.py` works when
        # `scripts` is not an importable package on sys.path (cron form).
        import importlib.util

        mod_path = Path(__file__).resolve().parent / "lib" / "critique_question_writeback.py"
        spec = importlib.util.spec_from_file_location(
            "_maturity_critique_question_writeback", mod_path
        )
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load {mod_path}")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        artifact = cio / "wake_critique_question.jsonl"
        row = mod.latest_applied_writeback(artifact)
    except Exception as exc:  # noqa: BLE001
        return (
            "NOT_OBSERVED",
            f"needs critic verdict changing next_research_question on a live record ({exc})",
        )
    if not row:
        return (
            "NOT_OBSERVED",
            "needs critic verdict changing next_research_question on a live record",
        )
    before = row.get("before")
    after = row.get("after")
    base = (
        f"writeback as_of={row.get('as_of')} subject_key={row.get('subject_key')} "
        f"verdict={row.get('critique_verdict')} critique_id={row.get('critique_id')} "
        f"before={before!r} after={after!r} unattended={row.get('unattended')}"
    )
    if (
        row.get("applied")
        and row.get("unattended")
        and row.get("critique_id")
        and (before or "") != (after or "")
        and after
    ):
        return ("OBSERVED", f"{base} — critique changed next_research_question on the record")
    return ("CANDIDATE", base)



def _m3_from_effects(path: Path) -> tuple[str, str]:
    """M3: operator turn changed next wake behaviour — with vs without the turn."""
    if not _exists_nonempty(path):
        return (
            "NOT_OBSERVED",
            "needs operator reply on a record that changed the next wake "
            f"(wake_turn_effects missing path={path})",
        )
    last: dict | None = None
    try:
        # Bound scan: last ~2 MiB covers recent organic turns.
        size = path.stat().st_size
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            if size > 2_000_000:
                fh.seek(size - 2_000_000)
                fh.readline()
            for line in fh:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                if not row.get("turn_changed_decision"):
                    continue
                with_q = ((row.get("with_turn") or {}) if isinstance(row.get("with_turn"), dict) else {}).get(
                    "next_research_question"
                )
                without_q = (
                    (row.get("without_turn") or {}) if isinstance(row.get("without_turn"), dict) else {}
                ).get("next_research_question")
                if not with_q or not without_q or with_q == without_q:
                    continue
                last = row
    except OSError as exc:
        return ("NOT_OBSERVED", f"wake_turn_effects unreadable ({exc})")
    if not last:
        return (
            "CANDIDATE",
            f"wake_turn_effects present path={path} — no turn_changed_decision "
            "row with differing with/without next_research_question",
        )
    with_t = last.get("with_turn") if isinstance(last.get("with_turn"), dict) else {}
    without_t = last.get("without_turn") if isinstance(last.get("without_turn"), dict) else {}
    turn = last.get("turn") if isinstance(last.get("turn"), dict) else {}
    note = (
        f"effect as_of={last.get('at')} subject_key={last.get('subject_key')} "
        f"intent={turn.get('intent')} plan_id={turn.get('plan_id')} "
        f"with={with_t.get('next_research_question')!r} "
        f"without={without_t.get('next_research_question')!r}"
    )
    return (
        "OBSERVED",
        f"{note} — operator turn changed next_research_question vs counterfactual",
    )


def evaluate(root: Path | None = None) -> dict:
    root = root or ROOT
    cio = root / "data" / "cio"
    persist_cio = Path.home() / "trade-ai-releases/persistent-state/data/cio"
    if persist_cio.is_dir():
        cio = persist_cio

    wake_effects = cio / "wake_turn_effects.jsonl"
    research_persist = _load_json(cio / "wake_research_persist.json")
    m1_v, m1_n = _m1_from_persist(research_persist)
    m2_v, m2_n = _m2_from_writeback(cio)
    m3_v, m3_n = _m3_from_effects(wake_effects)
    m5_v, m5_n = _m5_evaluate(cio)
    m4_v, m4_n = _m4_from_soak(root)

    proofs = {
        "M1_Research": {"verdict": m1_v, "note": m1_n},
        "M2_Advice": {
            "verdict": m2_v,
            "note": m2_n,
        },
        "M3_Feedback": {"verdict": m3_v, "note": m3_n},
        "M4_Consistency": {"verdict": m4_v, "note": m4_n},
        "M5_Persistence": {"verdict": m5_v, "note": m5_n},
    }
    return {
        "schema": SCHEMA,
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pin": _pin(),
        "authority": "READ_ONLY_ADVISORY",
        "proofs": proofs,
        "rule": "Do not score as a percentage (AGENTS.md §15).",
        "no_consumer_reason": NO_CONSUMER_REASON,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rep = evaluate()
    if args.json:
        print(json.dumps(rep, indent=2))
    else:
        print(f"Maturity bar M1–M5 as_of={rep['as_of']} pin={rep['pin']}")
        for k, v in rep["proofs"].items():
            print(f"  {k}: {v['verdict']} — {v['note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
