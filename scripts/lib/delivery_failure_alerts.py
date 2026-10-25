"""Delivery lifecycle failure alerts — every delivery failure pages the operator at once (AGENTS.md §29, PROPOSED).

Operator 2026-10-25, verbatim: "The objective to the lifecycle is multiple agents can read the agents.md, see how to
design and deliver their stuff and queue. We have all of the testers that's testing everything and it's deployed,
tested. Any failures I need to be emailed, notified, and texted."

Triggers (each a pure detector over files the release machinery already writes; nothing here acts on a release):

  main_ci_red          the required push/main workflows of main HEAD concluded with a failure
                       (scripts/main_ci_watch.py receipt when fresh, else its read-only GitHub GET)
  train_outcome        a live train ended FAILED_PRE_MERGE / MERGED_NOT_LIVE / ROLLED_BACK / ROLLBACK_FAILED / STOPPED
                       (<release state>/trains/<train_id>/outcome.json, TrainOutcome@v1)
  train_receipt        a live (non-drill) window request was REFUSED or FAILED (train_requests/receipts/*.json)
  stop_latched         the release STOP latch is SET or UNREADABLE (release_train_window_view.read_latch)
  manual_release       a manual promote/rollback failed or rolled back
                       (~/.local/state/cio-phase2-exact-main/deploy_receipt_history.jsonl)
  post_release_tester  the post-release tester's API or light browser check failed (scripts/post_release_tester.py)
  nightly_sweep        the nightly full sweep found "broken" findings
  request_slot_missed  an enabled release-train request timer did not fire, failed, or left no request for its slot

Delivery: an immediate P1, never the digest. Telegram through the ``telegram_alert.send_telegram`` chokepoint
(priority P1); email and SMS through the communications gateway (``send_via_gateway``, channels ``email`` and
``sms``). A channel whose configuration is absent is NOT_CONFIGURED and is never attempted; this module tests only
whether an env key is set and never reads, prints or stores a value. One line plus a link to System -> Releases &
schedules. Deduped per incident key (re-sent once per ``remind_hours`` while it is still reported), rate limited per
hour, and folded into one message when a run has more than ``max_separate_per_run`` due incidents.

Dry run (default) renders every message and its channel list and writes only the dry-run receipt; it never sends
and never touches the dedupe state. MBI_BEHAVIOR = 0. Authority: OPERATOR_NOTIFY_SYSTEM_OPS (no remediation).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "delivery_failure_alerts.json"
POLICY_PATH = ROOT / "config" / "release_train_policy.json"
SCHEMA = "DeliveryFailureAlerts@v1"
STATE_SCHEMA = "DeliveryFailureAlertsState@v1"
PRODUCER = "delivery_failure_alerts"
RECEIPT_REL = "data/runtime/delivery_failure_alerts_last.json"
DRY_RUN_RECEIPT_REL = "data/runtime/delivery_failure_alerts_dry_run_last.json"
HISTORY_REL = "data/runtime/delivery_failure_alerts.jsonl"
STATE_REL = "data/runtime/delivery_failure_alerts_state.json"
TESTER_DIR_REL = "data/runtime/post_release_tester"
MAIN_CI_RECEIPT_REL = "data/runtime/main-ci-watch_last.json"
ET = ZoneInfo("America/New_York")
CHANNELS = ("telegram", "email", "sms")
TRIGGERS = (
    "main_ci_red",
    "train_outcome",
    "train_receipt",
    "stop_latched",
    "manual_release",
    "post_release_tester",
    "nightly_sweep",
    "request_slot_missed",
)
SENT, FAILED, NOT_CONFIGURED, DISABLED, DRY_RUN, SKIPPED = (
    "SENT",
    "FAILED",
    "NOT_CONFIGURED",
    "DISABLED",
    "DRY_RUN",
    "SKIPPED",
)
#: release_train_controller.ALERT_PRIORITY's P1 rows (pinned by test): the controller texts these itself.
CONTROLLER_P1_OUTCOMES = frozenset({"ROLLED_BACK", "ROLLBACK_FAILED", "MERGED_NOT_LIVE"})
REQUEST_FILE_RE = re.compile(r"^rtw-([0-9]{8})-([0-9]{4})-win\.json$")
UNIT_RE = re.compile(r"^(?P<prefix>.+@)(?P<slot>[0-9]{4})\.timer$")


# ── data ───────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class Incident:
    trigger: str
    key: str
    line: str  # one line, the whole message on SMS
    detail: str = ""
    at: Optional[str] = None
    summary_path: Optional[str] = None
    skip_channels: tuple[str, ...] = ()
    skip_reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["skip_channels"] = list(self.skip_channels)
        return d


@dataclass
class Context:
    state_root: Path
    release_state_dir: Path
    deploy_state_dir: Path
    now: datetime
    config: dict[str, Any]
    policy_path: Path = POLICY_PATH
    #: () -> MainCiWatch@v1 summary, or raises; None = use the receipt only
    ci_reader: Optional[Callable[[], Mapping[str, Any]]] = None
    #: (unit, props) -> {prop: value}; systemctl --user show
    systemd_show: Optional[Callable[[str, tuple[str, ...]], Mapping[str, str]]] = None
    #: () -> [unit names]; systemctl --user list-timers --all
    systemd_timers: Optional[Callable[[], list[str]]] = None
    notes: list[str] = field(default_factory=list)


# ── helpers ────────────────────────────────────────────────────────────────────────────────────────


def load_config(path: Optional[Path] = None) -> dict[str, Any]:
    doc = json.loads(Path(path or CONFIG_PATH).read_text(encoding="utf-8"))
    if doc.get("schema") != "DeliveryFailureAlertsConfig@v1":
        raise ValueError("delivery_failure_alerts config: wrong schema")
    return doc


def _read_json(p: Path) -> Optional[dict]:
    try:
        doc = json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def parse_ts(v: Any) -> Optional[datetime]:
    if not v or not isinstance(v, str):
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _recent(ts: Any, ctx: Context) -> bool:
    d = parse_ts(ts)
    return d is not None and ctx.now - timedelta(
        hours=float(ctx.config.get("lookback_hours", 24))
    ) <= d <= ctx.now + timedelta(minutes=10)


def _enabled(ctx: Context, trigger: str) -> bool:
    return bool(((ctx.config.get("triggers") or {}).get(trigger) or {}).get("enabled", True))


def one_line(text: Any, limit: int = 300) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def releases_link(config: Mapping[str, Any]) -> str:
    path = str(config.get("link_path") or "/v3/system/releases")
    try:
        from scripts.notification_url_builder import build_dashboard_url
    except Exception:  # noqa: BLE001 — a link is never worth failing an alert
        try:
            from notification_url_builder import build_dashboard_url  # type: ignore[no-redef]
        except Exception:  # noqa: BLE001
            return "https://ms01-openclaw.tail163d14.ts.net" + path
    try:
        return build_dashboard_url(path)
    except Exception:  # noqa: BLE001
        return "https://ms01-openclaw.tail163d14.ts.net" + path


# ── detectors ──────────────────────────────────────────────────────────────────────────────────────


def detect_main_ci(ctx: Context) -> list[Incident]:
    max_age = float(((ctx.config.get("triggers") or {}).get("main_ci_red") or {}).get("receipt_max_age_min", 20))
    receipt = _read_json(ctx.state_root / MAIN_CI_RECEIPT_REL)
    summary = None
    if receipt:
        s = receipt.get("summary") if isinstance(receipt.get("summary"), dict) else receipt
        checked = parse_ts((s or {}).get("checked_at") or receipt.get("finished_at") or receipt.get("as_of"))
        if s and s.get("state") and checked and ctx.now - checked <= timedelta(minutes=max_age):
            summary = s
    if summary is None and ctx.ci_reader is not None:
        try:
            summary = dict(ctx.ci_reader())
        except Exception as exc:  # noqa: BLE001 — GitHub unreadable is a note, not a page
            ctx.notes.append(f"main_ci_red: GitHub unreadable ({type(exc).__name__})")
            return []
    if not summary:
        ctx.notes.append("main_ci_red: no fresh main-ci-watch receipt and no reader")
        return []
    if summary.get("state") != "FAILURE":
        return []
    sha = str(summary.get("head_sha") or "")
    failed = [w for w in summary.get("workflows") or [] if w.get("state") == "FAILURE"]
    names = ", ".join(str(w.get("name") or w.get("path")) for w in failed[:3]) or "required workflow"
    url = next((w.get("url") for w in failed if w.get("url")), None)
    return [
        Incident(
            "main_ci_red",
            f"main_ci_red:{sha}",
            f"main CI RED on {sha[:9]}: {names} failed",
            detail=f"run {url}" if url else "",
            at=summary.get("checked_at"),
        )
    ]


def _is_drill(rec: Mapping[str, Any]) -> bool:
    return rec.get("shadow") is not False or rec.get("mode") == "simulate" or bool(rec.get("injected_failures"))


def detect_train_outcomes(ctx: Context) -> list[Incident]:
    alert = set((ctx.config.get("train") or {}).get("alert_outcomes") or [])
    out: list[Incident] = []
    base = ctx.release_state_dir / "trains"
    try:
        dirs = sorted(p for p in base.iterdir() if p.is_dir())
    except OSError:
        return out
    for d in dirs[-200:]:
        doc = _read_json(d / "outcome.json")
        if not doc or doc.get("outcome") not in alert or not _recent(doc.get("finished_at"), ctx):
            continue
        tid = str(doc.get("train_id") or d.name)
        notes = one_line(doc.get("notes") or "", 140)
        sha = doc.get("candidate_sha") or doc.get("main_sha") or ""
        # The controller already pages Telegram P1 for these three (release_window.Host.notify via
        # ALERT_PRIORITY); we add email + SMS and never double-text. Its STOPPED / FAILED_PRE_MERGE notice is P2
        # (digest-held), so those still get an immediate Telegram here.
        p1_paged = doc["outcome"] in CONTROLLER_P1_OUTCOMES
        out.append(
            Incident(
                "train_outcome",
                f"train_outcome:{tid}",
                f"release train {tid} {doc['outcome']}" + (f" ({str(sha)[:9]})" if sha else ""),
                detail=notes,
                at=doc.get("finished_at"),
                summary_path=str(d / "outcome.json"),
                skip_channels=("telegram",) if p1_paged else (),
                skip_reason="controller already sent the Telegram P1" if p1_paged else None,
            )
        )
    return out


def detect_train_receipts(ctx: Context) -> list[Incident]:
    benign = set((ctx.config.get("train") or {}).get("benign_refusal_codes") or [])
    out: list[Incident] = []
    base = ctx.release_state_dir / "train_requests" / "receipts"
    try:
        files = sorted(base.glob("*.json"))[-400:]
    except OSError:
        return out
    for f in files:
        rec = _read_json(f)
        if not rec or rec.get("state") not in ("REFUSED", "FAILED") or _is_drill(rec):
            continue
        if not _recent(rec.get("finished_at") or rec.get("acknowledged_at"), ctx):
            continue
        ref = rec.get("refusal") or {}
        code = str(ref.get("code") or "")
        if rec["state"] == "REFUSED" and code in benign:
            continue
        rid = str(rec.get("request_id") or f.stem)
        out.append(
            Incident(
                "train_receipt",
                f"train_receipt:{rid}",
                f"release train request {rid} {rec['state']}: {code or 'no code'}",
                detail=one_line(ref.get("detail"), 160),
                at=rec.get("finished_at"),
                summary_path=str(f),
            )
        )
    return out


def detect_stop_latch(ctx: Context) -> list[Incident]:
    try:
        from scripts.lib.release_train_window_view import read_latch
    except Exception:  # noqa: BLE001
        from lib.release_train_window_view import read_latch  # type: ignore[no-redef]
    state = read_latch(ctx.release_state_dir)
    if state == "ABSENT":
        return []
    latch = ctx.release_state_dir / "STOP.json"
    doc = _read_json(latch) or {}
    try:
        stamp = int(latch.lstat().st_mtime)
    except OSError:
        stamp = 0
    reason = one_line(doc.get("reason") or doc.get("detail") or doc.get("code") or "", 140)
    return [
        Incident(
            "stop_latched",
            f"stop_latched:{state}:{stamp}",
            f"release STOP {state}" + (f": {reason}" if reason else ""),
            detail="new main writes, train pushes and promotions are refused until the operator resumes",
            at=datetime.fromtimestamp(stamp, timezone.utc).isoformat() if stamp else None,
            summary_path=str(latch),
        )
    ]


def detect_manual_release(ctx: Context, *, train_shas: Iterable[str] = ()) -> list[Incident]:
    skip = {s for s in train_shas if s}
    out: list[Incident] = []
    path = ctx.deploy_state_dir / "deploy_receipt_history.jsonl"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-400:]
    except OSError:
        return out
    for raw in lines:
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get("mode") not in ("promote", "rollback"):
            continue
        failed = row.get("ok") is False or row.get("rolled_back") is True
        if not failed:
            continue
        when = row.get("at") or row.get("started_at")
        if not _recent(when, ctx):
            continue
        sha = str(row.get("sha") or (row.get("attempted_target") or {}).get("sha") or "")
        if sha in skip:
            continue  # the train incident for the same SHA already covers it
        verb = "rolled back" if row.get("rolled_back") else "FAILED"
        out.append(
            Incident(
                "manual_release",
                f"manual_release:{row.get('mode')}:{sha}:{when}",
                f"release {row.get('mode')} {verb} ({sha[:9] or 'unknown sha'}): "
                f"{one_line(row.get('extra') or row.get('health') or '', 80)}",
                at=when,
                summary_path=str(ctx.deploy_state_dir / "deploy_receipt.json"),
            )
        )
    return out


def _tester_receipt(ctx: Context, mode: str) -> Optional[dict]:
    return _read_json(ctx.state_root / TESTER_DIR_REL / f"last_{mode}.json")


def detect_post_release(ctx: Context) -> list[Incident]:
    out: list[Incident] = []
    for mode in ("api", "light"):
        rec = _tester_receipt(ctx, mode)
        if not rec or rec.get("status") != "FAILED" or not _recent(rec.get("finished_at"), ctx):
            continue
        sha = str(rec.get("release_sha") or "")
        fails = [c for c in rec.get("checks") or [] if c.get("ok") is False]
        what = "; ".join(one_line(f"{c.get('name')}: {c.get('detail') or ''}", 70) for c in fails[:2]) or one_line(
            rec.get("reason"), 120
        )
        out.append(
            Incident(
                "post_release_tester",
                f"post_release_tester:{mode}:{sha}:{rec.get('run_id')}",
                f"post-release {mode} check FAILED on {sha[:9] or 'release'}: {what}",
                at=rec.get("finished_at"),
                summary_path=rec.get("summary_path"),
            )
        )
    return out


def detect_nightly_sweep(ctx: Context) -> list[Incident]:
    rec = _tester_receipt(ctx, "nightly")
    if not rec or not _recent(rec.get("finished_at"), ctx):
        return []
    broken = rec.get("broken") or []
    if rec.get("status") != "FAILED" or not broken:
        return []
    kinds: dict[str, int] = {}
    for f in broken:
        kinds[str(f.get("kind"))] = kinds.get(str(f.get("kind")), 0) + 1
    top = ", ".join(f"{k} {n}" for k, n in sorted(kinds.items(), key=lambda x: -x[1])[:3])
    day = str(rec.get("finished_at") or "")[:10]
    return [
        Incident(
            "nightly_sweep",
            f"nightly_sweep:{day}:{rec.get('run_id')}",
            f"nightly site sweep: {len(broken)} broken finding(s) ({top})",
            at=rec.get("finished_at"),
            summary_path=rec.get("summary_path"),
        )
    ]


# request slots ----------------------------------------------------------------------------------------

_DOW = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def _dow_set(spec: str) -> Optional[set[int]]:
    out: set[int] = set()
    for part in spec.lower().split(","):
        if ".." in part:
            a, b = (x[:3] for x in part.split("..", 1))
            if a not in _DOW or b not in _DOW:
                return None
            i = _DOW[a]
            while True:
                out.add(i)
                if i == _DOW[b]:
                    break
                i = (i + 1) % 7
        elif part[:3] in _DOW:
            out.add(_DOW[part[:3]])
        else:
            return None
    return out


def parse_on_calendar(spec: str) -> Optional[tuple[Optional[set[int]], dtime, ZoneInfo]]:
    """The subset of systemd OnCalendar the request timers use: ``[DOW] *-*-* HH:MM[:SS] [TZ]``. None = unparsed."""
    toks = spec.split()
    if not toks:
        return None
    tz = ET
    if "/" in toks[-1]:
        try:
            tz = ZoneInfo(toks[-1])
        except Exception:  # noqa: BLE001
            return None
        toks = toks[:-1]
    days: Optional[set[int]] = None
    if toks and not toks[0][0].isdigit() and toks[0][0] != "*":
        days = _dow_set(toks[0])
        if days is None:
            return None
        toks = toks[1:]
    if len(toks) != 2 or toks[0] not in ("*-*-*",):
        return None
    m = re.fullmatch(r"([0-9]{1,2}):([0-9]{2})(?::([0-9]{2}))?", toks[1])
    if not m:
        return None
    return days, dtime(int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)), tz


def last_due(spec: str, now: datetime, horizon_h: float) -> Optional[datetime]:
    parsed = parse_on_calendar(spec)
    if parsed is None:
        return None
    days, at, tz = parsed
    local = now.astimezone(tz)
    for back in range(0, int(horizon_h // 24) + 2):
        d = (local - timedelta(days=back)).date()
        if days is not None and d.weekday() not in days:
            continue
        cand = datetime.combine(d, at, tzinfo=tz)
        if cand <= local and now - cand <= timedelta(hours=horizon_h):
            return cand.astimezone(timezone.utc)
    return None


def _calendar_specs(raw: str) -> list[str]:
    """``TimersCalendar`` -> the OnCalendar expressions (``{ OnCalendar=Mon..Fri *-*-* 12:00:00 ; next_elapse=...}``)."""
    return [m.strip() for m in re.findall(r"OnCalendar=([^;}]+)", raw or "")]


def _systemd_show_default(unit: str, props: tuple[str, ...]) -> Mapping[str, str]:
    p = subprocess.run(
        ["systemctl", "--user", "show", unit, *[f"-p{x}" for x in props]],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    out: dict[str, str] = {}
    for line in p.stdout.splitlines():
        k, _, v = line.partition("=")
        out[k] = v
    return out


def _systemd_timers_default() -> list[str]:
    p = subprocess.run(
        ["systemctl", "--user", "list-timers", "--all", "--no-legend", "--plain"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return sorted({t for t in p.stdout.split() if t.endswith(".timer")})


def _systemd_ts(v: str) -> Optional[datetime]:
    """``Sun 2026-10-25 06:00:01 EDT`` -> aware UTC (EST/EDT only; anything else unparsed)."""
    m = re.match(r"^\w{3} (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) (\w+)$", (v or "").strip())
    if not m:
        return None
    naive = datetime.fromisoformat(m.group(1))
    if m.group(2) in ("EDT", "EST"):
        return naive.replace(tzinfo=ET).astimezone(timezone.utc)
    if m.group(2) == "UTC":
        return naive.replace(tzinfo=timezone.utc)
    return None


def _request_present(ctx: Context, due: datetime, slot: str) -> bool:
    day = due.astimezone(ET).strftime("%Y%m%d")
    base = ctx.release_state_dir / "train_requests"
    name = f"rtw-{day}-{slot}-win.json"
    return any((base / sub / name).exists() for sub in ("pending", "claimed", "receipts", "journal"))


def detect_request_slots(ctx: Context) -> list[Incident]:
    cfg = ctx.config.get("request_slots") or {}
    prefix = str(cfg.get("unit_prefix") or "tradeai-release-train-request@")
    grace = timedelta(minutes=float(cfg.get("grace_minutes", 15)))
    horizon = float(cfg.get("horizon_hours", 26))
    show = ctx.systemd_show or _systemd_show_default
    try:
        timers = (ctx.systemd_timers or _systemd_timers_default)()
    except Exception as exc:  # noqa: BLE001
        ctx.notes.append(f"request_slot_missed: systemd unreadable ({type(exc).__name__})")
        return []
    out: list[Incident] = []
    for unit in timers:
        m = UNIT_RE.match(unit)
        if not m or m.group("prefix") != prefix:
            continue
        slot = m.group("slot")
        props = show(unit, ("LoadState", "UnitFileState", "ActiveState", "TimersCalendar", "LastTriggerUSec"))
        if props.get("LoadState") != "loaded" or props.get("UnitFileState") not in ("enabled", "enabled-runtime"):
            continue
        dues = [
            d
            for d in (last_due(s, ctx.now, horizon) for s in _calendar_specs(props.get("TimersCalendar", "")))
            if d is not None
        ]
        if not dues:
            if props.get("TimersCalendar"):
                ctx.notes.append(f"request_slot_missed: {unit} calendar not understood; not checked")
            continue
        due = max(dues)
        if ctx.now - due < grace:
            continue
        last = _systemd_ts(props.get("LastTriggerUSec", ""))
        due_et = due.astimezone(ET).strftime("%a %H:%M ET")
        key = f"request_slot_missed:{slot}:{due.astimezone(ET).strftime('%Y%m%d')}"
        if props.get("ActiveState") != "active" or last is None or last < due - timedelta(seconds=60):
            out.append(
                Incident(
                    "request_slot_missed",
                    key,
                    f"release-train request {slot} did not fire for {due_et}",
                    detail=f"timer {props.get('ActiveState')}; last trigger {props.get('LastTriggerUSec') or 'never'}",
                    at=due.isoformat(),
                )
            )
            continue
        svc = show(unit[: -len(".timer")] + ".service", ("Result", "ExecMainStatus"))
        if svc.get("Result") not in (None, "", "success"):
            out.append(
                Incident(
                    "request_slot_missed",
                    key,
                    f"release-train request {slot} FAILED for {due_et}: {svc.get('Result')} "
                    f"(exit {svc.get('ExecMainStatus')})",
                    at=due.isoformat(),
                )
            )
            continue
        if not _request_present(ctx, due, slot):
            out.append(
                Incident(
                    "request_slot_missed",
                    key,
                    f"release-train request {slot} fired for {due_et} but wrote no request",
                    at=due.isoformat(),
                )
            )
    return out


DETECTORS: dict[str, Callable[[Context], list[Incident]]] = {
    "main_ci_red": detect_main_ci,
    "train_outcome": detect_train_outcomes,
    "train_receipt": detect_train_receipts,
    "stop_latched": detect_stop_latch,
    "post_release_tester": detect_post_release,
    "nightly_sweep": detect_nightly_sweep,
    "request_slot_missed": detect_request_slots,
}


def detect_all(ctx: Context, only: Optional[Iterable[str]] = None) -> list[Incident]:
    wanted = set(only or TRIGGERS)
    out: list[Incident] = []
    train_shas: set[str] = set()
    for trig in TRIGGERS:
        if trig not in wanted or not _enabled(ctx, trig):
            continue
        try:
            if trig == "manual_release":
                found = detect_manual_release(ctx, train_shas=train_shas)
            else:
                found = DETECTORS[trig](ctx)
        except Exception as exc:  # noqa: BLE001 — one broken detector never silences the others
            ctx.notes.append(f"{trig}: detector error {type(exc).__name__}: {one_line(exc, 120)}")
            out.append(
                Incident(
                    trig, f"detector_error:{trig}", f"failure-alert detector {trig} crashed", detail=one_line(exc, 160)
                )
            )
            continue
        if trig == "train_outcome":
            for i in found:
                doc = _read_json(Path(i.summary_path or "")) or {}
                train_shas.update(str(doc.get(k) or "") for k in ("candidate_sha", "main_sha", "served_sha"))
        out.extend(found)
    seen: set[str] = set()
    return [i for i in out if not (i.key in seen or seen.add(i.key))]


# ── channels ───────────────────────────────────────────────────────────────────────────────────────


def channel_readiness(config: Mapping[str, Any], env: Optional[Mapping[str, str]] = None) -> dict[str, dict]:
    """Per channel: ready / why. Tests only whether a key is set; never returns or logs a value."""
    env = os.environ if env is None else env
    out: dict[str, dict] = {}
    for ch in CHANNELS:
        c = (config.get("channels") or {}).get(ch) or {}
        if not c.get("enabled", False):
            out[ch] = {"ready": False, "status": DISABLED, "why": "disabled in config"}
            continue
        flag = c.get("enable_flag")
        if flag and str(env.get(flag, c.get("enable_flag_default", "true"))).strip().lower() != "true":
            out[ch] = {"ready": False, "status": NOT_CONFIGURED, "why": f"{flag} is not true"}
            continue
        need_all = list(c.get("required_env_all") or [])
        missing = [k for k in need_all if not str(env.get(k) or "").strip()]
        if missing:
            out[ch] = {"ready": False, "status": NOT_CONFIGURED, "why": "missing " + ", ".join(missing)}
            continue
        any_sets = [list(s) for s in c.get("required_env_any") or []]
        if any_sets and not any(all(str(env.get(k) or "").strip() for k in s) for s in any_sets):
            out[ch] = {
                "ready": False,
                "status": NOT_CONFIGURED,
                "why": "needs one of: " + " | ".join("+".join(s) for s in any_sets),
            }
            continue
        out[ch] = {"ready": True, "status": "READY", "why": ""}
    return out


def render(incidents: list[Incident], config: Mapping[str, Any]) -> dict[str, Any]:
    """One message for these incidents: ``text`` (Telegram), ``subject``/``body`` (email), ``sms``."""
    link = releases_link(config)
    sms_max = int(((config.get("channels") or {}).get("sms") or {}).get("max_chars", 155))
    if len(incidents) == 1:
        i = incidents[0]
        head = f"TRADE AI FAILURE: {i.line}"
        text = f"{head} — {link}"
        subject = one_line(f"Trade AI failure: {i.line}", 120)
        body_lines = [head, ""] + ([i.detail, ""] if i.detail else []) + [f"Releases & schedules: {link}"]
        if i.summary_path:
            body_lines.append(f"Summary file: {i.summary_path}")
        sms = one_line(f"TradeAI FAIL: {i.line}", sms_max)
    else:
        head = f"TRADE AI FAILURES ({len(incidents)})"
        lines = [f"• {one_line(i.line, 160)}" for i in incidents[:10]]
        if len(incidents) > 10:
            lines.append(f"• … and {len(incidents) - 10} more")
        text = "\n".join([head, *lines, link])
        subject = f"Trade AI: {len(incidents)} delivery failures"
        body_lines = [head, "", *lines, ""]
        for i in incidents[:10]:
            if i.summary_path:
                body_lines.append(f"{i.trigger}: {i.summary_path}")
        body_lines.append(f"Releases & schedules: {link}")
        sms = one_line(f"TradeAI: {len(incidents)} failures. {incidents[0].line}", sms_max)
    return {"text": text, "subject": subject, "body": "\n".join(body_lines), "sms": sms, "link": link}


Sender = Callable[[dict, str], dict]  # (message, identity) -> {"ok": bool, "error": str|None, ...}


def default_senders() -> dict[str, Sender]:
    def telegram(msg: dict, identity: str) -> dict:
        try:
            from telegram_alert import send_telegram
        except ImportError:
            from scripts.telegram_alert import send_telegram  # type: ignore[no-redef]
        ok = send_telegram(msg["text"], priority="P1", dedupe_minutes=0, producer=PRODUCER)
        return {"ok": bool(ok), "error": None if ok else "not_accepted"}

    def gateway(channel: str) -> Sender:
        def send(msg: dict, identity: str) -> dict:
            from scripts.lib.comms.channel_adapters import send_via_gateway

            gw = send_via_gateway(
                channel,
                body=msg["sms"] if channel == "sms" else msg["body"],
                subject=msg["subject"] if channel == "email" else None,
                producer=PRODUCER,
                subject_key=f"{identity}:{channel}",
                event_type="delivery_failure_alert",
                message_class="ops",
                retention_class="operational_30d",
                deliver=True,
                severity="critical",
            )
            return {
                "ok": bool(gw.get("delivered")),
                "error": gw.get("error"),
                "gateway_mode": gw.get("gateway_mode"),
                "event_id": gw.get("event_id"),
            }

        return send

    return {"telegram": telegram, "email": gateway("email"), "sms": gateway("sms")}


# ── dedupe state + plan ────────────────────────────────────────────────────────────────────────────


def load_state(path: Path) -> dict[str, Any]:
    doc = _read_json(path)
    if not doc or doc.get("schema") != STATE_SCHEMA:
        return {"schema": STATE_SCHEMA, "incidents": {}, "sends": []}
    doc.setdefault("incidents", {})
    doc.setdefault("sends", [])
    return doc


def due(incidents: list[Incident], state: Mapping[str, Any], now: datetime, remind_h: float) -> list[Incident]:
    out = []
    for i in incidents:
        prev = (state.get("incidents") or {}).get(i.key)
        last = parse_ts((prev or {}).get("last_sent_at"))
        if last is None or now - last >= timedelta(hours=remind_h):
            out.append(i)
    return out


def plan_messages(
    due_now: list[Incident], state: Mapping[str, Any], now: datetime, config: Mapping[str, Any]
) -> tuple[list[list[Incident]], list[Incident]]:
    """(groups to send, incidents held by the hourly cap). Pure."""
    cap = int(config.get("max_messages_per_hour", 6))
    sent_last_hour = sum(
        1 for s in state.get("sends") or [] if (t := parse_ts(s)) is not None and now - t < timedelta(hours=1)
    )
    budget = max(0, cap - sent_last_hour)
    if not due_now or budget == 0:
        return [], list(due_now)
    sep = int(config.get("max_separate_per_run", 3))
    groups = [[i] for i in due_now] if len(due_now) <= sep else [list(due_now)]
    return groups[:budget], [i for g in groups[budget:] for i in g]


def run(
    ctx: Context,
    *,
    live: bool,
    senders: Optional[Mapping[str, Sender]] = None,
    env: Optional[Mapping[str, str]] = None,
    only: Optional[Iterable[str]] = None,
) -> dict[str, Any]:
    """Detect, plan, and (live) send. Returns the DeliveryFailureAlerts@v1 receipt; writes it (and, live, the state)."""
    from scripts.lib.atomic_json_store import append_jsonl, atomic_write_json

    cfg = ctx.config
    incidents = detect_all(ctx, only)
    state_path = ctx.state_root / STATE_REL
    state = load_state(state_path)
    now = ctx.now
    due_now = due(incidents, state, now, float(cfg.get("remind_hours", 24)))
    groups, held = plan_messages(due_now, state, now, cfg)
    ready = channel_readiness(cfg, env)
    send = dict(senders or (default_senders() if live else {}))
    messages = []
    for g in groups:
        msg = render(g, cfg)
        identity = "dfa:" + "|".join(sorted(i.key for i in g))[:200]
        skip_all = set(g[0].skip_channels) if all(set(i.skip_channels) == set(g[0].skip_channels) for i in g) else set()
        results: dict[str, dict] = {}
        for ch in CHANNELS:
            r = ready[ch]
            if ch in skip_all:
                results[ch] = {"status": SKIPPED, "why": g[0].skip_reason or "already sent"}
            elif not r["ready"]:
                results[ch] = {"status": r["status"], "why": r["why"]}
            elif not live:
                results[ch] = {"status": DRY_RUN}
            else:
                try:
                    res = send[ch](msg, identity)
                except Exception as exc:  # noqa: BLE001 — recorded; another channel still goes out
                    res = {"ok": False, "error": f"{type(exc).__name__}: {one_line(exc, 120)}"}
                results[ch] = {
                    "status": SENT if res.get("ok") else FAILED,
                    **{k: v for k, v in res.items() if k in ("error", "gateway_mode", "event_id")},
                }
        delivered = any(v["status"] == SENT for v in results.values())
        messages.append(
            {
                "incident_keys": [i.key for i in g],
                "triggers": sorted({i.trigger for i in g}),
                "rendered": msg,
                "channels": results,
                "delivered": delivered,
            }
        )
        if live and delivered:
            for i in g:
                prev = state["incidents"].get(i.key) or {"first_sent_at": now.isoformat(), "count": 0}
                state["incidents"][i.key] = {
                    **prev,
                    "last_sent_at": now.isoformat(),
                    "count": prev["count"] + 1,
                    "trigger": i.trigger,
                    "line": i.line,
                }
            state["sends"].append(now.isoformat())
    receipt = {
        "schema": SCHEMA,
        "mode": "live" if live else "dry_run",
        "as_of": now.isoformat(),
        "state_root": str(ctx.state_root),
        "release_state_dir": str(ctx.release_state_dir),
        "deploy_state_dir": str(ctx.deploy_state_dir),
        "incidents": [i.to_dict() for i in incidents],
        "due": [i.key for i in due_now],
        "held_rate_limited": [i.key for i in held],
        "messages": messages,
        "channel_readiness": ready,
        "notes": list(ctx.notes),
        "ok": all(m["delivered"] for m in messages) if live else True,
    }
    if live:
        state["sends"] = [s for s in state["sends"] if (t := parse_ts(s)) and now - t < timedelta(hours=24)]
        cutoff = now - timedelta(days=14)
        state["incidents"] = {
            k: v for k, v in state["incidents"].items() if (t := parse_ts(v.get("last_sent_at"))) and t >= cutoff
        }
        atomic_write_json(state_path, state)
        atomic_write_json(ctx.state_root / RECEIPT_REL, receipt)
        append_jsonl(
            ctx.state_root / HISTORY_REL,
            {k: receipt[k] for k in ("as_of", "mode", "due", "ok")}
            | {
                "messages": [
                    {"keys": m["incident_keys"], "channels": {c: v["status"] for c, v in m["channels"].items()}}
                    for m in messages
                ]
            },
        )
    else:
        atomic_write_json(ctx.state_root / DRY_RUN_RECEIPT_REL, receipt)
    return receipt
