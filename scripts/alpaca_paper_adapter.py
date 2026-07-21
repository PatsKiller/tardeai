#!/usr/bin/env python3
"""alpaca_paper_adapter.py — Paper-only Alpaca trading adapter.

SAFETY: This adapter ONLY connects to Alpaca paper trading.
It is DISABLED by default. Set ENABLE_ALPACA_PAPER=true in .env to enable.
Never uses live Alpaca endpoint.
"""
import argparse, json, logging, os, sys, time
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / '.env')

log = logging.getLogger(__name__)

PAPER_BASE_URL = 'https://paper-api.alpaca.markets'
DATA_BASE_URL = 'https://data.alpaca.markets'
MAX_POSITION_SIZE = 2000
MIN_SCORE_ALPACA = 45

def _get_max_positions():
    """Read max_concurrent from ATM config. Fallback to 6."""
    try:
        import yaml
        cfg_path = Path(__file__).resolve().parent.parent / 'config' / 'atm_config.yaml'
        if cfg_path.exists():
            cfg = yaml.safe_load(cfg_path.read_text())
            return cfg.get('accounts', {}).get('tradeai_automated', {}).get('position_limits', {}).get('max_concurrent',
                   cfg.get('defaults', {}).get('position_limits', {}).get('max_concurrent', 6))
    except Exception:
        pass
    return 6

