# Market Opportunities Phase 3 - Apply Plan

Status:      HISTORICAL
as_of:       2026-05-25T14:16:20-04:00
Measured at: efcc51365 / not measured

## Pre-flight

Verify the source files have not changed since the replacements were designed:

```bash
cd apps/command-center-v2/src/pages
sha256sum TradeAI.tsx
# Expected: 100acd120f2bba7fa9dba07bb675e2c9e66e199a92f922b79d07c470e626e907

sha256sum Prospects.tsx
# Expected: b2d6fd13148ad576ddfbc9d5af777fa28f3a3727de868c8ef36bf2b8bbdd8de4
```

If hashes do not match, STOP. The source files have been modified since the replacements were designed. Re-read the originals and reconcile changes before applying.

## Apply Order

Apply in this exact order. The files are independent so order is for rollback safety.

### Step 1: Backup originals

```bash
cd apps/command-center-v2/src/pages
cp TradeAI.tsx TradeAI.tsx.BACKUP_PHASE3
cp Prospects.tsx Prospects.tsx.BACKUP_PHASE3
```

### Step 2: Apply TradeAI.tsx replacement

Extract the tsx block from `TradeAI.tsx.REPLACEMENT.md` and write to `TradeAI.tsx`:

```bash
# From repo root:
cp apps/command-center-v2/src/pages/TradeAI.tsx.BACKUP_PHASE3 apps/command-center-v2/src/pages/TradeAI.tsx.BACKUP_PHASE3
# Apply the replacement content (extract from .REPLACEMENT.md tsx block)
```

### Step 3: Apply Prospects.tsx replacement

Extract the tsx block from `Prospects.tsx.REPLACEMENT.md` and write to `Prospects.tsx`.

### Step 4: Build

```bash
cd apps/command-center-v2
npm run build
```

Expected: Clean build with zero errors. If build fails, check for:
- Import path issues (all imports use `../components/` relative paths)
- Prop signature violations (see warnings below)

## Smoke Test Routes

After build, start the dev server and verify these routes:

1. **`/v2/trade-ai`** (Market Opportunities page)
   - Page loads with "Market Opportunities" title
   - StateCard summary row visible at top (GO, WAIT, NO GO, VIX, Regime, Last Run, Top Ticker, Deltas)
   - Run health banner shows StatusBadge
   - Decision filter buttons (Universe/GO/WAIT) are ActionButton components
   - Table renders with StatusBadge for decision column
   - Clicking a row opens DetailDrawer with full content
   - TOS export copy buttons work
   - Empty state shows if no data

2. **`/v2/prospects`** (Prospect Discovery page)
   - Page loads with "Prospect Discovery" title
   - StateCard summary row visible (Total, GO, WAIT, AVOID, Last Scan, Strategy)
   - Tab buttons (scalp/swing/income/position/all) are ActionButton components
   - Filter inputs work (price range, min score)
   - Clear button works
   - Table renders with StatusBadge for decision, HELD, incubator badges
   - Side panel opens on row click
   - Add to Watchlist buttons work
   - Empty state shows with clear filter action if no results

## Rollback

If anything breaks:

```bash
cd apps/command-center-v2/src/pages
cp TradeAI.tsx.BACKUP_PHASE3 TradeAI.tsx
cp Prospects.tsx.BACKUP_PHASE3 Prospects.tsx
```

Then rebuild:

```bash
cd apps/command-center-v2
npm run build
```

## CRITICAL WARNINGS: Prop Signatures

These are build-breaking mistakes. Verify NONE of these patterns exist in the applied files:

```
WRONG: <ActionButton label="Text">        CORRECT: <ActionButton>Text</ActionButton>
WRONG: <AgentChip agent="maria">           CORRECT: <AgentChip name="maria">
WRONG: <StateCard label="Title">           CORRECT: <StateCard title="Title">
```

Quick grep to verify after applying:

```bash
cd apps/command-center-v2/src/pages
grep -n 'ActionButton label=' TradeAI.tsx Prospects.tsx
grep -n 'AgentChip agent=' TradeAI.tsx Prospects.tsx
grep -n 'StateCard label=' TradeAI.tsx Prospects.tsx
# All three should return zero results
```

## Post-Apply Cleanup

After verifying everything works:

```bash
cd apps/command-center-v2/src/pages
rm TradeAI.tsx.BACKUP_PHASE3
rm Prospects.tsx.BACKUP_PHASE3
```
