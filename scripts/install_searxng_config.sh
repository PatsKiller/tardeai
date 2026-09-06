#!/usr/bin/env bash
# install_searxng_config.sh — put the reviewed engine pool live, with the Brave
# API key injected from the local secret store and never printed.
#
#   sudo -E bash scripts/install_searxng_config.sh            # install + restart
#   bash scripts/install_searxng_config.sh --dry-run          # show, touch nothing
#
# WHY THIS EXISTS AS A SCRIPT
# ---------------------------
# infra/searxng/core-config/ is owned by the container user (977) and this host
# user is not in that group, so the file cannot be edited directly. The obvious
# workaround — chown it to the human — is what took SearXNG down on 2026-09-05:
# the file came back mode 600 and the worker, which is not uid 977, could no
# longer read it:
#
#     SearxSettingsException: [Errno 13] Permission denied: '/etc/searxng/settings.yml'
#     [ERROR] Unexpected exit from worker-1
#
# So ownership and mode are restored explicitly here (977:977, 0644 — the state
# that was working before), the YAML is validated BEFORE anything is replaced,
# and the container is rolled back if it does not come up.
#
# THE KEY IS NEVER PRINTED AND NEVER COMMITTED
# --------------------------------------------
# `braveapi` takes a mandatory api_key and SearXNG does no environment
# substitution in settings.yml, so the value has to be literal in the installed
# file. That file is instance config, not the repo copy — SearXNG already writes
# a `secret_key` into it at startup. The repo template keeps api_key: "".
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE="${REPO_ROOT}/infra/searxng/core-config/settings.yml"
LIVE_DIR="${SEARXNG_CONFIG_DIR:-${HOME}/trade-ai-v12-rebuild/trade-ai-v12-rebuild/infra/searxng/core-config}"
LIVE="${LIVE_DIR}/settings.yml"
ENV_FILE="${TRADEAI_ENV:-${HOME}/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.env}"
DRY=0
[[ "${1:-}" == "--dry-run" ]] && DRY=1

say() { printf '  %s\n' "$*"; }
die() { printf '  ERROR: %s\n' "$*" >&2; exit 1; }

[[ -f "$TEMPLATE" ]] || die "template missing: $TEMPLATE"
[[ -f "$LIVE" ]] || die "live config missing: $LIVE"

# ── 1. the key, read but never echoed ───────────────────────────────────────
KEY="$(grep -m1 '^BRAVE_SEARCH_API_KEY=' "$ENV_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"'"'"' \r')"
if [[ -z "$KEY" ]]; then
  say "no BRAVE_SEARCH_API_KEY in $ENV_FILE — braveapi will stay disabled"
else
  say "brave key found (length ${#KEY}, value not shown)"
fi

# ── 2. build the candidate in a temp file ───────────────────────────────────
TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
cp "$TEMPLATE" "$TMP"

# Carry forward the instance secret SearXNG generated. Losing it logs every user
# out and, on some versions, refuses to start.
SECRET="$(grep -m1 -E '^\s*secret_key:' "$LIVE" 2>/dev/null || true)"
if [[ -n "$SECRET" ]]; then
  if grep -qE '^\s*secret_key:' "$TMP"; then
    python3 - "$TMP" "$SECRET" <<'PY'
import re, sys
p, line = sys.argv[1], sys.argv[2]
s = open(p).read()
s = re.sub(r'^\s*secret_key:.*$', line, s, count=1, flags=re.M)
open(p, 'w').write(s)
PY
  else
    python3 - "$TMP" "$SECRET" <<'PY'
import re, sys
p, line = sys.argv[1], sys.argv[2]
s = open(p).read()
s = re.sub(r'^(server:\s*\n)', r'\1' + line + '\n', s, count=1, flags=re.M)
open(p, 'w').write(s)
PY
  fi
  say "carried forward the existing secret_key"
fi

# Inject the key and enable braveapi, only when a key exists.
if [[ -n "$KEY" ]]; then
  BRAVE_KEY="$KEY" python3 - "$TMP" <<'PY'
import os, re, sys
p = sys.argv[1]
s = open(p).read()
block = re.search(r'(  - name: braveapi\n(?:    .*\n)+)', s)
if block:
    b = block.group(1)
    nb = b.replace('api_key: ""', 'api_key: "%s"' % os.environ["BRAVE_KEY"])
    nb = nb.replace('disabled: true', 'disabled: false')
    # `inactive` is a separate gate from `disabled`. SearXNG defaults ship
    # braveapi inactive: true, which means NEVER REGISTERED — clearing only
    # `disabled` leaves it silently absent, which is what happened on the
    # 2026-09-06 03:42 install.
    if 'inactive:' not in nb:
        nb = nb.replace('engine: braveapi\n', 'engine: braveapi\n    inactive: false\n')
    else:
        nb = nb.replace('inactive: true', 'inactive: false')
    s = s.replace(b, nb)
    open(p, 'w').write(s)
    print("  braveapi: key injected, enabled")
else:
    print("  braveapi block not found — left as-is")
PY
fi

