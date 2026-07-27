# Stage 4 Plan — Additive /api/v3/active-trader Read Plane

**Run ID:** 20260722-01 · **Start HEAD:** 4bb4b8aa7c74a607a7a058da67c2cf88b2c7753d
**Branch:** feat/active-trader-next · PR #150 (draft)

## Steps
1. Verify continuation (HEAD exact, clean); confirm port 8134 free (it was — used as ruled).
2. Framework ruling applied: the repository's only HTTP framework is **stdlib
   http.server** (portfolio_server.py; no Flask/FastAPI in requirements) — the read API
   uses the same stdlib transport around a transport-independent core (`App.request`)
   that a later stage can mount elsewhere unchanged. No package added.
3. Provision READ-ONLY lab role `trade_ai_lab_ro` (SELECT-only, session-level
   default_transaction_read_only=on, statement_timeout=5s, application_name) via
   committed script; DSN stored as `ACTIVE_TRADER_READ_API_DSN` in Bitwarden
   trade-ai-lab through the lab machine-account token.
4. Implement `read_queries.py` (parameterized SQL, allowlists, opaque cursors,
   deterministic ordering, limits 50/200, lab-guard with no env fallback) and
   `read_api.py` (15 GET routes, envelopes, factory-injected test identity, CORS off /
   single-localhost-origin profile, rate limits 120/30 per minute, response-size and
   warning/source ceilings, metrics, gated dev server: default-disabled, loopback-only,
   SHADOW/SIMULATION-only).
5. Fixture loader (WRITE identity) + SYNTHETIC candidates fixture + machine-readable
   route-contract manifest (`read_api_contract.json`).
6. Tests (26 new) + full all-stage regression (128 total, 3 consecutive stable runs).
7. Localhost smoke on 127.0.0.1:8134 (8 endpoints + POST→405), terminate, prove no
   listener/process/unit remains.
8. Proofs, artifacts, commit, push, PR, Drive + hashes, checkpoint, email, stop.

## Non-goals
No mounting into portfolio_server; no systemd/proxy/firewall change; no /v3 or /v3-next
code; no production DB/broker/credential access; no Moomoo; no mutation of any state via
the API; no 2FA.
