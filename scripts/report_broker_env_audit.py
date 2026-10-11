#!/usr/bin/env python3
"""report_broker_env_audit.py — which jobs truly need broker env names (step 1 of 3, operator 2026-10-11).

READ-ONLY. Aggregates the broker-name read audit (``scripts/lib/broker_env_audit.py``, flag
``TRADEAI_BROKER_ENV_AUDIT=1``) over a window of days into per-lane, per-module and per-name tables, as JSON and
markdown. Writes only the ``--json`` / ``--md`` paths it is given (default: markdown to stdout). Opens no DB, reads
no env file, and never prints a value: audit records carry names only, and only whitelisted fields are read.

A lane NEEDS a broker name when one of its processes reads that name by key (``[]`` / ``get`` / ``in`` /
``os.getenv``). A lane whose only reads are ``bulk`` (whole-env copies such as ``dict(os.environ)`` for a child
process) is PASSTHROUGH: it hands names on without naming one, and a deny-by-default loader would not break it
unless the child itself reads the name (the child's own records say so).

Lane resolution, in order: the record's ``lane`` (env), the lane registry row owning the script
(``lane_registry.lane_state_for_command``), the registry row naming the systemd unit, else ``script:<path>``.

Usage:
    .venv/bin/python scripts/report_broker_env_audit.py --days 7 --json out.json --md out.md
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT, ROOT / "scripts" / "lib"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import broker_env_audit as BEA  # noqa: E402

NO_CONSUMER_REASON = (
    "Operator-read report for the one-week broker env-name audit (step 1 of 3); its consumer is the operator's "
    "deny-by-default loader decision (step 3), not code. docs/implementation/n8n-maturity/BROKER_ENV_AUDIT.md."
)
FIELDS = ("ts", "host", "pid", "ppid", "name", "access", "script", "arg1", "lane", "unit", "caller", "caller_file",
          "via", "mode")
NAMED_ACCESS = frozenset({"getitem", "get", "contains"})
_SCRIPT_RE = re.compile(r"(scripts/[\w/.-]+\.(?:py|sh))")
_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# env_bootstrap.is_broker_name also matches broker CONFIG knobs (BROKER_PRICE_MAX_AGE_MIN, ALPACA_MODE); the
# deny-by-default decision is about credentials, so each name is tagged by shape. A tag, never a gate.
_CREDENTIAL_RE = re.compile(r"(KEY|SECRET|TOKEN|PASSWORD|PWD|PASS|TOTP|LOGIN|ACCOUNT|AUTH)")


def name_kind(name: str) -> str:
    return "credential" if _CREDENTIAL_RE.search(str(name).upper()) else "config"


def rel_path(path: str | None) -> str | None:
    """A repo-relative ``scripts/...`` path, a ``site-packages/...`` tail, or the basename. Pure."""
    if not path:
        return None
    s = str(path)
    m = _SCRIPT_RE.search(s)
    if m:
        return m.group(1)
    if "site-packages/" in s:
        return "site-packages/" + s.split("site-packages/", 1)[1]
    return Path(s).name


def window_dates(days: int, until: date) -> list[date]:
    return [until - timedelta(days=i) for i in range(max(1, days) - 1, -1, -1)]


def load_records(audit_dir: Path, dates: Iterable[date]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Whitelisted fields of every audit record in the window; malformed lines are counted, never echoed."""
    out: list[dict[str, Any]] = []
    stats = {"files": 0, "lines": 0, "malformed": 0, "foreign": 0}
    for d in dates:
        f = Path(audit_dir) / f"{d.isoformat()}.jsonl"
        if not f.is_file():
            continue
        stats["files"] += 1
        with f.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.strip():
                    continue
                stats["lines"] += 1
                try:
                    rec = json.loads(line)
                except ValueError:
                    stats["malformed"] += 1
                    continue
                if not isinstance(rec, dict) or rec.get("schema") != BEA.SCHEMA or rec.get("mode") != "audit" \
                        or not _NAME_RE.match(str(rec.get("name") or "")):
                    stats["foreign"] += 1
                    continue
                out.append({k: rec.get(k) for k in FIELDS})
    return out, stats


