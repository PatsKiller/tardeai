# n8n run relay: allowlisted secrets env, strict fail-closed (operator packet, 2026-10-21)

```
Status:      DRAFT (operator packet; nothing in it has run on the host)
as_of:       2026-10-21
Measured at: origin/main 7faa8cddf + branch integ/cleanup-batch-d-20261021; host env files measured by NAME only
Authority:   operator 2026-10-21, "approve all your recommendations" (PR triage row #1599). Installing a user unit
             is §17 operator-only: a config-write grant naming tradeai-n8n-run-relay.service.
Source:      PR #1599 (B2-D2, due diligence 2026-10-09)
```

## What this changes

`tradeai-n8n-run-relay.service` loads the full secrets file `%t/tradeai/env` today. Measured 2026-10-21 by name
only, that file holds 123 names: 22 broker, 31 provider and 10 other credential names, beyond the relay's own. The
relay needs three of them: `TRADEAI_N8N_RELAY_BEARER`, `TRADEAI_N8N_RELAY_BEARER_PREVIOUS` (the rotation overlap)
and `TRADEAI_N8N_GATEWAY_HMAC_KEY_N8N`. The two required names are present in the file today. The companion files
`~/.config/tradeai/n8n-relay.env` and `~/.config/tradeai/n8n-live-lanes.env` each hold one name,
`TRADEAI_N8N_RELAY_LIVE_LANES`.

This change has two layers:

1. **Code (in the release, no host change).** `scripts/n8n_run_relay.py main()` calls
   `scripts/lib/n8n_relay_env.enforce()` before it binds. Without `RELAY_STRICT_ENV` (the unit today), it scrubs
   `os.environ` to the allowlist. The relay never spawns, so nothing inherits the dropped names. The scrub cannot
   rewrite `/proc/<pid>/environ`; only layer 2 cleans that.
2. **Unit (this packet, operator step).** `tradeai-n8n-run-relay.service` in this directory is the committed
   `config/systemd/user/tradeai-n8n-run-relay.service` with four changes. A test checks that nothing else differs
   (`test_packet_unit_differs_from_the_committed_unit_only_in_the_env_lines`).
   - `EnvironmentFile=-%t/tradeai/n8n-relay-secrets.env` replaces `EnvironmentFile=-%t/tradeai/env`.
   - `ExecStartPre=` runs `scripts/render_n8n_relay_env.py --source %t/tradeai/env --out %t/tradeai/n8n-relay-secrets.env`
     from CURRENT. The output is mode 0600 on tmpfs and holds only the three names. It refuses (exit 2, nothing
     written) when a required name is missing. Because a failed ExecStartPre stops the start, the relay is down
     rather than running on the wrong env.
   - `Environment=RELAY_STRICT_ENV=1`: any broker, provider or credential name outside the allowlist exits 3. It
     prints names only.
   - `UnsetEnvironment=SSH_AUTH_SOCK GPG_AGENT_INFO DBUS_SESSION_BUS_ADDRESS`.

## Order (do not reorder)

| # | Step | Who / authority | Proof before the next step |
|---|---|---|---|
| 0 | Release containing this commit is CURRENT (`scripts/render_n8n_relay_env.py` exists under `~/trade-ai-releases/portfolio-server/CURRENT/scripts/`) | release grant | `test -f` on that path |
| 1 | Dry run (below) | operator, read-only | render `ok: true` with `names` listing the two required names; strict check `ok: true`, `forbidden: {}` |
| 2 | Install the packet unit and restart | operator, config-write grant naming the unit | step 3 |
| 3 | Verify | operator | `/proc/<MainPID>/environ` has no broker or provider name (names only); a new `{"op":"due"}` line in `persistent-state/data/runtime/n8n_relay/relay_log.jsonl` after the restart |

### 1 · Dry run (no unit change; writes only a scratch file under `$XDG_RUNTIME_DIR`)

```bash
CUR=$HOME/trade-ai-releases/portfolio-server/CURRENT
PY=$HOME/trade-ai-v12-rebuild/trade-ai-v12-rebuild/.venv/bin/python
"$PY" "$CUR/scripts/render_n8n_relay_env.py" --source "$XDG_RUNTIME_DIR/tradeai/env" \
      --out "$XDG_RUNTIME_DIR/tradeai/n8n-relay-secrets.env.dryrun"        # prints names only
# Strict check with the user manager's own environment plus the rendered file (names only on stdout):
systemd-run --user --wait --pipe --quiet \
  -p EnvironmentFile=$XDG_RUNTIME_DIR/tradeai/n8n-relay-secrets.env.dryrun \
  -p EnvironmentFile=-$HOME/.config/tradeai/n8n-relay.env \
  -p EnvironmentFile=-$HOME/.config/tradeai/n8n-live-lanes.env \
  -p Environment=RELAY_STRICT_ENV=1 \
  -p "UnsetEnvironment=SSH_AUTH_SOCK GPG_AGENT_INFO DBUS_SESSION_BUS_ADDRESS" \
  -p WorkingDirectory=$CUR \
  "$PY" -c 'import json,os; from scripts.lib.n8n_relay_env import enforce; r=enforce(os.environ); print(json.dumps({"ok":r["ok"],"forbidden":r["forbidden"]}))'
rm -f "$XDG_RUNTIME_DIR/tradeai/n8n-relay-secrets.env.dryrun"
```

If the strict check shows `ok: false`, stop. The names it lists come from the user manager's environment (check
them with `systemctl --user show-environment | cut -d= -f1`, names only). Remove them there, or leave the relay on
the scrub-only layer.

### 2 · Install (config-write grant naming `tradeai-n8n-run-relay.service`)

```bash
cp -a ~/.config/systemd/user/tradeai-n8n-run-relay.service \
      ~/.config/systemd/user/tradeai-n8n-run-relay.service.pre-b2d2-20261021     # archive, never delete
install -m 0644 "$CUR/docs/ops/packets/n8n-relay-env-allowlist-20261021/tradeai-n8n-run-relay.service" \
      ~/.config/systemd/user/tradeai-n8n-run-relay.service
systemctl --user daemon-reload
systemctl --user restart tradeai-n8n-run-relay.service
```

### 3 · Verify (names only)

```bash
PID=$(systemctl --user show -p MainPID --value tradeai-n8n-run-relay.service)
tr '\0' '\n' < /proc/$PID/environ | cut -d= -f1 | sort      # expect the three relay names + config/runtime names
ls -l "$XDG_RUNTIME_DIR/tradeai/n8n-relay-secrets.env"      # -rw------- 
```

Once the packet is installed, a reviewed PR updates `config/systemd/user/tradeai-n8n-run-relay.service` to match.
That PR also points `UNIT` in `tests/test_n8n_relay_env_allowlist_20261009.py` back at it.

## Rollback

Reinstall the archived `tradeai-n8n-run-relay.service.pre-b2d2-20261021` (or the committed
`config/systemd/user/tradeai-n8n-run-relay.service`), then run `daemon-reload` and `restart`. Layer 1 (scrub) stays
in the code. It needs no rollback because it only removes names the relay never reads.
