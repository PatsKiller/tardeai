"""
Runtime Awareness — discovers what is actually running live, not just what's in dev.
Must answer: what process serves port 7777? From what directory? What cache file does it use?
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

class RuntimeAwareness:
    """Discovers live runtime state independent of dev assumptions."""

    def __init__(self):
        self._live_dir = None
        self._server_pid = None
        self._server_cmdline = None
        self._live_cache_path = None
        self._findings = {}

    def discover(self):
        """Full discovery pass. Returns dict of findings."""
        findings = {}

        # 1: What's listening on 7777?
        pid = self._find_port_pid(7777)
        if pid:
            findings['server_pid'] = pid
            cmdline = self._get_cmdline(pid)
            findings['server_cmdline'] = cmdline

            # 2: What directory is it running from?
            script_path = self._extract_script_path(cmdline)
            if script_path:
                findings['server_script'] = script_path
                server_dir = str(Path(script_path).resolve().parent.parent)
                findings['live_directory'] = server_dir
                self._live_dir = server_dir

                # 3: What cache file does it serve?
                cache_path = os.path.join(server_dir, 'data', 'runtime', 'trade_ai_cache.json')
                findings['live_cache_path'] = cache_path
                findings['live_cache_exists'] = os.path.exists(cache_path)

                if os.path.exists(cache_path):
                    try:
                        with open(cache_path) as f:
                            d = json.load(f)
                        findings['live_cache_run_date'] = d.get('run_date')
                        findings['live_cache_stale'] = d.get('stale')
                        findings['live_cache_tickers'] = len(d.get('tickers', []))
                        findings['live_cache_vix'] = d.get('vix')
                        findings['live_cache_size'] = os.path.getsize(cache_path)
                    except Exception:
                        findings['live_cache_parse_error'] = True

        # 4: What systemd services are running?
        findings['systemd_services'] = self._get_systemd_services()

        # 5: What agent runtime services failed?
        findings['failed_services'] = self._get_failed_services()

        # 6: Dev directory vs live directory
        findings['dev_directory'] = '/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild'
        findings['dev_live_mismatch'] = (self._live_dir is not None and
                                          self._live_dir != findings['dev_directory'])

        self._findings = findings
        return findings

    def _find_port_pid(self, port):
        try:
            result = subprocess.run(['ss', '-tlnp'], capture_output=True, text=True, timeout=5)
            for line in result.stdout.split('\n'):
                if f':{port}' in line:
                    m = re.search(r'pid=(\d+)', line)
                    if m:
                        return int(m.group(1))
        except Exception:
            pass
        return None

    def _get_cmdline(self, pid):
        try:
            return subprocess.run(['ps', '-fp', str(pid)],
                                  capture_output=True, text=True, timeout=5).stdout
        except Exception:
            return None

    def _extract_script_path(self, cmdline):
        """From ps output, find the Python script path."""
        if not cmdline:
            return None
        m = re.search(r'/(?:[^/\s]+/)+[^/\s]+\.py', cmdline)
        return m.group(0) if m else None

    def _get_systemd_services(self):
        try:
            result = subprocess.run(
                ['systemctl', '--user', 'list-units', '--type=service', '--no-legend', '--no-pager'],
                capture_output=True, text=True, timeout=5
            )
            services = {}
            for line in result.stdout.strip().split('\n'):
                if 'tradeai' in line.lower() or 'portfolio' in line.lower():
                    parts = line.split()
                    if len(parts) >= 3:
                        name = parts[0].replace('.service', '')
                        status = parts[3] if len(parts) > 3 else 'unknown'
                        services[name] = status
            return services
        except Exception:
            return {}

    def _get_failed_services(self):
        try:
            result = subprocess.run(
                ['systemctl', '--user', 'list-units', '--type=service', '--state=failed', '--no-legend', '--no-pager'],
                capture_output=True, text=True, timeout=5
            )
            failed = []
            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    failed.append(line.split()[0].replace('.service', ''))
            return failed
        except Exception:
            return []

    def is_live_serving(self):
        """Check if the live endpoint responds."""
        import urllib.request
        try:
            req = urllib.request.urlopen('http://localhost:7777/api/v2/health', timeout=5)
            return req.status == 200
        except Exception:
            return False

    def get_live_directory(self):
        """Return the directory the live server is running from."""
        if not self._findings:
            self.discover()
        return self._findings.get('live_directory')

    def resolve_path(self, relative_path):
        """Resolve a path relative to either the live directory or dev directory."""
        live = self.get_live_directory()
        if live:
            live_path = os.path.join(live, relative_path)
            if os.path.exists(live_path):
                return live_path
        return os.path.join('/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild', relative_path)

    def report(self):
        """Human-readable summary."""
        if not hasattr(self, '_findings') or not self._findings:
            self.discover()
        f = self._findings
        lines = [
            "=== Runtime Awareness Report ===",
            f"Server PID: {f.get('server_pid', 'UNKNOWN')}",
            f"Server script: {f.get('server_script', 'UNKNOWN')}",
            f"Live directory: {f.get('live_directory', 'UNKNOWN')}",
            f"Dev/live mismatch: {f.get('dev_live_mismatch', True)}",
            f"Live cache: {f.get('live_cache_path', 'UNKNOWN')}",
            f"  run_date: {f.get('live_cache_run_date', 'UNKNOWN')}",
            f"  stale: {f.get('live_cache_stale', 'UNKNOWN')}",
            f"  tickers: {f.get('live_cache_tickers', 'UNKNOWN')}",
            f"Failed services: {len(f.get('failed_services', []))}",
        ]
        return '\n'.join(lines)
