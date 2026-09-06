"""Daily integrity engine — the deterministic checks, run on a schedule.

WHY
---
On 2026-09-06 a single session found nine defects. Every one was mechanically
detectable, and every one had been silently true for weeks or months:

  taxonomy_tagger cron commented out            2 months   sector tagging at 5%
  librarian dedup guards unbounded              96 days    advisory_events dead
  strategy_rule_engine scheduled nowhere        30+ days   0 CIO decisions
  rows_produced defaulting to 0                 always     4 false alarms
  six .env paths resolved via Path(__file__)    always     latent on every release
  build_catalyst_graph unscheduled              always     graph frozen
  no_match sentinel with no TTL                 always     would foreclose a corpus
  overnight lane schedule vs guard disjoint     lifetime   never ran once
  cio_decision_engine inner-joining empty table 30 days    every layer "success"

None needed judgment. They needed someone to look, on a schedule, at things that
do not announce themselves. That is what this is.

FINDS, DOES NOT FIX
-------------------
Every check reports; none repairs. That is deliberate and it is not timidity:

  · AGENTS.md forbids auto-remediating divergent copies of an authoritative store
  · scheduling a producer is an operator decision with cost and blast radius
  · re-enabling taxonomy_tagger would have DESTROYED a 32,060-row corpus — the
    obvious "fix" was the damaging action, and an auto-fixer would have taken it

A check that proposes is auditable. A check that acts is another thing nobody is
watching. `--json` output is machine-readable so a human or an operator-approved
runbook can act on it.

NO MODEL RUNS HERE
------------------
Every question below is a count, a clock, a scheduler lookup or an AST walk.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = "DeterministicIntegrity@v1"
AUTHORITY = "READ_ONLY_ADVISORY"

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"

P0, P1, P2 = "P0", "P1", "P2"


def _finding(check: str, sev: str, subject: str, detail: str, fix: str) -> dict[str, Any]:
    return {"check": check, "severity": sev, "subject": subject,
            "detail": detail, "remediation": fix}


def _py_files() -> Iterable[Path]:
    for p in sorted(SCRIPTS.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        yield p


def _source(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _code_only(text: str) -> str:
    """Strip docstrings so a comment describing a defect cannot satisfy a check —
    the trap that made three guards pass while the defect was still present."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    try:
        return ast.unparse(tree)
    except Exception:
        return text


# ── C1: credentials or durable state resolved relative to the source tree ───

_TREE_ENV = re.compile(
    r"(Path\(__file__\)[^\n]{0,80}\.env|os\.path\.dirname\(__file__\)[^\n]{0,80}\.env"
    r"|PR\s*/\s*[\"']\.env[\"']|PROJECT_ROOT\s*/\s*[\"']\.env[\"'])")


def check_tree_relative_secrets() -> list[dict[str, Any]]:
    """A release has no .env — secrets are deliberately not deployed. Anything
    resolving .env from its own file location dies the moment it runs from a
    release, and works forever from the dev tree, so it hides."""
    out = []
    for p in _py_files():
        code = _code_only(_source(p))
        if _TREE_ENV.search(code):
            out.append(_finding(
                "tree_relative_secret", P1, str(p.relative_to(ROOT)),
                "resolves .env relative to its own file; a release has no .env",
                "use lib/env_bootstrap.load_env(); raise on missing, never return None"))
    return out


# ── C2: producers nothing schedules ─────────────────────────────────────────

def _crontab() -> str:
    try:
        r = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=20)
        return r.stdout or ""
    except Exception:
        return ""


def _timers() -> str:
    try:
        r = subprocess.run(["systemctl", "--user", "list-timers", "--all"],
                           capture_output=True, text=True, timeout=20)
        return r.stdout or ""
    except Exception:
        return ""