def registry_resolver(registry_path: Path | None) -> Callable[[dict[str, Any]], str | None]:
    """lane_id for a record from the lane registry (script, then systemd unit); None when no row owns it."""
    from scripts.lib import lane_registry as LR
    try:
        reg = LR.load_registry(registry_path) if registry_path else LR.load_registry()
    except Exception:  # noqa: BLE001 — no registry: lanes fall back to script:<path>
        reg = {"lanes": []}
    rows = reg.get("lanes") or []
    cache: dict[tuple, str | None] = {}

    def resolve(rec: dict[str, Any]) -> str | None:
        script, arg1, unit = rel_path(rec.get("script")), rec.get("arg1"), rec.get("unit")
        key = (script, arg1, unit)
        if key in cache:
            return cache[key]
        lane = None
        cmd = " ".join(x for x in (script, arg1 if str(arg1 or "").endswith((".py", ".sh")) else None) if x)
        if cmd:
            lane = LR.lane_state_for_command(cmd, reg).get("lane_id")
        if lane is None and unit and str(unit).endswith(".service") and unit not in ("cron.service",):
            for row in rows:
                sched = row.get("scheduler") or {}
                if sched.get("kind") == "systemd" and unit in " ".join(str(sched.get(k) or "") for k in ("expression", "match")):
                    lane = row.get("lane_id")
                    break
        cache[key] = lane
        return lane
    return resolve


# Source scan (a floor, not proof): literal broker names in an env-read position. The broker execution subsystem is
# not read (AGENTS §0 rule 2: out of scope without a grant); its need for broker names is presumed.
STATIC_EXCLUDED_DIRS = BEA.BROKER_SCRIPT_DIRS
_STATIC_RES = (
    re.compile(r"""(?:environ(?:\.get|\.setdefault|\.pop)?\s*[\[(]\s*|getenv\s*\(\s*)["']([A-Z][A-Z0-9_]+)["']"""),
    re.compile(r"""["']([A-Z][A-Z0-9_]+)["']\s+(?:not\s+)?in\s+(?:os\.)?environ\b"""),
)


def static_references(root: Path, classify: Callable[[str], bool]) -> dict[str, list[str]]:
    """scripts/**.py (tests and the broker execution subsystem excluded) -> broker names read by literal. Pure-ish:
    reads source files only."""
    out: dict[str, list[str]] = {}
    base = Path(root) / "scripts"
    for f in sorted(base.rglob("*.py")):
        rel = f.relative_to(root).as_posix()
        if "__pycache__" in rel or rel.startswith(STATIC_EXCLUDED_DIRS + ("scripts/archive/",)) \
                or rel.endswith("broker_env_audit.py"):
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        names = {m for rx in _STATIC_RES for m in rx.findall(text)}
        names = sorted(n for n in names if n != BEA.FLAG_ENV and classify(n))
        if names:
            out[rel] = names
    return out


def static_vs_runtime(static: dict[str, list[str]], report: dict[str, Any]) -> list[dict[str, Any]]:
    """Per statically-reading module: which of its names were observed read at runtime (by any module)."""
    seen_by_module = {m["module"]: set(m["names_needed"]) | set(m["names_bulk_only"]) for m in report["modules"]}
    seen_any = {n["name"] for n in report["names"]}
    rows = []
    for mod, names in sorted(static.items()):
        here = seen_by_module.get(mod, set())
        rows.append({"module": mod, "names": names, "observed_in_module": sorted(set(names) & here),
                     "not_observed_anywhere": sorted(set(names) - seen_any)})
    return rows


def lane_of(rec: dict[str, Any], resolver: Callable[[dict[str, Any]], str | None] | None) -> str:
    if rec.get("lane"):
        return str(rec["lane"])
    if resolver is not None:
        lane = resolver(rec)
        if lane:
            return str(lane)
    unit = rec.get("unit")
    if unit and str(unit).endswith(".service") and unit != "cron.service" and not rec.get("script"):
        return f"unit:{unit}"
    return f"script:{rel_path(rec.get('script')) or '?'}"


