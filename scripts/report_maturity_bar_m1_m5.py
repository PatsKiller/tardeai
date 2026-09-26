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
import os
import re
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


def _read_stamp(release_dir: Path) -> tuple[str | None, str | None]:
    """(sha, promoted_at ISO-UTC) from the release's SOURCE_COMMIT/BUILD_SHA stamp."""
    for name in ("SOURCE_COMMIT", "BUILD_SHA"):
        f = release_dir / name
        try:
            if f.is_file():
                sha = f.read_text(encoding="utf-8").strip() or None
                promoted = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                return sha, promoted.strftime("%Y-%m-%dT%H:%M:%SZ")
        except OSError:
            continue
    return None, None


def served_runtime(
    *,
    current: Path | None = None,
    boot_json: Path | None = None,
) -> dict:
    """What is actually serving: pin path, its SHA, when it was promoted, when
    the server process booted on it.

    2026-09-25: M1–M5 verdicts were computed from artifact files with no check
    that the evidence post-dates the served release. M1/M3 evidence was written
    on a pre-deploy SHA and M4's soak ledger last observed a 5-day-old pin;
    all read as OBSERVED. The report now carries this block and every proof
    states whether its evidence lies on the served SHA.
    """
    cur = current or (Path.home() / "trade-ai-releases/portfolio-server/CURRENT")
    out: dict = {
        "pin": _pin() if current is None else str(cur.resolve()) if cur.exists() else "UNKNOWN",
        "served_sha": None,
        "promoted_at": None,
        "boot_at": None,
        "boot_pin_sha": None,
        "boot_matches_pin": None,
    }
    try:
        if cur.exists():
            out["served_sha"], out["promoted_at"] = _read_stamp(cur.resolve())
    except OSError:
        pass
    boot = _load_json(boot_json or (Path.home() / ".local/state/tradeai/portfolio_server_boot.json"))
    if boot:
        out["boot_at"] = boot.get("process_started_at")
        out["boot_pin_sha"] = boot.get("loaded_pin_sha") or boot.get("current_pin_sha")
        if out["served_sha"] and out["boot_pin_sha"]:
            out["boot_matches_pin"] = str(out["boot_pin_sha"]).startswith(str(out["served_sha"])[:12]) \
                or str(out["served_sha"]).startswith(str(out["boot_pin_sha"])[:12])
    return out


_AS_OF_RE = re.compile(r"as_of=([0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9:.]+(?:Z|[+-][0-9]{2}:?[0-9]{2})?)")


def evidence_as_of(note: str) -> str | None:
    """The evidence timestamp a proof note names (`... as_of=<iso> ...`)."""
    m = _AS_OF_RE.search(note or "")
    return m.group(1) if m else None


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def served_gate(verdict: str, note: str, served: dict | None) -> dict:
    """Attach the served-SHA gate to one proof.

    `verdict` is the artifact-level reading (unchanged contract). `served_verdict`
    is what may be claimed for the deployed release: OBSERVED only when the
    evidence post-dates the promotion of the served pin. Evidence older than the
    pin is OBSERVED_PRE_DEPLOY; evidence without a timestamp is
    OBSERVED_UNDATED. Neither is a default PASS.
    """
    as_of = evidence_as_of(note)
    row = {
        "verdict": verdict,
        "note": note,
        "evidence_as_of": as_of,
        "on_served_sha": None,
        "served_verdict": verdict,
    }
    if verdict != "OBSERVED":
        return row
    promoted = _parse_iso((served or {}).get("promoted_at"))
    ev = _parse_iso(as_of)
    if promoted is None:
        row["served_verdict"] = "OBSERVED_UNGATED"
        row["gate_note"] = "served pin promoted_at unknown; cannot place evidence on the served SHA"
        return row
    if ev is None:
        row["served_verdict"] = "OBSERVED_UNDATED"
        row["gate_note"] = "evidence carries no as_of; cannot place it on the served SHA"
        return row
    row["on_served_sha"] = ev >= promoted
    if row["on_served_sha"]:
        row["gate_note"] = f"evidence {as_of} post-dates promotion {served.get('promoted_at')} of {served.get('served_sha')}"
    else:
        row["served_verdict"] = "OBSERVED_PRE_DEPLOY"
        row["gate_note"] = (f"evidence {as_of} predates promotion {served.get('promoted_at')} "
                            f"of {served.get('served_sha')}; needs a natural re-observation")
    return row


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


