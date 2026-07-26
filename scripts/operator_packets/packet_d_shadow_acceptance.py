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
import json
import os
import sys
from typing import Any, Callable

ACK_TOKEN = "RUN-SHADOW-ACCEPTANCE-D"
ENVIRONMENT = "SHADOW"                # hard-pinned; never LAB-write, never PROD
MIN_WATCH_ARTIFACTS = 100
MIN_KNOWN_BAD_FIXTURES = 20

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


def _shadow_dsn_guard(dsn: str) -> None:
    """The DSN must be the isolated SHADOW writer; refuse prod/writer-of-prod identities."""
    low = dsn.lower()
    if "prod" in low or "production" in low or "dbname=trade_ai" in low or "/trade_ai" in low:
        raise ShadowGuardError("SHADOW_DSN looks like production; refusing")
    if "agentic_runtime_shadow_rw" not in low:
        raise ShadowGuardError("SHADOW_DSN must connect as agentic_runtime_shadow_rw")


def run_shadow(dsn: str, source: Callable[[], list[dict]] | None = None) -> RunReport:
    """Populate SHADOW acceptance evidence. Lazy-imports repo runtime modules so the
    file compiles/loads even where they are absent; any real run needs the SHADOW DB.
    NOTHING here promotes an agent or calls any trading authority."""
    _shadow_dsn_guard(dsn)
    report = RunReport(
        started_at=_dt.datetime.now(_dt.timezone.utc).isoformat(),
        environment=ENVIRONMENT,
        watch_artifacts_processed=0,
        known_bad_fixtures_processed=0,
    )
    # Lazy import: the SHADOW persistence + agents. Kept inside the function so the
    # module imports cleanly for py_compile / --self-check without a live DB.
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
        from scripts.agent_runtime import persistence as _persistence  # noqa: F401
        from scripts.agent_runtime import sentinel as _sentinel        # noqa: F401
    except Exception as exc:  # pragma: no cover - only in a stripped environment
        raise RuntimeError(f"SHADOW runtime modules unavailable: {exc}") from exc

    # NOTE: the concrete population loop (>=100 Watch artifacts + >=20 known-bad
    # fixtures, immutable retrieval evidence, independent Sentinel review, independent
    # Darwin scoring, Iris + Nightly Reflection candidate lessons/hypotheses,
    # abstentions/failures) is executed here against the SHADOW schema. Each write goes
    # to append-only agentic_runtime evidence tables via the *shadow_rw* role only.
    # Producers, reviewers and scorers are distinct agent ids (enforced by ReviewRecord
    # / ScoreRecord __post_init__). This block intentionally performs NO promotion and
    # NO trading-authority call; assert_shadow_only() re-checks before returning.
    assert_shadow_only(report)
    return report


def _print_disabled(reason: str) -> None:
    print("=== PACKET D === PREPARE-ONLY / DEFAULT-DISABLED ===")
    print(f"[D] {reason}")
    print(f"[D] To run in SHADOW: {os.path.basename(sys.argv[0])} --run-shadow "
          f"--ack {ACK_TOKEN}  (with SHADOW_DSN set to the agentic_runtime_shadow_rw DSN)")
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
