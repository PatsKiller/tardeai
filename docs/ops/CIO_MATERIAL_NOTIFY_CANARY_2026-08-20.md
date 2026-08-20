# CIO material notify canary — 2026-08-20

Authority: **READ_ONLY_ADVISORY**. Phase B canary only.

This receipt documents the **exact flags** to enable a narrow material-situation
Telegram canary on `@tradeai_cio_bot`. It does **not** enable live financial-lane
spam (material-scan publisher / bulk financial Telegram).

## Non-goals

- Do **not** flip Telegram to always-on.
- Do **not** enable the financial material-scan publisher lane.
- Do **not** create new discovery / bulk scanners.
- Residual: **financial lane = `OFF_BY_POLICY`** until an operator explicitly
  enables that separate path.

## Canary enable checklist

All of the following must be true for a canary send. Defaults stay notify-off.

### 1. Host env (dedicated CIO bot)

File: `~/.config/tradeai/cio-telegram.env` (or unit EnvironmentFile).

```bash
CIO_SITUATION_NOTIFY=1
# Alias also accepted (OR): CIO_SITUATIONS_NOTIFY=1
# Both names are OR'd in detector + enrichment; either is enough when truthy.
```

Also required for live CIO delivery (separate from this canary flag):

| Key | Role |
|---|---|
| `TELEGRAM_CIO_BOT_TOKEN` | Dedicated `@tradeai_cio_bot` only |
| `TELEGRAM_CIO_CHAT_IDS` (or `TELEGRAM_CIO_ALLOWLIST`) | Chat allowlist |
| `AUTHORIZE_P2_LIVE_OPERATOR_DELIVERY=1` | Live delivery authorization |
| `ENABLE_TELEGRAM` not off | Transport not killed |
| `CIO_TELEGRAM_INTERDICT` not on | Kill switch clear |

Verify:

```bash
grep -E 'CIO_SITUATION_NOTIFY|CIO_SITUATIONS_NOTIFY|TELEGRAM_CIO_' \
  ~/.config/tradeai/cio-telegram.env
```

### 2. Policy master — `config/cio_llm_policy.yaml`

```yaml
situation_notify_telegram: true   # canary on; default in repo is false
```

Fail-closed: enrichment requires **env OR policy** (`CIO_SITUATION_NOTIFY` /
`CIO_SITUATIONS_NOTIFY` **or** `situation_notify_telegram`). Prefer leaving
policy `false` in git and enabling via env for host canary; if you flip policy
in a checkout, revert after the canary.

### 3. Situations catalog — `config/cio_situations.yaml`

```yaml
enabled: true
shadow: true          # plans + events still advisory
notify: false         # default; env override may set true for canary
dedup_hours: 12
max_plans_per_pass: 5
max_notify_per_pass: 3
```

Env overrides (OR for notify naming):

| Env | Effect |
|---|---|
| `CIO_SITUATIONS_ENABLED` | Detector on/off |
| `CIO_SITUATIONS_SHADOW` | Shadow mode |
| `CIO_SITUATIONS_NOTIFY` **or** `CIO_SITUATION_NOTIFY` | Catalog `notify` flag (OR) |

Default notify remains **false** when both env names are unset/0.

### 4. Notify type allowlist (canary)

Policy key: `notify_situation_types`.

**Canary allowlist (material only):**

- `S1_POSITION_LIFECYCLE`
- `S5_CASH_DEPLOYMENT`
- `S6_CONCENTRATION_OR_DISPOSITION`
- `S8_DEFENSIVE_REGIME`

Plus detector path **`calendar_catalyst_material`** on S1 (not a separate
`notify_situation_types` entry): medium+ within research-gap horizon, or high+
within warm horizon, gates S1 calendar materiality. Low ex-div / distribution
must **not** elevate.

Repo default policy may also list `S2_STOP_GAP`. For this Phase B canary prefer
**excluding S2** (stop-gap noise) so only S1/S5/S6/S8 + calendar material fire.

### 5. Once-per-fingerprint ledger

| Piece | Path / flag |
|---|---|
| Ledger | `data/cio/cio_plan_notify_ledger.json` |
| Policy | `notify_once_per_fingerprint: true` |
| Cooldown | `notify_cooldown_hours: 12` (legacy rows) |
| Min gap | `notify_min_gap_minutes: 5` (fingerprint change) |

Same `plan_id` + same fingerprint → skip re-push. Re-enrich alone must not spam.
Force only via `CIO_SITUATION_NOTIFY_FORCE=1` or `maybe_notify_plan(..., force=True)`.

### 6. Residual — financial lane

| Lane | Canary state |
|---|---|
| Situation plan notify (`maybe_notify_plan` / `@tradeai_cio_bot`) | Operator-gated canary (flags above) |
| Financial / material-scan publisher (`cio_material_scan` bulk Telegram) | **`OFF_BY_POLICY`** — leave off |

Do not enable live financial Telegram spam as part of this canary.

## Naming footgun (fixed in code)

Docs historically mixed:

- `CIO_SITUATION_NOTIFY` — enrichment / host ops (singular)
- `CIO_SITUATIONS_NOTIFY` — situations yaml env override (plural)

**Code now accepts either name (OR)** in detector `load_config`, enrichment
`load_llm_policy` / `maybe_notify_plan`, and wake-trace flag snapshot. Default
remains notify=false when unset.

## Disable / rollback

```bash
# Host
CIO_SITUATION_NOTIFY=0
# or unset both CIO_SITUATION_NOTIFY and CIO_SITUATIONS_NOTIFY

# Policy (if flipped in checkout)
# situation_notify_telegram: false

# Force kill outbound
CIO_TELEGRAM_INTERDICT=1
```

## Related

- `docs/cio/P2B_PLAN_ENRICHMENT.md` — enrich → notify path
- `docs/cio/SITUATIONS.md` — notify guard / ledger
- `docs/cio/CATALYST_AND_HERMES.md` — severity gates / `calendar_catalyst_material`
- `config/cio_llm_policy.yaml` / `config/cio_situations.yaml`
