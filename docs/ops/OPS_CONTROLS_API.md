# Ops → Controls: Command Center API contract

```
Status:      DRAFT (branch feat/ops-controls-20261022; built INERT — nothing armed, no migration applied)
as_of:       2026-10-22T18:00:00-04:00
Measured at: not measured (shape contract; base origin/main b9804fa57)
Owner:       platform
Authority:   OPERATOR_ONLY · MBI_BEHAVIOR = 0
Policy:      AGENTS.md 19.0.0 §27.2–§27.3 (PROPOSED). Every mutating route refuses POLICY_NOT_ACTIVE until 19.0.0 is ACTIVE.
Backend:     scripts/lib/ops_controls_api.py (routes), scripts/lib/ops_controls_core.py (kinds, preview, phrases),
             scripts/lib/ops_controls_store.py (Postgres + test store), scripts/lib/ops_controls_auth.py (WebAuthn, TOTP,
             step-up), scripts/ops/operator_controls_applier.py (the one host applier)
Frontend:    apps/command-center-v3/src/pages/OpsControls.tsx, apps/command-center-v3/src/lib/opsControls.ts
```

The Command Center **Ops → Controls** page (`/v3/system/ops-controls`) builds against this contract. The architecture,
the threat model and the operator activation steps are in `docs/ops/OPS_CONTROLS.md`.

## 1. Rules every consumer must follow

1. **Agents never call these routes.** The server derives the actor from the authenticated request: only a tailnet
   operator identity on the `serve_proxy` listener (`tailnet:<login>` in `config/cc_auth.yaml` `allowed_logins`) is
   accepted. The service token (`service-token` principal: cron, agents, n8n, scripts) is refused with
   `AGENT_CALLER_REFUSED` on every route, GET included. There is no agent token.
2. **CSRF and origin** are enforced by the handler itself (`cc_auth.command_csrf_check`), whatever `report_only` says:
   every POST needs an allowlisted `Origin` or `Sec-Fetch-Site: same-origin` and `Content-Type: application/json`.
3. **Inert until 19.0.0 is ACTIVE.** Every POST answers `409 {"error": "POLICY_NOT_ACTIVE"}` while the `AGENTS.md`
   version-history row for 19.0.0 is not `ACTIVE` (read at request time, fail closed). `GET /state` still answers and
   shows `policy.state`.
4. **Missing data is never zero and never green.** A section that could not be read has `"state": "UNAVAILABLE"`
   and a `reason`; render it as UNAVAILABLE.
5. **Safe direction is one click; risky direction is a passkey and a typed phrase.** The server decides the
   direction of every change kind (`kinds[].direction`); the client never chooses it.
6. **Telegram is notification only.** No Telegram button confirms anything.

Every response is JSON. Errors: `{"ok": false, "error": "<CODE>", "detail": "<text>"}` with an HTTP status
(400 bad input, 403 caller/CSRF/factor refused, 404 unknown request, 409 state conflict or policy, 503 store or
dependency unavailable).

## 2. Routes

All under `/api/v2/ops/controls`.

