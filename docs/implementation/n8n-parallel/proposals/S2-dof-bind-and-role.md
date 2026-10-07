# Proposal S2 — DOF app exposure and database role

Status: PROPOSED 2026-10-07. Operator decisions: DOF repo change, DB role grant, policy merge. Nothing applied.

Evidence (09-live-audit §6 S2): `nyc-dof-auction/dof_server.py:1091` runs `app.run(host="0.0.0.0", port=PORT)`
with no auth hook; its `.env` DSN uses the production `trade_ai` role; two POST routes write the DB;
`tailscale serve` proxies `:8443 → localhost:7776`; branch `wt/n8n-dof-policy-20261007` holds two docs.

Steps, each reversible:
1. DOF repo: `host = os.environ.get("DOF_BIND", "0.0.0.0")` and `dof-dashboard.service` drop-in
   `Environment=DOF_BIND=127.0.0.1` (operator flips). The tailscale path keeps working.
2. Postgres (DB grant): `CREATE ROLE dof_reader LOGIN PASSWORD '<SM>' NOSUPERUSER; GRANT CONNECT ON DATABASE trade_ai TO dof_reader;
   GRANT USAGE ON SCHEMA public TO dof_reader; GRANT SELECT ON ALL TABLES IN SCHEMA public TO dof_reader;`
   restricted further to `dof_*` if the owner prefers (`REVOKE` then per-table `GRANT`). Password rendered
   from Bitwarden SM. Nothing in n8n until decision 3 is taken.
3. Merge `wt/n8n-dof-policy-20261007` so the agent policy and least-privilege doc are binding.
4. Only then: the n8n DOF monitor may use a read-only Postgres credential (one, scoped, rotated),
   and DOF queue views enter the coordination projection.
