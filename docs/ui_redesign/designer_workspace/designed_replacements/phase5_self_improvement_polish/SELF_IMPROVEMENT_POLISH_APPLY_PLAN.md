# Self-Improvement Polish -- Apply Plan

**Phase:** 5
**Target file:** `apps/command-center-v2/src/pages/SelfImprovement.tsx`
**Replacement spec:** `SelfImprovement.tsx.REPLACEMENT.md`

---

## Pre-flight

1. Verify original hash matches:
```bash
sha256sum apps/command-center-v2/src/pages/SelfImprovement.tsx
# Expected: fc411dfaa7f87fbbaf82f89cb6476cbe79d19d4aa9213c68e4eb90adc44e4831
```

2. Verify shared primitives exist and export correctly:
```bash
head -5 apps/command-center-v2/src/components/StatusBadge.tsx
head -5 apps/command-center-v2/src/components/SeverityBadge.tsx
head -5 apps/command-center-v2/src/components/ActionButton.tsx
head -5 apps/command-center-v2/src/components/StateCard.tsx
```

---

## Step 1: Backup

```bash
cp apps/command-center-v2/src/pages/SelfImprovement.tsx \
   apps/command-center-v2/src/pages/SelfImprovement.tsx.BACKUP
```

---

## Step 2: Apply replacement

Extract the TSX code block from `SelfImprovement.tsx.REPLACEMENT.md` and write it to the target file.

---

## Step 3: Build

```bash
cd apps/command-center-v2 && npm run build
```

Expected: clean build, no TypeScript errors.

Common issues to watch for:
- Import path typos for shared primitives
- Prop name mismatches (e.g., `label=` vs `title=` on StateCard)
- Missing `children` on ActionButton (required prop)

---

## Step 4: Smoke test

1. Open browser to `http://localhost:7777/v2/self-improvement`
2. Verify:
   - Page title reads "Self-Improvement Center"
   - PAPER MODE ACTIVE banner displays with green border
   - Overview cards render as StateCards with left color stripe
   - Component health shows StatusBadge pills (not raw dots)
   - Subsystem dashboard buttons render as ActionButtons
   - Cross-link row shows Agent Calibration, Weekly Learning, Automation Trust
   - Refresh button works (data reloads)
   - All navigation links route correctly
   - Empty state messages appear when applicable (review queue empty)
   - Warnings section renders with StatusBadge indicators

---

## Step 5: Rollback (if needed)

```bash
cp apps/command-center-v2/src/pages/SelfImprovement.tsx.BACKUP \
   apps/command-center-v2/src/pages/SelfImprovement.tsx
cd apps/command-center-v2 && npm run build
```

---

## Post-apply cleanup

```bash
rm apps/command-center-v2/src/pages/SelfImprovement.tsx.BACKUP
```