| Method | Path | Purpose |
|---|---|---|
| GET | `/state` | Everything the page renders (section 3). |
| POST | `/requests` | Create a change request: validate, preview (dry run), phrase. Body `{kind, params, idempotency_key, one_click?}`. With `one_click: true` and a **safe** kind the request is also approved in the same call. |
| GET | `/requests/{id}` | One request (section 4); the page polls it after approval until a terminal status. |
| POST | `/requests/{id}/approve` | Safe kind: body `{}`. Risky kind: body `{step_up_token}`. Marks the request `APPROVED` (HMAC-signed); the host applier applies it within 120 s. |
| POST | `/requests/{id}/step-up/options` | WebAuthn `PublicKeyCredentialRequestOptions` (JSON, base64url) with a single-use challenge bound to this request, `userVerification: "required"`, every active passkey allowed. |
| POST | `/requests/{id}/step-up/verify` | Body `{credential, phrase}`. `credential` is the `PublicKeyCredential` JSON (base64url fields). Verifies the typed phrase and the assertion; returns `{step_up_token, expires_at}` (2 minutes, single use, this request only). |
| POST | `/requests/{id}/step-up/totp` | Body `{code, phrase}`. Recovery only: accepted only for `passkey.register` when **no** active passkey exists. Returns `{step_up_token, expires_at}`. |
| POST | `/requests/{id}/cancel` | Cancel a request that is not yet applying. |
| POST | `/requests/{id}/undo` | Body `{idempotency_key}`. Creates the inverse request (its own direction and factors) from the applied request's backup; returns it like `POST /requests`. |
| POST | `/passkeys/register/options` | Body `{request_id}`; the `passkey.register` request must be `APPROVED`. Returns `PublicKeyCredentialCreationOptions` JSON (`residentKey: preferred`, `userVerification: required`, existing passkeys excluded). |
| POST | `/passkeys/register/verify` | Body `{request_id, credential}`. Stores the passkey under the request's `name`; the request becomes `APPLIED`. |

Passkey revocation is the change kind `passkey.revoke` (risky).

### Flows

- **Safe (one click):** `POST /requests {kind, params, idempotency_key, one_click: true}` → status `APPROVED` → poll
  `GET /requests/{id}` until `APPLIED` / `FAILED` / `REFUSED` / `EXPIRED`.
- **Risky (three steps):** (1) `POST /requests` → show `preview` and `phrase`; (2) `POST .../step-up/options` →
  `navigator.credentials.get({publicKey})` → `POST .../step-up/verify {credential, phrase}` → `step_up_token`;
  (3) `POST .../approve {step_up_token}` → poll until terminal.
- **Add a passkey:** `POST /requests {kind: "passkey.register", params: {name}}` → step-up with an existing passkey
  (or TOTP when none remains) → `POST .../approve {step_up_token}` → `POST /passkeys/register/options {request_id}` →
  `navigator.credentials.create({publicKey})` → `POST /passkeys/register/verify {request_id, credential}`.

## 3. `GET /state`

