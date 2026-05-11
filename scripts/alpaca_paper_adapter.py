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
MAX_POSITIONS = 3
MAX_POSITION_SIZE = 2000
MIN_SCORE_ALPACA = 45

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

            # Update existing open paper trade if exists
            cur.execute("""
                UPDATE paper_trades
                SET current_price = %s, unrealized_pnl = %s, last_synced_at = NOW()
                WHERE symbol = %s AND account = 'ALPACA_PAPER' AND status = 'open'
            """, [current, unrealized, symbol])

            if cur.rowcount == 0:
                # Position exists in Alpaca but not in paper_trades — create record
                cur.execute("""
                    INSERT INTO paper_trades (strategy_id, symbol, account, entry_price, entry_time,
                        shares, dollar_size, current_price, unrealized_pnl, status,
                        opened_via, logged_by, last_synced_at)
                    VALUES ('momentum_scalp', %s, 'ALPACA_PAPER', %s, NOW(),
                        %s, %s, %s, %s, 'open',
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
            WHERE account = 'ALPACA_PAPER' AND status = 'open'
        """)
        open_trades = cur.fetchall()

        if not open_trades:
            return 0

        alpaca_positions = self.get_positions()
        alpaca_symbols = {p['symbol'] for p in alpaca_positions}

        closed = 0
        for trade_id, symbol in open_trades:
            if symbol not in alpaca_symbols:
                # Position no longer in Alpaca — likely closed
                log.info(f"[alpaca] {symbol} no longer in Alpaca positions — marking closed")
                cur.execute("""
                    UPDATE paper_trades
                    SET status = 'closed', closed_at = NOW(), closed_via = 'alpaca_sync',
                        exit_reason = 'position_closed_in_alpaca', updated_at = NOW()
                    WHERE id = %s
                """, [trade_id])
                # Agent curation hooks (non-blocking)
                try:
                    from agent_curation_hooks import on_paper_trade_closed
                    on_paper_trade_closed(conn, trade_id)
                except Exception as e:
                    log.warning(f"[alpaca] Curation hooks failed for {symbol}: {e}")
                closed += 1

        if closed:
            conn.commit()
        return closed

    def submit_entry(self, symbol, shares, entry_price, stop_price, target_price, strategy_id, conn):
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
        if open_count >= MAX_POSITIONS:
            log.warning(f"[alpaca] Max positions ({MAX_POSITIONS}) reached")
            return {'status': 'rejected', 'reason': 'max_positions'}

        # Determine order type based on price proximity
        # If current price is within 2% of entry, use market order for immediate fill.
        # If current price is below entry (better price), use market order.
        # If current price is significantly above entry, use limit at entry for value.
        current_price = None
        try:
            quote = self._api_get(f'/v2/stocks/{symbol}/quotes/latest')
            current_price = float(quote.get('quote', {}).get('ap') or quote.get('quote', {}).get('bp') or 0)
        except Exception:
            pass

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

        # Submit order (bracket if limit, simple + separate stop if market)
        try:
            if use_market:
                # Market order — immediate fill. Set stop separately after fill.
                order_data = {
                    'symbol': symbol,
                    'qty': str(shares),
                    'side': 'buy',
                    'type': 'market',
                    'time_in_force': 'day',
                }
            else:
                # Limit order with bracket — fills when price reaches entry
                order_data = {
                    'symbol': symbol,
                    'qty': str(shares),
                    'side': 'buy',
                    'type': 'limit',
                    'time_in_force': 'day',
                    'limit_price': str(entry_price),
                    'order_class': 'bracket',
                    'stop_loss': {'stop_price': str(stop_price)},
                    'take_profit': {'limit_price': str(target_price)},
                }
            result = self._api_post('/v2/orders', order_data)
            order_id = result.get('id', '')
            fill_price = entry_price  # default to proposed

            # For market orders, set stop loss separately after fill
            if use_market:
                import time as _time
                _time.sleep(2)  # brief wait for fill
                try:
                    # Check fill
                    fill_check = self._api_get(f'/v2/orders/{order_id}')
                    if fill_check.get('status') == 'filled':
                        fill_price = float(fill_check.get('filled_avg_price', entry_price))
                        log.info(f"[alpaca] {symbol} FILLED @ ${fill_price:.2f}")
                    # Place stop loss
                    stop_order = {
                        'symbol': symbol, 'qty': str(shares), 'side': 'sell',
                        'type': 'stop', 'stop_price': str(stop_price),
                        'time_in_force': 'gtc',
                    }
                    self._api_post('/v2/orders', stop_order)
                    log.info(f"[alpaca] {symbol} STOP set @ ${stop_price}")
                except Exception as stop_err:
                    log.warning(f"[alpaca] {symbol} stop placement failed: {stop_err}")

            # Record in paper_trades
            actual_entry = fill_price if use_market else entry_price
            cur.execute("""
                INSERT INTO paper_trades (strategy_id, symbol, account, shares, dollar_size,
                    stop_loss, target_1, planned_entry, entry_price, dollar_risk,
                    broker_order_id, broker_status, order_type,
                    status, opened_via, logged_by, risk_gate_result)
                VALUES (%s, %s, 'ALPACA_PAPER', %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, 'alpaca_adapter', 'alpaca_adapter', 'APPROVED')
            """, [strategy_id, symbol, shares, round(shares * actual_entry, 2),
                  stop_price, target_price, entry_price, actual_entry,
                  round(abs(actual_entry - stop_price) * shares, 2),
                  order_id, result.get('status', 'new'),
                  'market' if use_market else 'bracket',
                  'open' if use_market and result.get('status') == 'accepted' else 'pending'])
            conn.commit()

            log.info(f"[alpaca] Order submitted: {symbol} {shares}sh @ ${actual_entry:.2f} "
                     f"({'market' if use_market else 'limit'}) (order {order_id})")
            return {'status': 'submitted', 'order_id': order_id, 'symbol': symbol,
                    'order_type': 'market' if use_market else 'limit',
                    'reason': order_type_reason, 'fill_price': fill_price if use_market else None}
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
        return self.submit_entry(symbol, int(shares), float(entry), float(stop), float(target), strategy_id or 'momentum_scalp', conn)

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
