# Stage 2 Plan — Broker Account Discovery and Capability Registry

**Run ID:** 20260722-01 · **Start HEAD:** 42f0c2cbccfed016ae3295a9abd7db995f6f688c
**Branch:** feat/active-trader-next · PR #150 (draft)
**Authorization:** architecture-owner Stage 2 launcher (2026-07-22): brokers alpaca/moomoo/schwab
in scope; SnapTrade/Fidelity/Tastytrade excluded from the v1 execution plane; read-only probes
through existing approved read paths; lab-token-only Bitwarden ops; lab-DB-only persistence.

## Steps
1. Verify continuation point (HEAD 42f0c2cb, clean worktree).
2. Bitwarden lab-isolation gate with `~/.openclaw/credentials/bws_lab_token` (mode 0600):
   lab read/write + temp-sentinel lifecycle + production enumeration/read/write denial;
   org-wide token unused for the entire stage.
3. Implement adapter-neutral discovery (`scripts/active_trader/discovery.py`): typed
   DiscoveredAccount/BrokerDiscoveryResult, capability factory enforcing per-source expiry
   rules, identifier masking, Moomoo NOT_INSTALLED placeholder, registry projection with
   9 discrepancy kinds, lab-guarded idempotent persistence.
4. Broker implementations: Alpaca read-only discovery over the existing credential-slot
   convention (GET only); Schwab read-only discovery over the existing managed-token
   `schwab_transport` (no refresh race; write fences untouched); Moomoo typed placeholder.
5. Safe probe runner (`scripts/active_trader/probe_brokers.py`): read-only method plan,
   --dry-run, broker allowlist, masked output, JSON+Markdown, lab-only persistence,
   nonzero on safety violation, Moomoo absence never fails the fleet.
6. Tests: mocks/fixtures (capability logic, per-broker fixtures, discrepancies, runner
   safety) + lab-DB persistence tests + Stage 1 regression.
7. Live bounded read-only probe (method plan printed first) → evidence + lab rows.
8. Regression/safety proofs; artifacts; commit; push; PR update; Drive sync + hash
   verification; checkpoint; operator email; stop before Stage 3.

## Non-goals
No rejection-classifier runtime (Stage 3), no read API (Stage 4), no Moomoo install
(Stage 5), no UI, no write capability probing of any kind, no production writes.
