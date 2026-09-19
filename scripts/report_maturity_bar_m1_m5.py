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
    as_of = consult.get("as_of")
    entry = consult.get("entrypoint")
    base = (
        f"consult as_of={as_of} entry={entry} unattended={unattended} "
        f"subject_resolved={resolved} record_found={found} "
        f"changed_by_record={changed} skipped_cadence={skipped}"
    )
    disposition = changed >= 1 or skipped >= 1
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


def _m1_from_persist(persist: dict | None) -> tuple[str, str]:
    """M1: self-raised research that persisted onto a record (field diff still required for OBSERVED)."""
    if not persist:
        return (
            "NOT_OBSERVED",
            "needs self-raised research → InstrumentRecord field diff from served release",
        )
    current = persist.get("current") if isinstance(persist.get("current"), dict) else {}
    hits = persist.get("hits") if isinstance(persist.get("hits"), list) else []
    recent = [h for h in hits if isinstance(h, dict) and int(h.get("persisted") or 0) >= 1]
    cur_persisted = int(current.get("persisted") or 0)
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


def evaluate(root: Path | None = None) -> dict:
    root = root or ROOT
    cio = root / "data" / "cio"
    persist_cio = Path.home() / "trade-ai-releases/persistent-state/data/cio"
    if persist_cio.is_dir():
        cio = persist_cio

    wake_effects = cio / "wake_turn_effects.jsonl"
    consult = _load_json(cio / "wake_record_consult.json")
    research_persist = _load_json(cio / "wake_research_persist.json")
    m1_v, m1_n = _m1_from_persist(research_persist)
    m5_v, m5_n = _m5_from_consult(consult)
    m4_v, m4_n = _m4_from_soak(root)

    proofs = {
        "M1_Research": {"verdict": m1_v, "note": m1_n},
        "M2_Advice": {
            "verdict": "NOT_OBSERVED",
            "note": "needs critic verdict changing next_research_question on a live record",
        },
        "M3_Feedback": {
            "verdict": "CANDIDATE" if _exists_nonempty(wake_effects) else "NOT_OBSERVED",
            "note": f"wake_turn_effects present={_exists_nonempty(wake_effects)} path={wake_effects}",
        },
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
