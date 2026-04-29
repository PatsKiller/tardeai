# Claude Code Prompt — Install Trade AI Agent Router Kit

You are working inside the Trade AI project root:

```bash
~/trade-ai-v12-rebuild/trade-ai-v12-rebuild
```

Install the agent router kit from the staging directory:

```bash
~/agent_router_stage/trade_ai_agent_router_kit
```

## Hard boundaries

- Do not modify existing portfolio pipeline logic.
- Do not touch existing AI prompts except for optional import tests.
- Do not change Telegram/OpenClaw handlers yet.
- Do not commit until all verification steps pass.
- JSON/file writes remain source-of-truth; Postgres audit write must be non-blocking.

## Tasks

1. Copy files:
   - `config/agents.json` → `config/agents.json`
   - `scripts/agent_router.py` → `scripts/agent_router.py`
   - `sql/004_agent_handoffs.sql` → `linux_port_v2/linux/migrations/004_agent_handoffs.sql`
   - docs into `docs/agent_router/`

2. Ensure `scripts/agent_router.py` is executable.

3. Confirm PyYAML is installed in the project venv. If missing, install `pyyaml`.

4. Apply SQL migration using `.env` DB credentials.

5. Run these tests and capture output:

```bash
python3 scripts/agent_router.py --message "Compare DGRO vs SCHD sectors and dividends" --json
python3 scripts/agent_router.py --message "Should DGRO be added and which portfolio should it go in?" --json
python3 scripts/agent_router.py --message "Add DGRO to rebalancing in the app" --json
python3 scripts/agent_router.py --message "LMT is close to my stop, should I honor it?" --json
python3 scripts/agent_router.py --message "What are the Roth conversion tax impacts?" --json
```

6. Test DB write:

```bash
python3 scripts/agent_router.py --message "Should DGRO be added and which portfolio should it go in?" --save --json
```

Then verify:

```sql
SELECT created_at, from_agent, to_agent, intent, confidence, action_type, status
FROM agent_handoffs
ORDER BY created_at DESC
LIMIT 5;
```

## Expected results

- DGRO/SCHD comparison routes to `maria`.
- “Which portfolio” routes to `steph`.
- “Add DGRO to rebalancing” routes to `steph` but status is `pending_approval`.
- Stop alert routes to `risk_agent`.
- Roth/tax routes to `tax_agent`.
- `agent_handoffs` table receives a row when `--save` is used.

## Final report

Produce a short report with:

- Files copied
- SQL migration status
- Test outputs summarized
- Any stale/missing freshness files detected
- Git status

Do not commit until John approves.
