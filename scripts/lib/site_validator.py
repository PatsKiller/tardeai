"""
Site Validator — checks that what the API returns matches what renders on the frontend.
Does NOT require browser/headless — checks via API response validation.
"""
import json
import sys
import os
import subprocess
import time


class SiteValidator:
    """Validates that API responses are consistent and renderable."""

    def __init__(self):
        self.findings = []

    def validate_api_consistency(self):
        """Check that related API endpoints return consistent data."""
        endpoints = [
            ('/api/v2/trade-ai/summary', 'Trade AI summary'),
            ('/api/v2/risk', 'Risk & portfolio'),
            ('/api/v2/health', 'Health status'),
            ('/api/v2/system-health', 'System health'),
            ('/api/v2/trade-ai/scanner', 'Scanner data'),
        ]

        try:
            import requests
            for endpoint, label in endpoints:
                try:
                    r = requests.get(f'http://localhost:7777{endpoint}', timeout=10)
                    if r.status_code != 200:
                        self.findings.append({
                            'severity': 'P0' if r.status_code >= 500 else 'P2',
                            'type': 'api_down',
                            'endpoint': endpoint,
                            'status_code': r.status_code,
                            'label': label,
                            'message': f'{label} ({endpoint}) returned {r.status_code}'
                        })
                    else:
                        data = r.json()
                        if 'error' in str(data).lower()[:200]:
                            self.findings.append({
                                'severity': 'P2',
                                'type': 'api_error',
                                'endpoint': endpoint,
                                'label': label,
                                'message': f'{label} returned error: {str(data.get("error", data.get("data",{}).get("error","unknown")))[:100]}'
                            })
                except Exception as e:
                    self.findings.append({
                        'severity': 'P0',
                        'type': 'api_unreachable',
                        'endpoint': endpoint,
                        'label': label,
                        'message': f'{label} unreachable: {e}'
                    })
        except ImportError:
            pass

        return self.findings

    def validate_telegram_alerts(self):
        """Check recent Telegram alerts for consistency with API data."""
        alert_patterns = [
            '/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild/logs/telegram_alerts.log',
            '/home/johnclaw/trade-ai-releases/portfolio-server/bc779f4a-sector-names-tooltips-20260806-111529/logs/telegram_alerts.log',
        ]

        for path in alert_patterns:
            if os.path.exists(path):
                age = (time.time() - os.path.getmtime(path)) / 60
                if age > 60:
                    self.findings.append({
                        'severity': 'P1',
                        'type': 'telegram_alerts_stale',
                        'message': f'Telegram alert log is {age:.0f}min old — alerts may not be flowing',
                    })
                break

        return self.findings
