# Automation Trust Center -- Apply Plan

Status:      HISTORICAL
as_of:       2026-05-25T14:00:12-04:00
Measured at: efcc51365 / not measured

## Prerequisites

1. Phase 2a shared primitives must be created first:
   - `apps/command-center-v2/src/components/StatusBadge.tsx`
   - `apps/command-center-v2/src/components/SeverityBadge.tsx`
   - `apps/command-center-v2/src/components/AgentChip.tsx`
   - `apps/command-center-v2/src/components/StateCard.tsx`
   - `apps/command-center-v2/src/components/ActionButton.tsx`

2. Verify the build is green before starting:
   ```bash
   cd apps/command-center-v2 && npm run build
   ```

---

## Apply Order

Apply smallest/safest first, largest/riskiest last.

### Step 1: OpsHub.tsx (smallest, lowest risk)

```bash
# Backup
cp apps/command-center-v2/src/pages/OpsHub.tsx apps/command-center-v2/src/pages/OpsHub.tsx.bak

# Apply replacement (copy tsx from OpsHub.tsx.REPLACEMENT.md)
# Verify SHA256 of original matches before overwriting:
sha256sum apps/command-center-v2/src/pages/OpsHub.tsx
# Expected: 662fa85e8ad4a39b557eb2df591d3ab08df1a600a5f83b28f4cb67d637b776ad

# Build check
cd apps/command-center-v2 && npm run build
```

### Step 2: PipelineHub.tsx (small, low risk)

```bash
# Backup
cp apps/command-center-v2/src/pages/PipelineHub.tsx apps/command-center-v2/src/pages/PipelineHub.tsx.bak

# Verify SHA256:
sha256sum apps/command-center-v2/src/pages/PipelineHub.tsx
# Expected: 58a46df8622af09ccd98ff1e794704c13cf38a2dc5b51cc78078268cd6bdba55

# Apply replacement
# Build check
cd apps/command-center-v2 && npm run build
```

### Step 3: SystemHealth.tsx (medium, moderate risk)

```bash
# Backup
cp apps/command-center-v2/src/pages/SystemHealth.tsx apps/command-center-v2/src/pages/SystemHealth.tsx.bak

# Verify SHA256:
sha256sum apps/command-center-v2/src/pages/SystemHealth.tsx
# Expected: f2ed031181c2d2dbbfe04b8f9b94f07d7505230c9645ca91e9bb5f8636a8acd7

# Apply replacement
# Build check
cd apps/command-center-v2 && npm run build
```

### Step 4: AgentPipeline.tsx (largest, highest risk)

```bash
# Backup
cp apps/command-center-v2/src/pages/AgentPipeline.tsx apps/command-center-v2/src/pages/AgentPipeline.tsx.bak

# Verify SHA256:
sha256sum apps/command-center-v2/src/pages/AgentPipeline.tsx
# Expected: 184f18a89be83638d15287ab586a94e104ed79b75239c27058d4887e58714aa1

# Apply replacement
# Build check
cd apps/command-center-v2 && npm run build
```

---

## Build Command

```bash
cd apps/command-center-v2 && npm run build
```

Run after each individual file replacement. If the build fails, restore from `.bak` and investigate before continuing.

---

## Smoke Test Routes

After build succeeds and the dev server is running, manually verify these routes:

| Route | Page | What to Check |
|-------|------|---------------|
| `/v2/ops` | OpsHub | Title says "Automation Trust Center", tabs show correct labels, all 4 tabs load |
| `/v2/pipeline` | PipelineHub | Title says "Pipeline Health", tabs show "Stage Health" / "Stage Controller" |
| `/v2/system-health` | SystemHealth | Title says "System Health & Services", ActionButtons render, StatusBadge in data products |
| `/v2/agent-pipeline` | AgentPipeline | Title says "Agent Pipeline & Queue", StateCards show counts, AgentChips render, all tables populated |

### Detailed Checks per Route

