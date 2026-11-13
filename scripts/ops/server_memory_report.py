#!/usr/bin/env python3
"""Summarize a server_memory_samples*.jsonl series (LQ-20261113-3020). Read-only; prints JSON. MBI_BEHAVIOR = 0.

    server_memory_report.py <jsonl> [--window-s 10] [--high-gap-s 6]

Reads the sampler's lines (v2 or the lead's interim v1: missing keys are simply absent, never defaulted to 0) and
reports:
  span            first/last ts, samples, the largest gap between samples (a gap is a sampler stall, not "no data")
  peaks           max cg_current_b, proc RSS, proc HWM, threads, pressure some/full avg10, tcp est / close_wait,
                  each with the ts it happened
  high_bursts     runs of samples whose memory.events ``high`` delta was > 0 (a new burst starts after --high-gap-s
                  without one): start/end, total high events, and the maxima inside the burst
  pid_changes     every sample whose pid changed (restart), with the release before and after
  release_changes every release change
  recreated       every ``cgroup_recreated`` marker
  correlation     for the peak sample and for each burst: the window [ts-window, ts+window] with that window's max of
                  memory, pressure, threads, close_wait and the number of reaped-compute log lines
Lines that do not parse are counted in ``bad_lines`` and skipped.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

PSI_RE = re.compile(r"(some|full) avg10=([\d.]+)")


def load(path: Path) -> tuple[list[dict[str, Any]], int]:
    rows, bad = [], 0
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                bad += 1
                continue
            if not isinstance(d, dict) or not isinstance(d.get("ts"), (int, float)):
                bad += 1
            elif d.get("markers") != ["stopped_at_cap"]:   # the cap line is a marker, not a sample
                rows.append(d)
    rows.sort(key=lambda r: r["ts"])
    return rows, bad


def psi10(r: dict[str, Any]) -> dict[str, Optional[float]]:
    out: dict[str, Optional[float]] = {"some": None, "full": None}
    for kind, v in PSI_RE.findall(r.get("cg_pressure") or ""):
        out[kind] = float(v)
    return out


def metrics(r: dict[str, Any]) -> dict[str, Optional[float]]:
    p = r.get("proc") or {}
    t = r.get("tcp7777") or {}
    ps = psi10(r)
    log = r.get("app_log") or {}
    return {"cg_current_b": r.get("cg_current_b"), "rss_kb": p.get("rss_kb"), "hwm_kb": p.get("hwm_kb"),
            "threads": p.get("threads"), "psi_some10": ps["some"], "psi_full10": ps["full"],
            "tcp_est": t.get("est"), "tcp_close_wait": t.get("close_wait"), "reaped": log.get("reaped")}


def _max(rows: list[dict[str, Any]], key: str) -> Optional[dict[str, Any]]:
    best = None
    for r in rows:
        v = metrics(r)[key]
        if v is not None and (best is None or v > best["value"]):
            best = {"value": v, "ts": r["ts"]}
    return best


def window(rows: list[dict[str, Any]], centre: float, w: float) -> dict[str, Any]:
    inside = [r for r in rows if centre - w <= r["ts"] <= centre + w]
    out: dict[str, Any] = {"from": centre - w, "to": centre + w, "samples": len(inside)}
    for k in ("cg_current_b", "psi_some10", "psi_full10", "threads", "tcp_close_wait"):
        vals = [metrics(r)[k] for r in inside if metrics(r)[k] is not None]
        out["max_" + k] = max(vals) if vals else None
    reaped = [metrics(r)["reaped"] for r in inside if metrics(r)["reaped"] is not None]
    out["reaped_log_lines"] = sum(reaped) if reaped else None
    return out


def bursts(rows: list[dict[str, Any]], gap: float) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    cur: Optional[dict[str, Any]] = None
    for r in rows:
        d = (r.get("cg_events_delta") or {}).get("high") or 0
        if d <= 0:
            continue
        if cur is None or r["ts"] - cur["end"] > gap:
            cur = {"start": r["ts"], "end": r["ts"], "high_events": 0, "_rows": []}
            out.append(cur)
        cur["end"] = r["ts"]
        cur["high_events"] += d
        cur["_rows"].append(r)
    for b in out:
        rs = b.pop("_rows")
        b["max_cg_current_b"] = (_max(rs, "cg_current_b") or {}).get("value")
        b["max_psi_some10"] = (_max(rs, "psi_some10") or {}).get("value")
        b["max_threads"] = (_max(rs, "threads") or {}).get("value")
    return out


def report(rows: list[dict[str, Any]], bad: int, window_s: float = 10.0, gap_s: float = 6.0) -> dict[str, Any]:
    if not rows:
        return {"samples": 0, "bad_lines": bad, "note": "no samples"}
    gaps = [(b["ts"] - a["ts"], a["ts"]) for a, b in zip(rows, rows[1:])]
    big = max(gaps) if gaps else (0.0, rows[0]["ts"])
    peaks = {k: _max(rows, k) for k in ("cg_current_b", "rss_kb", "hwm_kb", "threads", "psi_some10", "psi_full10",
                                         "tcp_est", "tcp_close_wait")}
    pid_changes, rel_changes, recreated = [], [], []
    for a, b in zip(rows, rows[1:]):
        if a.get("pid") != b.get("pid"):
            pid_changes.append({"ts": b["ts"], "from": a.get("pid"), "to": b.get("pid"),
                                "release_from": a.get("release"), "release_to": b.get("release")})
        if a.get("release") != b.get("release"):
            rel_changes.append({"ts": b["ts"], "from": a.get("release"), "to": b.get("release")})
    for r in rows:
        if "cgroup_recreated" in (r.get("markers") or []):
            recreated.append(r["ts"])
    bs = bursts(rows, gap_s)
    corr = []
    if peaks["cg_current_b"]:
        corr.append({"what": "peak_cg_current", **window(rows, peaks["cg_current_b"]["ts"], window_s)})
    for b in bs:
        corr.append({"what": "high_burst", "start": b["start"], **window(rows, (b["start"] + b["end"]) / 2, max(window_s, (b["end"] - b["start"]) / 2 + window_s))})
    return {"samples": len(rows), "bad_lines": bad,
            "span": {"first_ts": rows[0]["ts"], "last_ts": rows[-1]["ts"], "max_gap_s": round(big[0], 3), "max_gap_at": big[1]},
            "peaks": peaks, "high_bursts": bs, "pid_changes": pid_changes, "release_changes": rel_changes,
            "recreated": recreated, "correlation": corr}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("jsonl")
    ap.add_argument("--window-s", type=float, default=10.0)
    ap.add_argument("--high-gap-s", type=float, default=6.0)
    a = ap.parse_args(argv)
    try:
        rows, bad = load(Path(a.jsonl))
    except OSError as exc:
        print(json.dumps({"error": type(exc).__name__, "path": a.jsonl}))
        return 2
    print(json.dumps(report(rows, bad, a.window_s, a.high_gap_s), indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