def _m1_from_wake_log_alone(
    *,
    log_path: Path | None = None,
) -> tuple[str, str] | None:
    """Recover M1 when hit retention dropped persist rows but the log still has them.

    Measured 2026-09-19: HELD:BAH ``persisted=True changed=next_eligible_at,cc_narrative``
    at 15:46 ET was real and unattended; later research-only hits FIFO-evicted it
    from ``wake_research_persist.json``. Prefer the log over reporting NOT_OBSERVED.
    """
    path = log_path or (
        Path.home()
        / "trade-ai-releases"
        / "persistent-state"
        / "logs"
        / "cio_wake_dispatcher.log"
    )
    if not _exists_nonempty(path):
        return None
    last: dict | None = None
    try:
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
                subj = None
                if "subject=" in line:
                    try:
                        subj = line.split("subject=", 1)[1].split()[0].strip()
                    except IndexError:
                        subj = None
                if not subj or subj in {"None", "null"}:
                    continue
                try:
                    raw = line.split("changed=", 1)[1].strip()
                except IndexError:
                    continue
                raw = raw.split()[0] if raw.split() else raw
                named = [
                    p.strip()
                    for p in raw.split(",")
                    if p.strip() in _M1_COGNITION_FIELDS
                ]
                if not named:
                    continue
                # leading "YYYY-MM-DD HH:MM:SS,mmm"
                as_of = line[:19].replace(" ", "T") + "Z" if len(line) >= 19 else None
                last = {
                    "as_of": as_of,
                    "subject_key": subj,
                    "field_changes": named,
                }
    except OSError:
        return None
    if not last:
        return None
    return (
        "OBSERVED",
        f"unattended persist as_of={last['as_of']} subject_key={last['subject_key']} "
        f"field_changes={last['field_changes']} via=wake_dispatcher_log "
        f"(hit retention lost persist row; log is authoritative)",
    )


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
    # 2026-09-25: a cadence skip (`next_eligible_at` not yet due) is the record
    # honoring its OWN prior write, which every routine cycle produces. It is
    # not a days-later operator/critic disposition changing what happens next,
    # which is what M5 claims. Only `decisions_changed_by_record` counts as a
    # disposition; cadence-only cycles stay CANDIDATE and say so.
    if unattended and found >= 1 and changed >= 1:
        return (
            "OBSERVED",
            f"{base} — load-by-subject ran on schedule and a recorded disposition changed a decision",
        )
    if unattended and found >= 1 and (skipped >= 1 or ie_skipped >= 1):
        return (
            "CANDIDATE",
            f"{base} — cadence honored (routine); no recorded disposition changed a decision yet",
        )
    if unattended and found >= 1 and resolved >= 1:
        return (
            "CANDIDATE",
            f"{base} — load works; waiting for a cycle where a recorded disposition changes a decision",
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
                if found >= 1 and changed >= 1:
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


def _m5_evaluate(cio: Path, *, log_path: Path | None = None) -> tuple[str, str]:
    consult = _load_json(cio / "wake_record_consult.json")
    v, note = _m5_from_consult(consult)
    if v == "OBSERVED":
        return v, note
    hist = _m5_from_consult_history(cio / "wake_record_consult.jsonl")
    if hist and hist[0] == "OBSERVED":
        return hist
    logged = _m5_from_wake_log(log_path=log_path)
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
    recovered = _m1_from_wake_log_alone(log_path=log_path)
    if recovered is not None:
        return recovered
    return (
        "NOT_OBSERVED",
        "needs self-raised research → InstrumentRecord field diff from served release",
    )


def _m4_census_paths() -> list[Path]:
    return [
        Path.home() / ".local/state/tradeai/operator_number_census.json",
        Path.home()
        / "trade-ai-releases/persistent-state/data/runtime/operator_number_census.json",
        ROOT / "data" / "runtime" / "operator_number_census.json",
    ]


def _m4_soak_paths(root: Path) -> list[Path]:
    """Prefer local state (no release-write), then persistent, then checkout."""
    return [
        Path.home() / ".local/state/tradeai/bridge_pin_soak.jsonl",
        Path.home()
        / "trade-ai-releases/persistent-state/data/runtime/bridge_pin_soak.jsonl",
        root / "data" / "runtime" / "bridge_pin_soak.jsonl",
    ]


M4_MAX_AGE_HOURS = float(os.environ.get("TRADEAI_M4_MAX_AGE_HOURS", "48"))


def _m4_from_soak(
    root: Path,
    *,
    soak_path: Path | None = None,
    census_paths: list[Path] | None = None,
    now: datetime | None = None,
    max_age_hours: float = M4_MAX_AGE_HOURS,
    served_sha: str | None = None,
) -> tuple[str, str]:
    """M4: pin soak + operator-number census (one producer / no FAIL / no WARN).

    Operator remasures treat residual census WARNs as M4 PARTIAL even when
    ``ok`` is true (fail=0). Match that bar: WARN>0 stays PARTIAL.
    """
    soak = soak_path
    if soak is None:
        for cand in _m4_soak_paths(root):
            if _exists_nonempty(cand):
                soak = cand
                break
        else:
            soak = _m4_soak_paths(root)[0]
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
    soak_note = (
        f"bridge pin soak streak={streak} soak_ready={'YES' if ready else 'NO'} "
        f"last_as_of={(last or {}).get('as_of')}"
    )
    # Freshness (2026-09-25): the ledger last observed 2026-09-20 on pin
    # 8c12ea757 while 1c60ecb42 served; a 5-day-old streak on another SHA
    # read as OBSERVED. A soak row older than max_age_hours, or one whose
    # observed pin is not the served pin, cannot vouch for the served release.
    _now = now or datetime.now(timezone.utc)
    last_dt = _parse_iso((last or {}).get("as_of"))
    if last_dt is None:
        return ("PARTIAL", f"{soak_note}; soak row carries no parseable as_of")
    age_h = (_now - last_dt).total_seconds() / 3600.0
    if age_h > max_age_hours:
        return (
            "PARTIAL",
            f"{soak_note}; soak stale age_hours={age_h:.1f} > {max_age_hours:g} "
            f"(observed pin={Path(str((last or {}).get('current_resolved') or '')).name or None})",
        )
    observed_pin = Path(str((last or {}).get("current_resolved") or "")).name
    if served_sha and observed_pin and not observed_pin.startswith(str(served_sha)[:9]):
        return (
            "PARTIAL",
            f"{soak_note}; soak observed pin={observed_pin} is not the served sha={served_sha[:12]}",
        )

    census = None
    census_path = None
    for cand in census_paths or _m4_census_paths():
        if cand.is_file():
            try:
                census = json.loads(cand.read_text(encoding="utf-8"))
                census_path = cand
                break
            except (OSError, ValueError):
                continue
    if not isinstance(census, dict) or not census.get("as_of"):
        return (
            "PARTIAL",
            f"{soak_note}; full operator-number census not run "
            "(run scripts/check_command_center_data_consistency.py)",
        )
    census_dt = _parse_iso(census.get("as_of"))
    if census_dt is not None and (_now - census_dt).total_seconds() / 3600.0 > max_age_hours:
        return (
            "PARTIAL",
            f"{soak_note}; census stale as_of={census.get('as_of')} "
            f"(> {max_age_hours:g}h) path={census_path}",
        )
    fails = int(census.get("fail") or 0)
    warns = int(census.get("warn") or 0)
    ok = bool(census.get("ok")) and fails == 0 and warns == 0
    census_note = (
        f"census as_of={census.get('as_of')} pass={census.get('pass')} "
        f"warn={warns} fail={fails} path={census_path}"
    )
    if ready and ok:
        return (
            "OBSERVED",
            f"{soak_note}; {census_note} — one producer / no FAIL / no WARN on operator-number census",
        )
    return ("PARTIAL", f"{soak_note}; {census_note}")


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


def evaluate(root: Path | None = None, *, served: dict | None = None) -> dict:
    """Evaluate M1–M5.

    With ``root=None`` the served persistent-state tree is read (operator
    form). With an explicit ``root`` the evaluation is hermetic to that tree:
    no home-directory fallback (persistent-state, dispatcher log) is consulted,
    so a test or an isolated replay cannot pick up production evidence.
    """
    hermetic = root is not None
    root = root or ROOT
    cio = root / "data" / "cio"
    persist_cio = Path.home() / "trade-ai-releases/persistent-state/data/cio"
    if not hermetic and persist_cio.is_dir():
        cio = persist_cio
    served = served if served is not None else served_runtime()
    log_path = (root / "logs" / "cio_wake_dispatcher.log") if hermetic else None

    wake_effects = cio / "wake_turn_effects.jsonl"
    research_persist = _load_json(cio / "wake_research_persist.json")
    m1_v, m1_n = _m1_from_persist(research_persist, log_path=log_path)
    m2_v, m2_n = _m2_from_writeback(cio)
    m3_v, m3_n = _m3_from_effects(wake_effects)
    m5_v, m5_n = _m5_evaluate(cio, log_path=log_path)
    m4_v, m4_n = _m4_from_soak(root, served_sha=served.get("served_sha"))

    proofs = {
        "M1_Research": served_gate(m1_v, m1_n, served),
        "M2_Advice": served_gate(m2_v, m2_n, served),
        "M3_Feedback": served_gate(m3_v, m3_n, served),
        "M4_Consistency": served_gate(m4_v, m4_n, served),
        "M5_Persistence": served_gate(m5_v, m5_n, served),
    }
    on_served = sum(1 for p in proofs.values() if p.get("served_verdict") == "OBSERVED")
    return {
        "schema": SCHEMA,
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pin": served.get("pin") or _pin(),
        "served": served,
        "authority": "READ_ONLY_ADVISORY",
        "proofs": proofs,
        "observed_on_served_sha": on_served,
        "rule": (
            "Do not score as a percentage (AGENTS.md §15). `verdict` reads the "
            "artifact; `served_verdict` is what may be claimed for the deployed SHA."
        ),
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
        sv = rep.get("served") or {}
        print(
            f"Maturity bar M1–M5 as_of={rep['as_of']} pin={rep['pin']} "
            f"served_sha={sv.get('served_sha')} promoted_at={sv.get('promoted_at')} "
            f"boot_at={sv.get('boot_at')}"
        )
        for k, v in rep["proofs"].items():
            print(f"  {k}: {v['verdict']} [served: {v.get('served_verdict')}] — {v['note']}")
            if v.get("gate_note"):
                print(f"      gate: {v['gate_note']}")
        print(f"  observed_on_served_sha={rep.get('observed_on_served_sha')}/5")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
