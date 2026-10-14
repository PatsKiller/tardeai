CC TAILSCALE-IDENTITY AUTH — OPERATOR PACKET (2026-10-14, SPCX incident security review)
==========================================================================================

Operator decision: "tailscale identity now, no hardware key".
Branch: fix/cc-tailscale-identity-auth-20261014 (local commit only; nothing pushed, merged or deployed).
Every script here is a DRY RUN unless given --apply. Nothing in this packet calls a broker.

WHAT CHANGES
------------
portfolio_server.py now answers on TWO listeners (same process, same app):

  service      127.0.0.1:7777                         loopback callers. Needs the per-host
                                                      service token (header X-TradeAI-Service-Token,
                                                      or Authorization: Bearer). Tailscale-User-*
                                                      headers are IGNORED here (any local process
                                                      could forge them).
                                                      No-token exemptions (GET only): /api/health,
                                                      /api/v2/health, /v3/build-meta.json.
  serve_proxy  unix:/run/user/1000/tradeai-cc/serve.sock   0600 socket in a 0700 dir. The ONLY target
                                                      `tailscale serve` should use. Needs
                                                      Tailscale-User-Login in allowed_logins
                                                      (john@jwwhiting.com). tailscale serve strips
                                                      client-sent copies and sets the header from
                                                      the tailnet identity; tagged devices and
                                                      Funnel get none -> 403.

Step-up: 42 method+path pairs (order/pilot arm-execute-cancel, order routing, paper submits,
stop changes, Schwab exchange-code/reauth-url, credential changes, risk-control changes) call
require_step_up(), which REFUSES with 403 "step-up required — TOTP unlock not yet enabled" on BOTH
listeners, from the moment the release is served (independent of report_only). The full list is in
config/cc_auth.yaml (step_up.routes) and tests/test_cc_tailscale_identity_auth_20261014.py.

