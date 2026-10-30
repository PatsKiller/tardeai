#!/usr/bin/env python3
"""disk_monitor.py — host-resident disk GROWTH monitor: baseline + transition alerts, no deletion.

The n8n band monitor (scripts/disk_usage_monitor.py, lane ``disk-usage-monitor``) fires only when ``/`` crosses
80/90% used and is gated behind the n8n relay; it keeps no baseline, so a store growing 63 MB/day or a cache that
doubles between polls is invisible until the band trips. The 2026-10-30 ENOSPC (root hit 98%, holdings.json
truncated to 0 bytes, Command Center broke) happened with no growth signal at all.

This monitor is host-resident (never n8n, not LLM-heavy), runs a few times a day, and is the growth half of the
pair:

    python3 scripts/disk_monitor.py                  # default = --dry-run: measure + print, write/send NOTHING
    python3 scripts/disk_monitor.py --apply          # record the baseline + alert on a TRANSITION + LaneRunReceipt
    python3 scripts/disk_monitor.py --with-hygiene   # also run scripts/disk_hygiene.py --dry-run and quote it

What it measures (config/config/disk_monitor.json):
  * df-style used% of each mount (used / (used + available), the same reach disk_usage_monitor uses);
  * du of each hotspot (the known ENOSPC consumers: ~/.cache, ~/.npm, ~/.codex, ~/.hermes/state.db, ~/logs,
    ~/worktrees, ~/wt, ~/wt-*, ~/tradeai-wt-*);
  * per-mount growth vs a rolling ``growth_window_hours`` window and per-hotspot growth vs the persisted baseline.

Baseline: ``<state root>/data/runtime/disk_monitor_baseline.json`` (DiskMonitorBaseline@v1), written atomically.
The first run seeds it and sends nothing. Later runs alert ONLY on a TRANSITION into warn/critical via
telegram_alert.send_telegram, deduped by lib/alert_condition_state (condition keys ``host:disk_monitor:<mount>:used``,
``host:disk_monitor:<mount>:growth``, ``host:disk_monitor_hotspot:<id>``). warn -> P2, critical -> P1 (disk about to
fill is operator-actionable). It NEVER deletes: the alert names the exact paths + sizes, the reclaimable estimate
from the latest disk_hygiene manifest, and the operator-gated purge command; ``--with-hygiene`` additionally quotes
``scripts/disk_hygiene.py --dry-run``.

Fail closed (§7): a mount or hotspot that cannot be measured keeps its prior baseline value and records the failure
beside it — never an error string in the value slot, never a silent zero. An unmeasurable hotspot is a degradation
(recorded), not a run failure; only an unmeasurable mount or a failed write/send fails the run.

Exit: 0 = measured and (in --apply) baseline + receipt written and any due alert accepted; 1 = config unreadable, a
mount unmeasurable, a write failed, or a send failed; 2 = usage. MBI_BEHAVIOR = 0. No broker, no DB, no network
beyond the Telegram chokepoint (scripts/telegram_alert.py).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib import lane_last_receipt as R  # noqa: E402

LANE_ID = "disk-monitor"
SCRIPT = "scripts/disk_monitor.py"
CONFIG_PATH = ROOT / "config" / "disk_monitor.json"
CONFIG_SCHEMA = "DiskMonitorConfig@v1"
BASELINE_SCHEMA = "DiskMonitorBaseline@v1"
BANDS = ("ok", "warn", "critical")
SKIP_DEPENDENCY = "dependency_unavailable"


class ConfigError(ValueError):
    pass


# ── config ────────────────────────────────────────────────────────────────────────────────────────────────────────


def _expand(p: str, home: Path) -> Path:
    if p == "~":
        return home
    if p.startswith("~/"):
        return home / p[2:]
    return Path(p)


def hotspot_targets(entry: Mapping[str, Any], home: Path) -> list[Path]:
    p = _expand(str(entry["path"]), home)
    if entry.get("glob"):
        return sorted(x for x in p.parent.glob(p.name) if not x.is_symlink())
    return [p]


def load_config(path: Optional[Path] = None, *, home: Optional[Path] = None) -> dict[str, Any]:
    """Read config/disk_monitor.json with ``~`` expanded; raises ConfigError when unreadable or incomplete."""
    p = Path(path) if path else CONFIG_PATH
    try:
        raw = p.read_bytes()
        doc = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"monitor_config_unreadable:{type(exc).__name__}") from exc
    if not isinstance(doc, dict) or doc.get("schema") != CONFIG_SCHEMA:
        raise ConfigError("monitor_config_schema")
    for key in (
        "mounts", "warn_pct", "critical_pct", "grow_warn_bytes", "grow_critical_bytes",
        "hotspot_growth_min_bytes", "hotspot_growth_ratio", "state_name", "producer", "hotspots",
    ):
        if key not in doc:
            raise ConfigError(f"monitor_config_missing:{key}")
    if not float(doc["warn_pct"]) < float(doc["critical_pct"]):
        raise ConfigError("monitor_thresholds_out_of_order")
    h = Path(home) if home else _expand(str(doc.get("home") or "~"), Path.home())
    doc["_home"] = h
    doc["_path"] = str(p)
    doc["_sha256"] = hashlib.sha256(raw).hexdigest()
    doc["_hotspots"] = [{**e, "_paths": hotspot_targets(e, h)} for e in doc["hotspots"]]
    return doc


# ── measurement (read only) ────────────────────────────────────────────────────────────────────────────────────────


def measure_mount(mount: str) -> Optional[dict[str, Any]]:
    """df-style usage of ``mount`` (used / (used + available)); None when statvfs fails. Mirrors
    scripts/disk_usage_monitor.measure."""
    try:
        st = os.statvfs(mount)
    except OSError:
        return None
    used = (st.f_blocks - st.f_bfree) * st.f_frsize
    avail = st.f_bavail * st.f_frsize
    reach = used + avail
    return {
        "mount": mount,
        "used_pct": round(used / reach * 100.0, 2) if reach else 0.0,
        "used_bytes": used,
        "avail_bytes": avail,
        "size_bytes": st.f_blocks * st.f_frsize,
    }


def du_bytes(path: Path, timeout_s: float) -> Optional[int]:
    """Disk usage (bytes) like ``du -sB1 -x``; None when du fails or times out. Mirrors scripts/disk_hygiene.du_bytes."""
    try:
        proc = subprocess.run(["du", "-s", "-B1", "-x", str(path)], capture_output=True, text=True, timeout=timeout_s)
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        return int(proc.stdout.split()[0])
    except (IndexError, ValueError):
        return None


def measure_hotspots(mon: Mapping[str, Any], now: datetime) -> list[dict[str, Any]]:
    """One row per configured hotspot: total bytes over its (possibly globbed) paths. A path that cannot be measured
    is counted as unmeasured (fail closed); the row's bytes are the sum of the measured paths, or None when none
    measured."""
    to = float(mon.get("du_timeout_s") or 120)
    out: list[dict[str, Any]] = []
    for e in mon["_hotspots"]:
        total = 0
        measured = 0
        unmeasured = 0
        for p in e["_paths"]:
            b = du_bytes(p, to)
            if b is None:
                unmeasured += 1
            else:
                total += b
                measured += 1
        out.append({
            "id": e["id"], "path": e["path"], "purge": e.get("purge") or "",
            "bytes": total if measured else None,
            "measured_paths": measured, "unmeasured": unmeasured,
            "measured_at": now.isoformat(),
        })
    return out


# ── bands / flags (pure) ───────────────────────────────────────────────────────────────────────────────────────────


def band_of(pct: float, mon: Mapping[str, Any]) -> str:
    if pct >= float(mon["critical_pct"]):
        return "critical"
    if pct >= float(mon["warn_pct"]):
        return "warn"
    return "ok"


def growth_band(delta: Optional[int], mon: Mapping[str, Any]) -> str:
    if delta is None:
        return "unknown"
    if delta >= int(mon["grow_critical_bytes"]):
        return "critical"
    if delta >= int(mon["grow_warn_bytes"]):
        return "warn"
    return "ok"


def hotspot_flag(cur: Optional[int], base: Optional[int], mon: Mapping[str, Any]) -> str:
    if cur is None:
        return "unknown"
    if base is None or base <= 0:
        return "new"
    if cur >= int(mon["hotspot_growth_min_bytes"]) and cur >= float(mon["hotspot_growth_ratio"]) * base:
        return "growing"
    return "ok"


def condition_key(mount: str, kind: str) -> str:
    """The stable dedupe key (never a raw percent, never a timestamp): band changes are the only transitions."""
    return f"host:disk_monitor:{mount}:{kind}"


# ── baseline ───────────────────────────────────────────────────────────────────────────────────────────────────────


def baseline_path(state_root: Optional[Path], mon: Mapping[str, Any]) -> Path:
    return R.runtime_dir(state_root) / mon["state_name"]


def load_baseline(state_root: Optional[Path], mon: Mapping[str, Any]) -> dict[str, Any]:
    p = baseline_path(state_root, mon)
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) and doc.get("schema") == BASELINE_SCHEMA else {}


def growth_reference(baseline: Mapping[str, Any], mon: Mapping[str, Any], now: datetime, mount: str) -> Optional[int]:
    """The reference ``used_bytes`` to measure growth against: the earliest sample within growth_window_hours (so the
    delta spans the whole window), else the baseline mount value. None when neither exists."""
    window = float(mon.get("growth_window_hours") or 24) * 3600.0
    best: Optional[tuple[float, int]] = None
    for s in baseline.get("samples") or []:
        try:
            at = datetime.fromisoformat(str(s.get("at"))).timestamp()
        except (ValueError, TypeError):
            continue
        v = (s.get("mounts") or {}).get(mount)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and now.timestamp() - window <= at <= now.timestamp():
            if best is None or at < best[0]:
                best = (at, int(v))
    if best is not None:
        return best[1]
    m = (baseline.get("mounts") or {}).get(mount) or {}
    if isinstance(m.get("used_bytes"), (int, float)) and not isinstance(m.get("used_bytes"), bool):
        return int(m["used_bytes"])
    return None


def evaluate(baseline: Mapping[str, Any], mounts: list[dict], hotspots: list[dict],
             mon: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    """Pure: turn raw measurements into bands, growth deltas and hotspot flags. No I/O."""
    rows: list[dict[str, Any]] = []
    for m in mounts:
        if "used_pct" not in m:
            rows.append({"mount": m["mount"], "error": m["error"]})
            continue
        ref = growth_reference(baseline, mon, now, m["mount"])
        delta = (m["used_bytes"] - ref) if ref is not None else None
        window = float(mon.get("growth_window_hours") or 24)
        rate = (delta / window * 24) if delta is not None else None
        rows.append({
            **m,
            "used_band": band_of(m["used_pct"], mon),
            "growth_band": growth_band(delta, mon),
            "delta_bytes": delta,
            "rate_bytes_per_day": rate,
        })
    base_hs: dict[str, Any] = {}
    for hid, entry in (baseline.get("hotspots") or {}).items():
        if isinstance(entry, dict):
            base_hs[hid] = entry.get("bytes")
    hs: list[dict[str, Any]] = []
    for h in hotspots:
        base = base_hs.get(h["id"])
        hs.append({**h, "baseline_bytes": base, "flag": hotspot_flag(h["bytes"], base, mon)})
    return {"mounts": rows, "hotspots": hs}


def build_baseline(mon: Mapping[str, Any], mounts: list[dict], hotspots: list[dict],
                   now: datetime, previous: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    prev = dict(previous or {})
    mounts_map = dict(prev.get("mounts") or {})
    for m in mounts:
        if "used_pct" not in m:
            continue
        mounts_map[m["mount"]] = {
            "used_bytes": m["used_bytes"], "used_pct": m["used_pct"],
            "size_bytes": m["size_bytes"], "avail_bytes": m["avail_bytes"],
            "recorded_at": now.isoformat(),
        }
    hs_map = dict(prev.get("hotspots") or {})
    for h in hotspots:
        if h["bytes"] is None:
            # fail closed: keep the prior value, record the failure beside it — never the error as the value
            prior = hs_map.get(h["id"]) or {}
            hs_map.setdefault(h["id"], {"bytes": prior.get("bytes"), "path": h["path"]})
            hs_map[h["id"]]["unmeasured"] = h.get("unmeasured") or 0
            hs_map[h["id"]]["last_failure"] = now.isoformat()
            continue
        hs_map[h["id"]] = {"bytes": h["bytes"], "path": h["path"], "recorded_at": now.isoformat()}
    samples = [s for s in (prev.get("samples") or []) if isinstance(s, dict)]
    samples.append({
        "at": now.isoformat(),
        "mounts": {m["mount"]: m["used_bytes"] for m in mounts if "used_pct" in m},
        "hotspots": {h["id"]: h["bytes"] for h in hotspots},
    })
    samples = samples[-int(mon.get("samples_to_keep") or 8):]
    return {
        "schema": BASELINE_SCHEMA,
        "baseline_at": prev.get("baseline_at") or now.isoformat(),
        "updated_at": now.isoformat(),
        "mounts": mounts_map,
        "hotspots": hs_map,
        "samples": samples,
    }


# ── hygiene reclaim estimate (read only) ───────────────────────────────────────────────────────────────────────────


def latest_manifest(state_root: Optional[Path], mon: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    root = state_root if state_root else R.runtime_dir(None).parent.parent
    p = root / mon["hygiene_manifest_rel"]
    try:
        m = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError):
        return None
    t = m.get("totals") or {}
    return {
        "generated_at": m.get("generated_at"),
        "candidates": t.get("candidates"),
        "reclaimable_bytes": t.get("reclaimable_bytes"),
    }


def hygiene_dry_run(mon: Mapping[str, Any]) -> str:
    """Run scripts/disk_hygiene.py --dry-run --report (read only) and return its combined output."""
    rules = ROOT / mon.get("hygiene_rules_rel", "config/disk_hygiene_rules.json")
    cmd = [sys.executable, str(ROOT / "scripts" / "disk_hygiene.py"), "--dry-run", "--report", "--rules", str(rules)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=float(mon.get("du_timeout_s") or 600))
    except (OSError, subprocess.SubprocessError) as exc:
        return f"hygiene_dry_run_unavailable:{type(exc).__name__}"
    out = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    return out.strip() or f"hygiene_dry_run_empty_rc:{proc.returncode}"


def purge_command(mon: Mapping[str, Any]) -> str:
    return mon.get("purge_command", "").replace("{py}", sys.executable)


# ── alert text ─────────────────────────────────────────────────────────────────────────────────────────────────────


def _gb(n: Optional[int]) -> str:
    return f"{(n or 0) / 1024**3:.1f}G"


def mount_alert_text(m: Mapping[str, Any], mon: Mapping[str, Any],
                     manifest: Optional[Mapping[str, Any]], hotspots: list[dict]) -> tuple[str, str]:
    """(subject, summary) for a mount transition. The subject names what actually tripped (used% and/or growth),
    never a bare threshold on the wrong axis."""
    mount = m["mount"]
    used = m["used_band"]
    growth = m["growth_band"]
    if used == "ok" and growth == "ok":
        subject = f"Disk {mount} recovered: below {float(mon['warn_pct']):.0f}% used"
    else:
        sev = "critical" if "critical" in (used, growth) else "warn"
        triggers: list[str] = []
        if used != "ok":
            thr = float(mon["critical_pct"] if used == "critical" else mon["warn_pct"])
            triggers.append(f"used at or above {thr:.0f}%")
        if growth not in ("ok", "unknown"):
            gthr = int(mon["grow_critical_bytes"] if growth == "critical" else mon["grow_warn_bytes"])
            triggers.append(f"growth at or above {_gb(gthr)}/{float(mon.get('growth_window_hours') or 24):.0f}h")
        subject = f"Disk {mount} {sev.upper()}: " + " and ".join(triggers)
    parts = [f"{m['used_pct']:.1f}% used, {_gb(m['avail_bytes'])} free of {_gb(m['size_bytes'])}"]
    if m.get("delta_bytes") is not None:
        parts.append(f"growth {_gb(m['delta_bytes'])} over {float(mon.get('growth_window_hours') or 24):.0f}h"
                     f" (rate {_gb(m.get('rate_bytes_per_day'))}/day)")
    if hotspots:
        parts.append("top: " + ", ".join(f"{h['id']} {_gb(h['bytes'])}" for h in hotspots))
    if manifest and manifest.get("reclaimable_bytes") is not None:
        parts.append(f"reclaimable {_gb(manifest['reclaimable_bytes'])} in {manifest.get('candidates')} items"
                     f" per hygiene manifest {str(manifest.get('generated_at') or '')[:16]} (apply is operator-gated)")
    parts.append("purge: " + purge_command(mon))
    return subject, "; ".join(parts)


def hotspot_alert_text(h: Mapping[str, Any]) -> str:
    return (f"Hotspot {h['id']} growing: {_gb(h['bytes'])} now (baseline {_gb(h.get('baseline_bytes'))},"
            f" +{_gb((h['bytes'] or 0) - (h.get('baseline_bytes') or 0))}); purge: {h.get('purge') or 'none'}")


# ── notify ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def default_notify(text: str, priority: str) -> str:
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from telegram_alert import send_telegram  # noqa: PLC0415 (host-only lane; never an n8n closure)

        ok = send_telegram(text, message_class="operator_alert", priority=priority, producer="disk_monitor")
        return "accepted" if ok else "send_returned_false"
    except Exception as exc:  # noqa: BLE001 - alerting never raises past the monitor
        return f"error:{type(exc).__name__}"


def _observe(key: str, band: str, alertable: bool, mon: Mapping[str, Any],
             state_path: Optional[Path], extra: Mapping[str, Any]) -> dict[str, Any]:
    from scripts.lib.alert_condition_state import observe

    try:
        return observe(key, band, alertable=alertable, path=state_path,
                       min_realert_minutes=int(mon.get("realert_minutes") or 360), extra=dict(extra))
    except Exception as exc:  # noqa: BLE001 - a dedupe-state failure never suppresses measurement
        return {"action": "error", "notify": False, "error": type(exc).__name__, "key": key, "state": band}


def _load_condition(state_path: Optional[Path]) -> dict[str, Any]:
    """Read-only peek at the dedupe store (never writes). A dry run predicts its sends from this, so --dry-run
    exercises the real transition rule without mutating the store (AGENTS.md §6: a dry run must not reach the write)."""
    try:
        from scripts.lib.alert_condition_state import load_store

        return (load_store(state_path) or {}).get("conditions") or {}
    except Exception:  # noqa: BLE001
        return {}


def _predict_notify(prev: Optional[Mapping[str, Any]], band: str, alertable: bool) -> bool:
    """Whether ``observe()`` would notify for a transition, given the stored prior record (no write, no heartbeat
    re-alert — a dry run never advances the real clock)."""
    if prev is None:
        return bool(alertable)
    prev_state = prev.get("state")
    prev_alertable = bool(prev.get("alertable")) if prev else None
    if prev_state == band and bool(prev_alertable) == bool(alertable):
        return False  # ongoing: no new event
    if prev_alertable and not alertable:
        return True  # recovered
    if prev_state != band:
        return bool(alertable)  # new / reversed / cleared
    return bool(alertable)  # same state string, alertable flipped False -> True


def _transition(apply: bool, key: str, band: str, alertable: bool, mon: Mapping[str, Any],
                state_path: Optional[Path], extra: Mapping[str, Any]) -> dict[str, Any]:
    """observe (write) in --apply, predict (read-only) in --dry-run. Same transition rule either way."""
    if apply:
        return _observe(key, band, alertable, mon, state_path, extra)
    prev = _load_condition(state_path).get(key)
    return {"notify": _predict_notify(prev, band, alertable), "action": "dry-run-predicted",
            "key": key, "state": band}


# ── run ────────────────────────────────────────────────────────────────────────────────────────────────────────────


def run(
    *,
    mon: Mapping[str, Any],
    state_root: Optional[Path],
    apply: bool,
    now: datetime,
    wall_start: Optional[datetime] = None,
    notify: Optional[Callable[[str, str], str]] = None,
    alert_state_path: Optional[Path] = None,
    with_hygiene: bool = False,
) -> int:
    notify = notify or default_notify  # resolved at call time so tests can monkeypatch module.default_notify
    wall_start = wall_start or datetime.now(timezone.utc)
    failures = 0
    mounts: list[dict[str, Any]] = []
    for mount in mon["mounts"]:
        m = measure_mount(mount)
        if m is None:
            mounts.append({"mount": mount, "error": "statvfs_failed"})
            failures += 1
        else:
            mounts.append(m)
    hotspots = measure_hotspots(mon, now)
    degraded_hotspots = sum(1 for h in hotspots if h["bytes"] is None)  # fail-closed, not a run failure (§7)
    manifest = latest_manifest(state_root, mon)
    hygiene_out = hygiene_dry_run(mon) if with_hygiene else None
    baseline = load_baseline(state_root, mon)
    ev = evaluate(baseline, mounts, hotspots, mon, now)
    next_baseline = build_baseline(mon, mounts, hotspots, now, baseline or None)
    bpath = baseline_path(state_root, mon)

    sends: list[dict[str, Any]] = []
    if baseline:
        top_hotspots = sorted((h for h in ev["hotspots"] if h["bytes"] is not None),
                              key=lambda h: -(h["bytes"] or 0))[: int(mon.get("top_consumers") or 5)]
        # mount used-band + growth-band, one alert per mount per transition
        for m in ev["mounts"]:
            if "used_pct" not in m:
                continue
            used_obs = _transition(apply, condition_key(m["mount"], "used"), m["used_band"],
                                   m["used_band"] != "ok", mon, alert_state_path, {"used_pct": m["used_pct"]})
            grow_obs = _transition(apply, condition_key(m["mount"], "growth"), m["growth_band"],
                                   m["growth_band"] not in ("ok", "unknown"),
                                   mon, alert_state_path, {"delta_bytes": m.get("delta_bytes")})
            if used_obs.get("notify") or grow_obs.get("notify"):
                subject, summary = mount_alert_text(m, mon, manifest, top_hotspots)
                priority = "P1" if "critical" in (m["used_band"], m["growth_band"]) else "P2"
                if not apply:
                    sends.append({"kind": "mount", "subject": subject, "summary": summary, "priority": priority})
                    continue
                body = subject + "\n" + summary
                if with_hygiene and hygiene_out:
                    body += "\n" + hygiene_out[:1500]
                outcome = notify(body, priority)
                sends.append({"kind": "mount", "subject": subject, "summary": summary, "priority": priority,
                              "outcome": outcome})
                if outcome.startswith("error:"):
                    failures += 1
        # hotspot growth, P2 (diagnostic; the mount alert is the actionable one)
        for h in ev["hotspots"]:
            if h["flag"] not in ("growing", "new"):
                continue
            obs = _transition(apply, condition_key(h["id"], "hotspot"), h["flag"], True, mon, alert_state_path,
                              {"bytes": h["bytes"], "baseline_bytes": h.get("baseline_bytes")})
            if obs.get("notify"):
                if not apply:
                    sends.append({"kind": "hotspot", "hotspot": h["id"], "priority": "P2",
                                  "summary": hotspot_alert_text(h)})
                    continue
                outcome = notify(hotspot_alert_text(h), "P2")
                sends.append({"kind": "hotspot", "hotspot": h["id"], "priority": "P2", "outcome": outcome})
                if outcome.startswith("error:"):
                    failures += 1

    report = {
        "dry_run": not apply,
        "mode": "apply" if apply else "dry-run",
        "now": now.isoformat(),
        "host": os.uname().nodename if hasattr(os, "uname") else "",
        "config": mon["_path"],
        "baseline": str(bpath),
        "first_run": not baseline,
        "mounts": ev["mounts"],
        "hotspots": ev["hotspots"],
        "manifest": manifest,
        "hygiene_dry_run": hygiene_out,
        "would_send": sends if not apply else None,
        "sent": sends if apply else None,
        "degraded_hotspots": degraded_hotspots,
        "failures": failures,
    }
    if not apply:
        R.dry_run_report(
            LANE_ID,
            {k: report[k] for k in ("mounts", "hotspots", "manifest", "would_send", "first_run",
                                    "degraded_hotspots", "failures")},
            would_write=[str(bpath), str(R.receipt_path(LANE_ID, state_root))],
            receipt=R.receipt_path(LANE_ID, state_root),
        )
        print(json.dumps(report, default=str))
        return 0 if failures == 0 else 1

    try:
        from scripts.lib.atomic_json_store import atomic_write_json

        atomic_write_json(bpath, next_baseline, indent=1)
    except OSError as exc:
        report["error"] = f"baseline_write_failed:{type(exc).__name__}"
        failures += 1
    measured = sum(1 for m in ev["mounts"] if "used_pct" in m)
    ok = failures == 0
    R.write_lane_receipt(
        LANE_ID,
        ok=ok,
        exit_code=0 if ok else 1,
        started_at=wall_start,
        script=SCRIPT,
        summary={k: report[k] for k in ("mounts", "hotspots", "sent", "first_run", "degraded_hotspots",
                                        "failures", "manifest")},
        error=report.get("error"),
        path=R.receipt_path(LANE_ID, state_root),
        output={"produced_count": measured, "attempted_count": len(mon["mounts"]),
                "skipped_reasons": {SKIP_DEPENDENCY: len(mon["mounts"]) - measured} if measured < len(mon["mounts"]) else {},
                "empty_reason": None,
                "output_evidence": [{"kind": "file", "ref": str(bpath)}]},
    )
    print(json.dumps(report, default=str))
    return 0 if ok else 1


# ── CLI ────────────────────────────────────────────────────────────────────────────────────────────────────────────


def _parse_now(text: Optional[str]) -> Optional[datetime]:
    if not text:
        return datetime.now(timezone.utc)
    try:
        d = datetime.fromisoformat(text)
    except ValueError:
        return None
    return d if d.tzinfo else None


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="the default: measure + print; write and send nothing")
    g.add_argument("--apply", action="store_true", help="record the baseline + alert on a transition + receipt")
    ap.add_argument("--with-hygiene", action="store_true", help="also run scripts/disk_hygiene.py --dry-run and quote it")
    ap.add_argument("--config", help="config file (default config/disk_monitor.json)")
    ap.add_argument("--state-root", help="persistent-state root (default TRADEAI_STATE_ROOT / resolver)")
    ap.add_argument("--home", help=argparse.SUPPRESS)  # tests
    ap.add_argument("--now", help=argparse.SUPPRESS)  # tests: aware ISO 8601
    ap.add_argument("--alert-state", help=argparse.SUPPRESS)  # tests
    try:
        a = ap.parse_args(argv)
    except SystemExit as exc:
        return 2 if exc.code else 0
    wall_start = datetime.now(timezone.utc)
    now = _parse_now(a.now)
    if now is None:
        print("--now must be an aware ISO 8601 timestamp", file=sys.stderr)
        return 2
    try:
        mon = load_config(Path(a.config) if a.config else None, home=Path(a.home) if a.home else None)
    except ConfigError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    return run(
        mon=mon,
        state_root=Path(a.state_root) if a.state_root else None,
        apply=bool(a.apply),
        now=now,
        wall_start=wall_start,
        alert_state_path=Path(a.alert_state) if a.alert_state else None,
        with_hygiene=a.with_hygiene,
    )


if __name__ == "__main__":
    raise SystemExit(main())
