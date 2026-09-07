"""
Portfolio Validator — cross-references displayed portfolio values
against broker data to detect P&L discrepancies.
"""
import json, os

class PortfolioValidator:
    TOLERANCE_PCT = 1.0

    def __init__(self, live_dir=None):
        """`live_dir` is the release the caller is validating.

        The health inspector has always called this as
        `PortfolioValidator(live_dir=live_dir)` — every other validator in that
        module takes it — while __init__ accepted nothing, so every run raised

            Portfolio validation failed: PortfolioValidator.__init__() got an
            unexpected keyword argument 'live_dir'

        and the P2 finding reported the TypeError instead of a portfolio check.
        Portfolio validation has therefore never actually run from that path.

        It is recorded rather than ignored. This validator reads the API rather
        than the filesystem, so live_dir does not change what it measures — but
        it does say WHICH deployment the numbers were taken against, and a
        finding that cannot name its subject is the weaker finding. Accepting a
        parameter only to discard it would fix the traceback and keep the
        silence.
        """
        self.findings = []
        self.live_dir = live_dir

    def _api(self, path):
        import urllib.request
        try:
            r = urllib.request.urlopen(f'http://localhost:7777{path}', timeout=10)
            return json.loads(r.read()).get('data', {})
        except:
            return {}

    def get_displayed_portfolio(self):
        data = self._api('/api/v2/risk')
        return {
            'total_value': data.get('portfolio_value') or data.get('total_equity'),
            'today_pnl': data.get('today_pnl') or data.get('daily_pnl'),
            'source': 'api/v2/risk'
        }

    def get_broker_portfolio(self):
        data = self._api('/api/v2/brokers/schwab/accounts')
        accounts = data.get('accounts', [data] if isinstance(data, dict) else [])
        total = 0
        pnl = 0
        for acct in accounts:
            if isinstance(acct, dict):
                total += float(acct.get('currentValue', 0) or acct.get('marketValue', 0) or 0)
                pnl += float(acct.get('todayProfitLoss', 0) or acct.get('dailyPnl', 0) or 0)
        if total > 0:
            return {'total_value': total, 'today_pnl': pnl, 'source': 'schwab_accounts'}
        return None

    def _tag(self, finding):
        """Stamp the release under validation onto a finding."""
        if self.live_dir:
            finding.setdefault("live_dir", self.live_dir)
        return finding

    def _tagged(self):
        """Every finding leaves here naming the deployment it was taken from.

        Applied at the exits rather than at each append: three return points is
        a smaller surface than every raise site, and a finding added later
        cannot forget to be tagged.
        """
        return [self._tag(f) for f in self.findings]

    def validate(self):
        displayed = self.get_displayed_portfolio()
        broker = self.get_broker_portfolio()

        if not displayed:
            self.findings.append({
                'severity': 'P1', 'type': 'portfolio_data_unavailable',
                'message': 'Cannot read portfolio value from /api/v2/risk'
            })
            return self._tagged()

        if not broker:
            self.findings.append({
                'severity': 'P2', 'type': 'broker_data_unavailable',
                'message': 'Cannot reach Schwab for portfolio validation'
            })
            return self._tagged()

        if displayed.get('total_value') and broker.get('total_value'):
            dv = float(displayed['total_value'])
            bv = float(broker['total_value'])
            if dv > 0 and bv > 0:
                diff = abs(dv - bv) / bv * 100
                if diff > self.TOLERANCE_PCT:
                    self.findings.append({
                        'severity': 'P0' if diff > 3 else 'P1',
                        'type': 'portfolio_value_mismatch',
                        'displayed_total': round(dv, 2),
                        'broker_total': round(bv, 2),
                        'diff_pct': round(diff, 2),
                        'message': f'Portfolio: ${dv:,.0f} displayed vs ${bv:,.0f} broker ({diff:.1f}% diff)'
                    })

        if displayed.get('today_pnl') is not None and broker.get('today_pnl') is not None:
            dp = float(displayed['today_pnl'])
            bp = float(broker['today_pnl'])
            pnl_diff = abs(dp - bp)
            if pnl_diff > 100:
                self.findings.append({
                    'severity': 'P1', 'type': 'pnl_mismatch',
                    'displayed_pnl': round(dp, 2),
                    'broker_pnl': round(bp, 2),
                    'diff_dollars': round(pnl_diff, 2),
                    'message': f'P&L: ${dp:,.0f} displayed vs ${bp:,.0f} broker (${pnl_diff:,.0f} diff)'
                })

        return self._tagged()