class AlpacaPaperAdapter:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.enabled = os.getenv('ENABLE_ALPACA_PAPER', 'false').lower() == 'true'
        self.api_key = os.getenv('ALPACA_API_KEY', '')
        self.secret_key = os.getenv('ALPACA_SECRET_KEY', '')
        self.base_url = PAPER_BASE_URL

        # Safety: reject live endpoint
        configured_url = os.getenv('ALPACA_BASE_URL', PAPER_BASE_URL)
        if 'api.alpaca.markets' in configured_url and 'paper-api' not in configured_url:
            raise RuntimeError("BLOCKED: Live Alpaca endpoint detected. Only paper-api.alpaca.markets is allowed.")

        self.headers = {
            'APCA-API-KEY-ID': self.api_key,
            'APCA-API-SECRET-KEY': self.secret_key,
        }

        # Smoke test: verify data API connectivity on init
        if self.enabled and self.api_key:
            try:
                import requests
                resp = requests.get(f'{DATA_BASE_URL}/v2/stocks/SPY/quotes/latest',
                                    headers=self.headers, timeout=5)
                if resp.status_code != 200:
                    log.warning(f"[alpaca] Data API smoke test failed: SPY quotes returned {resp.status_code}")
            except Exception as e:
                log.warning(f"[alpaca] Data API smoke test failed: {e}")

    def _api_get(self, path):
        import requests
        resp = requests.get(f'{self.base_url}{path}', headers=self.headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _api_post(self, path, data):
        import requests
        resp = requests.post(f'{self.base_url}{path}', headers=self.headers, json=data, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def _data_get(self, path):
        """GET from Alpaca data API (data.alpaca.markets) for market data."""
        import requests
        resp = requests.get(f'{DATA_BASE_URL}{path}', headers=self.headers, timeout=10)
        resp.raise_for_status()
        return resp.json()

    def get_positions(self):
        if not self.enabled or not self.api_key:
            log.info("[alpaca] Disabled or no API key — returning empty positions")
            return []
        try:
            return self._api_get('/v2/positions')
        except Exception as e:
            log.warning(f"[alpaca] Failed to get positions: {e}")
            return []

    def get_account(self):
        if not self.enabled or not self.api_key:
            return {'status': 'disabled', 'equity': 0}
        try:
            return self._api_get('/v2/account')
        except Exception as e:
            log.warning(f"[alpaca] Failed to get account: {e}")
            return {'status': 'error', 'error': str(e)}

    def get_status(self):
        """Return adapter health status — same contract as Schwab/Tastytrade adapters."""
        return {
            "broker": "alpaca",
            "enabled": self.enabled,
            "authenticated": bool(self.api_key and self.secret_key),
            "configured": bool(self.api_key and self.secret_key),
            "dry_run": self.dry_run,
            "mode": "paper",
            "base_url": self.base_url,
            "features": ["stocks", "etfs"],
            "ira_support": False,
            "account_types": ["paper"],
        }

    def _match_filled_order(self, symbol, qty=None):
        """Find the broker's most-recent FILLED BUY order for `symbol` — the order that opened the
        current position — so a pending row is promoted ANCHORED to a real order id, never by
        symbol coincidence. Returns the order dict (id, client_order_id, ...) or None. Read-only."""
        if not self.enabled or not self.api_key:
            return None
        try:
            orders = self._api_get(f"/v2/orders?status=closed&symbols={symbol}&direction=desc&limit=50")
        except Exception as e:
            log.warning(f"[alpaca] _match_filled_order({symbol}) failed: {e}")
            return None
        buys = [o for o in (orders or [])
                if o.get("symbol") == symbol and o.get("side") == "buy" and o.get("status") == "filled"]
        if not buys:
            return None
        if qty is not None:
            for o in buys:
                try:
                    if int(float(o.get("filled_qty") or 0)) == int(qty):
                        return o
                except (TypeError, ValueError):
                    pass
        return buys[0]   # most recent filled buy (direction=desc)

    def sync_positions(self, conn):
        """Sync Alpaca paper positions with paper_trades table."""
        positions = self.get_positions()
        if not positions:
            log.info("[alpaca] No open positions to sync")
            return 0

        cur = conn.cursor()
        synced = 0
        for pos in positions:
            symbol = pos.get('symbol', '')
            qty = int(float(pos.get('qty', 0)))
            avg_entry = float(pos.get('avg_entry_price', 0))
            current = float(pos.get('current_price', 0))
            unrealized = float(pos.get('unrealized_pl', 0))

            # Update existing open paper trade if exists (check any account)
            cur.execute("""
                UPDATE paper_trades
                SET current_price = %s, unrealized_pnl = %s, last_synced_at = NOW()
                WHERE symbol = %s AND status = 'open'
                  AND id = (SELECT id FROM paper_trades WHERE symbol = %s AND status = 'open' ORDER BY created_at DESC LIMIT 1)
            """, [current, unrealized, symbol, symbol])

            if cur.rowcount == 0:
                # ORDER-ANCHORED PROMOTION (STEP 3a). A pending row becomes 'open' (= COUNTED) ONLY
                # when matched to a SPECIFIC filled broker order, capturing its broker_order_id.
                # Symbol-only promotion was the proposal_approved phantom source — a pending row
                # flipped 'open' against a coincidental position with no order linkage. If a pending
                # row exists but no filled order matches, it is LEFT pending (never promoted
                # unanchored), and no unknown_sync duplicate is created for it.
                cur.execute("""SELECT id FROM paper_trades
                               WHERE symbol=%s AND status='pending' AND lifecycle_state='open'
                               ORDER BY created_at DESC LIMIT 1""", [symbol])
                pend = cur.fetchone()
                if pend:
                    filled = self._match_filled_order(symbol, qty)
                    if filled and filled.get("id"):
                        cur.execute("""
                            UPDATE paper_trades
                            SET status = 'open', broker_status = 'filled',
                                broker_order_id = COALESCE(broker_order_id, %s),
                                client_order_id = COALESCE(client_order_id, %s),
                                entry_price = %s, current_price = %s, unrealized_pnl = %s,
                                filled_at = COALESCE(filled_at, NOW()), last_synced_at = NOW()
                            WHERE id = %s
                            RETURNING id, stop_loss
                        """, [filled.get("id"), filled.get("client_order_id"),
                              avg_entry, current, unrealized, pend[0]])
                        fixed_row = cur.fetchone()
                        if fixed_row:
                            trade_id_fixed, old_stop = fixed_row
                            log.info(f"[alpaca] {symbol} promoted pending→open ANCHORED to order "
                                     f"{str(filled.get('id'))[:8]} (filled at ${avg_entry:.2f})")
                            # Universal stop validation (Fix 5)
                            from trade_outcome_helpers import validate_and_recalc_stop
                            new_stop, _recalced, _reason = validate_and_recalc_stop(
                                entry_price=avg_entry, stop_loss=float(old_stop) if old_stop else None, direction='long')
                            if _recalced:
                                cur.execute("UPDATE paper_trades SET stop_loss=%s, stop_loss_price=%s WHERE id=%s",
                                            [new_stop, new_stop, trade_id_fixed])
                                log.warning(f"[alpaca] {symbol} stop recalculated: ${old_stop}→${new_stop} ({_reason})")
                            # mandatory two-source fill verification on promotion (NON-FATAL)
                            try:
                                from trade_fill_verifier import verify_and_stamp_fill
                                verify_and_stamp_fill(conn, trade_id_fixed)
                            except Exception as _ve:
                                log.warning(f"[alpaca] {symbol} fill-verify hook error (non-fatal): {_ve}")
                            synced += 1
                            continue
                    # pending exists but could NOT be anchored to a filled order → leave pending,
                    # do not promote unanchored, do not create an unknown_sync duplicate.
                    log.warning(f"[alpaca] {symbol} held at broker but no matching filled order — "
                                f"leaving pending (not promoting unanchored)")
                    synced += 1
                    continue

            if cur.rowcount == 0:
                # DEDUP GUARD (2026-06-18): only create an unknown_sync recovery for a TRUE orphan — a
                # symbol with NO tracked row. If a pending/open/superseded row exists (or one closed in
                # the last few days), this Alpaca position is already represented; creating unknown_sync
                # here is what produced the phantom $0 duplicates. Skip it.
                cur.execute("""SELECT 1 FROM paper_trades WHERE symbol=%s
                                 AND (status IN ('open','pending','superseded_by_fill')
                                      OR (status='closed' AND closed_at > NOW() - INTERVAL '3 days')) LIMIT 1""",
                            [symbol])
                if cur.fetchone():
                    log.warning(f"[alpaca] {symbol} held at broker but already tracked — skipping unknown_sync duplicate")
                    synced += 1
                    continue
                # Position exists in Alpaca but not in paper_trades — create a broker-confirmed
                # record. (Creating here is correct: a position Alpaca holds but the system doesn't
                # track is real — e.g. ANY, a position the system closed but the broker still held,
                # recovered as a live +$1.5k trade. Genuine phantoms — a position that's already gone
                # from Alpaca — are detected and P&L-voided by detect_closed_positions, NOT skipped
                # here, so we never drop a real recovered position.)
                cur.execute("""
                    INSERT INTO paper_trades (strategy_id, symbol, account, entry_price, entry_time,
                        shares, dollar_size, current_price, unrealized_pnl, status,
                        lifecycle_state, broker_status, filled_at,
                        opened_via, logged_by, last_synced_at)
                    VALUES ('unknown_sync', %s, 'ALPACA_PAPER', %s, NOW(),
                        %s, %s, %s, %s, 'open',
                        'open', 'filled', NOW(),
                        'alpaca_sync', 'alpaca_adapter', NOW())
                """, [symbol, avg_entry, qty, round(qty * avg_entry, 2), current, unrealized])
            synced += 1

        conn.commit()
        log.info(f"[alpaca] Synced {synced} positions")
        return synced

    def detect_closed_positions(self, conn):
        """Detect paper trades that closed in Alpaca."""
        cur = conn.cursor()
        cur.execute("""
            SELECT id, symbol FROM paper_trades
            WHERE status = 'open'
        """)
        open_trades = cur.fetchall()

        if not open_trades:
            return 0

        alpaca_positions = self.get_positions()
        if not alpaca_positions and len(open_trades) > 0:
            # API returned empty but we have open trades — likely API failure, not real close
            log.warning(f"[alpaca] Positions API returned empty with {len(open_trades)} open DB trades — skipping close detection (possible API issue)")
            return 0
        alpaca_symbols = {p['symbol'] for p in alpaca_positions}

        closed = 0
        for trade_id, symbol in open_trades:
            if symbol not in alpaca_symbols:
                # Position no longer in Alpaca — fetch actual exit from broker order history
                log.info(f"[alpaca] {symbol} no longer in Alpaca positions — fetching close data from broker")
                _exit_price = None
                _exit_time = None
                _exit_pnl = None
                _exit_reason = 'position_closed_in_alpaca'   # generic default; OCO reconcile overrides
                # Get entry + order ids (for reconciliation and PnL calc)
                cur.execute("""SELECT entry_price, shares, stop_loss, dollar_risk,
                                      broker_order_id, stop_order_id, take_profit_order_id,
                                      side, COALESCE(execution_account, account)
                               FROM paper_trades WHERE id=%s""", [trade_id])
                _tr = cur.fetchone()
                _entry = float(_tr[0]) if _tr and _tr[0] else 0
                _shares = int(_tr[1]) if _tr and _tr[1] else 0
                _stop = float(_tr[2]) if _tr and len(_tr) > 2 and _tr[2] else None
                _dr = float(_tr[3]) if _tr and len(_tr) > 3 and _tr[3] else None
                _side = _tr[7] if _tr and len(_tr) > 7 else None
                _acct = _tr[8] if _tr and len(_tr) > 8 else None
                _dir = 'short' if str(_side or 'buy').lower() in ('sell', 'short') else 'long'
                from trade_outcome_helpers import classify_verdict, reconcile_broker_exit, get_order_status_for
                from broker_adapter import FillConfirmation
                # Prefer OCO-leg reconciliation (distinguishes stop_hit vs target_hit; shared,
                # broker-agnostic — resolves the account's adapter). Fall back to a local Alpaca
                # get_order_status shim, then to the generic latest-sell lookup below.
                _gos = get_order_status_for(_acct) if _acct else None
                if _gos is None:
                    def _gos(oid):
                        o = self._api_get(f'/v2/orders/{oid}')
                        if not isinstance(o, dict):
                            return FillConfirmation(confirmed=False, status='unknown')
                        fap = o.get('filled_avg_price')
                        return FillConfirmation(confirmed=(o.get('status') == 'filled'),
                                                filled_price=(float(fap) if fap not in (None, '') else None),
                                                status=(o.get('status') or 'unknown'), raw=o)
                try:
                    _rec = reconcile_broker_exit(_gos, _tr[4] if _tr else None,
                                                 _tr[5] if _tr else None, _tr[6] if _tr else None,
                                                 _entry or None, _shares, _dr, direction=_dir)
                except Exception:
                    _rec = {"kind": "filled_no_exit"}
                if _rec.get("kind") == "reconciled":
                    _exit_price = _rec["exit_price"]; _exit_pnl = _rec["pnl"]
                    _pnl_pct = _rec["pnl_pct"]; _r_mult = _rec["r_multiple"]
                    _verdict = _rec["verdict"]; _exit_reason = _rec["exit_reason"]
                else:
                    try:
                        _orders = self._api_get(f'/v2/orders?status=filled&symbols={symbol}&limit=5&direction=desc')
                        sell_orders = [o for o in (_orders if isinstance(_orders, list) else []) if o.get('side') == 'sell' and o.get('status') == 'filled']
                        if sell_orders:
                            _exit_price = float(sell_orders[0].get('filled_avg_price', 0))
                            _exit_time = sell_orders[0].get('filled_at')
                    except Exception as _oe:
                        log.warning(f"[alpaca] Could not fetch close orders for {symbol}: {_oe}")
                    if _exit_price and _entry:
                        _exit_pnl = round((_exit_price - _entry) * _shares, 2)
                    _pnl_pct = round((_exit_price - _entry) / _entry * 100, 2) if _exit_price and _entry and _entry > 0 else None
                    _r_mult = None
                    if _exit_pnl is not None and _dr and _dr > 0:
                        _r_mult = round(_exit_pnl / _dr, 3)
                    elif _exit_price and _entry and _stop and abs(_entry - _stop) > 0:
                        _r_mult = round((_exit_price - _entry) / abs(_entry - _stop), 3)
                    _verdict = classify_verdict(_exit_pnl)

                cur.execute("""
                    UPDATE paper_trades
                    SET status = 'closed', lifecycle_state = 'closed',
                        exit_price = COALESCE(%s, current_price),
                        pnl = %s, pnl_pct = COALESCE(%s, pnl_pct),
                        r_multiple = COALESCE(%s, r_multiple),
                        outcome_verdict = %s,
                        closed_at = COALESCE(%s, NOW()), closed_via = 'alpaca_sync',
                        exit_reason = %s, updated_at = NOW(),
                        hold_time_min = COALESCE(hold_time_min,
                            EXTRACT(EPOCH FROM (COALESCE(%s, NOW()) - COALESCE(entry_time, created_at))) / 60)
                    WHERE id = %s
                """, [_exit_price, _exit_pnl, _pnl_pct, _r_mult, _verdict, _exit_time, _exit_reason, _exit_time, trade_id])
                # Agent curation hooks (non-blocking)
                try:
                    from agent_curation_hooks import on_paper_trade_closed
                    on_paper_trade_closed(conn, trade_id)
                except Exception as e:
                    log.warning(f"[alpaca] Curation hooks failed for {symbol}: {e}")
                closed += 1

        if closed:
            conn.commit()
            # Trigger post-close processors
            try:
                import subprocess
                subprocess.Popen(
                    [str(PROJECT_ROOT / ".venv/bin/python"),
                     str(PROJECT_ROOT / "scripts/post_trade_thesis_reviewer.py"), "--apply"],
                    cwd=str(PROJECT_ROOT),
                    stdout=open(str(PROJECT_ROOT / "logs/post_trade_thesis_auto.log"), "a"),
                    stderr=subprocess.STDOUT,
                )
                subprocess.Popen(
                    [str(PROJECT_ROOT / ".venv/bin/python"),
                     str(PROJECT_ROOT / "scripts/paper_outcome_analytics.py"), "--since", "7", "--apply"],
                    cwd=str(PROJECT_ROOT),
                    stdout=open(str(PROJECT_ROOT / "logs/paper_outcome_analytics_auto.log"), "a"),
                    stderr=subprocess.STDOUT,
                )
                log.info(f"[alpaca] Triggered post-close processors for {closed} trade(s)")
            except Exception as e:
                log.warning(f"[alpaca] Post-close processor trigger failed: {e}")
        return closed

    def submit_entry(self, symbol, shares, entry_price, stop_price, target_price, strategy_id, conn, proposal_id=None, validated_price=None, revalidation_snapshot=None):
        """Submit a bracket order to Alpaca paper."""
        if not self.enabled:
            log.info(f"[alpaca] DISABLED — would submit {shares} {symbol} @ ${entry_price}")
            return {'status': 'simulation', 'symbol': symbol}

        if self.dry_run:
            log.info(f"[alpaca] DRY RUN — {shares} {symbol} @ ${entry_price} stop=${stop_price} target=${target_price}")
            return {'status': 'dry_run', 'symbol': symbol}

        # Risk gate check
        try:
            from risk_gate import RiskGate
            gate = RiskGate(conn)
            decision = gate.check(symbol, strategy_id,
                {'stop_loss': stop_price, 'dollar_size': shares * entry_price},
                'ALPACA_PAPER', 'paper', 'paper_trade')
            if not decision.approved:
                log.warning(f"[alpaca] Risk gate REJECTED {symbol}: {decision.reason_codes}")
                return {'status': 'rejected', 'reason': decision.reason_codes}
        except Exception as e:
            log.error(f"[alpaca] Risk gate error for {symbol}: {e} — BLOCKING (fail-closed)")
            return {'status': 'blocked', 'reason': f'risk_gate_error: {e}'}

        # Check max positions
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM paper_trades WHERE account='ALPACA_PAPER' AND status='open'")
        open_count = cur.fetchone()[0] or 0
        _max_pos = _get_max_positions()
        if open_count >= _max_pos:
            log.warning(f"[alpaca] Max positions ({_max_pos}) reached ({open_count} open)")
            return {'status': 'rejected', 'reason': f'max_positions ({open_count}/{_max_pos})'}

        # Block duplicate symbol — no second position on same symbol
        cur.execute("SELECT id, strategy_id FROM paper_trades WHERE symbol=%s AND status='open' LIMIT 1", [symbol])
        _dup = cur.fetchone()
        if _dup:
            log.warning(f"[alpaca] BLOCKED {symbol}: already have open trade #{_dup[0]} ({_dup[1]}). No duplicate positions.")
            return {'status': 'rejected', 'reason': f'duplicate_symbol: already open as {_dup[1]} (trade #{_dup[0]})'}

        # Also check Alpaca directly — broker is source of truth
        try:
            _positions = self.get_positions()
            if any(p['symbol'] == symbol for p in _positions):
                log.warning(f"[alpaca] BLOCKED {symbol}: already on Alpaca. No duplicate positions.")
                return {'status': 'rejected', 'reason': 'duplicate_symbol: already on broker'}
        except Exception:
            pass

        # Determine order type based on price proximity
        # If current price is within 2% of entry, use market order for immediate fill.
        # If current price is below entry (better price), use market order.
        # If current price is significantly above entry, use limit at entry for value.
        current_price = None
        _price_source = None
        try:
            # Primary: quotes/latest from data API (bid/ask mid-price)
            quote = self._data_get(f'/v2/stocks/{symbol}/quotes/latest')
            ask = float(quote.get('quote', {}).get('ap') or 0)
            bid = float(quote.get('quote', {}).get('bp') or 0)
            if ask and bid:
                current_price = round((ask + bid) / 2, 4)
                _price_source = "data_api_quote_mid"
            elif ask:
                current_price = ask
                _price_source = "data_api_quote_ask"
            elif bid:
                current_price = bid
                _price_source = "data_api_quote_bid"
        except Exception as _qe:
            log.warning(f"[alpaca] Data API quote failed for {symbol}: {_qe}")

        if not current_price:
            try:
                # Fallback 1: bars/latest from data API
                bar = self._data_get(f'/v2/stocks/{symbol}/bars/latest')
                current_price = float(bar.get('bar', {}).get('c', 0))
                if current_price:
                    _price_source = "data_api_bar_close"
            except Exception as _be:
                log.warning(f"[alpaca] Data API bar failed for {symbol}: {_be}")

        if not current_price:
            try:
                # Fallback 2: yfinance
                import yfinance as yf
                t = yf.Ticker(symbol)
                h = t.history(period='1d')
                if not h.empty:
                    current_price = float(h['Close'].iloc[-1])
                    _price_source = "yfinance"
            except Exception:
                pass

        # Last resort: validated price from revalidator
        if not current_price and validated_price:
            current_price = validated_price
            _price_source = "validated_price_fallback"

        if _price_source:
            log.info(f"[alpaca] {symbol} price=${current_price:.2f} source={_price_source}")
        if _price_source and "fallback" in _price_source:
            log.warning(f"[alpaca] {symbol}: using fallback price source ({_price_source})")

        # ── FAIL-CLOSED: Block if no live price available ──
        if not current_price:
            log.error(f"[alpaca] BLOCKED {symbol}: no price source available — fail-closed")
            return {'status': 'blocked', 'reason': 'no_price_source: all quote providers failed'}

        # ── HARD SAFETY GATE 1: Stop already breached ──
        if current_price and stop_price and current_price <= stop_price:
            log.error(f"[alpaca] BLOCKED {symbol}: price ${current_price:.2f} <= stop ${stop_price:.2f} — would immediately stop out")
            return {'status': 'blocked', 'reason': f'stop_breached: price ${current_price:.2f} <= stop ${stop_price:.2f}'}

        # ── HARD SAFETY GATE 2: Excessive drift from proposed entry ──
        if current_price and entry_price and entry_price > 0:
            adapter_drift = abs(current_price - entry_price) / entry_price * 100
            if adapter_drift > 5.0:
                log.error(f"[alpaca] BLOCKED {symbol}: drift {adapter_drift:.1f}% exceeds 5% threshold (entry=${entry_price:.2f} vs live=${current_price:.2f})")
                return {'status': 'blocked', 'reason': f'excessive_drift: {adapter_drift:.1f}% from proposed entry ${entry_price:.2f}'}

        use_market = False
        order_type_reason = "limit_at_proposed_entry"
        if current_price and entry_price:
            drift_pct = abs(current_price - entry_price) / entry_price * 100
            if current_price <= entry_price:
                # Price is at or below entry — market order for immediate fill at better price
                use_market = True
                order_type_reason = f"market_better_price (${current_price:.2f} <= ${entry_price:.2f})"
            elif drift_pct <= 2.0:
                # Price within 2% of entry — close enough, market order
                use_market = True
                order_type_reason = f"market_within_drift ({drift_pct:.1f}% drift)"
            else:
                order_type_reason = f"limit_price_drifted ({drift_pct:.1f}% above entry)"

        log.info(f"[alpaca] {symbol}: order_type={('market' if use_market else 'limit')} reason={order_type_reason}")

        # ── Gap 4 fix: Market hours gate (includes extended hours) ──
        _extended_hours = False
        try:
            from datetime import datetime as _dt, timezone as _tz
            import zoneinfo
            _et = _dt.now(zoneinfo.ZoneInfo("America/New_York"))
            _wd = _et.weekday()  # 0=Mon, 6=Sun
            _h, _m = _et.hour, _et.minute
            _market_open = (_wd < 5 and ((_h == 9 and _m >= 30) or (10 <= _h < 16)))
            _extended_hours = (_wd < 5 and ((4 <= _h < 9) or (_h == 9 and _m < 30) or (16 <= _h < 20)))
            if not _market_open and not _extended_hours:
                log.warning(f"[alpaca] BLOCKED: {symbol} submission outside trading hours ({_et.strftime('%H:%M %Z %A')})")
                return {'status': 'blocked', 'reason': f'outside_trading_hours ({_et.strftime("%H:%M %Z %A")})'}
        except Exception as _mhe:
            log.warning(f"[alpaca] Market hours check failed ({_mhe}), proceeding cautiously")

        # Submit order (bracket if limit, simple + separate stop if market)
        # Extended hours: Alpaca requires limit orders only, no brackets
        try:
            if _extended_hours and use_market:
                log.info(f"[alpaca] {symbol}: forcing limit order for extended hours (market orders not allowed)")
                use_market = False
            if use_market:
                order_data = {
                    'symbol': symbol, 'qty': str(shares), 'side': 'buy',
                    'type': 'market', 'time_in_force': 'day',
                }
            elif _extended_hours:
                # Extended hours: simple limit order, no bracket (not supported in extended hours)
                order_data = {
                    'symbol': symbol, 'qty': str(shares), 'side': 'buy',
                    'type': 'limit', 'time_in_force': 'day',
                    'limit_price': str(entry_price),
                    'extended_hours': True,
                }
            else:
                order_data = {
                    'symbol': symbol, 'qty': str(shares), 'side': 'buy',
                    'type': 'limit', 'time_in_force': 'day',
                    'limit_price': str(entry_price), 'order_class': 'bracket',
                    'stop_loss': {'stop_price': str(stop_price)},
                    'take_profit': {'limit_price': str(target_price)},
                }
            result = self._api_post('/v2/orders', order_data)
            order_id = result.get('id', '')

            # ── Gap 1 fix: Fill verification loop ──
            import time as _time
            fill_price = entry_price
            fill_status = result.get('status', 'new')
            filled_qty = 0
            for _attempt in range(8):  # up to ~20 sec
                _time.sleep(1 + _attempt * 0.5)
                try:
                    fill_check = self._api_get(f'/v2/orders/{order_id}')
                    fill_status = fill_check.get('status', '')
                    filled_qty = int(float(fill_check.get('filled_qty', 0)))
                    if fill_status == 'filled':
                        fill_price = float(fill_check.get('filled_avg_price', entry_price))
                        log.info(f"[alpaca] {symbol} FILLED @ ${fill_price:.2f} ({filled_qty} shares)")
                        break
                    if fill_status in ('canceled', 'cancelled', 'rejected', 'expired'):
                        log.error(f"[alpaca] {symbol} order {fill_status} — aborting")
                        return {'status': 'error', 'reason': f'order_{fill_status}', 'order_id': order_id}
                    # partially_filled is usually transient for market orders — keep polling
                    if fill_status == 'partially_filled':
                        log.info(f"[alpaca] {symbol} partially filled {filled_qty}/{shares} — waiting for completion (attempt {_attempt+1}/8)")
                except Exception as _fce:
                    log.warning(f"[alpaca] Fill check attempt {_attempt}: {_fce}")
            else:
                # Loop exhausted without a 'filled' break — check final state
                try:
                    _final = self._api_get(f'/v2/orders/{order_id}')
                    fill_status = _final.get('status', 'unknown')
                    filled_qty = int(float(_final.get('filled_qty', 0)))
                    fill_price = float(_final.get('filled_avg_price', 0)) or entry_price
                except Exception:
                    fill_status = 'unknown'

                if fill_status == 'filled':
                    log.info(f"[alpaca] {symbol} FILLED (late confirm) @ ${fill_price:.2f} ({filled_qty} shares)")
                elif fill_status == 'partially_filled' and filled_qty > 0:
                    # Genuine partial fill — cancel remainder but keep what we got
                    log.warning(f"[alpaca] {symbol} PARTIAL FILL confirmed: {filled_qty}/{shares} — canceling remainder, keeping filled shares")
                    try:
                        self._api_delete(f'/v2/orders/{order_id}')
                    except Exception:
                        pass
                    fill_status = 'filled'  # treat partial as filled for downstream (stop placement, DB record)
                    shares = filled_qty     # adjust expected shares to actual fill
                elif not use_market:
                    log.info(f"[alpaca] {symbol} limit order pending (not yet filled)")
                    fill_status = 'pending_new'
                else:
                    log.error(f"[alpaca] {symbol} market order final status={fill_status} filled={filled_qty} — canceling")
                    try:
                        self._api_delete(f'/v2/orders/{order_id}')
                    except Exception:
                        pass
                    if filled_qty > 0:
                        # Some shares filled before cancel — treat as partial fill, keep them
                        log.warning(f"[alpaca] {symbol} salvaging {filled_qty} filled shares from canceled order")
                        fill_status = 'filled'
                        fill_price = float(_final.get('filled_avg_price', 0)) or entry_price
                        shares = filled_qty
                    else:
                        return {'status': 'error', 'reason': f'fill_timeout_status_{fill_status}'}

            # ── Universal stop validation (Fix 5) ──
            # Validate stop against actual fill price on ALL order types
            from trade_outcome_helpers import validate_and_recalc_stop
            _actual_entry = fill_price if (fill_status == 'filled' and fill_price) else float(entry_price)
            effective_stop, _stop_recalced, _stop_reason = validate_and_recalc_stop(
                entry_price=_actual_entry, stop_loss=stop_price, direction='long')
            if _stop_recalced:
                log.warning(f"[alpaca] {symbol} stop recalculated: ${stop_price}→${effective_stop} ({_stop_reason})")
            # Phase 190C: track broker confirmation of the protective stop.
            stop_placed = False
            stop_broker_id = None  # set ONLY from a confirmed broker API response
            if (use_market or _extended_hours) and fill_status == 'filled':
                for _sa in range(3):
                    try:
                        stop_order = {
                            'symbol': symbol, 'qty': str(filled_qty or shares), 'side': 'sell',
                            'type': 'stop', 'stop_price': str(effective_stop), 'time_in_force': 'gtc',
                        }
                        _stop_resp = self._api_post('/v2/orders', stop_order)
                        stop_broker_id = (_stop_resp or {}).get('id')
                        log.info(f"[alpaca] {symbol} STOP set @ ${effective_stop} (broker order {stop_broker_id})")
                        stop_placed = True
                        break
                    except Exception as _se:
                        log.warning(f"[alpaca] {symbol} stop attempt {_sa}: {_se}")
                        _time.sleep(1)
                if not stop_placed:
                    # CRITICAL: position is unhedged — close it immediately
                    log.error(f"[alpaca] CRITICAL: {symbol} stop placement FAILED — closing unhedged position")
                    try:
                        self._api_delete(f'/v2/positions/{symbol}')
                    except Exception:
                        pass
                    return {'status': 'error', 'reason': 'stop_placement_failed_position_closed'}

            # Record in paper_trades — only if fill confirmed or limit pending
            actual_entry = fill_price if (use_market and fill_status == 'filled') else entry_price
            actual_shares = filled_qty if filled_qty > 0 else shares
            _regime, _vix = None, None
            try:
                cur.execute("SELECT regime_label FROM market_regime_snapshots ORDER BY created_at DESC LIMIT 1")
                _rr = cur.fetchone()
                if _rr: _regime = _rr[0]
                cur.execute("SELECT value FROM market_regime_indicators WHERE indicator_key IN ('vix_close','vix') ORDER BY created_at DESC LIMIT 1")
                _vr = cur.fetchone()
                if _vr: _vix = float(_vr[0])
            except Exception:
                pass
            # Only create paper_trades record if broker confirmed the fill
            if fill_status != 'filled':
                log.info(f"[alpaca] {symbol} order not filled (status={fill_status}) — no paper_trades record created. Monitor will detect fill via sync.")
                conn.commit()
                return {'status': 'pending', 'order_id': order_id, 'fill_status': fill_status,
                        'reason': 'limit_order_pending_fill', 'symbol': symbol}
            _db_status = 'open'
            import json as _json
            _risk_snap = _json.dumps({
                "proposed_entry": entry_price,
                "live_price_at_submit": current_price,
                "filled_avg_price": actual_entry,
                "stop": stop_price,
                "target": target_price,
                "drift_pct": round(abs(current_price - entry_price) / entry_price * 100, 2) if current_price and entry_price and entry_price > 0 else None,
                "order_type": "market" if use_market else "limit",
                "order_type_reason": order_type_reason,
            })
            # Extract revalidation snapshot fields (Gap 7)
            _reval_verdict = None
            _reval_score = None
            _reval_flags = None
            _price_at_approval = None
            _staleness_min = None
            if revalidation_snapshot:
                _reval_verdict = revalidation_snapshot.get("status") or revalidation_snapshot.get("eligibility_status")
                _reval_score = revalidation_snapshot.get("execution_readiness_score")
                _mc = revalidation_snapshot.get("material_change_reasons")
                _reval_flags = json.dumps(_mc) if _mc else None
                _price_at_approval = revalidation_snapshot.get("price_at_recommendation")
                elapsed = revalidation_snapshot.get("elapsed_since_approval_seconds")
                _staleness_min = int(elapsed / 60) if elapsed else None

            # Phase 190C: derive the stop note + tracking metadata from BROKER CONFIRMATION,
            # never from the use_market boolean. A note must not claim "placed" without proof.
            if use_market or _extended_hours:
                if stop_broker_id:
                    _stop_desc = f"broker-confirmed (order {stop_broker_id})"
                    _stop_status, _stop_src = "STOP_CONFIRMED", "alpaca_post_confirmed"
                elif stop_placed:
                    _stop_desc = "STOP_SUBMITTED_UNCONFIRMED (no broker id returned)"
                    _stop_status, _stop_src = "STOP_SUBMITTED_UNCONFIRMED", None
                else:
                    _stop_desc = "STOP_PLACEMENT_FAILED"
                    _stop_status, _stop_src = "STOP_PLACEMENT_FAILED", None
            else:
                # atomic bracket: stop is a child leg, confirmed via the accepted parent order
                _stop_desc = f"atomic bracket (parent {order_id})"
                _stop_status, _stop_src = "STOP_BRACKET_CHILD", "alpaca_bracket"
            _prot_status = "PROTECTED_TRACKED" if stop_broker_id else (
                "PROTECTED_UNRECORDED" if _stop_status in ("STOP_SUBMITTED_UNCONFIRMED", "STOP_BRACKET_CHILD") else "NAKED")
            _prot_defect = None if stop_broker_id else _stop_status
            # ── ROOT-CAUSE DEDUP (2026-06-18): a proposal first creates a 'pending' placeholder row
            # (paper_trade_logger.approve_proposal). This broker fill is the single canonical row, so
            # supersede that placeholder instead of letting it become a duplicate $0/breakeven closed
            # trade. Excluded from the journal (status not in open/closed); audit trail preserved.
            if proposal_id:
                cur.execute("""UPDATE paper_trades SET status='superseded_by_fill', lifecycle_state='superseded',
                                 notes=COALESCE(notes,'')||' [superseded by broker fill '||COALESCE(%s,'')||']', updated_at=NOW()
                               WHERE proposal_id=%s AND status IN ('pending','open')
                                 AND opened_via='proposal_approved'""", [str(order_id or ''), proposal_id])
                if cur.rowcount:
                    log.info(f"[alpaca] {symbol}: superseded {cur.rowcount} proposal placeholder row(s) for proposal {proposal_id}")
            cur.execute("""
                INSERT INTO paper_trades (proposal_id, strategy_id, symbol, account, shares, dollar_size,
                    stop_loss, planned_stop, target_1, planned_entry, entry_price, dollar_risk,
                    broker_order_id, broker_status, order_type,
                    market_regime, vix_at_entry,
                    status, opened_via, logged_by, risk_gate_result,
                    risk_params_at_fill, lifecycle_state,
                    filled_at, submitted_at,
                    revalidation_verdict, revalidation_score, revalidation_flags,
                    price_at_approval, staleness_at_submit_min,
                    stop_order_id, stop_verified_at, stop_verified_source, broker_stop_status,
                    current_stop, protection_status, protection_defect_reason,
                    notes)
                VALUES (%s, %s, %s, 'ALPACA_PAPER', %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s, 'alpaca_adapter', 'alpaca_adapter', 'APPROVED',
                    %s, %s,
                    NOW(), NOW(),
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s)
                RETURNING id
            """, [proposal_id, strategy_id, symbol, actual_shares, round(actual_shares * actual_entry, 2),
                  effective_stop, effective_stop, target_price, entry_price, actual_entry,
                  round(abs(actual_entry - effective_stop) * actual_shares, 2),
                  order_id, fill_status,
                  'market' if use_market else 'bracket',
                  _regime, _vix, _db_status,
                  _risk_snap, _db_status,
                  _reval_verdict, _reval_score, _reval_flags,
                  _price_at_approval, _staleness_min,
                  stop_broker_id, (datetime.now(timezone.utc) if stop_broker_id else None), _stop_src, _stop_status,
                  effective_stop, _prot_status, _prot_defect,
                  f"Order type: {order_type_reason}. Fill verified: {fill_status}. "
                  f"Shares: {actual_shares}. Stop: ${effective_stop} {_stop_desc}."])
            _new_trade_id = cur.fetchone()[0]
            conn.commit()

            # Mandatory two-source fill verification on every automated trade (NON-FATAL — records
            # broker truth + TradeAI/Hermes verdicts; never blocks execution or closes a position).
            if _db_status == 'open' and _new_trade_id:
                try:
                    from trade_fill_verifier import verify_and_stamp_fill
                    verify_and_stamp_fill(conn, _new_trade_id)
                except Exception as _ve:
                    log.warning(f"[alpaca] {symbol} fill-verify hook error (non-fatal): {_ve}")

            log.info(f"[alpaca] Order complete: {symbol} {actual_shares}sh @ ${actual_entry:.2f} "
                     f"({'market' if use_market else 'limit'}) status={_db_status} (order {order_id})")
            return {'status': 'submitted', 'order_id': order_id, 'symbol': symbol,
                    'order_type': 'market' if use_market else 'limit',
                    'fill_status': fill_status, 'fill_price': fill_price if fill_status == 'filled' else None,
                    'reason': order_type_reason}
        except Exception as e:
            log.error(f"[alpaca] Order submission failed: {e}")
            return {'status': 'error', 'error': str(e)}

    def get_alpaca_paper_status(self) -> dict:
        """Return paper trading status without exposing secrets."""
        status = {
            'configured': bool(self.api_key and self.secret_key),
            'enabled': self.enabled,
            'paper_endpoint': 'paper-api' in self.base_url,
            'connected': False,
            'account_status': None,
            'equity': 0,
            'buying_power': 0,
            'cash': 0,
            'open_positions': 0,
            'open_orders': 0,
            'last_success': None,
            'last_error': None,
            'trading_blocked': False,
            'api_key_masked': (self.api_key[:4] + '***' + self.api_key[-4:]) if len(self.api_key) > 8 else '***',
        }
        if not self.api_key or not self.secret_key:
            return status
        try:
            acct = self._api_get('/v2/account')
            status['connected'] = True
            status['account_status'] = acct.get('status')
            status['equity'] = float(acct.get('equity', 0))
            status['buying_power'] = float(acct.get('buying_power', 0))
            status['cash'] = float(acct.get('cash', 0))
            status['last_success'] = datetime.now(timezone.utc).isoformat()

            positions = self.get_positions()
            status['open_positions'] = len(positions)

            try:
                orders = self._api_get('/v2/orders?status=open')
                status['open_orders'] = len(orders) if isinstance(orders, list) else 0
            except Exception:
                pass

            # Check halts
            try:
                from session13_db import get_conn
                conn = get_conn()
                from risk_gate import RiskGate
                halt = RiskGate(conn).check_halt('momentum_scalp', 'paper')
                conn.close()
                status['trading_blocked'] = halt is not None
            except Exception:
                pass
        except Exception as e:
            status['last_error'] = str(e)[:200]
        return status

    def get_open_orders(self) -> list:
        """Get open Alpaca paper orders."""
        if not self.enabled or not self.api_key:
            return []
        try:
            return self._api_get('/v2/orders?status=open')
        except Exception:
            return []

    def submit_approved_paper_trade(self, conn, paper_trade_id: int) -> dict:
        """Submit an approved paper trade to Alpaca as bracket order."""
        if not self.enabled:
            return {'status': 'disabled', 'message': 'Alpaca paper not enabled'}

        cur = conn.cursor()
        cur.execute("""
            SELECT symbol, shares, entry_price, stop_loss, target_1, strategy_id
            FROM paper_trades WHERE id = %s AND status = 'open'
        """, [paper_trade_id])
        row = cur.fetchone()
        if not row:
            return {'status': 'error', 'message': f'Paper trade #{paper_trade_id} not found or not open'}

        symbol, shares, entry, stop, target, strategy_id = row
        if not strategy_id:
            log.warning(f"[alpaca] Paper trade #{paper_trade_id} has no strategy_id — using 'unknown'")
        return self.submit_entry(symbol, int(shares), float(entry), float(stop), float(target), strategy_id or 'unknown', conn)

    def write_sync_log(self, conn, status: str, message: str, payload: dict = None):
        """Write to paper_system_sync_log."""
        try:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO paper_system_sync_log (component, status, message, payload)
                VALUES ('alpaca_sync', %s, %s, %s)
            """, [status, message, json.dumps(payload or {}, default=str)])
            conn.commit()
        except Exception:
            pass

    def find_candidates(self, conn):
        """Find GO/A+ signals eligible for Alpaca paper entry."""
        cur = conn.cursor()
        cur.execute("""
            SELECT DISTINCT ON (tas.symbol) tas.symbol, tas.score, tas.decision,
                   tas.price, tas.rvol, tas.float_m, tas.catalyst, tas.catalyst_verified,
                   tp.entry_high, tp.stop_loss, tp.target_1, tp.shares, tp.dollar_risk,
                   tp.id as plan_id, tp.strategy_id
            FROM trade_ai_scans tas
            LEFT JOIN trade_plans tp ON tp.symbol = tas.symbol
                AND tp.generated_at > NOW() - INTERVAL '2 days'
                AND NOT tp.disqualified
            WHERE tas.decision IN ('GO')
            AND tas.score >= %s
            AND tas.scanned_at > NOW() - INTERVAL '24 hours'
            AND tas.symbol NOT IN (
                SELECT symbol FROM paper_trades
                WHERE account = 'ALPACA_PAPER' AND status IN ('open', 'pending')
            )
            ORDER BY tas.symbol, tas.score DESC
        """, [MIN_SCORE_ALPACA])
        return cur.fetchall()


def get_latest_quote(symbol: str) -> dict:
    """Standalone helper: fetch latest quote for a symbol via data API."""
    import requests, os
    headers = {
        'APCA-API-KEY-ID': os.getenv('ALPACA_API_KEY', ''),
        'APCA-API-SECRET-KEY': os.getenv('ALPACA_SECRET_KEY', ''),
    }
    result = {'symbol': symbol, 'price': None, 'source': None, 'bid': None, 'ask': None}
    try:
        resp = requests.get(f'{DATA_BASE_URL}/v2/stocks/{symbol}/quotes/latest',
                            headers=headers, timeout=10)
        resp.raise_for_status()
        q = resp.json().get('quote', {})
        ask = float(q.get('ap') or 0)
        bid = float(q.get('bp') or 0)
        result['ask'] = ask
        result['bid'] = bid
        result['price'] = round((ask + bid) / 2, 4) if ask and bid else (ask or bid)
        result['source'] = 'data_api_quote'
    except Exception as e:
        result['error'] = str(e)
    return result


def main():
    parser = argparse.ArgumentParser(description='Alpaca Paper Trading Adapter')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--sync-only', action='store_true')
    parser.add_argument('--no-entry', action='store_true')
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()

    adapter = AlpacaPaperAdapter(dry_run=args.dry_run)

    enabled_str = 'ENABLED' if adapter.enabled else 'DISABLED (simulation only)'
    has_keys = bool(adapter.api_key and adapter.secret_key)
    log.info(f"[alpaca] Adapter: {enabled_str} | Keys: {'present' if has_keys else 'MISSING'} | Dry-run: {args.dry_run}")

    if not has_keys:
        log.info("[alpaca] No Alpaca API keys configured. Running in simulation mode.")
        print("Alpaca paper adapter: No API keys. Simulation mode only.")
        return

    from session13_db import get_conn
    conn = get_conn()

    # Sync positions
    synced = adapter.sync_positions(conn)
    closed = adapter.detect_closed_positions(conn)
    log.info(f"[alpaca] Sync: {synced} positions synced, {closed} closed detected")

    if args.sync_only:
        conn.close()
        return

    # Find and submit candidates (if not --no-entry)
    candidates = []
    if not args.no_entry and not args.sync_only:
        # Check system halt
        try:
            from risk_gate import RiskGate
            gate = RiskGate(conn)
            halt = gate.check_halt('momentum_scalp', 'paper')
            if halt:
                log.info(f"[alpaca] System halt active: {halt}")
                conn.close()
                return
        except Exception:
            pass

        candidates = adapter.find_candidates(conn)
        log.info(f"[alpaca] Found {len(candidates)} candidates for paper entry")

        for cand in candidates:
            symbol = cand[0]
            entry = float(cand[8] or cand[3] or 0)
            stop = float(cand[9] or 0)
            target = float(cand[10] or 0)
            shares = int(cand[11] or 0)
            strategy = cand[14] or 'momentum_scalp'

            if not all([entry, stop, target, shares]):
                log.info(f"[alpaca] {symbol}: incomplete plan — skipping")
                continue

            if shares * entry > MAX_POSITION_SIZE:
                shares = int(MAX_POSITION_SIZE / entry)

            result = adapter.submit_entry(symbol, shares, entry, stop, target, strategy, conn)
            log.info(f"[alpaca] {symbol}: {result.get('status')}")

    conn.close()
    print(f"Alpaca paper adapter complete: {synced} synced, {closed} closed, {len(candidates)} candidates")


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
        handlers=[logging.FileHandler(str(PROJECT_ROOT / 'logs/alpaca_paper_adapter.log')), logging.StreamHandler()])
    main()
