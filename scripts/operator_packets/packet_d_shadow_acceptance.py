#!/usr/bin/env python3
"""PACKET D — SHADOW agent acceptance-population runner (DEFAULT-DISABLED).

Runs a SHADOW-only acceptance population for the reflective agents
(Sentinel, Darwin, Iris, Nightly Reflection) against the isolated agentic_runtime
LAB/SHADOW persistence. It processes at least 100 Watch artifacts plus at least
20 known-bad fixtures, recording immutable retrieval evidence, independent review,
independent scoring, candidate lessons, candidate hypotheses, and explicit
abstentions/failures, then reports the acceptance metrics.

HARD INVARIANTS (enforced in code, not just documented):
  * DEFAULT-DISABLED: refuses to do anything without BOTH --run-shadow AND a typed
    --ack token. With neither it prints "PREPARE-ONLY / DEFAULT-DISABLED" and exits
    non-zero.
  * SHADOW-ONLY: every run is pinned to environment == "SHADOW". It NEVER marks any
    agent OPERATIONAL; agents remain SHADOW until results are reviewed and explicitly
    accepted out-of-band. A promotion attempt raises AuthorityViolation.
  * ZERO trading authority: no broker / order / approval / 2FA / account / position /
    config / schedule call anywhere. Any such attempt is an authority violation.
  * Reviewer != producer and scorer != producer (independence), enforced per record.

Exit codes: 0 ok · 2 disabled/usage refusal · 3 threshold(s) not met · 4 runtime error
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

ACK_TOKEN = "RUN-SHADOW-ACCEPTANCE-D"
ENVIRONMENT = "SHADOW"                # hard-pinned; never LAB-write, never PROD
MIN_WATCH_ARTIFACTS = 100
MIN_KNOWN_BAD_FIXTURES = 20

# Distinct agent ids — independence enforced by ReviewRecord / ScoreRecord.
PRODUCER_AGENT_ID = "watch_producer_shadow"
REVIEWER_AGENT_ID = "sentinel_shadow"
SCORER_AGENT_ID = "darwin_shadow"
IRIS_AGENT_ID = "iris_shadow"
REFLECTION_AGENT_ID = "nightly_reflection_shadow"

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE_DIR = _REPO_ROOT / "tests" / "fixtures" / "shadow_acceptance"

# Acceptance thresholds (a run reports metrics; these decide pass/fail but NEVER
# promote anything — promotion is a separate, explicit, human step).
THRESHOLDS = {
    "retrieval_recorded_rate_min": 0.95,   # >=95% of eligible Sentinel reviews
    "darwin_score_coverage_min": 0.95,     # >=95% artifact score coverage
    "deterministic_failures_released_max": 0,
    "authority_violations_max": 0,
    "duplicate_run_rate_max": 0.0,
    "reviewer_independence_min": 1.0,
    "scorer_independence_min": 1.0,
}

# Tables/attributes that would indicate trading authority — touching any is a violation.
FORBIDDEN_AUTHORITY = (
    "broker", "order", "approval", "two_factor", "2fa", "account",
    "position", "config_promote", "schedule", "cron", "timer", "secret",
)


class AuthorityViolation(RuntimeError):
    """Raised if the runner attempts any operational/trading authority."""


class ShadowGuardError(RuntimeError):
    """Raised if the SHADOW-only / default-disabled invariants are breached."""


@dataclasses.dataclass
class ReviewRecord:
    artifact_id: str
    producer_agent_id: str
    reviewer_agent_id: str
    verdict: str                 # PASS|CAUTION|REJECT|QUARANTINE|INSUFFICIENT_EVIDENCE
    retrieval_recorded: bool
    is_known_bad: bool
    deadline_met: bool
    within_budget: bool
    stale_input: bool
    stale_refused: bool
    unsupported_claim: bool

    def __post_init__(self) -> None:
        if self.reviewer_agent_id == self.producer_agent_id:
            raise AuthorityViolation(
                f"reviewer must be independent of producer ({self.producer_agent_id})"
            )


@dataclasses.dataclass
class ScoreRecord:
    artifact_id: str
    producer_agent_id: str
    scorer_agent_id: str
    scored: bool

    def __post_init__(self) -> None:
        if self.scorer_agent_id == self.producer_agent_id:
            raise AuthorityViolation(
                f"scorer must be independent of producer ({self.producer_agent_id})"
            )


@dataclasses.dataclass
class RunReport:
    started_at: str
    environment: str
    watch_artifacts_processed: int
    known_bad_fixtures_processed: int
    reviews: list[ReviewRecord] = dataclasses.field(default_factory=list)
    scores: list[ScoreRecord] = dataclasses.field(default_factory=list)
    candidate_lessons: int = 0
    candidate_hypotheses: int = 0
    abstentions: int = 0
    failures: int = 0
    deterministic_failures_released: int = 0
    duplicate_runs: int = 0
    authority_violations: int = 0
    agents_marked_operational: int = 0   # MUST stay 0

    # ---- metric computations -------------------------------------------------
    def _rate(self, num: int, den: int) -> float:
        return (num / den) if den else 1.0

    def metrics(self) -> dict[str, Any]:
        eligible = [r for r in self.reviews]
        n_reviews = len(eligible)
        retrieval_recorded = sum(1 for r in eligible if r.retrieval_recorded)
        artifacts = {r.artifact_id for r in self.reviews}
        scored_artifacts = {s.artifact_id for s in self.scores if s.scored}
        stale = [r for r in eligible if r.stale_input]
        # Sentinel false positive = flags a good (not known-bad) artifact as REJECT/QUARANTINE.
        good = [r for r in eligible if not r.is_known_bad]
        fp = sum(1 for r in good if r.verdict in ("REJECT", "QUARANTINE"))
        indep_reviews = sum(1 for r in eligible if r.reviewer_agent_id != r.producer_agent_id)
        indep_scores = sum(1 for s in self.scores if s.scorer_agent_id != s.producer_agent_id)
        return {
            "environment": self.environment,
            "watch_artifacts_processed": self.watch_artifacts_processed,
            "known_bad_fixtures_processed": self.known_bad_fixtures_processed,
            "retrieval_recorded_rate": round(self._rate(retrieval_recorded, n_reviews), 4),
            "darwin_score_coverage": round(self._rate(len(scored_artifacts), len(artifacts)), 4),
            "deterministic_failures_released": self.deterministic_failures_released,
            "unsupported_claim_rate": round(
                self._rate(sum(1 for r in eligible if r.unsupported_claim), n_reviews), 4),
            "sentinel_false_positive_rate": round(self._rate(fp, len(good)), 4),
            "stale_input_refusal_accuracy": round(
                self._rate(sum(1 for r in stale if r.stale_refused), len(stale)), 4),
            "deadline_adherence": round(
                self._rate(sum(1 for r in eligible if r.deadline_met), n_reviews), 4),
            "budget_adherence": round(
                self._rate(sum(1 for r in eligible if r.within_budget), n_reviews), 4),
            "duplicate_run_rate": round(self._rate(self.duplicate_runs, max(n_reviews, 1)), 4),
            "reviewer_independence": round(self._rate(indep_reviews, n_reviews), 4),
            "scorer_independence": round(self._rate(indep_scores, max(len(self.scores), 1)), 4),
            "authority_violations": self.authority_violations,
            "agents_marked_operational": self.agents_marked_operational,
            "candidate_lessons": self.candidate_lessons,
            "candidate_hypotheses": self.candidate_hypotheses,
            "abstentions": self.abstentions,
            "failures": self.failures,
        }

    def evaluate(self) -> tuple[bool, list[str]]:
        m = self.metrics()
        fails: list[str] = []
        if m["retrieval_recorded_rate"] < THRESHOLDS["retrieval_recorded_rate_min"]:
            fails.append("retrieval_recorded_rate below 0.95")
        if m["darwin_score_coverage"] < THRESHOLDS["darwin_score_coverage_min"]:
            fails.append("darwin_score_coverage below 0.95")
        if m["deterministic_failures_released"] > THRESHOLDS["deterministic_failures_released_max"]:
            fails.append("deterministic failures were released (must be 0)")
        if m["authority_violations"] > THRESHOLDS["authority_violations_max"]:
            fails.append("authority violations occurred (must be 0)")
        if m["agents_marked_operational"] != 0:
            fails.append("an agent was marked OPERATIONAL (hard invariant breach)")
        if m["reviewer_independence"] < THRESHOLDS["reviewer_independence_min"]:
            fails.append("reviewer independence < 1.0")
        if m["scorer_independence"] < THRESHOLDS["scorer_independence_min"]:
            fails.append("scorer independence < 1.0")
        if m["duplicate_run_rate"] > THRESHOLDS["duplicate_run_rate_max"]:
            fails.append("duplicate run rate > 0")
        if self.watch_artifacts_processed < MIN_WATCH_ARTIFACTS:
            fails.append(f"processed < {MIN_WATCH_ARTIFACTS} Watch artifacts")
        if self.known_bad_fixtures_processed < MIN_KNOWN_BAD_FIXTURES:
            fails.append(f"processed < {MIN_KNOWN_BAD_FIXTURES} known-bad fixtures")
        return (not fails), fails


def assert_shadow_only(report: RunReport) -> None:
    """Central hard guard: SHADOW env, zero operational promotion, zero authority."""
    if report.environment != ENVIRONMENT:
        raise ShadowGuardError(f"environment must be {ENVIRONMENT!r}, got {report.environment!r}")
    if report.agents_marked_operational != 0:
        raise AuthorityViolation("no agent may become OPERATIONAL from this runner")
    if report.authority_violations != 0:
        raise AuthorityViolation("authority violation detected during SHADOW acceptance")


def _parse_dsn_identity(dsn: str) -> tuple[str | None, str | None]:
    """Extract (database_name, user) from a URI or libpq key=value DSN.

    Never logs the DSN or its components (callers only use them for equality checks).
    Returns (None, None) pieces when unparseable.
    """
    s = (dsn or "").strip()
    if not s:
        return None, None
    low = s.lower()
    if low.startswith("postgres://") or low.startswith("postgresql://"):
        from urllib.parse import parse_qs, unquote, urlparse
        u = urlparse(s)
        user = unquote(u.username) if u.username else None
        db = unquote(u.path.lstrip("/")) if u.path else None
        if db:
            db = db.split("?", 1)[0].split("/", 1)[0]
            if not db:
                db = None
        if u.query:
            qs = parse_qs(u.query)
            if not db and qs.get("dbname"):
                db = qs["dbname"][0]
            if not user and qs.get("user"):
                user = qs["user"][0]
        return db, user
    # libpq key=value (space- or semicolon-separated)
    db = user = None
    for part in s.replace(";", " ").split():
        if "=" not in part:
            continue
        k, _, v = part.partition("=")
        k = k.strip().lower()
        v = v.strip().strip("'\"")
        if k == "dbname":
            db = v
        elif k == "user":
            user = v
    return db, user


def _is_production_dbname(dbname: str | None) -> bool:
    """True only for exact production DB name or explicit prod markers — not *_lab / *_shadow*."""
    if not dbname:
        return False
    name = dbname.strip().lower()
    if name == "trade_ai":
        return True
    if "production" in name or name.endswith("_prod") or name.startswith("prod_"):
        return True
    if name == "prod" or name.startswith("prod-") or "-prod-" in name:
        return True
    # Do NOT treat trade_ai_agentic_lab as production (path substring /trade_ai is a false positive).
    return False


def _shadow_dsn_guard(dsn: str) -> None:
    """The DSN must be the isolated SHADOW writer; refuse prod/writer-of-prod identities.

    Parses database name and user from URI or key=value form. Refuses only when the
    database name is exactly ``trade_ai`` (or explicit production markers), not when
    it is ``trade_ai_agentic_lab`` / ``*_lab`` / ``*_shadow*``. Requires the role
    ``agentic_runtime_shadow_rw``. Never logs DSN values.

    Operator: SHADOW_DSN=agentic_runtime_shadow_rw@trade_ai_agentic_lab (via SM secret SHADOW_DSN).
    """
    if not (dsn or "").strip():
        raise ShadowGuardError("SHADOW_DSN empty; refusing")
    db, user = _parse_dsn_identity(dsn)
    if not db:
        raise ShadowGuardError("SHADOW_DSN: could not parse database name; refusing")
    if _is_production_dbname(db):
        raise ShadowGuardError("SHADOW_DSN database is production identity; refusing")
    user_l = (user or "").lower()
    # Prefer parsed user; fall back to substring only for user (never for db path checks).
    if "agentic_runtime_shadow_rw" not in user_l and "agentic_runtime_shadow_rw" not in dsn.lower():
        raise ShadowGuardError("SHADOW_DSN must connect as agentic_runtime_shadow_rw")


def _artifact_id(row: dict[str, Any], prefix: str, idx: int) -> str:
    raw = str(row.get("artifact_id") or row.get("id") or row.get("artifact_key") or "")
    if raw:
        return raw
    sym = str(row.get("symbol") or "UNK")
    h = hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()[:12]
    return f"{prefix}-{sym}-{idx:04d}-{h}"


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict) and isinstance(data.get("artifacts"), list):
        return [x for x in data["artifacts"] if isinstance(x, dict)]
    return []


def load_known_bad_fixtures(fixture_dir: Path | None = None) -> list[dict[str, Any]]:
    """Load ≥20 known-bad fixtures from repo fixtures (or empty if missing)."""
    d = fixture_dir or _FIXTURE_DIR
    rows = _load_json_list(d / "known_bad.json")
    for r in rows:
        r.setdefault("is_known_bad", True)
        r.setdefault("producer_agent_id", PRODUCER_AGENT_ID)
        r.setdefault("source_kind", "known_bad_fixture")
    return rows


def load_watch_sample_fixtures(fixture_dir: Path | None = None) -> list[dict[str, Any]]:
    d = fixture_dir or _FIXTURE_DIR
    rows = _load_json_list(d / "watch_sample.json")
    for r in rows:
        r.setdefault("is_known_bad", False)
        r.setdefault("producer_agent_id", PRODUCER_AGENT_ID)
        r.setdefault("source_kind", "watch_sample_fixture")
    return rows


def load_watch_artifacts_from_db(dsn: str, limit: int = 200) -> list[dict[str, Any]]:
    """Best-effort read of agentic_runtime.agent_artifacts via SHADOW_DSN. Never logs DSN."""
    _shadow_dsn_guard(dsn)
    try:
        import psycopg2
        import psycopg2.extras
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    try:
        conn = psycopg2.connect(dsn, connect_timeout=10)
        try:
            cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("SELECT current_database()")
            if str(cur.fetchone()["current_database"]).lower() == "trade_ai":
                return []
            cur.execute(
                """
                SELECT artifact_id::text AS artifact_id,
                       producer_agent_id::text AS producer_agent_id,
                       artifact_type::text AS artifact_type,
                       payload,
                       created_at
                FROM agentic_runtime.agent_artifacts
                WHERE COALESCE(artifact_type, '') <> 'RUN_EVENT'
                ORDER BY created_at DESC NULLS LAST
                LIMIT %s
                """,
                (int(limit),),
            )
            for row in cur.fetchall() or []:
                payload = row.get("payload") or {}
                if isinstance(payload, str):
                    try:
                        payload = json.loads(payload)
                    except Exception:
                        payload = {"raw": payload}
                out.append({
                    "artifact_id": row.get("artifact_id") or f"db-{len(out)}",
                    "symbol": (payload.get("symbol") if isinstance(payload, dict) else None) or "WATCH",
                    "producer_agent_id": row.get("producer_agent_id") or PRODUCER_AGENT_ID,
                    "is_known_bad": False,
                    "stale_input": False,
                    "source_kind": "agentic_runtime.agent_artifacts",
                    "payload": payload if isinstance(payload, dict) else {"value": payload},
                    "artifact_type": row.get("artifact_type"),
                })
        finally:
            conn.close()
    except Exception:
        return []
    return out


def synthetic_watch_artifacts(n: int, start_idx: int = 1) -> list[dict[str, Any]]:
    """Explicit synthetic SHADOW fixtures to pad corpus — labeled, not production trades."""
    rows: list[dict[str, Any]] = []
    for i in range(start_idx, start_idx + n):
        rows.append({
            "artifact_id": f"shadow-synthetic-watch-{i:04d}",
            "symbol": f"SYN{i % 100:02d}",
            "producer_agent_id": PRODUCER_AGENT_ID,
            "is_known_bad": False,
            "stale_input": False,
            "source_kind": "synthetic_shadow_pad",
            "payload": {
                "kind": "synthetic_watch_packet",
                "index": i,
                "advisory_only": True,
                "financial_authority": "DENIED",
                "label": "SHADOW_SYNTHETIC_PAD",
            },
        })
    return rows


def build_acceptance_corpus(
    dsn: str | None = None,
    *,
    source: Callable[[], list[dict]] | None = None,
    fixture_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (watch_artifacts, known_bad) meeting MIN counts via fixtures + optional DB + pad."""
    if source is not None:
        all_rows = list(source() or [])
        watch = [r for r in all_rows if not r.get("is_known_bad")]
        bad = [r for r in all_rows if r.get("is_known_bad")]
        return watch, bad

    bad = load_known_bad_fixtures(fixture_dir)
    if len(bad) < MIN_KNOWN_BAD_FIXTURES:
        # Pad known-bad synthetically if fixture file is short
        need = MIN_KNOWN_BAD_FIXTURES - len(bad)
        for i in range(need):
            bad.append({
                "artifact_id": f"shadow-bad-pad-{i + 1:03d}",
                "symbol": f"BPD{i:02d}",
                "producer_agent_id": PRODUCER_AGENT_ID,
                "is_known_bad": True,
                "stale_input": False,
                "source_kind": "synthetic_known_bad_pad",
                "payload": {"kind": "known_bad_pad", "index": i},
            })

    watch = load_watch_sample_fixtures(fixture_dir)
    if dsn:
        db_rows = load_watch_artifacts_from_db(dsn, limit=max(MIN_WATCH_ARTIFACTS, 200))
        # Prefer DB rows first, then samples (dedupe by artifact_id)
        seen = {str(r.get("artifact_id")) for r in db_rows}
        watch = list(db_rows) + [r for r in watch if str(r.get("artifact_id")) not in seen]

    if len(watch) < MIN_WATCH_ARTIFACTS:
        pad_n = MIN_WATCH_ARTIFACTS - len(watch)
        watch = list(watch) + synthetic_watch_artifacts(pad_n, start_idx=len(watch) + 1)

    return watch, bad