```jsonc
{
  "ok": true,
  "schema": "OpsControlsState@v1",
  "as_of": "2026-10-22T22:00:00Z",
  "operator": "tailnet:john@…",
  "policy":   {"state": "ACTIVE" | "NOT_ACTIVE" | "UNREADABLE", "required": "19.0.0", "detail": "…"},
  "store":    {"state": "OK" | "NOT_MIGRATED" | "UNAVAILABLE", "missing_tables": ["…"], "reason": "…"},
  "applier":  {"state": "OK" | "STALE" | "ABSENT", "heartbeat_at": "…" | null, "age_s": 12 | null, "reason": "…"},
  "factors":  {"webauthn_library": "available" | "missing", "hmac_key": "present" | "missing",
               "totp": "enrolled" | "not_enrolled", "passkeys_active": 2},
  "kinds": [{"kind": "crontab.pause", "label": "Pause a cron line", "direction": "safe" | "risky",
             "supported": true, "reason": null, "executor": "applier" | "cc", "tab": "jobs"}],
  "jobs": {"state": "OK" | "UNAVAILABLE", "reason": null, "as_of": "…",
           "rows": [{"lane_id": "…", "registry_state": "ACTIVE", "scheduler_kind": "cron",
                     "cron_state": "ACTIVE" | "PAUSED" | "ABSENT" | "AMBIGUOUS",
                     "schedule": "7,22 9-16 * * 1-5", "line_sha256": "…" | null, "display": "redacted line" | null,
                     "paused_on": "2026-10-14" | null, "paused_note": "…" | null,
                     "broker_class": false, "broker_tokens": [], "note": "…",
                     "dispatch_mode": "live" | "dry_run" | "off" | null, "registry_since": "2026-10-11" | null,
                     "registry_reason": "…" | null, "match_counts": {"active": 1, "paused": 0}}],
           "unmatched_active_lines": 3},
  "n8n": {"state": "OK" | "UNAVAILABLE", "reason": null, "live_list_path": "~/.config/tradeai/n8n-live-lanes.env",
          "live_lanes": ["…"],
          "rows": [{"lane_id": "…", "stage": "shadow", "mode": "dry_run", "on_live_list": false, "workflow": "…"}]},
  "settings": {"state": "OK" | "NOT_MIGRATED" | "UNAVAILABLE", "reason": null,
               "rows": [{"key": "…", "label": "…", "type": "bool" | "int" | "float" | "string" | "enum",
                         "default": 0.4, "current": 0.43 | null, "overridden": true, "min": 0, "max": 1,
                         "choices": null, "wired": false, "consumer": "…", "updated_at": "…", "updated_by": "…"}],
               "history": [{"key": "…", "old_value": 0.4, "new_value": 0.43, "actor": "…", "at": "…", "request_id": "…"}]},
  "grants": {"state": "OK" | "UNAVAILABLE", "reason": null, "tiers": ["db-write", "…"],
             "active": [{"tier": "release-write", "uses": "3", "minutes_left": 230, "grant_id8": "4af07346", "reason": "…"}]},
  "data_approvals": {"state": "OK" | "UNAVAILABLE", "schema": "DataDomainReadiness@v1",
                     "scan": {"state": "DONE" | "RUNNING" | "FAILED", "as_of": "…", "age_s": 12, "duration_s": 24.2,
                              "refreshing": false, "error": null, "refresh_error": null},
                     "ttl_s": 60,
                     "summary": {"approved": 0, "ready": 16, "not_ready": 1, "unchecked": 0, "findings": 31,
                                 "operator_approved_pending_pr": ["cio_prospect"]},
                     "criteria": [{"id": "row_valid", "label": "…", "source": "scripts/lib/data_dictionary.py validate()"}],
                     "rows": [{"domain": "cio_prospect", "title": "…", "status": "proposed" | "approved",
                               "store": "table:cio_prospect", "writer": "…" | null, "writer_status": "SINGLE" | "UNCONSOLIDATED",
                               "writer_target": "…", "projection": "…", "readers_declared": ["Home"],
                               "approved_reader_batches": [], "reader_gate": null, "derived_copies": [],
                               "approval": null, "operator_note": {"approval_given": true, "decision": "…"} | null,
                               "freshness": {"state": "MEASURED" | "EMPTY" | "MISSING" | "NO_SIGNAL" | "UNAVAILABLE",
                                             "newest_at": "…", "age_h": 8.6, "stale_after_hours": 24, "stale": false},
                               "verdict": "APPROVED" | "READY_TO_APPROVE" | "NOT_READY" | null,
                               "missing": ["…"], "criteria": [{"id": "…", "ok": true, "gaps": []}],
                               "approval_effects": ["…"],
                               "live": {"writer_files": {"count": 1, "files": ["…"], "truncated": false},
                                        "surface_reads": {}, "store_readers": {"count": 0, "files": []},
                                        "findings": [{"check": "NON_AUTHORITATIVE_READ", "copy": "…", "ceiling": 0, "now": 1}],
                                        "warn_count": 1} | null}],
                     "note": "Read-only. A grant is the operator's decision (AGENTS.md §17, §26.6) …"},
  "release_train": {"state": "OK" | "UNAVAILABLE", "mode": "UNARMED", "epoch": 3, "latch": "ABSENT"},
  "passkeys": [{"credential_id8": "a1b2c3d4", "name": "Pixel 11", "created_at": "…", "last_used_at": "…",
                "revoked_at": null}],
  "audit": {"state": "OK" | "NOT_MIGRATED" | "UNAVAILABLE",
            "rows": [{"seq": 41, "at": "…", "actor": "…", "action": "request.applied", "kind": "crontab.pause",
                      "request_id": "…", "outcome": "ok", "detail": {}, "undo_available": true}]},
  "requests": [/* the 20 most recent request objects (section 4) */]
}
```

