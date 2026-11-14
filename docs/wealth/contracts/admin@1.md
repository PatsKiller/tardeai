# admin@1 — LEAN Admin modal: Connections · Essential settings
Status: SCOPED (lead audit pass 1, 2026-11-14 ~18:40 ET). Not PROPOSED until the owner's audit (below) lands. REQUIRED PARITY (operator), not a later enhancement.
SCOPE LIMIT (operator 18:29 ET) supersedes the diagnostics tab — see §Lean scope.
Owner cc-deepseek-9 · reviewer cc-deepseek-2 · visual reference cc-opus-3 → reviewer cc-deepseek-3.

## Lean scope (binding, operator 2026-11-14 18:29 ET)
One compact modal, at most two sections. No extra tabs.
1. **Connections** — only connections John must maintain: Schwab (renewal/reauth), Finviz cookie, and any other cookie/provider the audit proves is actually used and operator-maintained. Per row: state OK | EXPIRING | ACTION_REQUIRED | UNKNOWN (computed, never declared); last verified time; expiry/renewal date only when supported by evidence (else UNKNOWN + last verified); one safe action (Schwab: sanctioned operator reauth/2FA handoff; cookie: authorized secure replacement path). Keeps the Schwab 7-day lifecycle and meaningful expiry/recovery alerts.
2. **Essential settings** — allowlisted non-Bitwarden settings John actually operates today (start from existing user-operated controls, not every env var). Plain labels, validation, effective vs pending, Save/Cancel.
Optional: a small "recent change / undo" disclosure.
Behind the scenes, unchanged rigor: redacted full audit, versioned atomic writes, concurrency token, server validation, current auth + step-up, rollback.
**Not in the modal** (stay in existing Ops/background): verbose logs, raw config browsing, n8n/workflow internals, service/agent controls, expert tuning, detailed diagnostics. Never: text-file editor, terminal, credential dump, duplicate Bitwarden manager.

## Placement of every existing function (lead first pass; owner -9 confirms with evidence)
| existing function | placement |
|---|---|
| Schwab token health + reauth handoff | MODAL · Connections |
| Finviz cookie status + replacement path | MODAL · Connections |
| YouTube cookie status | MODAL · Connections only if proven operator-maintained and in use; else background |
| Other provider keys (FRED, Brave, Alpha Vantage, etc. in credential_monitor) | background alerting; MODAL row only if expiry/rotation is operator action |
| Secrets listing/write (SecretsManager) | NOT modal (Bitwarden is the manager); presence shown only as a Connections row state |
| Ops controls switches (ops_controls.json) | MODAL · Essential settings only for the switches John flips today (audit names them); rest Ops |
| Accounts/brokers/broker-account api/policy | Ops (broker-lock adjacent) |
| Risk config, strategy enablement, ATM state | Ops (expert tuning) unless audit shows John operates one routinely |
| Audit log | background + modal's recent-change/undo disclosure (own changes only) |
| Alert ack/resolve | Ops |
| Cron retry, maintenance backfills | Ops/background (cron retry conflicts with n8n-only) |

