"""Dimensions 6 (self-healing proven) and 9 (recovery) of the n8n platform maturity scorer.

Dimension 6 evaluates the inventory ``config/self_healing_mechanisms.json`` (SelfHealingMechanisms@v1).
Every mechanism names an evidence source and a success predicate that describes a *successful runtime
action* (a heal, remediation or retry that worked), not merely "it ran". A generic evaluator reads the
source read-only through the probe and classifies each mechanism:

* ``PROVEN``         >= ``min_count`` successful actions inside the proof window (the predicate's
                     ``window_hours``, else ``proof_window_hours`` = 336 h / 14 days);
* ``RAN_NOT_HEALED`` the source has records, but too few successes in the window;
* ``NO_EVIDENCE``    no source (kind ``absent``, file missing, command refused/failed) or no records.

Evidence kinds: ``jsonl`` (one JSON object per line), ``json`` (one document), ``jsonstream``
(concatenated / pretty-printed JSON objects in a log), ``sqlite`` (opened ``mode=ro``), ``journal``
(``journalctl --user -u UNIT --since``), ``systemd`` (``systemctl --user show``), ``log`` (text lines,
timestamp from ``ts_regex``), ``psql`` (one read-only SELECT of the named ``columns`` built by
``core.psql_argv``; credentials come from ``~/.pgpass``, never argv; an auth/connect failure reports
NO_EVIDENCE) and ``absent`` (not built yet). Undated sources (a log without ``ts_regex``, a stream
without ``ts_key``) trust only their last ``undated_tail_lines`` records (the row's own value, else
``dimensions.self_healing.undated_tail_lines``) and date them with the file mtime, so an old success in
a file still being written is not counted as recent.

Formulas (every threshold is REQUIRED config via ``probe.need`` / ``core.need_top``; a missing key raises
``core.ConfigError`` — there are no in-code fallbacks):

Dimension 6 ``self_healing``::

    proven_ratio  = PROVEN / mechanisms                       (all inventory rows count; an empty or
                                                              missing inventory -> None, never 1.0)
    s_proven      = ratio_score(proven_ratio, proven_ratio_gate, top=1.0)
    ok_rate       = health_tick receipts with ok=true / receipts in health_tick_window_hours
                    (health_tick --apply exits 0 iff its receipt has ok=true). With no history rows in
                    the window the latest receipt is the only sample, and only when it is fresh
                    (<= health_tick_max_age_minutes); 0 receipts -> None (UNVERIFIED), never "ok"
    s_tick        = ratio_score(ok_rate, health_tick_ok_rate_gate, top=1.0)
    score         = mean_score([s_proven, s_tick])            (a missing part counts 0 -> PARTIAL)
    gate          = proven_ratio >= proven_ratio_gate AND ok_rate >= health_tick_ok_rate_gate AND
                    the latest receipt is ok and fresh
    a failed gate caps the score at the top-level gate_cap

Dimension 9 ``recovery``::

    s_backup = backup_ok_score if backup_verify_last.json verdict OK and age <= backup_verify_max_age_hours
               backup_warn_score if verdict WARN and fresh; backup_fail_score if FAIL or stale;
               None (UNVERIFIED) if absent
    s_drill  = restore_drill_pass_score if trade_ai_restore_drill_last.json outcome PASS and
               age <= restore_drill_max_age_days, else n8n_lab_restore_drill_credit if the n8n lab drill
               receipt is ok and fresh (it proves restore of the lab DB only); restore_drill_fail_score if
               receipts exist but none passes; None if absent
    score    = mean_score([s_backup, s_drill]); gate = backup OK+fresh and drill PASS+fresh;
               a failed gate caps at gate_cap
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
from pathlib import Path
from typing import Any, Optional

try:  # zoneinfo is stdlib on 3.9+; fall back to UTC if tzdata is missing.
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

from . import core

PROVEN = "PROVEN"
RAN_NOT_HEALED = "RAN_NOT_HEALED"
NO_EVIDENCE = "NO_EVIDENCE"
INVENTORY_SCHEMA = "SelfHealingMechanisms@v1"
INVENTORY_REL = "config/self_healing_mechanisms.json"
KINDS = ("jsonl", "json", "jsonstream", "sqlite", "journal", "systemd", "log", "psql", "absent")
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_JOURNAL_TS_RE = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:[.,]\d+)?[+-]\d\d:?\d\d)\s")
_SYSTEMD_PROPS = ("NRestarts", "ActiveState", "SubState", "Result", "LoadState", "Restart")
_MAX_BYTES = 64 * 1024 * 1024
_MAX_ROWS = 500_000

SELF_RULE = ">= 80% of mechanisms with a successful runtime action; health_tick exits 0"
RECOVERY_RULE = "daily backup-verify receipt green and a passed restore drill receipt"


# --------------------------------------------------------------------------- inventory

def load_inventory(probe: core.Probe, rel: str = INVENTORY_REL) -> "tuple[Optional[dict], Optional[str]]":
    doc = probe.json(probe.proj / rel)
    if not isinstance(doc, dict):
        return None, f"inventory {rel} missing or not JSON"
    if doc.get("schema") != INVENTORY_SCHEMA:
        return None, f"inventory schema {doc.get('schema')!r} != {INVENTORY_SCHEMA}"
    if not isinstance(doc.get("mechanisms"), list) or not doc["mechanisms"]:
        return None, "inventory has no mechanisms"
    return doc, None


def inventory_problems(doc: dict, proj: Path) -> list[str]:
    """Self-check: ids unique; every row has code, evidence_source (known kind) and success_predicate;
    repo code paths exist (``code_external`` rows name code outside the repo and say why)."""
    out: list[str] = []
    seen: set[str] = set()
    for i, m in enumerate(doc.get("mechanisms") or []):
        if not isinstance(m, dict):
            out.append(f"#{i}: mechanism is not an object")
            continue
        mid = m.get("id") or f"#{i}"
        if mid in seen:
            out.append(f"{mid}: duplicate id")
        seen.add(mid)
        for k in ("name", "category", "code", "evidence_source", "success_predicate", "expected"):
            if not m.get(k):
                out.append(f"{mid}: missing {k}")
        ev = m.get("evidence_source") or {}
        pred = m.get("success_predicate") or {}
        if ev.get("kind") not in KINDS:
            out.append(f"{mid}: unknown evidence kind {ev.get('kind')!r}")
        if not pred.get("description"):
            out.append(f"{mid}: success_predicate has no description")
        if not any(k in pred for k in ("regex", "field", "all", "any")):
            out.append(f"{mid}: success_predicate has no machine condition")
        if ev.get("kind") in ("journal", "systemd") and not ev.get("unit"):
            out.append(f"{mid}: {ev.get('kind')} evidence needs unit")
        if ev.get("kind") == "psql":
            for k in ("database", "table", "ts_key", "user", "columns"):
                if not ev.get(k):
                    out.append(f"{mid}: psql evidence needs {k}")
        if ev.get("kind") in ("jsonl", "json", "jsonstream", "sqlite", "log") and not ev.get("path"):
            out.append(f"{mid}: {ev.get('kind')} evidence needs path")
        for p in [ev.get("path")] + [a.get("path") for a in ev.get("alt") or []]:
            if p and (os.path.isabs(p) or ".." in Path(p).parts):
                out.append(f"{mid}: evidence path must be relative: {p}")
        code = str(m.get("code") or "")
        if code and not m.get("code_external") and not (proj / code).exists():
            out.append(f"{mid}: code path not in repo: {code}")
    return out


# --------------------------------------------------------------------------- predicates

def get_field(rec: Any, dotted: str) -> Any:
    if dotted in ("*", ""):
        return rec
    cur = rec
    for part in dotted.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def cond_match(rec: Any, cond: Optional[dict]) -> bool:
    """Structured condition: ``all``/``any`` lists, or ``field`` with one of equals / in / not_in / gte /
    truthy / nonempty / regex (a non-string value is JSON-serialised before ``regex``)."""
    if not cond:
        return True
    if "all" in cond:
        return all(cond_match(rec, c) for c in cond["all"])
    if "any" in cond:
        return any(cond_match(rec, c) for c in cond["any"])
    field_name = cond.get("field", "*")
    v = get_field(rec, field_name)
    if "equals" in cond:
        want = cond["equals"]
        if isinstance(want, bool):  # True must not match 1, nor False match 0
            return isinstance(v, bool) and v is want
        return v == want
    if "in" in cond:
        return v in cond["in"]
    if "not_in" in cond:
        return v not in cond["not_in"]
    if "gte" in cond:
        try:
            return float(v) >= float(cond["gte"])
        except (TypeError, ValueError):
            return False
    if cond.get("truthy"):
        return bool(v)
    if cond.get("nonempty"):
        return isinstance(v, (list, dict, str)) and len(v) > 0
    if "regex" in cond:
        s = v if isinstance(v, str) else json.dumps(v, default=str, sort_keys=True)
        return bool(re.search(cond["regex"], s or ""))
    return False


def _pred_cond(pred: dict) -> dict:
    return {k: v for k, v in pred.items() if k not in ("description", "min_count", "window_hours")}


# --------------------------------------------------------------------------- evidence readers

class _Src:
    def __init__(self) -> None:
        self.available = False
        self.records: list[tuple[Optional[_dt.datetime], Any]] = []
        self.note: Optional[str] = None
        self.undated = False
        self.source = ""


def _tz(name: Optional[str]) -> _dt.tzinfo:
    if not name or name.upper() == "UTC" or ZoneInfo is None:
        return _dt.timezone.utc
    try:
        return ZoneInfo(name)
    except Exception:  # noqa: BLE001
        return _dt.timezone.utc


def _parse_naive(s: str, tz: _dt.tzinfo) -> Optional[_dt.datetime]:
    try:
        d = _dt.datetime.fromisoformat(s.strip().replace(",", ".").replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=tz)


def _ts_of(rec: Any, key: Optional[str]) -> Optional[_dt.datetime]:
    if not key:
        return None
    return core.parse_ts(get_field(rec, key))


def resolve_path(probe: core.Probe, inv: dict, base: Optional[str], rel: str) -> Path:
    home = Path(probe.env.get("HOME") or Path.home())
    b = base or "state"
    if b == "state":
        root = probe.root
    elif b == "repo":
        root = probe.proj
    elif b == "home":
        root = home
    elif b == "devtree":
        spec = probe.env.get("TRADEAI_DEV_TREE") or (inv.get("bases") or {}).get("devtree") or str(probe.proj)
        root = home / spec[2:] if spec.startswith("~/") else Path(spec)
    else:
        raise ValueError(f"unknown evidence base {b!r}")
    return root / rel


def _read_tail_text(path: Path) -> Optional[str]:
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            if size > _MAX_BYTES:
                fh.seek(size - _MAX_BYTES)
                fh.readline()
            return fh.read().decode("utf-8", errors="replace")
    except OSError:
        return None


def _undate_tail(probe: core.Probe, path: Path, recs: list, tail: int) -> list:
    mt = probe.mtime(path)
    return [(mt, r) for r in recs[-tail:]] if tail > 0 else []


def _read_file_source(probe: core.Probe, inv: dict, ev: dict, src: _Src, cache: dict, default_tail: int) -> None:
    kind = ev["kind"]
    locs = [(ev.get("base"), ev["path"])] + [(a.get("base"), a["path"]) for a in ev.get("alt") or []]
    src.source = ", ".join(f"{b or 'state'}:{p}" for b, p in locs)
    tail = int(ev["undated_tail_lines"]) if "undated_tail_lines" in ev else int(default_tail)
    flt = ev.get("filter")
    for base, rel in locs:
        path = resolve_path(probe, inv, base, rel)
        key = (kind, str(path))
        if key not in cache:
            cache[key] = _load(probe, kind, path, ev)
        loaded = cache[key]
        if loaded is None:
            continue
        src.available = True
        recs: list = []
        if kind == "log":
            line_re = re.compile(ev["line_regex"]) if ev.get("line_regex") else None
            ts_re = re.compile(ev["ts_regex"]) if ev.get("ts_regex") else None
            tz = _tz(ev.get("tz"))
            cur: Optional[_dt.datetime] = None
            for line in loaded:
                if ts_re:
                    mt = ts_re.search(line)
                    if mt:
                        cur = _parse_naive(mt.group(1), tz) or cur
                if not line.strip() or (line_re and not line_re.search(line)):
                    continue
                recs.append((cur, line))
            if not ts_re:
                src.undated = True
                recs = _undate_tail(probe, path, [r for _, r in recs], tail)
        else:
            rows = [r for r in loaded if cond_match(r, flt)] if flt else list(loaded)
            ts_key = ev.get("ts_key")
            if ts_key:
                recs = [(_ts_of(r, ts_key), r) for r in rows]
            else:  # undated: only the tail (a json document is its own tail) is dated with the file mtime
                src.undated = True
                recs = _undate_tail(probe, path, rows, len(rows) if kind == "json" else tail)
        src.records.extend(recs)
    if not src.available:
        src.note = "evidence file absent"


def _load(probe: core.Probe, kind: str, path: Path, ev: dict) -> Optional[list]:
    if kind == "jsonl":
        return probe.rows(path, limit=_MAX_ROWS)
    if kind == "json":
        doc = probe.json(path)
        if doc is None:
            return None
        return [d for d in doc if isinstance(d, dict)] if isinstance(doc, list) else [doc]
    if kind == "log":
        t = _read_tail_text(path)
        return None if t is None else t.splitlines()
    if kind == "jsonstream":
        t = _read_tail_text(path)
        if t is None:
            return None
        dec, out, i = json.JSONDecoder(), [], 0
        while True:
            j = t.find("{", i)
            if j < 0:
                break
            try:
                obj, end = dec.raw_decode(t, j)
            except json.JSONDecodeError:
                i = t.find("\n", j)
                if i < 0:
                    break
                continue
            if isinstance(obj, dict):
                out.append(obj)
            i = end
        return out
    if kind == "sqlite":
        table, ts_key = ev.get("table", ""), ev.get("ts_key")
        if not _IDENT_RE.match(table) or (ts_key and not _IDENT_RE.match(ts_key)):
            return None
        con = probe.sqlite_ro(path)
        if con is None:
            return None
        try:
            con.row_factory = __import__("sqlite3").Row
            cur = con.execute(f"SELECT * FROM {table} LIMIT {_MAX_ROWS}")  # noqa: S608 - identifier validated
            return [dict(r) for r in cur.fetchall()]
        except Exception:  # noqa: BLE001
            return None
        finally:
            con.close()
    return None


def _read_journal(probe: core.Probe, ev: dict, since: _dt.datetime, src: _Src) -> None:
    unit = ev["unit"]
    src.source = f"journalctl --user -u {unit}"
    since_s = since.astimezone(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    try:
        rc, out, _err = probe.run(["journalctl", "--user", "-u", unit, "--since", since_s, "--no-pager", "-o", "short-iso"])
    except PermissionError as exc:
        src.note = str(exc)
        return
    if rc != 0:
        src.note = f"journalctl rc={rc}"
        return
    src.available = True
    line_re = re.compile(ev["line_regex"]) if ev.get("line_regex") else None
    for line in out.splitlines():
        if not line.strip() or line.startswith("--"):
            continue
        m = _JOURNAL_TS_RE.match(line)
        ts = _parse_naive(m.group(1), _dt.timezone.utc) if m else None
        if line_re and not line_re.search(line):
            continue
        src.records.append((ts, line))


def _read_systemd(probe: core.Probe, ev: dict, src: _Src) -> None:
    unit = ev["unit"]
    src.source = f"systemctl --user show {unit}"
    argv = ["systemctl", "--user", "show", unit]
    for p in _SYSTEMD_PROPS:
        argv += ["-p", p]
    try:
        rc, out, _err = probe.run(argv)
    except PermissionError as exc:
        src.note = str(exc)
        return
    if rc != 0:
        src.note = f"systemctl rc={rc}"
        return
    props: dict[str, Any] = {}
    for line in out.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            props[k.strip()] = int(v) if v.strip().isdigit() else v.strip()
    if not props or props.get("LoadState") in (None, "not-found"):
        src.note = "unit not loaded"
        return
    src.available = True
    src.records.append((probe.now, props))


def psql_sql(ev: dict, since: _dt.datetime) -> Optional[str]:
    """The one SELECT a psql source issues: only the named ``columns`` (never ``*``, so token material such
    as fingerprints is not pulled), rows since the window start. None when an identifier is invalid."""
    table, ts_key = ev.get("table", ""), ev.get("ts_key", "")
    cols = list(ev.get("columns") or [])
    if not cols or not all(_IDENT_RE.match(str(c)) for c in cols + [table, ts_key]):
        return None
    if ts_key not in cols:
        cols.append(ts_key)
    return (f"SELECT row_to_json(t) FROM (SELECT {', '.join(cols)} FROM {table} "  # noqa: S608 - validated
            f"WHERE {ts_key} >= '{since.astimezone(_dt.timezone.utc).isoformat()}'::timestamptz "
            f"ORDER BY {ts_key} LIMIT {_MAX_ROWS}) t")


def psql_source_argv(ev: dict, since: _dt.datetime) -> Optional[list[str]]:
    """argv via ``core.psql_argv`` (host form; credentials from ~/.pgpass, never argv). None if invalid."""
    db, user, host = ev.get("database", ""), ev.get("user", ""), ev.get("host")
    sql = psql_sql(ev, since)
    if sql is None or not core.is_safe_sql(sql) or not (_IDENT_RE.match(db) and _IDENT_RE.match(user)):
        return None
    return core.psql_argv(sql, user=user, db=db, host=host or None)


def _read_psql(probe: core.Probe, ev: dict, since: _dt.datetime, src: _Src) -> None:
    src.source = f"psql {ev.get('database', '')}.{ev.get('table', '')}"
    argv = psql_source_argv(ev, since)
    if argv is None:
        src.note = "psql evidence identifiers/columns/user invalid or SQL not read-only"
        return
    try:
        rc, out, _err = probe.run(argv)
    except PermissionError as exc:
        src.note = str(exc)
        return
    if rc != 0:
        src.note = f"psql auth/connect failed rc={rc}"
        return
    src.available = True
    ts_key = ev["ts_key"]
    for line in out.splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(r, dict):
            src.records.append((_ts_of(r, ts_key), r))


# --------------------------------------------------------------------------- evaluation

def evaluate_mechanism(probe: core.Probe, inv: dict, mech: dict, *, default_window_h: float,
                       default_tail: int, cache: Optional[dict] = None) -> dict:
    """Classify one mechanism -> PROVEN / RAN_NOT_HEALED / NO_EVIDENCE with counts and last timestamps."""
    cache = {} if cache is None else cache
    ev = mech.get("evidence_source") or {}
    pred = mech.get("success_predicate") or {}
    kind = ev.get("kind")
    window_h = float(pred.get("window_hours") or ev.get("window_hours") or default_window_h)
    since = probe.since(window_h)
    src = _Src()
    try:
        if kind == "absent":
            src.source, src.note = "absent", ev.get("reason") or "no evidence source (not built)"
        elif kind in ("jsonl", "json", "jsonstream", "sqlite", "log"):
            _read_file_source(probe, inv, ev, src, cache, default_tail)
        elif kind == "journal":
            _read_journal(probe, ev, since, src)
        elif kind == "systemd":
            _read_systemd(probe, ev, src)
        elif kind == "psql":
            _read_psql(probe, ev, since, src)
        else:
            src.note = f"unknown evidence kind {kind!r}"
    except (OSError, ValueError, KeyError, re.error) as exc:
        src.available, src.records = False, []
        src.note = f"{type(exc).__name__}: {str(exc)[:160]}"

    text_kind = kind in ("log", "journal")
    rx = re.compile(pred["regex"]) if text_kind and pred.get("regex") else None
    cond = _pred_cond(pred)

    def ok(rec: Any) -> bool:
        if text_kind:
            return bool(rx and rx.search(rec))
        return cond_match(rec, cond)

    succ = [(ts, r) for ts, r in src.records if ok(r)]
    in_win = [ts for ts, _ in src.records if ts is not None and ts >= since]
    succ_win = [ts for ts, _ in succ if ts is not None and ts >= since]
    min_count = int(pred.get("min_count") or 1)
    if not src.available or not src.records:
        state = NO_EVIDENCE
    elif len(succ_win) >= min_count:
        state = PROVEN
    else:
        state = RAN_NOT_HEALED
    last = max((ts for ts, _ in src.records if ts), default=None)
    last_s = max((ts for ts, _ in succ if ts), default=None)
    return {
        "id": mech.get("id"), "category": mech.get("category"), "state": state, "kind": kind,
        "source": src.source, "window_hours": window_h, "records": len(src.records),
        "records_window": len(in_win), "successes": len(succ), "successes_window": len(succ_win),
        "last_record_ts": last.isoformat() if last else None,
        "last_success_ts": last_s.isoformat() if last_s else None,
        "undated": src.undated, "note": src.note,
    }


def evaluate_inventory(probe: core.Probe, doc: dict, default_window_h: float, default_tail: int) -> list[dict]:
    cache: dict = {}
    return [evaluate_mechanism(probe, doc, m, default_window_h=default_window_h, default_tail=default_tail, cache=cache)
            for m in doc.get("mechanisms") or [] if isinstance(m, dict)]


# --------------------------------------------------------------------------- health_tick

def health_tick_status(probe: core.Probe, dim: str = "self_healing") -> dict:
    last_rel = probe.need(dim, "health_tick_last")
    hist_rel = probe.need(dim, "health_tick_history")
    window_h = float(probe.need(dim, "health_tick_window_hours"))
    max_age_min = float(probe.need(dim, "health_tick_max_age_minutes"))
    last = probe.json(probe.root / last_rel)
    rows = probe.rows(probe.root / hist_rel, since=probe.since(window_h), ts_keys=("as_of",))
    # a row counts only with a parseable as_of inside the window (probe.rows keeps undated rows)
    cut = probe.since(window_h)
    rows = [r for r in rows or [] if r.get("mode", "apply") == "apply"
            and (core.parse_ts(r.get("as_of")) or cut - _dt.timedelta(seconds=1)) >= cut]
    out: dict = {"last_rel": last_rel, "hist_rel": hist_rel, "window_hours": window_h,
                 "runs": len(rows), "ok_runs": sum(1 for r in rows if r.get("ok") is True),
                 "ok_rate": None, "ok_rate_basis": None}
    if rows:
        out["ok_rate"], out["ok_rate_basis"] = round(out["ok_runs"] / len(rows), 4), "history"
    if isinstance(last, dict):
        as_of = core.parse_ts(last.get("as_of"))
        age = (probe.now - as_of).total_seconds() / 60 if as_of else None
        fresh = age is not None and 0 <= age <= max_age_min
        out.update(last_as_of=last.get("as_of"), last_ok=last.get("ok") is True,
                   last_failed=list(last.get("failed") or [])[:10],
                   last_timed_out=list(last.get("timed_out") or [])[:10],
                   last_age_min=round(age, 1) if age is not None else None, last_fresh=fresh)
        if out["ok_rate"] is None and fresh:  # no history in the window: one FRESH receipt is the only sample
            out["runs"], out["ok_runs"] = 1, int(out["last_ok"])
            out["ok_rate"], out["ok_rate_basis"] = float(out["ok_runs"]), "latest_receipt"
    else:
        out.update(last_as_of=None, last_ok=None, last_fresh=False, last_age_min=None)
    return out


# --------------------------------------------------------------------------- collectors

def _gates(probe: core.Probe) -> "tuple[float, float]":
    return float(core.need_top(probe.config, "gate_score")), float(core.need_top(probe.config, "gate_cap"))


def _cap(score: float, gate_pass: bool, gate_cap: float) -> float:
    return score if gate_pass else min(score, gate_cap)


def collect_self_healing(probe: core.Probe) -> dict:
    dim = "self_healing"
    try:
        rule = probe.need(dim, "gate_rule")
    except core.ConfigError:
        rule = SELF_RULE
    try:
        gate_score, gate_cap = _gates(probe)
        ratio_gate = float(probe.need(dim, "proven_ratio_gate"))
        tick_gate = float(probe.need(dim, "health_tick_ok_rate_gate"))
        window_h = float(probe.need(dim, "proof_window_hours"))
        default_tail = int(probe.need(dim, "undated_tail_lines"))
        inv_rel = probe.need(dim, "inventory")
        tick = health_tick_status(probe, dim)
    except core.ConfigError as exc:
        return core.unverified(dim, rule, str(exc))

    evid: list[dict] = []
    notes: list[str] = []
    doc, err = load_inventory(probe, inv_rel)
    results: list[dict] = []
    s_proven: Optional[float] = None
    ratio: Optional[float] = None
    if doc is None:
        notes.append(f"inventory: {err}")
    else:
        problems = inventory_problems(doc, probe.proj)
        if problems:
            notes.append(f"inventory self-check: {len(problems)} problem(s): {'; '.join(problems[:5])}")
        results = evaluate_inventory(probe, doc, window_h, default_tail)
        n = len(results)
        proven = sum(1 for r in results if r["state"] == PROVEN)
        ratio = proven / n if n > 0 else None  # an empty inventory proves nothing
        s_proven = core.ratio_score(ratio, ratio_gate, gate_score=gate_score, top=1.0) if ratio is not None else None
        evid.append(core.evidence(inv_rel, mechanisms=n, proven=proven, schema=doc.get("schema")))

    s_tick: Optional[float] = None
    if tick["ok_rate"] is not None:
        s_tick = core.ratio_score(tick["ok_rate"], tick_gate, gate_score=gate_score, top=1.0)
    else:
        notes.append(f"health_tick: 0 receipts in the last {tick['window_hours']} h and no fresh latest receipt")
    if not tick.get("last_fresh"):
        notes.append(f"health_tick latest receipt stale or missing (age_min={tick.get('last_age_min')})")
    evid.append(core.evidence(tick["hist_rel"], runs=tick["runs"], ok_runs=tick["ok_runs"], ok_rate=tick["ok_rate"],
                              basis=tick["ok_rate_basis"], window_hours=tick["window_hours"]))
    evid.append(core.evidence(tick["last_rel"], as_of=tick.get("last_as_of"), ok=tick.get("last_ok"),
                              failed=tick.get("last_failed") or None, timed_out=tick.get("last_timed_out") or None))

    score, status, mnotes = core.mean_score([("proven_ratio", s_proven), ("health_tick_exit0", s_tick)])
    gate_pass = (ratio is not None and ratio >= ratio_gate and tick["ok_rate"] is not None
                 and tick["ok_rate"] >= tick_gate and tick.get("last_ok") is True and bool(tick.get("last_fresh")))
    score = _cap(score, gate_pass, gate_cap)

    by_state = {s: sum(1 for r in results if r["state"] == s) for s in (PROVEN, RAN_NOT_HEALED, NO_EVIDENCE)}
    by_cat: dict[str, dict] = {}
    for r in results:
        c = by_cat.setdefault(r["category"] or "?", {"total": 0, "proven": 0})
        c["total"] += 1
        c["proven"] += r["state"] == PROVEN
    for r in results:
        evid.append(core.evidence(r["source"], mechanism=r["id"], state=r["state"], successes_window=r["successes_window"],
                                  records_window=r["records_window"], last_success_ts=r["last_success_ts"],
                                  undated=r["undated"] or None, note=r["note"]))
    metrics = {
        "proven_ratio": round(ratio, 4) if ratio is not None else None,
        "proven": by_state[PROVEN], "ran_not_healed": by_state[RAN_NOT_HEALED], "no_evidence": by_state[NO_EVIDENCE],
        "health_tick_ok_rate": tick["ok_rate"], "health_tick_ok_rate_basis": tick["ok_rate_basis"],
        "mechanisms_total": len(results), "health_tick_last_ok": tick.get("last_ok"),
        "health_tick_runs": tick["runs"], "proof_window_hours": window_h,
        "s_proven": None if s_proven is None else round(s_proven, 2),
        "s_health_tick": None if s_tick is None else round(s_tick, 2),
        "by_category": by_cat,
        "mechanisms": [{k: r[k] for k in ("id", "state", "successes_window", "records_window", "last_success_ts")}
                       for r in results],
    }
    return core.dim_result(dim, score=score, gate_rule=rule, gate_pass=gate_pass, metrics=metrics,
                           evidence_list=evid, status=status, notes=notes + mnotes)


def _age_h(probe: core.Probe, ts: Any) -> Optional[float]:
    d = core.parse_ts(ts)
    return None if d is None else (probe.now - d).total_seconds() / 3600


def collect_recovery(probe: core.Probe) -> dict:
    dim = "recovery"
    try:
        rule = probe.need(dim, "gate_rule")
    except core.ConfigError:
        rule = RECOVERY_RULE
    try:
        _gate_score, gate_cap = _gates(probe)
        bv_rel = probe.need(dim, "backup_verify_receipt")
        bv_max_h = float(probe.need(dim, "backup_verify_max_age_hours"))
        ok_s, warn_s, fail_s = (float(probe.need(dim, k)) for k in ("backup_ok_score", "backup_warn_score", "backup_fail_score"))
        rd_rel = probe.need(dim, "restore_drill_receipt")
        rd_max_h = float(probe.need(dim, "restore_drill_max_age_days")) * 24
        pass_s, dfail_s = float(probe.need(dim, "restore_drill_pass_score")), float(probe.need(dim, "restore_drill_fail_score"))
        lab_rel = probe.need(dim, "n8n_lab_restore_drill_receipt")
        lab_credit = float(probe.need(dim, "n8n_lab_restore_drill_credit"))
    except core.ConfigError as exc:
        return core.unverified(dim, rule, str(exc))
    notes: list[str] = []

    bv = probe.json(probe.root / bv_rel)
    s_backup: Optional[float] = None
    bv_ok = False
    bv_age = None
    if isinstance(bv, dict):
        bv_age = _age_h(probe, bv.get("as_of"))
        fresh = bv_age is not None and 0 <= bv_age <= bv_max_h
        verdict = bv.get("verdict")
        bv_ok = fresh and verdict == "OK"
        s_backup = ok_s if bv_ok else (warn_s if fresh and verdict == "WARN" else fail_s)
        if not fresh:
            notes.append(f"backup-verify receipt stale (age_h={None if bv_age is None else round(bv_age, 1)})")
    else:
        notes.append(f"backup-verify receipt absent ({bv_rel}): lane not yet run with --write")

    rd = probe.json(probe.root / rd_rel)
    lab = probe.json(probe.root / lab_rel)
    rd_ok = False
    rd_age = lab_age = None
    parts_present = False
    s_drill: Optional[float] = None
    if isinstance(rd, dict):
        parts_present = True
        rd_age = _age_h(probe, rd.get("as_of"))
        rd_ok = rd.get("outcome") == "PASS" and rd_age is not None and 0 <= rd_age <= rd_max_h
        s_drill = pass_s if rd_ok else dfail_s
    else:
        notes.append(f"trade_ai restore-drill receipt absent ({rd_rel}): drill never run with --write")
    lab_ok = False
    if isinstance(lab, dict):
        parts_present = True
        lab_age = _age_h(probe, lab.get("finished") or lab.get("as_of") or lab.get("started"))
        lab_ok = lab.get("ok") is True and lab_age is not None and 0 <= lab_age <= rd_max_h
        if not rd_ok:
            s_drill = max(v for v in (s_drill, lab_credit if lab_ok else dfail_s) if v is not None)
            if lab_ok:
                notes.append("restore drill credit from the n8n lab drill only (lab DB, not trade_ai)")
    if not parts_present:
        s_drill = None

    score, status, mnotes = core.mean_score([("backup_verify", s_backup), ("restore_drill", s_drill)])
    gate_pass = bv_ok and rd_ok
    score = _cap(score, gate_pass, gate_cap)
    r1 = lambda v: None if v is None else round(v, 1)  # noqa: E731
    metrics = {
        "backup_verify_verdict": (bv or {}).get("verdict") if isinstance(bv, dict) else None,
        "backup_verify_age_h": r1(bv_age),
        "restore_drill_outcome": rd.get("outcome") if isinstance(rd, dict) else None,
        "restore_drill_age_h": r1(rd_age),
        "n8n_lab_drill_ok": lab.get("ok") if isinstance(lab, dict) else None,
        "n8n_lab_drill_age_h": r1(lab_age),
        "s_backup": s_backup, "s_drill": s_drill,
    }
    evid = [core.evidence(bv_rel, present=isinstance(bv, dict), verdict=metrics["backup_verify_verdict"],
                          age_h=metrics["backup_verify_age_h"], max_age_h=bv_max_h),
            core.evidence(rd_rel, present=isinstance(rd, dict), outcome=metrics["restore_drill_outcome"],
                          age_h=metrics["restore_drill_age_h"], max_age_h=rd_max_h),
            core.evidence(lab_rel, present=isinstance(lab, dict), ok=metrics["n8n_lab_drill_ok"],
                          age_h=metrics["n8n_lab_drill_age_h"])]
    return core.dim_result(dim, score=score, gate_rule=rule, gate_pass=gate_pass, metrics=metrics,
                           evidence_list=evid, status=status, notes=notes + mnotes)


COLLECTORS = {"self_healing": collect_self_healing, "recovery": collect_recovery}