def is_scheduled(script: str, cron: Optional[str] = None,
                 timers: Optional[str] = None) -> bool:
    """cron OR systemd, and a COMMENTED cron does not count.

    taxonomy_tagger's line sat commented for two months and every audit that
    grepped the filename found it and concluded it was scheduled.
    """
    cron = _crontab() if cron is None else cron
    timers = _timers() if timers is None else timers
    for line in cron.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if script in s:
            return True
    return script.replace(".py", "") in timers


def check_unscheduled_producers(producers: Iterable[str]) -> list[dict[str, Any]]:
    cron, timers = _crontab(), _timers()
    out = []
    for script in producers:
        if not is_scheduled(script, cron, timers):
            out.append(_finding(
                "producer_unscheduled", P1, script,
                "no active cron line and no systemd timer",
                "schedule it, or record it as deliberately manual in AGENTS.md"))
    return out


def check_commented_out_crons(watch: Iterable[str]) -> list[dict[str, Any]]:
    """A cron that exists only as a comment is the most deceptive state there is:
    present to a grep, absent to the scheduler."""
    cron = _crontab()
    out = []
    for script in watch:
        commented = any(l.strip().startswith("#") and script in l for l in cron.splitlines())
        active = any((not l.strip().startswith("#")) and script in l
                     for l in cron.splitlines() if l.strip())
        if commented and not active:
            out.append(_finding(
                "cron_commented_out", P1, script,
                "present in crontab ONLY as a comment — a grep finds it, the scheduler does not",
                "re-enable deliberately, or delete the line so it stops reading as scheduled"))
    return out


# ── C3: suppression without a shelf life ────────────────────────────────────

_COUNT_GUARD = re.compile(
    r"SELECT\s+COUNT\(\*\)\s+FROM\s+(\w+)(?P<body>[^;\"']{0,400})", re.I)


def check_unbounded_dedup(paths: Iterable[Path]) -> list[dict[str, Any]]:
    """A dedup COUNT over all history is a permanent mute, not deduplication.

    Three rows filed on 2026-06-02 switched off two of four librarian detectors
    for 96 days while 108,102 catalysts matched.
    """
    out = []
    for p in paths:
        code = _code_only(_source(p))
        for m in _COUNT_GUARD.finditer(code):
            body = m.group("body")
            if "WHERE" not in body.upper():
                continue
            bounded = any(k in body for k in
                          ("make_interval", "INTERVAL", "interval", "now() -", "NOW() -"))
            if not bounded:
                out.append(_finding(
                    "unbounded_dedup_guard", P2, str(p.relative_to(ROOT)),
                    f"COUNT(*) over all history on {m.group(1)} gates a detector",
                    "bound it with a TTL; one old row must not mute a detector forever"))
                break
    return out


# ── C4: a consumer inner-joining an empty producer ──────────────────────────

def check_empty_join_inputs(conn, pairs: Iterable[tuple[str, str]]) -> list[dict[str, Any]]:
    """cio_decision_engine INNER JOINed a table with 0 rows and reported success
    on 3,010 runs a week for 30 days. An empty producer is indistinguishable from
    a quiet market unless something counts the rows."""
    out = []
    cur = conn.cursor()
    for consumer, table in pairs:
        try:
            cur.execute(f"SELECT count(*) FROM {table}")
            n = cur.fetchone()[0]
        except Exception as exc:
            out.append(_finding("join_input_unreadable", P2, table,
                                f"{type(exc).__name__}", "check the table exists"))
            continue
        if n == 0:
            out.append(_finding(
                "join_input_empty", P0, table,
                f"{consumer} INNER JOINs {table}, which has 0 rows — it can never produce",
                "find and schedule the producer; the consumer will keep reporting success"))
    return out


# ── C5: stores that stopped ─────────────────────────────────────────────────

