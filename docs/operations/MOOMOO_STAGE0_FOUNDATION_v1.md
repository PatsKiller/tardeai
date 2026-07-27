# Moomoo Stage 0 Foundation v1 — Read-plane only

**Packet:** F (`scripts/operator_packets/packet_f_moomoo_stage0.{sh,py}`)  
**Stage:** 0 — market-intelligence **data plane** foundation  
**Authority:** quotes / history / subscription design only  
**Controlling architecture:**  
`docs/architecture/TRADE_AI_MASTER_AGENTIC_FINANCIAL_SYSTEM_ARCHITECTURE_v3_3.md` §15  
**Related program (out of scope for Stage 0):**  
`docs/prompts/CODEX_ACTIVE_TRADER_MOOMOO_SCALP_IMPLEMENTATION_v1_1.md` (Active Trader stages 1+)

## Hard boundaries

| In plane (Stage 0) | Out of plane (later stages) |
|--------------------|-----------------------------|
| OpenD **data** connectivity design | Live place / modify / cancel orders |
| Quote, K-line history, subscription scaffolding | Active Trader stages 1–13 |
| Config presence + health preflight | OpenD **trade unlock** |
| Fail-closed client if OpenD down | Agent `OPERATIONAL` promotion |
| Optional TCP reachability probe (opt-in) | Enabling agent timers / cron |
| Read-path health registration file only | Production schedule mutation |
| Secret **names** in docs/config examples | Logging secret **values** or DSNs |

**Order path is OUT.** Stage 0 must never import, call, or register broker order routing.
Normalized internal consumers (Watch / Scalp / Pulse) must not talk to OpenD directly
in later stages; Stage 0 only scaffolds the gateway client interface.

```text
  [OpenD data port] --> [MoomooClient adapter] --> [normalized read API / features]
                              |
                         fail-closed if down
                              |
                         NO order / unlock / 2FA path
```

## Host prerequisites (names only — no secret values)

| Prerequisite | Notes |
|--------------|--------|
| Host | Production target documented as `ms01-openclaw` (verify before ops) |
| OpenD binary | Candidate version family documented in architecture (e.g. 10.9.x); pin later |
| OpenD data port | Default example `127.0.0.1:11111` (config only; not a secret) |
| Trade port | **Must remain unused / locked** in Stage 0 |
| Runtime secrets dir | Architecture: `/run/trade-ai-prod/moomoo/` mode `0600` (not written by Packet F) |
| Bitwarden secret **names** (examples) | `MOOMOO_OPEND_LOGIN_ACCOUNT` · `MOOMOO_OPEND_LOGIN_PWD` · `MOOMOO_OPEND_SECURITY_FIRM` — data-only; **never** print values |
| Env config path | `MOOMOO_STAGE0_CONFIG` → YAML path (defaults to example for preflight dry checks) |
| Python | Repo `.venv` preferred for CLI |
| Network policy | CI preflight runs **without** network; live probe requires explicit `--probe-opend` |

### Secret name inventory (values never logged)

```text
MOOMOO_OPEND_LOGIN_ACCOUNT     # data-only login id (SM name)
MOOMOO_OPEND_LOGIN_PWD         # data-only password (SM name)
MOOMOO_OPEND_SECURITY_FIRM     # firm/region code if required (SM name)
MOOMOO_OPEND_HOST              # optional override host (not a secret)
MOOMOO_OPEND_PORT              # optional override port (not a secret)
```

Packet F and `scripts/moomoo` only check whether required **names** are declared in config
or whether corresponding env vars are **set** (presence), never print values.

## Code map

| Path | Role |
|------|------|
| `config/moomoo.stage0.example.yaml` | Example config — no live secrets |
| `scripts/moomoo/config.py` | Load/validate Stage 0 config |
| `scripts/moomoo/client.py` | Thin adapter interface; fail-closed |
| `scripts/moomoo/preflight.py` | Health/preflight CLI |
| `scripts/moomoo/health_registry.py` | Read-path health registration (local JSON) |
| `scripts/operator_packets/packet_f_moomoo_stage0.sh` | Operator packet wrapper |
| `scripts/operator_packets/packet_f_moomoo_stage0.py` | Packet logic |
| `tests/test_moomoo_stage0_preflight.py` | Unit tests — no network in CI |

## Operator packet F

```bash
# Default-disabled
./scripts/operator_packets/packet_f_moomoo_stage0.sh

# Self-check (no network)
./scripts/operator_packets/packet_f_moomoo_stage0.sh --self-check

# Preflight only
./scripts/operator_packets/packet_f_moomoo_stage0.sh <RELEASE_SHA> --preflight \
  --ack APPLY-MOOMOO-STAGE0 \
  [--config config/moomoo.stage0.example.yaml] \
  [--probe-opend]   # optional live TCP; not used in CI

# Execute: still no orders; only safe read-path health registration
./scripts/operator_packets/packet_f_moomoo_stage0.sh <RELEASE_SHA> --execute \
  --ack APPLY-MOOMOO-STAGE0 \
  [--config PATH]
```

| Exit | Meaning |
|------|---------|
| 0 | OK |
| 2 | Usage / gate / ack refusal |
| 3 | Prepare-only (no action) |
| 4 | Preflight fail / runtime error |

## Stage 0 acceptance checklist

- [ ] `config/moomoo.stage0.example.yaml` present; no live secret values committed
- [ ] Preflight passes against example config **without** network (`--probe-opend` off)
- [ ] Client fail-closed when OpenD marked unavailable / probe fails
- [ ] Packet F default-disabled (exit non-zero without `--preflight` / `--execute`)
- [ ] Missing ack refuses; ack must be `APPLY-MOOMOO-STAGE0`
- [ ] `--execute` does **not** place orders, unlock trading, enable timers, or mark agents OPERATIONAL
- [ ] `--execute` may only write read-path health registration under `docs/operations/moomoo_health/` (or test override dir)
- [ ] Unit tests green in CI without network
- [ ] Operator understands order path remains OUT until a later explicit stage

## Explicit out of scope

- Moomoo live trading / place order / trade unlock
- Active Trader stages 1–13 (`feat/active-trader-next` program)
- Enabling agent timers or Packet D/E behavior changes
- Production `trade_ai` writes from this packet
- Dual OpenD production session ownership (architecture: one gateway owner later)

## Related docs

- Promotion gate (agents, not Moomoo): `docs/operations/PROMOTION_GATE_v1.md`
- Architecture §15 Moomoo market-intelligence plane (v3.3)
- Historical reference: `MOOMOO_REFERENCE_ARCHITECTURE_v2_2.md` (superseded; evidence only)
- Active Trader program (later): `docs/prompts/CODEX_ACTIVE_TRADER_MOOMOO_SCALP_IMPLEMENTATION_v1_1.md`