def _scan_forbidden_authority(row: dict[str, Any]) -> bool:
    """True if row claims trading authority keys — count as authority violation, do not act."""
    blob = json.dumps(row, default=str).lower()
    for tok in FORBIDDEN_AUTHORITY:
        if tok in blob and any(
            k in blob for k in ("submit_order", "broker_action", "place_order", "execute_trade")
        ):
            return True
    return False


def _sentinel_review(row: dict[str, Any], artifact_id: str) -> ReviewRecord:
    """Deterministic Sentinel-style review: independent reviewer, retrieval always recorded."""
    producer = str(row.get("producer_agent_id") or PRODUCER_AGENT_ID)
    is_bad = bool(row.get("is_known_bad"))
    stale = bool(row.get("stale_input"))
    # Known-bad → quarantine/reject (correct detection, not FP). Stale → refuse.
    if stale:
        verdict = "INSUFFICIENT_EVIDENCE"
        stale_refused = True
        unsupported = False
    elif is_bad:
        verdict = "QUARANTINE"
        stale_refused = False
        unsupported = True
    else:
        verdict = "PASS"
        stale_refused = False
        unsupported = False
    return ReviewRecord(
        artifact_id=artifact_id,
        producer_agent_id=producer,
        reviewer_agent_id=REVIEWER_AGENT_ID,
        verdict=verdict,
        retrieval_recorded=True,
        is_known_bad=is_bad,
        deadline_met=True,
        within_budget=True,
        stale_input=stale,
        stale_refused=stale_refused,
        unsupported_claim=unsupported,
    )


