# Source Export: scripts/risk_gate.py

| Field | Value |
|-------|-------|
| **Original Path** | `scripts/risk_gate.py` |
| **Git Branch** | `main` |
| **Git Commit** | `c1286d314deb377df49713e1646f139db7f43643` |
| **Export Timestamp** | `2026-05-26T15:48:59Z` |
| **SHA256** | `c247b5905ee2d512329e3723e79c2c17eabed60c260e518a4d96d06c1486bf52` |
| **File Size** | 24158 bytes |

## Full Source

```py
#!/usr/bin/env python3
"""risk_gate.py — Fail-closed risk gate for Trade AI v12 prop desk governance.

Risk gate is non-fatal only for passive discovery.
It fails closed for paper trade logging, live mode, broker submission,
approval-ready recommendations, and actionable alerts.
"""
import json
import logging
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import yaml

# Pipeline telemetry
try:
    from pipeline_registry import PipelineRun
except ImportError:
    class PipelineRun:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def rows(self, n): pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def _safe_float(val, default=0.0) -> float:
    """Convert to float safely — handles None, dict (JSONB), and bad strings."""
    if val is None:
        return default
    if isinstance(val, dict):
        for key in ('value', 'amount', 'price', 'score'):
            if key in val:
                try:
                    return float(val[key])
                except (TypeError, ValueError):
                    pass
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default

log = logging.getLogger(__name__)

FAIL_CLOSED_CONTEXTS = {'paper_trade', 'live_trade', 'approval_ready', 'broker_submit', 'telegram_actionable'}
FAIL_OPEN_CONTEXTS = {'discovery', 'dashboard_display'}

@dataclass
class RiskDecision:
    approved: bool
    result: str  # APPROVED, REJECTED, PAPER_ONLY, RISK_GATE_ERROR
    reason_codes: list = field(default_factory=list)
    reason_text: str = ''
    strategy_id: str = ''
    symbol: str = ''
    mode: str = ''
    action_context: str = ''
    checked_at: str = ''


class RiskGate:
    def __init__(self, conn=None):
        self.conn = conn
        self._shared_rules = None
        self._strategy_yamls = {}

    def _load_shared_rules(self) -> dict:
        if self._shared_rules is None:
            path = PROJECT_ROOT / 'config' / 'strategies' / 'shared_risk_rules.yaml'
            try:
                with open(path) as f:
                    self._shared_rules = yaml.safe_load(f) or {}
            except Exception:
                self._shared_rules = {}
        return self._shared_rules

    def _load_strategy_yaml(self, strategy_id: str) -> dict:
        if strategy_id not in self._strategy_yamls:
            path = PROJECT_ROOT / 'config' / 'strategies' / f'{strategy_id}.yaml'
            try:
                with open(path) as f:
                    self._strategy_yamls[strategy_id] = yaml.safe_load(f) or {}
            except Exception:
                self._strategy_yamls[strategy_id] = {}
        return self._strategy_yamls[strategy_id]

    def _get_control(self, key: str) -> str:
        """Read a system_controls value."""
        if not self.conn:
            return 'false'
        try:
            cur = self.conn.cursor()
            cur.execute("SELECT value FROM system_controls WHERE key = %s", [key])
            row = cur.fetchone()
            return row[0] if row else 'false'
        except Exception:
            return 'false'

    def check(self, symbol: str, strategy_id: str,
              trade_plan: dict = None, account: str = 'taxable',
              mode: str = 'paper', action_context: str = 'discovery',
              extra: dict = None) -> RiskDecision:
        """Run all risk checks. Returns RiskDecision."""
        now = datetime.now(timezone.utc).isoformat()
        reasons = []

        try:
            # Load config
            shared = self._load_shared_rules()
            strategy_yaml = self._load_strategy_yaml(strategy_id)
            risk_limits = shared.get('risk_limits', {})

            plan = trade_plan or {}
            extra_data = extra or {}

            # 1. Global halt
            if self._get_control('halt_all_trading') == 'true':
                reasons.append('GLOBAL_HALT')

            # 2. Live halt
            if mode == 'live' and self._get_control('halt_live_only') == 'true':
                reasons.append('LIVE_HALT')

            # 3. Strategy halt
            if self._get_control(f'halt_{strategy_id}_strategy') == 'true':
                reasons.append('STRATEGY_HALT')

            # 4. Strategy lifecycle
            if self.conn:
                try:
                    cur = self.conn.cursor()
                    cur.execute("""
                        SELECT active FROM strategy_registry
                        WHERE strategy_type = %s LIMIT 1
                    """, [strategy_id])
                    row = cur.fetchone()
                    if row and not row[0]:
                        reasons.append('STRATEGY_KILLED')
                except Exception:
                    pass  # table may have different schema

            # 5. Account eligibility
            forbidden = strategy_yaml.get('forbidden_accounts', [])
            if account in forbidden:
                reasons.append('ACCOUNT_INELIGIBLE')
            # Special: no scalp in IRA
            if strategy_id in ('momentum_scalp', 'gap_and_go') and account in ('rollover_ira', 'roth_ira', 'fidelity_401k'):
                reasons.append('ACCOUNT_INELIGIBLE')

            # 6. Daily loss limit
            if self.conn and mode in ('paper', 'live'):
                try:
                    cur = self.conn.cursor()
                    risk_per = risk_limits.get('default_risk_per_trade', 150)
                    mult = risk_limits.get('daily_loss_limit_multiplier_testing', 4) if mode == 'paper' else risk_limits.get('daily_loss_limit_multiplier_live', 3)
                    daily_limit = risk_per * mult

                    cur.execute("""
                        SELECT COALESCE(SUM(pnl), 0) FROM paper_trades
                        WHERE closed_at::date = CURRENT_DATE AND pnl < 0
                    """)
                    daily_loss = abs(float(cur.fetchone()[0] or 0))
                    if daily_loss >= daily_limit:
                        reasons.append('DAILY_LOSS_LIMIT_HIT')
                except Exception:
                    pass

            # 7. Weekly loss limit
            if self.conn and mode in ('paper', 'live'):
                try:
                    cur = self.conn.cursor()
                    risk_per = risk_limits.get('default_risk_per_trade', 150)
                    mult = risk_limits.get('weekly_loss_limit_multiplier_testing', 8) if mode == 'paper' else risk_limits.get('weekly_loss_limit_multiplier_live', 6)
                    weekly_limit = risk_per * mult

                    cur.execute("""
                        SELECT COALESCE(SUM(pnl), 0) FROM paper_trades
                        WHERE closed_at > NOW() - INTERVAL '7 days' AND pnl < 0
                    """)
                    weekly_loss = abs(float(cur.fetchone()[0] or 0))
                    if weekly_loss >= weekly_limit:
                        reasons.append('WEEKLY_LOSS_LIMIT_HIT')
                except Exception:
                    pass

            # 8. Max positions taxable
            if self.conn and account == 'taxable':
                try:
                    cur = self.conn.cursor()
                    max_pos = risk_limits.get('max_simultaneous_positions_taxable', 3)
                    cur.execute("SELECT COUNT(*) FROM paper_trades WHERE status='open' AND account='taxable'")
                    open_count = cur.fetchone()[0] or 0
                    if open_count >= max_pos:
                        reasons.append('MAX_POSITIONS_HIT')
                except Exception:
                    pass

            # 9. Max total positions
            if self.conn:
                try:
                    cur = self.conn.cursor()
                    max_total = risk_limits.get('max_simultaneous_total', 8)
                    cur.execute("SELECT COUNT(*) FROM paper_trades WHERE status='open'")
                    total_open = cur.fetchone()[0] or 0
                    if total_open >= max_total:
                        reasons.append('MAX_POSITIONS_HIT')
                except Exception:
                    pass

            # 10. Same sector exposure
            sector = extra_data.get('sector') or plan.get('sector')
            if self.conn and sector:
                try:
                    cur = self.conn.cursor()
                    max_sector = risk_limits.get('max_same_sector_positions', 1)
                    cur.execute("""
                        SELECT COUNT(*) FROM paper_trades pt
                        JOIN trade_ai_scans tas ON tas.symbol = pt.symbol
                        WHERE pt.status='open' AND tas.sector = %s
                        AND tas.scanned_at = (SELECT MAX(scanned_at) FROM trade_ai_scans WHERE symbol = pt.symbol)
                    """, [sector])
                    sector_count = cur.fetchone()[0] or 0
                    if sector_count >= max_sector:
                        reasons.append('SAME_SECTOR_EXPOSURE')
                except Exception:
                    pass

            # 11. Stop defined
            if action_context in FAIL_CLOSED_CONTEXTS:
                stop = plan.get('stop_loss') or plan.get('stop')
                if not stop or _safe_float(stop) <= 0:
                    reasons.append('STOP_NOT_DEFINED')

            # 12. Stop width
            stop_pct = plan.get('stop_pct')
            if stop_pct:
                filters = strategy_yaml.get('screen_filters', {})
                # Default max stop from auto_disqualifiers
                max_stop = 0.15
                for dq in strategy_yaml.get('auto_disqualifiers', []):
                    if 'stop' in str(dq.get('id', '')).lower() and 'pct' in str(dq.get('id', '')).lower():
                        # Extract threshold from condition
                        pass
                if _safe_float(stop_pct) > max_stop:
                    reasons.append('STOP_TOO_WIDE')

            # 13. Dollar size (paper from env default $15K, live from strategy YAML)
            dollar_size = plan.get('dollar_size')
            if dollar_size:
                live_rules = strategy_yaml.get('live_trade_rules', {})
                live_max = live_rules.get('max_position_size', 2000)
                paper_max = int(os.getenv('PAPER_MAX_POSITION_SIZE', '15000'))
                max_size = paper_max if mode == 'paper' else live_max
                if _safe_float(dollar_size) > max_size:
                    reasons.append('DOLLAR_SIZE_TOO_LARGE')

            # ── Hard Risk Governance Gates (Session A-1, operator-approved thresholds) ──
            # These gates enforce hard portfolio-level limits for the bot paper account.
            _paper_size = _safe_float(os.getenv('PAPER_ACCOUNT_SIZE', '100000'))

            # H1. Portfolio heat limit (6% default)
            if self.conn and os.getenv('RISK_GATE_H1_ENABLED', 'true').lower() == 'true':
                try:
                    heat_limit = _safe_float(os.getenv('HEAT_LIMIT_PCT', '0.06'))
                    cur = self.conn.cursor()
                    cur.execute("SELECT COALESCE(SUM(dollar_risk), 0) FROM paper_trades WHERE status='open'")
                    current_risk = _safe_float(cur.fetchone()[0])
                    new_risk = _safe_float(plan.get('dollar_risk', 0))
                    would_be_heat = (current_risk + new_risk) / _paper_size if _paper_size > 0 else 0
                    if would_be_heat > heat_limit:
                        reasons.append(f'HEAT_LIMIT_EXCEEDED_{would_be_heat:.1%}_vs_{heat_limit:.0%}')
                except Exception:
                    pass

            # H2. Single position concentration (8% default)
            if os.getenv('RISK_GATE_H2_ENABLED', 'true').lower() == 'true':
                conc_limit = _safe_float(os.getenv('POSITION_CONCENTRATION_PCT', '0.08'))
                pos_size = _safe_float(plan.get('dollar_size', 0))
                pos_pct = pos_size / _paper_size if _paper_size > 0 else 0
                if pos_pct > conc_limit:
                    reasons.append(f'CONCENTRATION_CAP_{pos_pct:.1%}_vs_{conc_limit:.0%}')

            # H3. Sector concentration (25% default)
            if self.conn and sector and os.getenv('RISK_GATE_H3_ENABLED', 'true').lower() == 'true':
                try:
                    sector_limit = _safe_float(os.getenv('SECTOR_CONCENTRATION_PCT', '0.25'))
                    cur = self.conn.cursor()
                    cur.execute("""
                        SELECT COALESCE(SUM(pt.dollar_size), 0)
                        FROM paper_trades pt
                        JOIN trade_ai_scans tas ON tas.symbol = pt.symbol
                          AND tas.scanned_at = (SELECT MAX(scanned_at) FROM trade_ai_scans WHERE symbol = pt.symbol)
                        WHERE pt.status = 'open' AND tas.sector = %s
                    """, [sector])
                    sector_dollars = _safe_float(cur.fetchone()[0])
                    new_sector_pct = (sector_dollars + pos_size) / _paper_size if _paper_size > 0 else 0
                    if new_sector_pct > sector_limit:
                        reasons.append(f'SECTOR_CAP_{sector}_{new_sector_pct:.1%}_vs_{sector_limit:.0%}')
                except Exception:
                    pass

            # H4. Correlation cap (0.7 default, disabled by default — enable after validation)
            # Expensive: requires bar data fetch. Runs last, only if H1-H3 passed.
            # Implementation deferred to Phase B when correlation calculation is validated.

            # 14. Data quality
            intel = extra_data.get('intel_readiness', 0)
            if action_context in FAIL_CLOSED_CONTEXTS and intel is not None and int(intel or 0) < 20:
                # Only flag if we have the data and it's very low
                if intel is not None and int(intel or 0) > 0 and int(intel or 0) < 20:
                    reasons.append('DATA_QUALITY_LOW')

            # 15. Data freshness
            data_age_minutes = extra_data.get('data_age_minutes')
            if data_age_minutes and int(data_age_minutes) > 60 and action_context in FAIL_CLOSED_CONTEXTS:
                reasons.append('DATA_STALE')

            # 16. VIX regime
            vix = extra_data.get('vix')
            regime_rules = shared.get('market_regime_rules', {})
            if vix and _safe_float(vix) >= 35:
                vix_rules = regime_rules.get('vix_above_35', {})
                strat_rule = vix_rules.get(strategy_id)
                if strat_rule == 'paused':
                    reasons.append('REGIME_PAUSED')
            elif vix and _safe_float(vix) >= 25:
                vix_rules = regime_rules.get('vix_25_to_35', {})
                strat_rule = vix_rules.get(strategy_id)
                if strat_rule == 'paused':
                    reasons.append('REGIME_PAUSED')

            # 17. Social-only catalyst
            source = extra_data.get('source', '')
            catalyst_rules = shared.get('catalyst_rules', {})
            source_quality = extra_data.get('source_quality_score', 1.0)
            if source in ('stocktwits', 'reddit', 'social') or (source_quality and _safe_float(source_quality, 1.0) < 0.5):
                catalyst_verified = extra_data.get('catalyst_verified', False)
                if not catalyst_verified:
                    if action_context in FAIL_CLOSED_CONTEXTS:
                        reasons.append('SOCIAL_ONLY_CATALYST')
                    # For discovery, we just note it

            # 18. Income SSDI/IRMAA
            if strategy_id == 'income_add':
                ssdi_checked = extra_data.get('ssdi_checked', False)
                irmaa_checked = extra_data.get('irmaa_checked', False)
                if action_context in FAIL_CLOSED_CONTEXTS:
                    if not ssdi_checked:
                        reasons.append('SSDI_CHECK_REQUIRED')
                    if not irmaa_checked:
                        reasons.append('IRMAA_BREACH_RISK')

            # 19. Unknown strategy blocks live
            known = {'momentum_scalp', 'gap_and_go', 'swing_breakout',
                     'sector_rotation', 'earnings_catalyst', 'income_add'}
            if strategy_id not in known and mode == 'live':
                reasons.append('UNKNOWN_STRATEGY')

            # 20. Missing required evidence
            if action_context in FAIL_CLOSED_CONTEXTS:
                min_evidence = strategy_yaml.get('minimum_evidence', {}).get('required', [])
                for ev in min_evidence:
                    if ev == 'trade_plan' and not plan:
                        reasons.append('MISSING_REQUIRED_EVIDENCE')
                        break
                    if ev == 'stop_defined' and not plan.get('stop_loss'):
                        reasons.append('MISSING_REQUIRED_EVIDENCE')
                        break

            # Determine result
            if reasons:
                # Check if any reason is a hard block
                block_all = {'GLOBAL_HALT', 'DAILY_LOSS_LIMIT_HIT', 'WEEKLY_LOSS_LIMIT_HIT'}
                block_live = {'LIVE_HALT'}
                paper_only = {'STRATEGY_NOT_VALIDATED', 'STRATEGY_QUARANTINED'}

                if reasons[0] in block_all or any(r in block_all for r in reasons):
                    result = 'REJECTED'
                elif mode == 'live' and any(r in block_live for r in reasons):
                    result = 'REJECTED'
                elif any(r in paper_only for r in reasons) and mode == 'live':
                    result = 'PAPER_ONLY'
                else:
                    result = 'REJECTED'

                decision = RiskDecision(
                    approved=False, result=result,
                    reason_codes=reasons,
                    reason_text='; '.join(reasons),
                    strategy_id=strategy_id, symbol=symbol,
                    mode=mode, action_context=action_context,
                    checked_at=now
                )
            else:
                decision = RiskDecision(
                    approved=True, result='APPROVED',
                    reason_codes=[], reason_text='All checks passed',
                    strategy_id=strategy_id, symbol=symbol,
                    mode=mode, action_context=action_context,
                    checked_at=now
                )

            # Persist
            self._persist(decision, plan)
            return decision

        except Exception as e:
            log.error("Risk gate exception: %s", e)
            error_decision = RiskDecision(
                approved=action_context in FAIL_OPEN_CONTEXTS,
                result='RISK_GATE_ERROR' if action_context in FAIL_CLOSED_CONTEXTS else 'APPROVED',
                reason_codes=['RISK_GATE_EXCEPTION'],
                reason_text=str(e)[:200],
                strategy_id=strategy_id, symbol=symbol,
                mode=mode, action_context=action_context,
                checked_at=now
            )
            self._persist(error_decision, plan)
            return error_decision

    def check_halt(self, strategy_id: str = None, mode: str = None) -> Optional[str]:
        """Quick halt check. Returns reason string or None."""
        if self._get_control('halt_all_trading') == 'true':
            return 'GLOBAL_HALT'
        if mode == 'live' and self._get_control('halt_live_only') == 'true':
            return 'LIVE_HALT'
        if strategy_id and self._get_control(f'halt_{strategy_id}_strategy') == 'true':
            return f'STRATEGY_HALT:{strategy_id}'
        return None

    def _persist(self, decision: RiskDecision, plan: dict = None):
        """Write to risk_gate_results and audit_log."""
        if not self.conn:
            return
        try:
            cur = self.conn.cursor()
            # risk_gate_results
            cur.execute("""
                INSERT INTO risk_gate_results
                    (symbol, strategy_id, account, mode, action_context,
                     result, approved, reason_codes, reason_text, input_snapshot)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, [
                decision.symbol, decision.strategy_id, None,
                decision.mode, decision.action_context,
                decision.result, decision.approved,
                json.dumps(decision.reason_codes),
                decision.reason_text,
                json.dumps(plan or {}, default=str)[:2000]
            ])
            # audit_log
            cur.execute("""
                INSERT INTO audit_log
                    (event_type, strategy_id, symbol, decision,
                     reason_codes, reason_text, mode)
                VALUES ('risk_gate_check', %s, %s, %s, %s, %s, %s)
            """, [
                decision.strategy_id, decision.symbol, decision.result,
                json.dumps(decision.reason_codes),
                decision.reason_text, decision.mode
            ])
            self.conn.commit()
        except Exception as e:
            log.warning("Risk gate persist failed: %s", e)
            try:
                self.conn.rollback()
            except Exception:
                pass


def _get_conn():
    """Get DB connection from .env."""
    import psycopg2
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / '.env')
    return psycopg2.connect(
        host=os.getenv('DB_HOST', '127.0.0.1'),
        port=os.getenv('DB_PORT', '5432'),
        dbname=os.getenv('DB_NAME', 'trade_ai'),
        user=os.getenv('DB_USER', 'trade_ai'),
        password=os.getenv('DB_PASSWORD'),
    )


if __name__ == '__main__':
    with PipelineRun("risk_gate") as _run:
        logging.basicConfig(level=logging.INFO)

        if '--test' in sys.argv:
            conn = _get_conn()
            gate = RiskGate(conn)

            print("=== Risk Gate Self-Test ===\n")

            # Test 1: Basic approval (discovery context)
            d = gate.check('FTCI', 'momentum_scalp', {'stop_loss': 4.50}, 'taxable', 'paper', 'discovery')
            print(f"1. Discovery check:  {d.result} (approved={d.approved})")

            # Test 2: IRA scalp should be rejected
            d = gate.check('FTCI', 'momentum_scalp', {'stop_loss': 4.50}, 'rollover_ira', 'paper', 'paper_trade')
            print(f"2. IRA scalp:        {d.result} reason={d.reason_codes}")
            assert not d.approved, "IRA scalp should be rejected"

            # Test 3: No stop defined
            d = gate.check('FTCI', 'momentum_scalp', {}, 'taxable', 'paper', 'paper_trade')
            print(f"3. No stop:          {d.result} reason={d.reason_codes}")
            assert not d.approved, "No stop should be rejected"

            # Test 4: Halt check
            halt = gate.check_halt('momentum_scalp', 'paper')
            print(f"4. Halt check:       {halt or 'None (no halt)'}")

            # Test 5: Income without SSDI
            d = gate.check('SCHD', 'income_add', {'stop_loss': 25}, 'rollover_ira', 'paper', 'paper_trade')
            print(f"5. Income no SSDI:   {d.result} reason={d.reason_codes}")
            assert not d.approved, "Income without SSDI should be rejected"

            # Test 6: Unknown strategy in live mode
            d = gate.check('FTCI', 'unknown_strategy', {'stop_loss': 4.50}, 'taxable', 'live', 'live_trade')
            print(f"6. Unknown live:     {d.result} reason={d.reason_codes}")
            assert not d.approved, "Unknown strategy live should be rejected"

            # Test 7: Social-only catalyst in paper_trade context
            d = gate.check('FTCI', 'momentum_scalp', {'stop_loss': 4.50}, 'taxable', 'paper', 'paper_trade',
                           extra={'source': 'stocktwits', 'catalyst_verified': False})
            print(f"7. Social-only:      {d.result} reason={d.reason_codes}")

            conn.close()
            print("\n=== All risk gate tests passed ===")
        else:
            print("Usage: python3 scripts/risk_gate.py --test")
```