def check_stale_stores(conn, max_age_days: int = 14,
                       min_rows: int = 100) -> list[dict[str, Any]]:
    """Newest ROW, not last autoanalyze — autoanalyze measures statistics
    collection, not writes, and reports tables as stale that are perfectly fine."""
    out = []
    cur = conn.cursor()
    cur.execute("""
        SELECT c.relname FROM pg_stat_user_tables s
        JOIN pg_class c ON c.oid = s.relid
        JOIN information_schema.columns col
          ON col.table_name = c.relname AND col.column_name = 'created_at'
        WHERE s.n_live_tup > %s
          AND c.relname NOT LIKE 'bak\\_%%' AND c.relname NOT LIKE '%%_history'
    """, (min_rows,))
    for (t,) in cur.fetchall():
        try:
            cur.execute(f"SELECT max(created_at), count(*) FROM {t}")
            newest, n = cur.fetchone()
        except Exception:
            continue
        if newest is None:
            continue
        age = (datetime.now(timezone.utc) - newest).days
        if age >= max_age_days:
            out.append(_finding(
                "store_stale", P2, t, f"newest row {age}d old ({n} rows)",
                "identify the producer and whether it is still scheduled"))
    return out


# ── C6: an unmeasured metric reported as a measurement ──────────────────────

def check_zero_default_metrics(paths: Iterable[Path]) -> list[dict[str, Any]]:
    """0 must not be the default for a measurement. It made 16 of 20 pipelines
    claim they produced nothing, so the alarm could neither fire nor clear."""
    out = []
    for p in paths:
        code = _code_only(_source(p))
        if re.search(r"rows_processed\s*:\s*int\s*=\s*0|self\._rows\s*=\s*0", code):
            out.append(_finding(
                "zero_default_metric", P1, str(p.relative_to(ROOT)),
                "a row-count metric defaults to 0, so unmeasured is indistinguishable from empty",
                "default to None and write JSON null; keep an explicit 0 meaningful"))
    return out


#: Checks whose findings are a POPULATION, not incidents. 314 scripts share the
#: tree-relative .env pattern; emitting 314 alarms produces an alert nobody
#: reads, and AGENTS.md is explicit that a mechanical sweep is a candidate
#: generator, not a count. These collapse to one finding carrying the count and a
#: sample, so the number is visible and the noise is not.
AGGREGATE_CHECKS = {"tree_relative_secret", "unbounded_dedup_guard"}

#: How many subjects to name inside an aggregated finding.
AGGREGATE_SAMPLE = 5


def _aggregate(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out, buckets = [], {}
    for f in findings:
        if f["check"] in AGGREGATE_CHECKS:
            buckets.setdefault(f["check"], []).append(f)
        else:
            out.append(f)
    for check, group in buckets.items():
        sample = [g["subject"] for g in group[:AGGREGATE_SAMPLE]]
        # A population is latent until something proves an instance is live.
        # Severity is deliberately one notch below the per-instance severity:
        # 314 scripts that work today from the dev tree are a debt, not an outage.
        out.append(_finding(
            check, P2, f"{len(group)} files",
            f"{len(group)} occurrences; sample: {', '.join(sample)}"
            + (" …" if len(group) > AGGREGATE_SAMPLE else ""),
            group[0]["remediation"] + " — systemic; fix as a class, not one by one"))
    return out


def run_all(*, conn=None, producers: Iterable[str] = (),
            watch_crons: Iterable[str] = (),
            join_pairs: Iterable[tuple[str, str]] = (),
            now: Optional[datetime] = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    findings: list[dict[str, Any]] = []
    findings += check_tree_relative_secrets()
    findings += check_unscheduled_producers(producers)
    findings += check_commented_out_crons(watch_crons)
    findings += check_unbounded_dedup(_py_files())
    findings += check_zero_default_metrics(_py_files())
    if conn is not None:
        findings += check_empty_join_inputs(conn, join_pairs)
        findings += check_stale_stores(conn)
    findings = _aggregate(findings)
    by_sev = {s: sum(1 for f in findings if f["severity"] == s) for s in (P0, P1, P2)}
    return {
        "schema": SCHEMA, "authority": AUTHORITY,
        "as_of": now.replace(microsecond=0).isoformat(),
        "findings": findings, "counts": by_sev,
        "ok": not findings, "financial_action": False,
    }