## Existing surfaces found on served R13 (3ac0b4058) — classification is the lead's first pass, UNVERIFIED until the owner's evidence
| capability | existing endpoint / controller | UI today (/v3) | class |
|---|---|---|---|
| Secret presence/age listing | GET /api/v2/admin/secrets → secrets_admin.list_secrets(principal) (presence for all, age/config values operator only) | SecretsManager.tsx, System→Admin | EXISTS_UNVERIFIED |
| Secret write / validate | POST /api/v2/admin/secrets, POST /api/v2/admin/validate-secret (admin_write_guard) | SecretsManager.tsx | EXISTS_UNVERIFIED — must confirm Bitwarden vs .env authority before any parity claim |
| Ops controls (switches) | /api/v2/ops/controls[/…] → lib/ops_controls_api.handle; operator tailnet identity only; service token refused; host changes applied only by scripts/ops/operator_controls_applier.py; config/ops_controls.json | OpsControls.tsx, OpsControlsSudo.tsx | EXISTS_UNVERIFIED (POLICY_NOT_ACTIVE gate to confirm) |
| Accounts / brokers config | GET/POST/PUT /api/v2/admin/accounts, GET /api/v2/admin/brokers, POST /api/v2/admin/broker-account/{api,policy}, /api/v2/broker-accounts/{enums,automation-policy,readiness}, POST broker-accounts/{api-read-toggle,test-connection} | System→Admin | EXISTS_UNVERIFIED — broker-lock adjacent: read-only in Wealth until separately approved |
| Risk config, strategy enablement, ATM state | POST /api/v2/admin/{risk-config,strategy/enablement,atm/set-state}; GET /api/v2/atm/config, /api/v2/admin/strategy-enablement | System→Admin | EXISTS_UNVERIFIED |
| Audit log | GET /api/v2/admin/audit-log | System→Admin | EXISTS_UNVERIFIED |
| Alert ack/resolve, cron retry | POST /api/v2/admin/alert/{ack,resolve}, /api/v2/admin/cron/retry, GET /api/v2/admin/cron-retryable | System→Admin | EXISTS_UNVERIFIED (cron retry conflicts with n8n-only rule — classify) |
| Maintenance actions | POST /api/v2/admin/{rag-backfill,backfill-news-strategy,fix-channel-name-mismatches,flag-orphan-transcripts} | System→Admin | EXISTS_UNVERIFIED — candidates to exclude from Wealth (not configuration) |
| Schwab token health | GET /api/v2/brokers/schwab/token-health (DB freshness + cached live probe, 5-min cache; ?probe=1 forces) | SchwabReauthBanner.tsx, SchwabMonitor.tsx | EXISTS_UNVERIFIED — ?probe=1 is a provider call: Wealth must never send it |
| Schwab reauth | GET /api/v2/brokers/schwab/reauth-url, POST /api/v2/brokers/schwab/exchange-code (step-up per config/cc_auth.yaml; code notes step-up has no TOTP so CC path "can never complete"; sanctioned paths = host token-manager CLI + Telegram redirect paste) | reauth page | PARTIAL (documented in code, 2026-10-21) |
| Schwab 7-day mechanism | scripts/schwab_token_manager.py: REFRESH_TTL_DAYS=7 ("cannot be renewed"; worst case, no roll-forward), ALERT_DAYS={5,6} | banner | EXISTS_UNVERIFIED — scheduler of the day-5/6 alert NOT FOUND in crontab, user timers or n8n by name; owner must trace |
| Finviz cookie expiry | scripts/credential_monitor.py check_finviz / classify_finviz_export_body / is_finviz_cookie_failure_text; health_agent maps finviz_cookie_expired → System→Admin secrets | FinvizCookieBanner.tsx | EXISTS_UNVERIFIED — no registered lane/cron/n8n schedule for credential_monitor found; check_finviz appears to make a provider request (probe policy question) |
| YouTube cookie health | scripts/youtube_cookie_health_check.py, lane youtube-cookie-health-check, crontab 19:45 daily (cron, not n8n) | YoutubeCookieBanner.tsx | EXISTS_UNVERIFIED (exception or n8n migration) |
| System youtube cookies write | POST /api/v2/system/youtube-cookies | — | EXISTS_UNVERIFIED |
| "Envelope files" | no file or config kind named "envelope" found in config/ or scripts/lib (only the word in unrelated registries) | — | UNRESOLVED — owner must establish from real files (likely the .env + config/*.env + ops_controls.json set) and report; no new hierarchy |

Hard rules for this slice: no arbitrary file editor, no shell executor; allowlisted keys only, typed + validated; atomic versioned writes with concurrency token, redacted before/after audit, rollback; current operator auth + step-up/2FA kept; Bitwarden-managed secrets never moved into config; no raw cookie/token/secret in any response, log, doc, test fixture or browser tool; unknown expiry renders UNKNOWN with last observation, never a date or green; no provider probe or resend as a test; no broker/order-lock change; cron/timers retire only after n8n parity + rollback proven.