## 4. Request object

```jsonc
{
  "request_id": "opsreq_…",
  "kind": "n8n_live_list.add",
  "label": "Add a lane to the n8n live list",
  "direction": "risky",
  "executor": "applier",
  "params": {"lane_id": "pr-hygiene-audit"},
  "phrase": "ADD LIVE pr-hygiene-audit 2026-10-22",      // risky kinds only; type it exactly
  "preview": {"summary": "…", "before": "…", "after": "…", "diff": ["- …", "+ …"], "warnings": ["…"]},
  "expected_state_digest": "sha256…",                       // the applier refuses if the target changed since
  "status": "PREVIEWED" | "AWAITING_STEP_UP" | "STEP_UP_VERIFIED" | "APPROVED" | "APPLYING" | "APPLIED"
          | "FAILED" | "REFUSED" | "EXPIRED" | "CANCELLED",
  "status_at": "…", "created_at": "…", "approved_at": "…" | null, "applied_at": "…" | null,
  "actor": "tailnet:…",
  "result": {"outcome": "…", "verify": {…}, "backup_ref": "…", "detail": "…"} | null,
  "undo_of": "opsreq_…" | null, "undone_by": "opsreq_…" | null,
  "undo": {"available": true, "kind": "n8n_live_list.remove", "direction": "risky", "reason": null}
}
```

## 5. Change kinds

| Kind | Tab | Direction | Executor | Supported |
|---|---|---|---|---|
| `release_train.stop` | jobs | safe | cc | yes — `release_train_stop.request_stop` (the writer the existing STOP button uses) |
| `release_train.pause` | jobs | safe | cc | yes — `ReleaseControl.request_pause` (refused while the train is UNARMED) |
| `release_train.resume` / `.arm` / `.change_scope` / `.revoke` | jobs | risky | cc | **NOT_SUPPORTED**: `release_control.OPERATOR_KINDS` is pinned to `{host_cli, telegram}` by the 17.0.0 policy test (D3); a passkey proof kind is its own PR after 19.0.0 is ACTIVE. Host CLI: `scripts/release_control_cli.py`. |
| `kill_switch.engage` | jobs | safe | applier | yes — the existing operator CLI `scripts/brokers/kill_switches.py --enable global --reason …` (called, never modified) |
| `kill_switch.clear` | jobs | risky | applier | **NOT_SUPPORTED**: the clear path is broker-execution code; calling or testing it needs an `execution-engineering` grant (§0 rule 2, §27.4). Host terminal. |
| `crontab.pause` / `crontab.resume` | jobs | risky | applier | yes — exact-text line match by sha256; `# PAUSED <date> ops-controls:<request> <line>` |
| `n8n_live_list.add` / `.remove` | n8n | risky | applier | yes — `~/.config/tradeai/n8n-live-lanes.env`, relay and gateway restarted |
| `setting.set` / `setting.unset` | flags | risky | applier | yes — `operator_settings` + history |
| `grant.issue` / `grant.revoke` | grants | risky | applier | yes — `bin/guard grant … --yes` / `bin/guard revoke … --grant-id` |
| `passkey.register` / `passkey.revoke` | (passkeys panel) | risky | cc | yes |

Parameter notes (aligned with the page): `kill_switch.engage` takes `{reason?}` (other keys ignored; level is
`config/ops_controls.json` `kill_switch.level`); `grant.issue` takes `{tier, for: "30m"|"2h"|"7200s", uses: 1..50,
reason}` (unlimited uses stay host-terminal only); `grant.revoke` takes `{tier, grant_id}` or `{tier, grant_id8}`;
`passkey.revoke` takes `{credential_id}` or an unambiguous `{credential_id8}`. The kill-switch state is not part of
`GET /state` (its read model belongs to broker-execution code); the page says so.