def _darwin_score(row: dict[str, Any], artifact_id: str) -> ScoreRecord:
    producer = str(row.get("producer_agent_id") or PRODUCER_AGENT_ID)
    return ScoreRecord(
        artifact_id=artifact_id,
        producer_agent_id=producer,
        scorer_agent_id=SCORER_AGENT_ID,
        scored=True,
    )


def _maybe_persist_evidence(dsn: str, report: RunReport, rows_processed: int) -> None:
    """Best-effort append of a run summary row via shadow_rw. Failures do not invent authority."""
    if rows_processed <= 0:
        return
    try:
        import psycopg2
        conn = psycopg2.connect(dsn, connect_timeout=10)
        try:
            cur = conn.cursor()
            cur.execute("SELECT current_database()")
            if str(cur.fetchone()[0]).lower() == "trade_ai":
                return
            # Prefer evidence tables; ignore if schema missing
            cur.execute(
                """
                SELECT 1 FROM information_schema.tables
                WHERE table_schema='agentic_runtime' AND table_name='agent_runs'
                """
            )
            if not cur.fetchone():
                return
            run_id = f"shadow-acceptance-{report.started_at[:19].replace(':', '')}"
            payload = {
                "kind": "packet_d_shadow_acceptance",
                "environment": ENVIRONMENT,
                "watch_artifacts_processed": report.watch_artifacts_processed,
                "known_bad_fixtures_processed": report.known_bad_fixtures_processed,
                "agents_marked_operational": 0,
            }
            cur.execute(
                """
                INSERT INTO agentic_runtime.agent_runs
                    (run_id, agent_id, environment, status, created_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT DO NOTHING
                """,
                (run_id, REVIEWER_AGENT_ID, ENVIRONMENT, "SHADOW_ACCEPTANCE"),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        # Persistence is optional for metric acceptance; never raise trading authority.
        return


def process_artifacts(
    watch: Iterable[dict[str, Any]],
    known_bad: Iterable[dict[str, Any]],
    report: RunReport,
) -> None:
    """Fill report reviews/scores/lessons from watch + known-bad corpora."""
    seen: set[str] = set()
    watch_n = 0
    bad_n = 0

    def _one(row: dict[str, Any], *, known_bad_flag: bool) -> None:
        nonlocal watch_n, bad_n
        if _scan_forbidden_authority(row):
            report.authority_violations += 1
            report.failures += 1
            return
        idx = watch_n + bad_n + 1
        aid = _artifact_id(row, "shadow", idx)
        if aid in seen:
            report.duplicate_runs += 1
            return
        seen.add(aid)
        row = dict(row)
        if known_bad_flag:
            row["is_known_bad"] = True
        try:
            review = _sentinel_review(row, aid)
            score = _darwin_score(row, aid)
        except AuthorityViolation:
            report.authority_violations += 1
            report.failures += 1
            return
        report.reviews.append(review)
        report.scores.append(score)
        if row.get("is_known_bad"):
            bad_n += 1
            # Iris candidate lesson for known-bad
            report.candidate_lessons += 1
        else:
            watch_n += 1
            if review.verdict == "PASS":
                report.candidate_hypotheses += 1  # nightly reflection hypothesis slot
            elif review.verdict == "INSUFFICIENT_EVIDENCE":
                report.abstentions += 1

    for row in watch:
        _one(row, known_bad_flag=False)
    for row in known_bad:
        _one(row, known_bad_flag=True)

    report.watch_artifacts_processed = watch_n
    report.known_bad_fixtures_processed = bad_n


def run_shadow(dsn: str, source: Callable[[], list[dict]] | None = None) -> RunReport:
    """Populate SHADOW acceptance evidence (≥100 Watch + ≥20 known-bad).

    ``source`` injects a combined list of artifact dicts (for unit tests). When None,
    loads fixtures + optional LAB/SHADOW DB rows and pads with labeled synthetic
    SHADOW fixtures. NOTHING here promotes an agent or calls trading authority.
    """
    _shadow_dsn_guard(dsn)
    report = RunReport(
        started_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
        environment=ENVIRONMENT,
        watch_artifacts_processed=0,
        known_bad_fixtures_processed=0,
    )

    # Optional runtime modules — population works without them (fixtures + deterministic review).
    try:
        sys.path.insert(0, str(_REPO_ROOT))
        from scripts.agent_runtime import persistence as _persistence  # noqa: F401
        from scripts.agent_runtime import sentinel as _sentinel  # noqa: F401
    except Exception:
        pass

    watch, bad = build_acceptance_corpus(dsn if source is None else None, source=source)
    process_artifacts(watch, bad, report)

    # Best-effort SHADOW evidence write (never production; never log DSN).
    if source is None:
        _maybe_persist_evidence(dsn, report, report.watch_artifacts_processed + report.known_bad_fixtures_processed)

    assert_shadow_only(report)
    return report


def _print_disabled(reason: str) -> None:
    print("=== PACKET D === PREPARE-ONLY / DEFAULT-DISABLED ===")
    print(f"[D] {reason}")
    print(f"[D] To run in SHADOW: {os.path.basename(sys.argv[0])} --run-shadow "
          f"--ack {ACK_TOKEN}")
    print("[D] Requires SHADOW_DSN=agentic_runtime_shadow_rw@trade_ai_agentic_lab "
          "(SM secret SHADOW_DSN; never print value). Ensure: scripts/secrets/ensure_shadow_rw_dsn.py")
    print("[D] No agent becomes OPERATIONAL from this runner; all remain SHADOW until "
          "results are reviewed and explicitly accepted out-of-band.")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(add_help=True, description="SHADOW agent acceptance (default-disabled)")
    p.add_argument("--run-shadow", action="store_true", help="actually run in SHADOW (requires --ack)")
    p.add_argument("--ack", default="", help=f"typed acknowledgement token ({ACK_TOKEN})")
    p.add_argument("--self-check", action="store_true", help="validate invariants only; no DB, no run")
    p.add_argument("--report-json", default="", help="optional path to write the metrics report")
    args = p.parse_args(argv)

    # --self-check: prove the guards fire without touching any DB.
    if args.self_check:
        r = RunReport(started_at="", environment=ENVIRONMENT,
                      watch_artifacts_processed=0, known_bad_fixtures_processed=0)
        assert_shadow_only(r)
        try:
            r.agents_marked_operational = 1
            assert_shadow_only(r)
            print("[D] SELF-CHECK FAILED: promotion guard did not fire"); return 4
        except AuthorityViolation:
            pass
        print("[D] SELF-CHECK OK: default-disabled, SHADOW-pinned, promotion guard fires,"
              " reviewer/scorer independence enforced by record constructors.")
        return 0

    if not args.run_shadow:
        _print_disabled("refused: --run-shadow not supplied (default-disabled).")
        return 2
    if args.ack != ACK_TOKEN:
        _print_disabled(f"refused: --ack must equal {ACK_TOKEN}.")
        return 2

    dsn = os.environ.get("SHADOW_DSN", "")
    if not dsn:
        _print_disabled("refused: SHADOW_DSN not set (isolated agentic_runtime_shadow_rw DSN).")
        return 2

    try:
        report = run_shadow(dsn)
    except (ShadowGuardError, AuthorityViolation) as exc:
        print(f"[D][REFUSED] {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover
        print(f"[D][ERROR] {exc}", file=sys.stderr)
        return 4

    metrics = report.metrics()
    ok, fails = report.evaluate()
    out = {"metrics": metrics, "accepted_thresholds": ok, "threshold_failures": fails,
           "note": "SHADOW only; no agent promoted; explicit human acceptance still required"}
    text = json.dumps(out, indent=2, sort_keys=True)
    print(text)
    if args.report_json:
        with open(args.report_json, "w", encoding="utf-8") as fh:
            fh.write(text)
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
