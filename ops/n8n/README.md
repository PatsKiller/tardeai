# n8n (production) — compose and cutover

This folder is the home of the production n8n (n8n program package 0.1a, 2026-11-06). It replaces
`~/m8m-bakeoff-lab/docker-compose.n8n.yml`, the 2026-10 bake-off folder n8n was started from.

| What | Where |
|---|---|
| Compose | `ops/n8n/docker-compose.n8n.yml` (project `m8m-n8n`; n8n 2.43.0, Postgres 16.15) |
| Secrets | `~/.config/tradeai/n8n/n8n.env`, mode 0600, directory 0700: `N8N_PG_PASSWORD`, `N8N_ENCRYPTION_KEY`, plus the non-secret `N8N_RELAY_GATEWAY` (`n8n.env.example`) |
| Volumes | `m8m-n8n_n8n-pg` (database), `m8m-n8n_n8n-data` (encryption key, settings) |
| Network | `m8m-n8n_lab`; the run relay is reached as `tradeai-relay:18092` (the lab network gateway, `N8N_RELAY_GATEWAY` in the env file) |
| UI | http://127.0.0.1:5678 (localhost only) |
| Cutover tool | `scripts/ops/n8n_compose_cutover.py` |

The compose file is the bake-off file byte for byte except the header comment and the `:?` guards on the two
secret references. **Do not rename the project**: the name decides which volumes and network compose uses; a new
name starts an empty n8n.

This n8n has its own Postgres. It is not given a production database URL, the Docker socket or a broker credential.
Command, SSH, FTP, email, messaging, database, file and agent nodes are excluded (`NODES_EXCLUDE`, a JSON array).
Workflows are not edited in the n8n screen; see AGENTS.md §23.

## Cutover (an operator go-ahead; outside market hours)

1. Dry run, read-only. It must print `"ok": true`:

       .venv/bin/python scripts/ops/n8n_compose_cutover.py

   It proves the repo compose resolves to the same compose config hash as each running container (so the services
   do not change) and records the active-workflow count.
2. Write the secrets file (values are copied, never printed):

       .venv/bin/python scripts/ops/n8n_compose_cutover.py --prepare-env

   Then run step 1 again.
3. Restart n8n from this folder:

       .venv/bin/python scripts/ops/n8n_compose_cutover.py --apply

   It recreates only the `n8n` container (same image, volumes and network), waits for `/healthz`, and fails unless
   the active-workflow count is unchanged. The receipt lands in `~/.cache/tradeai/n8n-cutover-<UTC>.json`.
4. Archive the old folder (never delete it): `mv ~/m8m-bakeoff-lab ~/m8m-bakeoff-lab-archived`. Its
   `docker-compose.yml` is the closed Kestra bake-off; it was never started and stays archived with the folder.

## Rollback

Start from the kept old compose; nothing in the volumes changed:

    docker compose -p m8m-n8n -f ~/m8m-bakeoff-lab-archived/docker-compose.n8n.yml \
      --env-file ~/m8m-bakeoff-lab-archived/.env up -d --no-deps --force-recreate n8n

## Everyday commands

    C="docker compose -p m8m-n8n -f ops/n8n/docker-compose.n8n.yml --env-file $HOME/.config/tradeai/n8n/n8n.env"
    $C ps            # state
    $C logs --tail 100 n8n
    $C stop          # stop both containers (volumes kept)