# yahoo_news is no longer injected here. It was added enabled on 2026-09-06
# purely to measure it, returned 0 results with an HTTP error, and now sits
# in the template disabled with that measurement recorded. The installer
# installs the reviewed template; it does not invent engines.

# ── 3. validate BEFORE replacing anything ───────────────────────────────────
python3 - "$TMP" <<'PY' || exit 1
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))
assert d.get("use_default_settings") is True, "use_default_settings lost"
assert d["server"]["port"] == 8080, "server port lost"
assert d["server"]["bind_address"] == "0.0.0.0", "bind address lost"
names = [e["name"] for e in d["engines"]]
assert len(names) == len(set(names)), "duplicate engine name"
sc = [e["shortcut"] for e in d["engines"]]
assert len(sc) == len(set(sc)), "duplicate shortcut"
# `inactive` is a SEPARATE gate from `disabled`. An engine left inactive is
# never registered and never logs anything — it simply is not there. This is
# the check that would have caught braveapi and `yahoo news` on 2026-09-06.
ghosts = [e["name"] for e in d["engines"]
          if not e.get("disabled") and e.get("inactive") is True]
assert not ghosts, "enabled but inactive (will never register): %s" % ghosts
print("  candidate YAML valid: %d engines" % len(names))
PY

if [[ $DRY -eq 1 ]]; then
  say "DRY RUN — nothing written. Engines that would be active:"
  python3 - "$TMP" <<'PY'
import sys, yaml
d = yaml.safe_load(open(sys.argv[1]))
for e in d["engines"]:
    if not e.get("disabled"):
        print("    %-14s %s" % (e["name"], "(keyed)" if e.get("api_key") else ""))
PY
  exit 0
fi

# ── 4. back up, install, restore the ownership/mode that worked ─────────────
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="${LIVE}.bak-${STAMP}"
cp -p "$LIVE" "$BACKUP" || die "could not back up $LIVE"
say "backup: $BACKUP"

cat "$TMP" > "$LIVE" || die "could not write $LIVE (run under sudo)"
chown 977:977 "$LIVE" 2>/dev/null || say "WARN could not chown to 977:977"
chmod 0644 "$LIVE" || say "WARN could not chmod 0644"
say "installed: $(stat -c '%U(%u):%G(%g) %A' "$LIVE")"

# ── 5. restart, and roll back if it does not come up ───────────────────────
sg docker -c 'docker restart searxng' >/dev/null 2>&1 || docker restart searxng >/dev/null 2>&1
for _ in $(seq 1 20); do
  sleep 3
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1:18888/ 2>/dev/null)"
  [[ "$code" == "200" ]] && break
done
if [[ "${code:-000}" != "200" ]]; then
  say "searxng did not come up (HTTP ${code:-000}) — ROLLING BACK"
  cat "$BACKUP" > "$LIVE"; chown 977:977 "$LIVE" 2>/dev/null; chmod 0644 "$LIVE"
  sg docker -c 'docker restart searxng' >/dev/null 2>&1 || docker restart searxng >/dev/null 2>&1
  die "rolled back to $BACKUP — config not applied"
fi
say "searxng up (HTTP 200)"

# ── 6. measure what actually serves, per engine ────────────────────────────
say "did every intended engine actually REGISTER?"
python3 - "$TMP" <<'PY'
import json, sys, urllib.request, yaml
want = [e["name"] for e in yaml.safe_load(open(sys.argv[1]))["engines"]
        if not e.get("disabled")]
try:
    with urllib.request.urlopen("http://127.0.0.1:18888/config", timeout=25) as r:
        loaded = {e["name"] for e in json.loads(r.read()).get("engines", [])}
except Exception as exc:
    print("    could not read /config: %s" % type(exc).__name__); raise SystemExit(0)
missing = [n for n in want if n not in loaded]
for n in want:
    print("    %-14s %s" % (n, "registered" if n in loaded else "MISSING FROM RUNNING CONFIG"))
if missing:
    print("    ^ these are configured but not registered. SearXNG skips an engine")
    print("      marked `inactive: true` silently — no error, no log line.")
PY

say "measuring each enabled engine (attribution, not result count):"
python3 - <<'PY'
import json, urllib.parse, urllib.request, collections
BASE = "http://127.0.0.1:18888/search"
for name in ("bing", "seznam", "yep", "yandex", "braveapi", "yahoo news", "wikipedia"):
    q = urllib.parse.urlencode({"q": "nvidia quarterly earnings",
                                "engines": name, "format": "json"})
    try:
        with urllib.request.urlopen(f"{BASE}?{q}", timeout=35) as r:
            d = json.loads(r.read())
    except Exception as exc:
        print(f"    {name:12} probe failed: {type(exc).__name__}")
        continue
    c = collections.Counter()
    for res in d.get("results") or []:
        for e in res.get("engines") or []:
            c[e] += 1
    own = c.get(name, 0)
    u = d.get("unresponsive_engines") or []
    verdict = "OK " if own else "ZERO"
    print(f"    {verdict} {name:12} own={own:3} all={dict(c) or '-'} unresp={u if u else '-'}")
PY
say "done. An engine reporting ZERO contributes nothing — disable it."