**`/v2/ops` (OpsHub)**
- [ ] Title reads "Automation Trust Center"
- [ ] Subtitle reads "Automation health, stale data, cron confidence, and queue status"
- [ ] Tab 1 label: "Trust Overview" -- loads SystemHub
- [ ] Tab 2 label: "Cron & Jobs" -- loads Ops
- [ ] Tab 3 label: "LLM Queue" -- loads LLMQueue
- [ ] Tab 4 label: "Orchestration" -- loads Orchestration

**`/v2/pipeline` (PipelineHub)**
- [ ] Title reads "Pipeline Health"
- [ ] Subtitle reads "Stage health, run history, and freshness"
- [ ] Tab 1 label: "Stage Health" -- loads PipelineHealthMaster
- [ ] Tab 2 label: "Stage Controller" -- loads PipelineController

**`/v2/system-health` (SystemHealth)**
- [ ] Title reads "System Health & Services"
- [ ] "Orchestration" and "Refresh" buttons render as ActionButton (not raw `<button>`)
- [ ] LLM Router tiles show correct values
- [ ] Data Product Health uses StatusBadge pills
- [ ] Weekend stale items show "Weekend Paused" with blue/info color
- [ ] Empty state shows when data_freshness not loaded
- [ ] System info footer still present

**`/v2/agent-pipeline` (AgentPipeline)**
- [ ] Title reads "Agent Pipeline & Queue"
- [ ] StateCard tiles show Queued/Processing/Completed/Failed with correct colors
- [ ] Agent names render as AgentChip (not plain text)
- [ ] Job status cells use StatusBadge
- [ ] Filter chips use ActionButton with active state
- [ ] Failed jobs section: SeverityBadge renders BUDGET/TIMEOUT/ERROR
- [ ] Results table: all columns render (Symbol, Agent, Rec, Conf, Model, RAG, Peers, Age)
- [ ] Handoffs: AgentChip for from/to agents, arrow between them
- [ ] Debates: empty state shows info tooltip
- [ ] Events: StatusBadge for status column
- [ ] Proposals: StatusBadge for action (BUY/SELL)

---

## Playwright Expectations

If running the Playwright visual crawler after applying:

1. **Route count**: No change -- same routes exist, just content differs
2. **Error count target**: 0 errors on all 4 routes
3. **Visual diff**: Titles, tab labels, and badge styling will differ from baseline
4. **New component rendering**: StatusBadge, AgentChip, StateCard, ActionButton should all render without console errors
5. **No missing imports**: Build must pass before Playwright runs

Expected Playwright routes to capture:
```
/v2/ops (tabs: hub, ops, queue, orchestration)
/v2/pipeline (tabs: health, controller)
/v2/system-health
/v2/agent-pipeline
```

---

## Rollback

If any issues are found after applying, restore all 4 files at once:

```bash
git checkout HEAD -- apps/command-center-v2/src/pages/OpsHub.tsx apps/command-center-v2/src/pages/PipelineHub.tsx apps/command-center-v2/src/pages/SystemHealth.tsx apps/command-center-v2/src/pages/AgentPipeline.tsx
```

Or restore from backups:

```bash
cp apps/command-center-v2/src/pages/OpsHub.tsx.bak apps/command-center-v2/src/pages/OpsHub.tsx
cp apps/command-center-v2/src/pages/PipelineHub.tsx.bak apps/command-center-v2/src/pages/PipelineHub.tsx
cp apps/command-center-v2/src/pages/SystemHealth.tsx.bak apps/command-center-v2/src/pages/SystemHealth.tsx
cp apps/command-center-v2/src/pages/AgentPipeline.tsx.bak apps/command-center-v2/src/pages/AgentPipeline.tsx
```

Then rebuild:
```bash
cd apps/command-center-v2 && npm run build
```

Clean up backups after successful deployment:
```bash
rm -f apps/command-center-v2/src/pages/{OpsHub,PipelineHub,SystemHealth,AgentPipeline}.tsx.bak
```
