"""
Site Validator — checks all API endpoints respond correctly
and Telegram alerts are flowing.
"""
import json, os, time

class SiteValidator:
    def __init__(self):
        self.findings = []
        self.ENDPOINTS = [
            ('/api/v2/trade-ai/summary', 'Trade AI summary'),
            ('/api/v2/risk', 'Risk & portfolio'),
            ('/api/v2/health', 'Health status'),
            ('/api/v2/system-health', 'System health'),
            ('/api/v2/trade-ai/scanner', 'Scanner data'),
        ]

    def validate_api_consistency(self):
        import urllib.request
        for endpoint, label in self.ENDPOINTS:
            try:
                r = urllib.request.urlopen(f'http://localhost:7777{endpoint}', timeout=10)
                if r.status != 200:
                    sev = 'P0' if r.status >= 500 else 'P2'
                    self.findings.append({
                        'severity': sev, 'type': 'api_down',
                        'endpoint': endpoint, 'label': label,
                        'status_code': r.status,
                        'message': f'{label} ({endpoint}) returned {r.status}'
                    })
                else:
                    data = json.loads(r.read()).get('data', {})
                    stale = data.get('stale') if isinstance(data, dict) else None
                    if stale:
                        self.findings.append({
                            'severity': 'P2', 'type': 'api_stale_data',
                            'endpoint': endpoint, 'label': label,
                            'message': f'{label} serving stale data'
                        })
            except Exception as e:
                self.findings.append({
                    'severity': 'P0', 'type': 'api_unreachable',
                    'endpoint': endpoint, 'label': label,
                    'message': f'{label} unreachable: {e}'
                })
        return self.findings

    def validate_telegram_alerts(self):
        paths = [
            '/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/logs/telegram_alerts.log',
        ]
        for path in paths:
            if os.path.exists(path):
                age = (time.time() - os.path.getmtime(path)) / 60
                if age > 60:
                    self.findings.append({
                        'severity': 'P1', 'type': 'telegram_alerts_stale',
                        'message': f'Telegram alert log stale ({age:.0f}min)'
                    })
                break
        return self.findings