def aggregate(records: list[dict[str, Any]], resolver: Callable[[dict[str, Any]], str | None] | None = None
              ) -> dict[str, Any]:
    """Per-lane / per-module / per-name tables. Pure over ``records`` and ``resolver``."""
    lanes: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "scripts": set(), "units": set(), "named": set(), "bulk": set(), "callers": set(), "procs": set(),
        "first_ts": None, "last_ts": None})
    modules: dict[str, dict[str, Any]] = defaultdict(lambda: {"named": set(), "bulk": set(), "lanes": set(),
                                                              "callers": set()})
    names: dict[str, dict[str, Any]] = defaultdict(lambda: {"lanes_named": set(), "lanes_bulk": set(),
                                                            "modules_named": set()})
    for rec in records:
        lane = lane_of(rec, resolver)
        name = str(rec["name"])
        bulk = rec.get("access") not in NAMED_ACCESS
        mod = rel_path(rec.get("caller_file")) or "?"
        L = lanes[lane]
        L["scripts"].add(rel_path(rec.get("script")) or "?")
        if rec.get("unit"):
            L["units"].add(str(rec["unit"]))
        L["bulk" if bulk else "named"].add(name)
        L["callers"].add(f"{rec.get('caller')}")
        L["procs"].add((rec.get("host"), rec.get("pid"), str(rec.get("ts") or "")[:10]))
        ts = str(rec.get("ts") or "")
        if ts:
            L["first_ts"] = min(L["first_ts"] or ts, ts)
            L["last_ts"] = max(L["last_ts"] or ts, ts)
        M = modules[mod]
        M["bulk" if bulk else "named"].add(name)
        M["lanes"].add(lane)
        M["callers"].add(str(rec.get("caller")))
        N = names[name]
        N["lanes_bulk" if bulk else "lanes_named"].add(lane)
        if not bulk:
            N["modules_named"].add(mod)

    def _lane_row(lane: str, L: dict[str, Any]) -> dict[str, Any]:
        return {"lane": lane, "verdict": "needs" if L["named"] else "passthrough_only",
                "names_needed": sorted(L["named"]), "names_bulk_only": sorted(L["bulk"] - L["named"]),
                "scripts": sorted(L["scripts"]), "units": sorted(L["units"]), "callers": sorted(L["callers"]),
                "processes": len(L["procs"]), "first_ts": L["first_ts"], "last_ts": L["last_ts"]}

    lane_rows = sorted((_lane_row(k, v) for k, v in lanes.items()), key=lambda r: (r["verdict"] != "needs", r["lane"]))
    module_rows = sorted(({"module": k, "names_needed": sorted(v["named"]),
                           "names_bulk_only": sorted(v["bulk"] - v["named"]), "lanes": sorted(v["lanes"]),
                           "callers": sorted(v["callers"])} for k, v in modules.items()),
                         key=lambda r: (not r["names_needed"], r["module"]))
    name_rows = sorted(({"name": k, "kind": name_kind(k), "lanes_needing": sorted(v["lanes_named"]),
                         "lanes_bulk_only": sorted(v["lanes_bulk"] - v["lanes_named"]),
                         "modules_reading": sorted(v["modules_named"])} for k, v in names.items()),
                       key=lambda r: r["name"])
    return {
        "lanes": lane_rows, "modules": module_rows, "names": name_rows,
        "summary": {"records": len(records), "lanes": len(lane_rows),
                    "lanes_needing": sum(1 for r in lane_rows if r["verdict"] == "needs"),
                    "lanes_passthrough_only": sum(1 for r in lane_rows if r["verdict"] == "passthrough_only"),
                    "names": len(name_rows), "modules": len(module_rows)},
    }


def _cell(xs: Iterable[str], limit: int = 6) -> str:
    xs = list(xs)
    s = ", ".join(f"`{x}`" for x in xs[:limit])
    return s + (f" (+{len(xs) - limit})" if len(xs) > limit else "") if xs else "—"