WS4-02 (secret writes): POST/PUT/PATCH/DELETE /api/v2/admin/secrets is REFUSED OUTRIGHT (403
"refused: secret writes are CLI-only ...") on both listeners, in every mode — report_only,
enforce:false, step_up off — until operator step-up (TOTP) exists. The handler itself also refuses
unless the request carries an authenticated tailnet operator identity, and its audit actor is that
identity (never the body's "actor"); a service token is not an operator. GET (masked presence list)
still works. The CC Secrets modal will show the refusal; rotate secrets with the host CLI.

WS4-03 (CSRF): tailscale serve stamps john@jwwhiting.com on a request a hostile page forges from the
operator's own phone/laptop, so identity is not enough. On every POST/PUT/PATCH/DELETE:
  * Origin (if sent) must be on csrf.allowed_origins: https://ms01-openclaw.tail163d14.ts.net,
    http://localhost:7789, http://127.0.0.1:7789; Sec-Fetch-Site (if sent) must be same-origin/none;
  * via the serve socket, a request with NEITHER header is refused;
  * a body must be Content-Type: application/json (signed /v3/go/cio/ form links may also be
    urlencoded, but only with a same-origin Origin/Sec-Fetch-Site present).
  * hard routes — admin/secrets|validate-secret, broker-orders/*, kill-switches/(disable|clear|
    release|reset), any .../unlock — are CSRF-enforced even in report_only and with enforce:false.
  * stop routes — kill-switches/(enable|engage), any .../panic — need same-origin only (no content
    type rule, never step-up). NOTE: main has NO HTTP kill-switch enable/disable, panic or unlock
    route today (kill switches are module/CLI; the read-only lock unlock is a file). These patterns
    are pre-registered so the routes are covered the day they are added.
  * CORS: Access-Control-Allow-Origin is now the exact allowlisted Origin (with Vary: Origin), never
    "*"; other origins get no CORS grant. Same-origin pages need none.
  Ordinary routes follow report_only (logged as kind=csrf would_deny until step 6).

Config: config/cc_auth.yaml. Committed: enforce: true, report_only: true.
Env overrides (systemd drop-in): TRADEAI_CC_AUTH_REPORT_ONLY=0|1, TRADEAI_CC_AUTH_ENFORCE=0|1
(kill switch), TRADEAI_CC_SERVICE_TOKEN_FILE.
Decision log (denials, would-be denials, step-up refusals; never a token):
  ~/.local/state/tradeai/cc_auth_decisions.jsonl   (+ "[cc-auth]" lines in logs/portfolio_server.log)
Describe effective config:  python3 <release>/scripts/lib/cc_auth.py --describe

ORDER OF OPERATIONS
-------------------
 1. Token:     ./01_generate_service_token.sh            (dry run)
               ./01_generate_service_token.sh --apply    -> ~/.config/tradeai/cc_service_token, 0600
 2. Deploy the merged code the normal way (prepare + promote exact main SHA; grant reason
    "PR #N sha <sha>"). It boots in report_only: nothing is denied except step-up routes.
    Check:  python3 ~/trade-ai-releases/portfolio-server/CURRENT/scripts/lib/cc_auth.py --describe
            (token_status "ok", serve_proxy_bind_ok true)
            ls -l /run/user/1000/tradeai-cc/serve.sock   (srw------- johnclaw)
            grep '\[cc-auth\]' logs/portfolio_server.log | tail   ("serve_proxy listener → unix:...")
 3. Re-point serve:  ./03_serve_repoint.sh   (dry run: snapshots `tailscale serve status --json`,
                                              checks socket mode 0600 and that it answers)
                     ./03_serve_repoint.sh --apply
                     = sudo tailscale serve --bg --https=443 unix:/run/user/1000/tradeai-cc/serve.sock
    Rollback:        ./03_serve_rollback.sh --apply
                     = sudo tailscale serve --bg --https=443 http://localhost:7777
    (If tailscale refuses to replace the existing 443 handler: sudo tailscale serve --https=443 off,
     then re-run. :8443 -> 7776 is not touched.)
    Fallback if the unix target misbehaves: set listeners.serve_proxy.transport: tcp (127.0.0.1:7779)
    and point serve at http://127.0.0.1:7779 — weaker (any local uid can connect to 7779).
 4. Crontab prewarm curls (3 invocations, 2 lines) -> scripts/cc_curl.sh:
                     ./05_crontab_install.sh          (dry run: snapshot + candidate + diff from LIVE crontab)
                     ./05_crontab_install.sh --apply
    Rollback:        ./05_crontab_rollback.sh --apply
    lane_registry.json needs no change (its match strings are the unchanged URLs).
 5. Watch report_only for >= 1 weekday session + the nightly run:
                     python3 04_check_decisions.py --hours 24
    GO when: no service would_deny rows you care about; no serve_proxy "no tailnet identity" rows from
    your own devices (that would mean serve does not set identity on the unix target -> stay in
    report_only and use the tcp fallback); no ident_on_7777=True rows.
 6. Enforce (outside market hours):  ./06_enforce.sh --apply
    (drop-in 44-cc-auth-enforce.conf: TRADEAI_CC_AUTH_REPORT_ONLY=0; restart; prints 401/200/403 probes)
    Rollback:        ./06_enforce_rollback.sh --apply   (archives the drop-in -> report_only)
    Emergency all-off: Environment=TRADEAI_CC_AUTH_ENFORCE=0 in that drop-in, daemon-reload, restart.
    Rollback order if everything must go: 06 rollback -> 03 rollback -> 05 rollback.

VERIFICATION CHECKLIST (after step 6)
-------------------------------------
[ ] Phone (Pixel 11 Pro XL / S26+) opens https://ms01-openclaw.tail163d14.ts.net -> CC loads, data shows.
[ ] Laptop (Lenovo_Aura / lbigjohn718) same.
[ ] From a tailnet device WITHOUT the allowed login (a tagged node, or a shared-in user):
      curl -s -o /dev/null -w '%{http_code}\n' https://ms01-openclaw.tail163d14.ts.net/api/v2/risk   -> 403
    (No such device today: all 4 devices are john@jwwhiting.com. Prove the deny path on-host instead:
      curl -s -o /dev/null -w '%{http_code}\n' --unix-socket /run/user/1000/tradeai-cc/serve.sock http://cc/api/v2/risk -> 403)
[ ] Forged header on :7777 is ignored:
      curl -s -o /dev/null -w '%{http_code}\n' -H 'Tailscale-User-Login: john@jwwhiting.com' http://127.0.0.1:7777/api/v2/risk -> 401
[ ] Local scripts still work:
      scripts/cc_curl.sh -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:7777/api/v2/risk -> 200
      python3 scripts/hermes_observation_check.py (or any migrated caller) -> no 401
      python3 04_check_decisions.py --hours 2 -> service deny count 0
[ ] Step-up: in the CC, any pilot arm / stop / Schwab reauth action -> "step-up required — TOTP unlock
    not yet enabled" (403); nothing reaches the broker.
[ ] Watchdog still green: /api/health on :7777 is exempt (GET).
[ ] Secrets: CC Secrets modal save -> "refused: secret writes are CLI-only ..." (403); nothing written.
[ ] CSRF: from the phone, open any page on another origin that POSTs to the CC (or on-host:
      curl -s -o /dev/null -w '%{http_code}\n' --unix-socket /run/user/1000/tradeai-cc/serve.sock \
        -H 'Tailscale-User-Login: john@jwwhiting.com' -H 'Origin: https://evil.example' \
        -H 'Content-Type: application/json' -d '{}' http://cc/api/v2/watchlist/x/refresh   -> 403)
[ ] CC buttons that POST (watchlist refresh, inbox decide, broker-orders preview) still work from
    the phone (same-origin JSON) — and 04_check_decisions.py shows no kind=csrf rows from them.

CALLERS (repo) MIGRATED — 64 Python + 15 shell scripts (plus 3 crontab invocations in step 4)
-------------------------------------------------------------------------------------------
Python, via lib.cc_client (cc_urlopen / cc_headers): see the commit; guard test
test_no_raw_loopback_cc_calls_in_python fails if a raw loopback :7777 urlopen/requests call returns.
Shell, via scripts/cc_curl.sh: guard test test_no_raw_loopback_cc_curl_in_shell.

OPERATOR FOLLOW-UPS (not done here)
-----------------------------------
F1  DOF dashboard :8443 -> 127.0.0.1:7776 (~/nyc-dof-auction/dof_server.py, NOT in this repo) is still
    open to every tailnet device with no auth. Same pattern applies (identity check on a serve-only
    socket), separate change in that repo.
F2  Out-of-repo OpenClaw skills call http://127.0.0.1:7777 without the token and will get 401 after
    step 6 unless they send it (header X-TradeAI-Service-Token from ~/.config/tradeai/cc_service_token):
      ~/.openclaw/skills/tradeai-health-inspect/scripts/_common.py
      ~/.openclaw/skills/tradeai-readonly/scripts/tradeai_readonly.py
      ~/.openclaw/skills/tradeai-readonly/scripts/tradeai_options.py
      ~/.openclaw/skills/tradeai-watchlist/scripts/tradeai_watchlist.py
    They will show up as service would_deny rows in step 5 (user_agent Python-urllib).
F3  linux_launchers/hermes_scalp_swarm_tmux.sh (interactive tmux `watch` pane) still uses bare curl.
F4  apps/command-center-v2/serve.py (legacy v2 proxy, not running) forwards to :7777 without a token;
    if ever started it will get 401 (fail-safe).
F5  Step-up blocks, until TOTP exists: the CC's manual Schwab reauth fallback page
    (/v3/system/schwab-reauth -> exchange-code) and scripts/schwab_stop_batch_request.py (POSTs
    /api/v2/holdings/protective-stop). Schwab AUTO-reauth calls the token manager directly and is
    unaffected. Temporary relief, if ever needed: step_up.mode report_only (logs, allows) — a
    deliberate operator decision.
F6  n8n monitor workflow fetches http://172.19.0.1:7777/v3/build-meta.json; the server binds loopback,
    so it cannot reach it today; the path is token-exempt if the bind ever changes.

RESIDUAL RISK
-------------
- Any process running as johnclaw (or root) can read the token file and can connect to the 0600
  serve socket and forge Tailscale-User-Login. That is host compromise and out of scope; the broker
  read-only lock and Schwab app control remain the controls. Other local uids cannot reach the serve
  socket (the tcp 7779 fallback would remove that protection).
- Allowlist is login-based: anyone who signs in to the tailnet AS john@jwwhiting.com (i.e. a stolen
  identity-provider session) passes. Device posture is not checked.
- report_only (the committed default) logs but allows everything except step-up routes. Until step 6
  the CC is only as protected as before, plus step-up.
- The token is a static bearer secret; rotate by moving the file aside and re-running step 1.
- WS4-21: this closes the TAILNET threat, not the local-AGENT threat. Every agent runs as johnclaw,
  so it can read the token, connect to the serve socket, and write the systemd drop-ins that set
  TRADEAI_CC_AUTH_ENFORCE=0 / REPORT_ONLY=1. The secret-write refusal and the hard-route CSRF checks
  ignore enforce/report_only, so those two flags do not reopen them — but pointing
  TRADEAI_CC_AUTH_CONFIG at another file, or editing the release config, does. The agent threat stays open until WS4-01 (uid separation) and WS4-11 (DB roles).
- CSRF relies on browsers sending Origin / Sec-Fetch-Site. All current browsers do on cross-site
  POSTs; a missing pair via serve is refused. A SameSite=Strict session cookie + CSRF token is the
  follow-up once the TOTP session exists.
