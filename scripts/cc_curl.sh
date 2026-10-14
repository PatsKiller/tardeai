#!/usr/bin/env bash
# cc_curl.sh — curl for loopback Command Center callers (2026-10-14, cc_auth).
#
# Usage: scripts/cc_curl.sh [curl args...] http://127.0.0.1:7777/api/...
#
# Adds the per-host service-token header (config/cc_auth.yaml service_token) ONLY when one of the
# arguments is a loopback URL on the CC service port. The header is passed through a process
# substitution (`-H @file`), so the token never appears in argv / ps. A missing token file is not an
# error: curl runs without the header and the server decides (report_only logs; enforce answers 401).
set -uo pipefail
_here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_py="${TRADEAI_PYTHON:-python3}"
mapfile -t _cc < <("$_py" "$_here/lib/cc_auth.py" --client-settings 2>/dev/null)
_hdr="${_cc[0]:-}"
_file="${_cc[1]:-}"
_port="${_cc[2]:-}"
_target=0
if [[ -n "$_port" ]]; then
  for _a in "$@"; do
    if [[ "$_a" =~ ^http://(127\.0\.0\.1|localhost|\[::1\]):${_port}(/|\?|$) ]]; then
      _target=1
      break
    fi
  done
fi
if [[ "$_target" == 1 && -n "$_hdr" && -n "$_file" && -r "$_file" ]]; then
  exec curl -H @<(printf '%s: %s\n' "$_hdr" "$(<"$_file")") "$@"
fi
exec curl "$@"