def render_markdown(report: dict[str, Any]) -> str:
    s, meta = report["summary"], report.get("meta", {})
    out = [
        "# Broker env-name read audit",
        "",
        f"Window: {meta.get('from')} .. {meta.get('until')} (UTC dates) · dir `{meta.get('audit_dir')}` · "
        f"files {meta.get('files')} · records {s['records']} · malformed {meta.get('malformed')} · "
        f"foreign {meta.get('foreign')}",
        "",
        f"**{s['lanes_needing']} lane(s) read a broker name by key; {s['lanes_passthrough_only']} only copy the "
        f"whole env (passthrough).** Names only — no value is recorded or shown.",
        "",
        "## Per lane",
        "",
        "| Lane | Verdict | Names read by key | Bulk-copy only | Scripts | Callers | Procs |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in report["lanes"]:
        out.append(f"| `{r['lane']}` | {r['verdict']} | {_cell(r['names_needed'])} | {_cell(r['names_bulk_only'])} | "
                   f"{_cell(r['scripts'], 3)} | {_cell(r['callers'], 3)} | {r['processes']} |")
    out += ["", "## Per module (where the read happens)", "",
            "| Module | Names read by key | Bulk-copy only | Lanes |", "|---|---|---|---|"]
    for r in report["modules"]:
        out.append(f"| `{r['module']}` | {_cell(r['names_needed'])} | {_cell(r['names_bulk_only'])} | "
                   f"{_cell(r['lanes'], 4)} |")
    out += ["", "## Per name", "", "| Name | Kind | Lanes needing it | Bulk-copy only | Modules reading it |",
            "|---|---|---|---|---|"]
    for r in report["names"]:
        out.append(f"| `{r['name']}` | {r['kind']} | {_cell(r['lanes_needing'], 5)} | {_cell(r['lanes_bulk_only'], 5)} | "
                   f"{_cell(r['modules_reading'], 4)} |")
    if report.get("static") is not None:
        out += ["", "## Source scan vs runtime", "",
                "Literal broker names in an env-read position under `scripts/` (tests and "
                + ", ".join(f"`{d}`" for d in STATIC_EXCLUDED_DIRS) + " excluded). A floor, not proof: names passed "
                "through variables are not seen. A name never observed at runtime in the window is a candidate the "
                "deny-by-default loader may withhold — confirm the module did run in the window first.", "",
                "| Module | Names (source) | Observed in this module | Not observed anywhere |", "|---|---|---|---|"]
        for r in report["static"]:
            out.append(f"| `{r['module']}` | {_cell(r['names'])} | {_cell(r['observed_in_module'])} | "
                       f"{_cell(r['not_observed_anywhere'])} |")
    out.append("")
    return "\n".join(out)


def build_report(audit_dir: Path, days: int, until: date, *, registry: Path | None = None,
                 resolve_lanes: bool = True, static_root: Path | None = None) -> dict[str, Any]:
    dates = window_dates(days, until)
    records, stats = load_records(audit_dir, dates)
    resolver = registry_resolver(registry) if resolve_lanes else None
    rep = aggregate(records, resolver)
    if static_root is not None:
        from env_bootstrap import is_broker_name
        rep["static"] = static_vs_runtime(static_references(static_root, is_broker_name), rep)
    rep["meta"] = {"schema": "BrokerEnvAuditReport@v1", "audit_dir": str(audit_dir), "from": dates[0].isoformat(),
                   "until": dates[-1].isoformat(), "days": len(dates),
                   "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), **stats}
    return rep


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Broker env-name read audit report (read-only)")
    p.add_argument("--dir", type=Path, help="audit dir (default $TRADEAI_STATE_ROOT/data/runtime/broker_env_audit)")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--until", type=date.fromisoformat, default=None, help="last UTC date (default today)")
    p.add_argument("--registry", type=Path, default=None, help="lane registry (default config/lane_registry.json)")
    p.add_argument("--no-lanes", action="store_true", help="skip lane-registry resolution")
    p.add_argument("--no-static", action="store_true", help="skip the source scan of literal broker-name reads")
    p.add_argument("--json", type=Path, help="write the JSON report here")
    p.add_argument("--md", type=Path, help="write the markdown report here")
    a = p.parse_args(argv)
    rep = build_report(a.dir or BEA.audit_dir(), a.days, a.until or datetime.now(timezone.utc).date(),
                       registry=a.registry, resolve_lanes=not a.no_lanes,
                       static_root=None if a.no_static else ROOT)
    md = render_markdown(rep)
    if a.json:
        a.json.write_text(json.dumps(rep, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if a.md:
        a.md.write_text(md, encoding="utf-8")
    if not a.json and not a.md:
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
