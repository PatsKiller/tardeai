"""learning_watermark.py — consume the VERIFIED Hermes learning completion once (process consolidation cohort 2).

Why. `discovery_yield_builder` and `tag_lift_discovery` read what the Hermes learning stage produces (the graded
outcome ledger and state/hermes/outcome_bus.json). Outcome learning moved to 10:50-11:35 ET on 2026-08-21 while
the two consumers stayed on the overnight clock (03:45 / 03:50 ET, since the C1 flip of 2026-10-11 the 02:20 ET
hermes_overnight night stage), so every consumption read learning output ~15-17 h old. Cohort 2 fires them from
the learning stage's verified completion (registry run_done trigger with require_verdict, the cohort-1 path:
event router -> gateway run -> executor) and keeps the clock as a watermark-aware fallback.

The watermark. `current_watermark` returns the newest VERIFIED completion of step outcome_learning
(config/learning_watermark.json `upstream`) from either scheduler:
  * n8n: a coordination-ledger RUN_DONE row of the upstream lane, mode in ledger_modes, whose receipt
    output_verdict.verdict is in require_verdict (produced / empty_allowed: the executor's verdict, read with the
    same function the due computation uses, n8n_due.run_output_verdict). id ``n8n:<run_id>``, at = finished_at.
  * cron runner: the PipelineStepReceipt@v1 line of the step (status ok, dry_run false) CORROBORATED by the
    stage's durable artifact — an outcome_bus history snapshot stamped within window_s before the step receipt
    (outcome_feedback_agent writes it inside the same stage run). id ``cron:<pipeline>:<stage>:<step>:<ts>``.
    A step receipt with no corroborating artifact is `upstream_unverified`, never a watermark (rail 8).
No source readable, or nothing verified -> (None, reason). The reader never raises: a fault is a reason.

The guard. `decide` is pure: (trigger, watermark, consumer state, now) -> Decision(run, reason).
  event  no watermark -> no fire (reason upstream_missing / upstream_unverified / reader_error:*);
         watermark already consumed (same id) or not newer than the consumed one -> no fire; else run.
  clock  the fallback: same id / not newer -> no-op with the reason, UNLESS the consumer's last consumption is
         older than clock_stale_ceiling_h (then it runs: stale_consumption_ceiling); a newer watermark -> run;
         no readable watermark -> run (clock_fallback_upstream_unreadable: the clock is the fallback for exactly
         this case and keeps the pre-cohort behaviour).
`record` writes <state_root>/data/runtime/<state_dir>/<lane>.json (LearningWatermarkConsumer@v1, atomic replace):
the consumed watermark after a successful LIVE run, and the last decisions (no-ops included, with the reason).
A dry run never records. Both triggers share the one state file, so an event consumption makes the next clock
fire a recorded no-op and a clock consumption makes a late event fire a recorded no-op: no double consumption.

AUTHORITY: READ_ONLY_ADVISORY for the reads (sqlite opened mode=ro, files read); the one write is the consumer's
own state file under the persistent state root. No DB, no broker, no send, no model call, no crontab/systemd.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "learning_watermark.json"
CONFIG_SCHEMA = "LearningWatermarkConfig@v1"
STATE_SCHEMA = "LearningWatermarkConsumer@v1"
TRIGGERS = ("event", "clock")
CLOCK_GUARD_MODES = ("enforce", "off")
#: Verdicts a run_done trigger may require (lane_dispatch.TRIGGER_VERIFIED_VERDICTS; the config may only narrow).
VERIFIED_VERDICTS = ("produced", "empty_allowed")
LEDGER_ENV = "TRADEAI_N8N_COORDINATION_LEDGER"
RUN_ID_ENV = "TRADEAI_RUN_ID"

try:
    from scripts.lib.n8n_due import run_output_verdict as _run_output_verdict
except ImportError:                                         # imported as lib.learning_watermark
    from lib.n8n_due import run_output_verdict as _run_output_verdict  # type: ignore


@dataclass(frozen=True)
class Watermark:
    id: str
    at: str            # ISO-8601 UTC: the upstream's verified completion time
    source: str        # "n8n" | "cron"
    verdict: str       # the executor verdict (n8n) or "corroborated" (cron runner + artifact)
    evidence: str


@dataclass(frozen=True)
class Decision:
    lane_id: str
    trigger: str
    run: bool
    reason: str
    watermark: Optional[dict]
    consumed: Optional[dict]
    decided_at: str
    input_age_s: Optional[float]   # now - watermark.at: the staleness this consumption would have


# ── config ─────────────────────────────────────────────────────────────────────────────────────────


def load_config(path: Path | str | None = None) -> dict:
    doc = json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))
    errs = validate_config(doc)
    if errs:
        raise ValueError("learning_watermark config invalid: " + "; ".join(errs))
    return doc


def validate_config(doc: Any) -> list[str]:
    errs: list[str] = []
    if not isinstance(doc, dict) or doc.get("schema") != CONFIG_SCHEMA:
        return [f"schema must be {CONFIG_SCHEMA}"]
    up = doc.get("upstream")
    if not isinstance(up, dict) or not isinstance(up.get("lane_id"), str):
        errs.append("upstream.lane_id missing")
    else:
        rv = up.get("require_verdict")
        if not isinstance(rv, list) or not rv or any(v not in VERIFIED_VERDICTS for v in rv):
            errs.append(f"upstream.require_verdict must be a non-empty subset of {VERIFIED_VERDICTS}")
        ps = up.get("pipeline_step")
        if not isinstance(ps, dict) or not all(isinstance(ps.get(k), str) for k in
                                               ("pipeline", "stage", "step", "steps_jsonl")):
            errs.append("upstream.pipeline_step needs pipeline, stage, step, steps_jsonl")
        co = up.get("corroboration")
        if not isinstance(co, dict) or not all(isinstance(co.get(k), str) for k in ("dir", "glob", "stamp_format")) \
                or not isinstance(co.get("window_s"), int) or co["window_s"] <= 0:
            errs.append("upstream.corroboration needs dir, glob, stamp_format and a positive window_s")
    cons = doc.get("consumers")
    if not isinstance(cons, dict) or not cons:
        errs.append("consumers must be a non-empty object")
    else:
        for lane, c in cons.items():
            if not isinstance(c, dict) or c.get("clock_guard") not in CLOCK_GUARD_MODES:
                errs.append(f"consumers.{lane}.clock_guard must be one of {CLOCK_GUARD_MODES}")
    for k in ("clock_stale_ceiling_h", "decision_history"):
        if not isinstance(doc.get(k), int) or doc[k] <= 0:
            errs.append(f"{k} must be a positive int")
    if not isinstance(doc.get("state_dir"), str) or "/" in doc.get("state_dir", "/"):
        errs.append("state_dir must be one path segment")
    if doc.get("event_trigger_state") not in ("shadow", "live"):
        errs.append("event_trigger_state must be shadow or live")
    return errs


# ── time helpers ───────────────────────────────────────────────────────────────────────────────────


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def parse_ts(v: Any) -> Optional[datetime]:
    if not isinstance(v, str) or not v.strip():
        return None
    s = v.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return _utc(datetime.fromisoformat(s))
    except ValueError:
        return None


def iso(dt: datetime) -> str:
    return _utc(dt).isoformat()


def _now(now: Optional[datetime]) -> datetime:
    return _utc(now) if now is not None else datetime.now(timezone.utc)


# ── upstream readers ───────────────────────────────────────────────────────────────────────────────


def default_ledger_path(env: Optional[Mapping[str, str]] = None) -> Path:
    """Same resolution as scripts/n8n_coordination_gateway.default_ledger_path (asserted equal by the tests)."""
    src = os.environ if env is None else env
    explicit = src.get(LEDGER_ENV)
    if explicit:
        return Path(explicit)
    root = src.get("TRADEAI_STATE_ROOT") or str(Path.home() / "trade-ai-releases" / "persistent-state")
    return Path(root) / "data" / "governance" / "n8n_coordination_ledger.sqlite"


def ledger_rows(path: Path | str, lane_id: str) -> list[dict]:
    """RUN_DONE rows of `lane_id` from the coordination ledger, opened read-only. Missing file -> []."""
    p = Path(path)
    if not p.exists():
        return []
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True, timeout=5)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT run_id, lane_id, mode, state, started_at, finished_at, receipt_json FROM runs "
            "WHERE lane_id = ? AND state = 'RUN_DONE'", (lane_id,)).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["receipt"] = json.loads(d.pop("receipt_json") or "null")
        except ValueError:
            d["receipt"] = None
        out.append(d)
    return out


def watermark_from_ledger(rows: Iterable[Mapping[str, Any]], cfg: Mapping[str, Any],
                          now: datetime) -> tuple[Optional[Watermark], int]:
    """Newest verified RUN_DONE (pure). Returns (watermark or None, count of RUN_DONE rows NOT verified)."""
    up = cfg["upstream"]
    modes = set(up.get("ledger_modes") or ["live"])
    best: Optional[tuple[datetime, Mapping[str, Any], str]] = None
    unverified = 0
    for r in rows:
        if r.get("state", "RUN_DONE") != "RUN_DONE" or str(r.get("mode")) not in modes:
            continue
        at = parse_ts(r.get("finished_at"))
        if at is None or at > now:
            continue
        verdict = _run_output_verdict(r)
        if verdict not in up["require_verdict"]:
            unverified += 1
            continue
        if best is None or at > best[0]:
            best = (at, r, str(verdict))
    if best is None:
        return None, unverified
    at, r, verdict = best
    return Watermark(id=f"n8n:{r.get('run_id')}", at=iso(at), source="n8n", verdict=verdict,
                     evidence=f"ledger RUN_DONE {r.get('run_id')} output_verdict={verdict}"), unverified


def _snapshot_stamps(dir_path: Path, glob: str, fmt: str) -> list[datetime]:
    out = []
    if not dir_path.is_dir():
        return out
    for f in dir_path.glob(glob):
        # outcome_bus_<stamp>_ofb_<id>.json -> <stamp>
        stem = f.name
        try:
            stamp = stem.split("outcome_bus_", 1)[1].split("_ofb_", 1)[0]
            out.append(datetime.strptime(stamp, fmt).replace(tzinfo=timezone.utc))
        except (IndexError, ValueError):
            continue
    return out


def watermark_from_steps(lines: Iterable[str], snapshot_stamps: Iterable[datetime], cfg: Mapping[str, Any],
                         now: datetime) -> tuple[Optional[Watermark], int]:
    """Newest corroborated cron-runner completion of the step (pure). Returns (watermark, uncorroborated count)."""
    ps = cfg["upstream"]["pipeline_step"]
    window = timedelta(seconds=int(cfg["upstream"]["corroboration"]["window_s"]))
    stamps = sorted(snapshot_stamps)
    best: Optional[tuple[datetime, str]] = None
    uncorroborated = 0
    for line in lines:
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if not isinstance(rec, dict) or rec.get("schema") != "PipelineStepReceipt@v1":
            continue
        if (rec.get("pipeline"), rec.get("stage"), rec.get("id")) != (ps["pipeline"], ps["stage"], ps["step"]):
            continue
        if rec.get("status") != "ok" or rec.get("dry_run") is not False:
            continue
        at = parse_ts(rec.get("ts"))
        if at is None or at > now:
            continue
        # the snapshot minute is truncated: allow it up to 60 s after the receipt's own second
        if not any(at - window <= s <= at + timedelta(seconds=60) for s in stamps):
            uncorroborated += 1
            continue
        if best is None or at > best[0]:
            best = (at, str(rec.get("ts")))
    if best is None:
        return None, uncorroborated
    at, ts = best
    return Watermark(id=f"cron:{ps['pipeline']}:{ps['stage']}:{ps['step']}:{ts}", at=iso(at), source="cron",
                     verdict="corroborated",
                     evidence=f"{ps['steps_jsonl']} status ok + outcome_bus snapshot within "
                              f"{cfg['upstream']['corroboration']['window_s']}s"), uncorroborated


def current_watermark(cfg: Mapping[str, Any], *, project_root: Path | str | None = None,
                      ledger_path: Path | str | None = None, now: Optional[datetime] = None,
                      env: Optional[Mapping[str, str]] = None) -> tuple[Optional[Watermark], str]:
    """(newest verified watermark or None, reason). Never raises: a reader fault becomes the reason."""
    now_utc = _now(now)
    root = Path(project_root) if project_root else ROOT
    up = cfg["upstream"]
    found: list[Watermark] = []
    notes: list[str] = []
    unverified = 0
    try:
        wm, n = watermark_from_ledger(ledger_rows(ledger_path or default_ledger_path(env), up["lane_id"]),
                                      cfg, now_utc)
        unverified += n
        if wm:
            found.append(wm)
    except (sqlite3.Error, OSError) as exc:
        notes.append(f"ledger:{type(exc).__name__}")
    try:
        steps = root / up["pipeline_step"]["steps_jsonl"]
        lines = steps.read_text(encoding="utf-8").splitlines() if steps.exists() else []
        co = up["corroboration"]
        wm, n = watermark_from_steps(lines, _snapshot_stamps(root / co["dir"], co["glob"], co["stamp_format"]),
                                     cfg, now_utc)
        unverified += n
        if wm:
            found.append(wm)
    except OSError as exc:
        notes.append(f"steps:{type(exc).__name__}")
    if found:
        return max(found, key=lambda w: parse_ts(w.at) or now_utc), "verified"
    if notes and not unverified:
        return None, "reader_error:" + ",".join(notes)
    if unverified:
        return None, "upstream_unverified"
    return None, "upstream_missing"


# ── consumer state ─────────────────────────────────────────────────────────────────────────────────


def state_path(lane_id: str, cfg: Mapping[str, Any], state_root: Path | str | None = None) -> Path:
    try:
        from scripts.lib.lane_last_receipt import runtime_dir
    except ImportError:
        from lib.lane_last_receipt import runtime_dir  # type: ignore
    return runtime_dir(state_root) / cfg["state_dir"] / f"{lane_id}.json"


def load_state(path: Path | str) -> dict:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) and doc.get("schema") == STATE_SCHEMA else {}


def decide(lane_id: str, trigger: str, wm: Optional[Watermark], wm_reason: str, state: Mapping[str, Any],
           cfg: Mapping[str, Any], now: Optional[datetime] = None) -> Decision:
    """Pure. See the module docstring for the table."""
    if trigger not in TRIGGERS:
        raise ValueError(f"trigger must be one of {TRIGGERS}")
    now_utc = _now(now)
    consumed = state.get("consumed") if isinstance(state.get("consumed"), dict) else None
    wm_d = asdict(wm) if wm else None
    age = (now_utc - parse_ts(wm.at)).total_seconds() if wm and parse_ts(wm.at) else None

    def out(run: bool, reason: str) -> Decision:
        return Decision(lane_id=lane_id, trigger=trigger, run=run, reason=reason, watermark=wm_d,
                        consumed=dict(consumed) if consumed else None, decided_at=iso(now_utc), input_age_s=age)

    if wm is None:
        if trigger == "event":
            return out(False, wm_reason)                      # upstream_missing / upstream_unverified / reader_error
        return out(True, "clock_fallback_upstream_unreadable" if wm_reason.startswith("reader_error")
                   else f"clock_fallback_{wm_reason}")
    if consumed:
        same = consumed.get("id") == wm.id
        c_at, w_at = parse_ts(consumed.get("at")), parse_ts(wm.at)
        not_newer = c_at is not None and w_at is not None and w_at <= c_at
        if same or not_newer:
            why = (f"watermark_already_consumed_by_{consumed.get('by', 'unknown')}" if same
                   else "watermark_not_newer")
            if trigger == "clock":
                last = parse_ts(consumed.get("consumer_finished_at"))
                ceiling = timedelta(hours=int(cfg["clock_stale_ceiling_h"]))
                if last is None or now_utc - last > ceiling:
                    return out(True, "stale_consumption_ceiling")
            return out(False, why)
    return out(True, "new_watermark")


def _atomic_write(path: Path, doc: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def record(decision: Decision, cfg: Mapping[str, Any], *, consumed: bool, started_at: Optional[str] = None,
           state_root: Path | str | None = None, now: Optional[datetime] = None) -> Path:
    """Record a LIVE decision (and, after a successful run, the consumed watermark). Never call on a dry run."""
    path = state_path(decision.lane_id, cfg, state_root)
    st = load_state(path) or {"schema": STATE_SCHEMA, "lane_id": decision.lane_id}
    entry = {k: v for k, v in asdict(decision).items() if k != "consumed"}
    entry["consumed_now"] = bool(consumed)
    run_id = os.environ.get(RUN_ID_ENV)
    if run_id:
        entry["run_id"] = run_id
    hist = [h for h in st.get("decisions") or [] if isinstance(h, dict)]
    st["decisions"] = (hist + [entry])[-int(cfg["decision_history"]):]
    st["last_decision"] = entry
    if consumed and decision.watermark:
        st["consumed"] = {"id": decision.watermark["id"], "at": decision.watermark["at"],
                          "source": decision.watermark["source"], "by": decision.trigger,
                          "consumer_started_at": started_at, "consumer_finished_at": iso(_now(now)),
                          "input_age_s": decision.input_age_s}
        if run_id:
            st["consumed"]["run_id"] = run_id
    _atomic_write(path, st)
    return path


# ── the guard the two consumer scripts call ────────────────────────────────────────────────────────


class Guard:
    """One consumer's guard for one invocation. `trigger` None = the legacy invocation = clock."""

    def __init__(self, lane_id: str, trigger: Optional[str] = None, *, cfg: Optional[Mapping[str, Any]] = None,
                 project_root: Path | str | None = None, state_root: Path | str | None = None,
                 ledger_path: Path | str | None = None, now: Optional[datetime] = None) -> None:
        self.cfg = dict(cfg) if cfg is not None else load_config()
        if lane_id not in self.cfg["consumers"]:
            raise ValueError(f"{lane_id} is not a learning_watermark consumer")
        self.lane_id = lane_id
        self.trigger = trigger or "clock"
        if self.trigger not in TRIGGERS:
            raise ValueError(f"trigger must be one of {TRIGGERS}")
        self.project_root, self.state_root, self.ledger_path, self._now = project_root, state_root, ledger_path, now
        self.started_at = iso(_now(now))
        self.decision: Optional[Decision] = None

    @property
    def enabled(self) -> bool:
        """The event trigger is always guarded; the clock only when its consumer's clock_guard is enforce."""
        return self.trigger == "event" or self.cfg["consumers"][self.lane_id]["clock_guard"] == "enforce"

    def evaluate(self) -> Decision:
        wm, why = current_watermark(self.cfg, project_root=self.project_root, ledger_path=self.ledger_path,
                                    now=self._now)
        st = load_state(state_path(self.lane_id, self.cfg, self.state_root))
        self.decision = decide(self.lane_id, self.trigger, wm, why, st, self.cfg, now=self._now)
        return self.decision

    def record_skip(self) -> Path:
        assert self.decision is not None and not self.decision.run
        return record(self.decision, self.cfg, consumed=False, state_root=self.state_root, now=self._now)

    def record_consumed(self) -> Path:
        assert self.decision is not None and self.decision.run
        return record(self.decision, self.cfg, consumed=self.decision.watermark is not None,
                      started_at=self.started_at, state_root=self.state_root, now=self._now)

    def line(self, *, dry_run: bool) -> str:
        d = self.decision
        assert d is not None
        wm = d.watermark or {}
        age = f"{d.input_age_s / 3600:.2f}h" if d.input_age_s is not None else "n/a"
        verb = ("WOULD RUN" if d.run else "WOULD NO-OP") if dry_run else ("RUN" if d.run else "NO-OP")
        return (f"[learning-watermark] {self.lane_id} trigger={d.trigger} {verb} reason={d.reason} "
                f"watermark={wm.get('id', 'none')} input_age={age}"
                + (" (dry run: nothing recorded)" if dry_run else ""))


def guard_for(lane_id: str, trigger: Optional[str]) -> tuple[Optional[Guard], Optional[str]]:
    """(guard or None, problem). For the consumer scripts: an unreadable config disables the CLOCK guard (the clock
    keeps its pre-cohort behaviour, the problem is printed) and refuses the EVENT trigger (the caller exits 1).
    A clock whose consumer has clock_guard off gets no guard."""
    try:
        g = Guard(lane_id, trigger)
    except (OSError, ValueError, KeyError) as exc:
        return None, f"learning_watermark config unusable: {type(exc).__name__}: {exc}"[:300]
    return (g if g.enabled else None), None
