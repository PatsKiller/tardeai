#!/usr/bin/env python3
"""plan.py: wrap every cutover-candidate cron line in scripts/effect_claim_cron.sh (2026-10-16).

Why: scripts/lib/effect_claim.py records one owner per process (cron or n8n), but on 2026-10-16 no crontab line ran
through the cron wrapper, so owner=n8n did not stop the cron copy. Only the shared `flock -n` kept the two
schedulers from overlapping, and n8n lost that race (26 lock skips that day). After this packet, a wrapped line of a
process n8n owns exits 0 with event `skipped_effect` and runs nothing.

Read-only. Inputs: a crontab text (default `crontab -l`), config/lane_registry.json, config/n8n_effect_keys.json,
docs/implementation/n8n-maturity/LANE_DISPOSITION_20261015.csv (families), the relay live list
(~/.config/tradeai/n8n-live-lanes.env, lane names only) and the coordination ledger opened mode=ro (owner rows only).
It never calls `crontab -`, never opens a ledger for writing and never reads a .env or credential file.

A line is WRAPPED when all of these hold, and SKIPPED with a reason otherwise:
  * it maps to exactly one registry lane (TRADEAI_LANE tag, else exactly one registry substring match);
  * that lane has an effect key (config/n8n_effect_keys.json);
  * its family is §23.25-approved: present in the disposition CSV, not F07, not registry_systemd, not wave
    DEFERRED-I2. F09 (broker) is held back unless --include-f09 (the directive orders broker last, wave CD6);
  * it is not already wrapped;
  * the line's shape is certain: `cd <the $PROJ tree> && [VAR=v ...] [flock OPTS LOCK | bash .../safe_flock.sh LOCK]
    COMMAND ... [redirects] [# comment]` with no unquoted `;`, `|`, `&`, backtick, `(`, `)` and no second `&&`;
  * an ARMED lane (cron_claim true) has an owner row; without one the wrapper refuses every cron run (exit 75), so
    such a line is skipped `armed_without_owner_row` until the owner row exists;
  * a lane n8n owns is in the relay live list; otherwise wrapping would leave it with no runner, so it is skipped
    `owner_n8n_not_relay_live`.

The rewrite inserts `env TRADEAI_EFFECT_CLAIM=<lane> bash scripts/effect_claim_cron.sh <lane> ` right after the lock
(inside it, so the flock still refuses an overlap) or, with no lock, before the command. Every other byte of the
line, and every other line, is unchanged.

    python3 plan.py                        # human table from the live crontab
    python3 plan.py --json                 # machine plan
    python3 plan.py --emit-candidate OUT   # the full rewritten crontab (apply.sh installs it)
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[4]
REGISTRY = ROOT / "config" / "lane_registry.json"
EFFECT_KEYS = ROOT / "config" / "n8n_effect_keys.json"
DISPOSITION = ROOT / "docs" / "implementation" / "n8n-maturity" / "LANE_DISPOSITION_20261015.csv"
RELAY_LIVE = Path.home() / ".config" / "tradeai" / "n8n-live-lanes.env"
WRAPPER_REL = "scripts/effect_claim_cron.sh"
WRAPPER_TOKEN = "effect_claim_cron.sh"

DEFERRED_FAMILIES = frozenset({"F07"})
DEFERRED_SOURCES = frozenset({"registry_systemd"})
DEFERRED_WAVE = "DEFERRED-I2"
BROKER_FAMILIES = frozenset({"F09"})

_TAG_RE = re.compile(r"#\s*TRADEAI_LANE\s+(\S+)")
_BARE_CRON = re.compile(r"^[\d*/,\-]+(\s+[\d*/,\-]+){4}$")
_ASSIGN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=\S*")
_FLOCK_FLAGS = frozenset({"-n", "--nonblock", "-x", "-e", "--exclusive", "-s", "--shared", "-o", "--close"})
_FLOCK_VALUED = frozenset({"-w", "--wait", "--timeout", "-E", "--conflict-exit-code"})


# ── inputs ───────────────────────────────────────────────────────────────────────────────────────────────────────


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def load_families(path: Path) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = {}
    with path.open(newline="") as fh:
        for row in csv.DictReader(fh):
            out.setdefault(row["lane_id"], []).append(row)
    return out


def load_relay_live(path: Path) -> set[str]:
    """Lane names from TRADEAI_N8N_RELAY_LIVE_LANES= (the only key read; values are lane ids, not secrets)."""
    if not path.exists():
        return set()
    for line in path.read_text().splitlines():
        if line.startswith("TRADEAI_N8N_RELAY_LIVE_LANES="):
            return set(line.split("=", 1)[1].strip().strip("'\"").split())
    return set()


def default_ledger() -> Path:
    explicit = os.environ.get("TRADEAI_N8N_COORDINATION_LEDGER")
    root = os.environ.get("TRADEAI_STATE_ROOT") or str(Path.home() / "trade-ai-releases" / "persistent-state")
    return Path(explicit) if explicit else Path(root) / "data" / "governance" / "n8n_coordination_ledger.sqlite"


def load_owners(path: Optional[Path]) -> Optional[dict[str, str]]:
    """process -> owner from a mode=ro open; None when the ledger cannot be read (owners then reported unknown)."""
    if path is None or not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=5)
        try:
            has = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='effect_owners'").fetchone()
            if has is None:
                return {}
            return {str(p): str(o) for p, o in conn.execute("SELECT process, owner FROM effect_owners")}
        finally:
            conn.close()
    except sqlite3.Error:
        return None


# ── crontab parsing (same active-line rule as scripts/n8n_lane_disposition.parse_crontab) ───────────────────────────


def parse_env(text: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        first = s.split()[0]
        if "=" in first and not s[0].isdigit() and not s.startswith("*"):
            k, _, v = s.partition("=")
            env[k.strip()] = v.strip().strip("'\"")
    return env


def is_job(line: str) -> bool:
    s = line.strip()
    if not s or s.startswith("#"):
        return False
    first = s.split()[0]
    return not ("=" in first and not s[0].isdigit() and not s.startswith("*"))


def command_offset(line: str) -> Optional[int]:
    """Offset of the command in the raw line (after the 5 schedule fields or the @spec)."""
    m = re.match(r"\s*@\S+\s+" if line.lstrip().startswith("@") else r"\s*(\S+\s+){5}", line)
    return m.end() if m else None


def registry_matchers(reg: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """(substring, row) for every cron-declaring row (scripts/n8n_lane_disposition.registry_matchers)."""
    out: list[tuple[str, dict[str, Any]]] = []
    for row in reg.get("lanes") or []:
        sched = row.get("scheduler") or {}
        if sched.get("kind") == "systemd":
            continue
        for key in ("match", "expression"):
            v = str(sched.get(key) or "")
            if not v or _BARE_CRON.match(v) or v in ("dispatcher", "tradeai-dispatcher"):
                continue
            if sched.get("kind") not in ("cron", "n8n") and key == "expression":
                continue
            out.append((v, row))
    return out


# ── shell shape ──────────────────────────────────────────────────────────────────────────────────────────────────


def scan(cmd: str) -> tuple[list[tuple[int, str]], Optional[int], Optional[int], Optional[str]]:
    """Quote-aware scan of a command. Returns (unquoted '&&' offsets, offset of the first unquoted redirect,
    offset of the first unquoted comment, the first forbidden metachar or None)."""
    ands: list[tuple[int, str]] = []
    redirect = comment = None
    bad = None
    q: Optional[str] = None
    i, n = 0, len(cmd)
    while i < n:
        c = cmd[i]
        if q:
            if c == "\\" and q == '"':
                i += 2
                continue
            if c == q:
                q = None
            i += 1
            continue
        if c == "\\":
            i += 2
            continue
        if c in "'\"":
            q = c
        elif c == "#" and (i == 0 or cmd[i - 1].isspace()):
            comment = i
            break
        elif c == ">" or (c in "012" and cmd[i + 1 : i + 2] == ">" and (i == 0 or cmd[i - 1].isspace())):
            if redirect is None:
                redirect = i
            # `2>&1` and `>&2` are redirects, not background operators.
            j = i + 1
            while j < n and cmd[j] in ">&012":
                j += 1
            i = j
            continue
        elif c == "<":
            bad = bad or "<"
        elif cmd.startswith("&&", i):
            if redirect is None:
                ands.append((i, "&&"))
            else:
                bad = bad or "&&"
            i += 2
            continue
        elif c in ";|&`()":
            bad = bad or c
        i += 1
    if q:
        bad = bad or "unbalanced_quote"
    return ands, redirect, comment, bad


def expand(word: str, env: dict[str, str], home: str) -> str:
    w = word.strip("'\"")
    for k, v in sorted(env.items(), key=lambda kv: -len(kv[0])):
        w = w.replace("${%s}" % k, v).replace("$" + k, v)
    w = w.replace("${HOME}", home).replace("$HOME", home)
    if w.startswith("~"):
        w = home + w[1:]
    return w.rstrip("/")


def insertion_point(cmd: str, env: dict[str, str], home: str) -> tuple[Optional[int], str]:
    """(offset in ``cmd`` where the wrapper goes, reason). Offset None = shape not certain (reason says why)."""
    ands, redirect, comment, bad = scan(cmd)
    if bad:
        return None, f"shell_metachar:{bad}"
    end = min(x for x in (redirect, comment, len(cmd)) if x is not None)
    if len(ands) != 1:
        return None, "no_cd_prefix" if not ands else "compound_command"
    amp = ands[0][0]
    m = re.fullmatch(r"\s*cd\s+(\S+)\s*", cmd[:amp])
    if not m:
        return None, "prefix_is_not_cd"
    proj = expand(env.get("PROJ", ""), env, home) if env.get("PROJ") else ""
    if not proj or expand(m.group(1), env, home) != proj:
        return None, "cwd_is_not_PROJ"
    pos = amp + 2
    while pos < end and cmd[pos].isspace():
        pos += 1
    # leading VAR=value assignments stay in front (they then apply to env, the wrapper and the command alike)
    while True:
        m2 = _ASSIGN_RE.match(cmd, pos)
        if not m2 or m2.end() >= end or not cmd[m2.end()].isspace():
            break
        pos = m2.end()
        while pos < end and cmd[pos].isspace():
            pos += 1
    words = [(mm.start() + pos, mm.group(0)) for mm in re.finditer(r"\S+", cmd[pos:end])]
    if not words:
        return None, "empty_command"
    w0 = words[0][1]
    if w0.rsplit("/", 1)[-1] == "flock":
        k = 1
        while k < len(words) and words[k][1].startswith("-"):
            flag = words[k][1]
            if flag in _FLOCK_FLAGS:
                k += 1
            elif flag in _FLOCK_VALUED:
                k += 2
            else:
                return None, f"flock_option:{flag}"
        if k + 1 >= len(words):  # need the lock path AND a command after it
            return None, "flock_without_command"
        if words[k + 1][1] in ("-c", "--command"):
            return None, "flock_dash_c"
        return words[k + 1][0], "after_flock"
    if w0 == "bash" and len(words) > 3 and words[1][1].rsplit("/", 1)[-1] == "safe_flock.sh":
        return words[3][0], "after_safe_flock"
    if w0.rsplit("/", 1)[-1] in ("flock", "safe_flock.sh"):
        return None, "lock_shape_unknown"
    return words[0][0], "before_command"


# ── plan ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def wrapper_prefix(lane: str) -> str:
    return f"env TRADEAI_EFFECT_CLAIM={lane} bash {WRAPPER_REL} {lane} "


_UNWRAP_RE = re.compile(
    r"env TRADEAI_EFFECT_CLAIM=(?P<lane>[a-z0-9][a-z0-9._-]*) bash " + re.escape(WRAPPER_REL) + r" (?P=lane) "
)


def unwrap(crontab_text: str) -> tuple[str, int]:
    """Remove exactly the prefix this packet inserts (rollback). Every other byte, and every other edit made to the
    crontab since the apply, is kept. Returns (text, lines changed)."""
    out: list[str] = []
    changed = 0
    for raw in crontab_text.splitlines(keepends=True):
        if is_job(raw.rstrip("\n")):
            new, k = _UNWRAP_RE.subn("", raw, count=1)
            if k:
                changed += 1
                raw = new
        out.append(raw)
    return "".join(out), changed


def systemd_matchers(reg: dict[str, Any]) -> list[tuple[str, str]]:
    """(substring, lane_id) for systemd rows: a crontab line that only they match is reported registry_systemd."""
    out: list[tuple[str, str]] = []
    for row in reg.get("lanes") or []:
        sched = row.get("scheduler") or {}
        v = str(sched.get("match") or "")
        if sched.get("kind") == "systemd" and v and not _BARE_CRON.match(v):
            out.append((v, row["lane_id"]))
    return out


def map_lane(
    line: str, matchers: list[tuple[str, dict[str, Any]]], reg_ids: set[str]
) -> tuple[Optional[str], str, list[str]]:
    """(lane or None, how / why not, every registry lane whose match the line contains)."""
    tag_m = _TAG_RE.search(line)
    tag = tag_m.group(1) if tag_m else ""
    hits: list[str] = []
    for pat, row in matchers:
        if pat in line and row["lane_id"] not in hits:
            hits.append(row["lane_id"])
    if tag:
        if tag in hits or (not hits and tag in reg_ids):
            return tag, "tag", hits
        if tag not in reg_ids:
            return None, "tag_not_in_registry", hits
        return None, "tag_registry_conflict", hits + [tag]
    if len(hits) == 1:
        return hits[0], "registry_match", hits
    return None, ("no_registry_match" if not hits else "ambiguous_registry_match"), hits


def build_plan(
    crontab_text: str,
    *,
    registry: dict[str, Any],
    effect_keys: dict[str, Any],
    families: dict[str, list[dict[str, str]]],
    relay_live: set[str],
    owners: Optional[dict[str, str]],
    home: str,
    include_f09: bool = False,
) -> dict[str, Any]:
    env = parse_env(crontab_text)
    matchers = registry_matchers(registry)
    sd_matchers = systemd_matchers(registry)
    reg_ids = {r["lane_id"] for r in registry.get("lanes") or []}
    reg_by_id = {r["lane_id"]: r for r in registry.get("lanes") or []}
    keys = effect_keys.get("lanes") or {}
    wrapped: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    out_of_scope: dict[str, int] = {}
    new_lines: list[str] = []
    jobs = 0
    for n, raw in enumerate(crontab_text.splitlines(keepends=True), 1):
        body = raw.rstrip("\n")
        if not is_job(body):
            new_lines.append(raw)
            continue
        jobs += 1
        lane, how, hits = map_lane(body, matchers, reg_ids)

        def skip(reason: str, *, keyed: bool = True) -> None:
            if keyed:
                skipped.append({"line_no": n, "lane": lane, "reason": reason, "line": body})
            else:
                out_of_scope[reason] = out_of_scope.get(reason, 0) + 1
            new_lines.append(raw)

        if WRAPPER_TOKEN in body:
            skip("already_wrapped")
            continue
        if lane is None:
            sd = [lid for pat, lid in sd_matchers if pat in body]
            if not hits and sd:
                skip("registry_systemd", keyed=any(x in keys for x in sd))
                continue
            # an unmapped line is reported per line when any lane it might be is keyed, else counted
            skip(how, keyed=any(x in keys for x in hits) or any(k in body for k in keys))
            continue
        if lane not in keys:
            skip("no_effect_key", keyed=False)
            continue
        spec = keys[lane]
        fam_rows = families.get(lane) or []
        fams = sorted({r.get("family_id", "") for r in fam_rows})
        sources = {r.get("source", "") for r in fam_rows}
        waves = {r.get("wave", "") for r in fam_rows}
        if (reg_by_id.get(lane, {}).get("scheduler") or {}).get("kind") == "systemd" or sources & DEFERRED_SOURCES:
            skip("registry_systemd")
            continue
        if not fam_rows or not any(fams):
            skip("family_unknown")
            continue
        if set(fams) & DEFERRED_FAMILIES:
            skip("family_F07")
            continue
        if DEFERRED_WAVE in waves:
            skip("wave_DEFERRED-I2")
            continue
        if set(fams) & BROKER_FAMILIES and not include_f09:
            skip("family_F09_broker_held_for_CD6")
            continue
        off = command_offset(body)
        if off is None:
            skip("schedule_unparsed")
            continue
        at, where = insertion_point(body[off:], env, home)
        if at is None:
            skip(f"shape:{where}")
            continue
        owner = None if owners is None else owners.get(str(spec.get("process") or lane), "none")
        if spec.get("cron_claim") is True and owner == "none":
            skip("armed_without_owner_row")
            continue
        if owner == "n8n" and lane not in relay_live:
            # n8n owns it but the relay would not run it live: wrapping would leave the lane with no runner at all
            skip("owner_n8n_not_relay_live")
            continue
        pos = off + at
        new_body = body[:pos] + wrapper_prefix(lane) + body[pos:]
        new_lines.append(new_body + raw[len(body) :])
        wrapped.append(
            {
                "line_no": n,
                "lane": lane,
                "mapped_by": how,
                "family": ",".join(fams),
                "process": spec.get("process") or lane,
                "cron_claim": bool(spec.get("cron_claim")),
                "owner": owner if owner is not None else "unknown",
                "relay_live": lane in relay_live,
                "insert": where,
                "old": body,
                "new": new_body,
            }
        )
    reasons: dict[str, int] = {}
    for s in skipped:
        reasons[s["reason"]] = reasons.get(s["reason"], 0) + 1
    return {
        "schema": "CronEffectClaimWrapPlan@v1",
        "active_job_lines": jobs,
        "wrapped_count": len(wrapped),
        "skipped_count": len(skipped),
        "skip_reasons": dict(sorted(reasons.items())),
        "out_of_scope": dict(sorted(out_of_scope.items())),
        "owners_read": owners is not None,
        "wrapped": wrapped,
        "skipped": skipped,
        "candidate": "".join(new_lines),
    }


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--crontab", default=None, help="crontab text file (default: `crontab -l`, read-only)")
    ap.add_argument("--registry", default=str(REGISTRY))
    ap.add_argument("--effect-keys", default=str(EFFECT_KEYS))
    ap.add_argument("--disposition", default=str(DISPOSITION))
    ap.add_argument("--relay-live", default=str(RELAY_LIVE))
    ap.add_argument("--ledger", default=None, help="coordination ledger, opened mode=ro (default: the gateway's)")
    ap.add_argument("--no-ledger", action="store_true", help="do not read owners (armed lanes are then not checked)")
    ap.add_argument("--home", default=str(Path.home()))
    ap.add_argument("--include-f09", action="store_true", help="also wrap F09 (broker family) lines")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--emit-candidate", default=None, help="write the full rewritten crontab here")
    ap.add_argument("--unwrap", action="store_true", help="rollback mode: remove this packet's wrapper prefixes")
    a = ap.parse_args(argv)
    text = Path(a.crontab).read_text() if a.crontab else subprocess.run(
        ["crontab", "-l"], check=True, capture_output=True, text=True
    ).stdout
    if a.unwrap:
        restored, changed = unwrap(text)
        if a.emit_candidate:
            Path(a.emit_candidate).write_text(restored)
        print(f"UNWRAP_COUNT={changed}")
        return 0
    owners = None if a.no_ledger else load_owners(Path(a.ledger) if a.ledger else default_ledger())
    plan = build_plan(
        text,
        registry=load_json(Path(a.registry)),
        effect_keys=load_json(Path(a.effect_keys)),
        families=load_families(Path(a.disposition)),
        relay_live=load_relay_live(Path(a.relay_live)),
        owners=owners,
        home=a.home,
        include_f09=a.include_f09,
    )
    if a.emit_candidate:
        Path(a.emit_candidate).write_text(plan["candidate"])
    if a.json:
        print(json.dumps({k: v for k, v in plan.items() if k != "candidate"}, indent=2, sort_keys=True))
        return 0
    print(f"active job lines: {plan['active_job_lines']}   wrap: {plan['wrapped_count']}   "
          f"skip (keyed): {plan['skipped_count']}   owners read: {plan['owners_read']}")
    print(f"skip reasons: {json.dumps(plan['skip_reasons'], sort_keys=True)}")
    print(f"out of scope (not reported per line): {json.dumps(plan['out_of_scope'], sort_keys=True)}")
    print("\n# WRAP")
    for w in plan["wrapped"]:
        print(f"L{w['line_no']} {w['lane']} family={w['family']} owner={w['owner']} cron_claim={w['cron_claim']} "
              f"relay_live={w['relay_live']} insert={w['insert']}")
        print(f"  - {w['old']}")
        print(f"  + {w['new']}")
    print("\n# SKIP")
    for s in plan["skipped"]:
        print(f"L{s['line_no']} {s['lane']} {s['reason']}")
        print(f"    {s['line'][:240]}")
    print(f"\nPLANNED_COUNT={plan['wrapped_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
