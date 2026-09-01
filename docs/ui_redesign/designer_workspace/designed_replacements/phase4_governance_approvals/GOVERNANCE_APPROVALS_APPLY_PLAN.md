# Phase 4 Governance & Approvals -- Apply Plan

Status:      HISTORICAL
as_of:       2026-05-25T15:07:30-04:00
Measured at: efcc51365 / not measured

## Prerequisites

1. Phase 1.5 shared primitives must exist:
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

## Pre-Apply Prop Signature Verification

```bash
# These MUST all print "OK" -- any "FAIL" means wrong prop usage
grep '<AgentChip agent=' docs/ui_redesign/designer_workspace/designed_replacements/phase4_governance_approvals/*.md && echo "FAIL: AgentChip uses name= not agent=" || echo "OK: AgentChip"
grep 'ActionButton label=' docs/ui_redesign/designer_workspace/designed_replacements/phase4_governance_approvals/*.md && echo "FAIL: ActionButton uses children not label=" || echo "OK: ActionButton"
grep '<StateCard label=' docs/ui_redesign/designer_workspace/designed_replacements/phase4_governance_approvals/*.md && echo "FAIL: StateCard uses title= not label=" || echo "OK: StateCard"
```

---

## Apply Order (smallest/safest first, largest last)

### Step 1: GovernanceHub.tsx (29 lines, lowest risk)

```bash
# Backup
cp apps/command-center-v2/src/pages/GovernanceHub.tsx apps/command-center-v2/src/pages/GovernanceHub.tsx.bak

# Apply replacement (copy tsx from GovernanceHub.tsx.REPLACEMENT.md)

# Build check
cd apps/command-center-v2 && npm run build
```

### Step 2: PaperReview.tsx (20 lines, low risk)

```bash
# Backup
cp apps/command-center-v2/src/pages/PaperReview.tsx apps/command-center-v2/src/pages/PaperReview.tsx.bak

# Apply replacement

# Build check
cd apps/command-center-v2 && npm run build
```

### Step 3: ProposalAlerts.tsx (107 lines, low risk)

```bash
# Backup
cp apps/command-center-v2/src/pages/ProposalAlerts.tsx apps/command-center-v2/src/pages/ProposalAlerts.tsx.bak

# Apply replacement

# Build check
cd apps/command-center-v2 && npm run build
```

### Step 4: PaperGovernance.tsx (182 lines, medium risk)

```bash
# Backup
cp apps/command-center-v2/src/pages/PaperGovernance.tsx apps/command-center-v2/src/pages/PaperGovernance.tsx.bak

# Apply replacement

# Build check
cd apps/command-center-v2 && npm run build
```

### Step 5: LearningGovernance.tsx (189 lines, medium risk)

```bash
# Backup
cp apps/command-center-v2/src/pages/LearningGovernance.tsx apps/command-center-v2/src/pages/LearningGovernance.tsx.bak

# Apply replacement

# Build check
cd apps/command-center-v2 && npm run build
```

### Step 6: Approvals.tsx (494 lines, high risk)

```bash
# Backup
cp apps/command-center-v2/src/pages/Approvals.tsx apps/command-center-v2/src/pages/Approvals.tsx.bak

# Apply replacement

# Build check
cd apps/command-center-v2 && npm run build

# Smoke test: verify decision controls render
curl -s http://127.0.0.1:7777/v2/governance | head -c 200
```

### Step 7: PaperProposals.tsx (1185 lines, highest risk -- apply last)

```bash
# Backup
cp apps/command-center-v2/src/pages/PaperProposals.tsx apps/command-center-v2/src/pages/PaperProposals.tsx.bak

# Apply replacement

# Build check
cd apps/command-center-v2 && npm run build

# Smoke test: verify proposal cards render
curl -s http://127.0.0.1:7777/v2/paper-proposals | head -c 200
```

---

## Full Backup (all at once)

```bash
BACKUP_DIR="docs/ui_redesign/designer_workspace/backups/phase4_apply_$(date +%Y%m%d_%H%M)"
mkdir -p "$BACKUP_DIR"
for f in GovernanceHub PaperProposals PaperReview ProposalAlerts PaperGovernance LearningGovernance Approvals; do
  [ -f "apps/command-center-v2/src/pages/${f}.tsx" ] && cp "apps/command-center-v2/src/pages/${f}.tsx" "$BACKUP_DIR/"
done
# Save SHA256 hashes
for f in GovernanceHub PaperProposals PaperReview ProposalAlerts PaperGovernance LearningGovernance Approvals; do
  [ -f "apps/command-center-v2/src/pages/${f}.tsx" ] && sha256sum "apps/command-center-v2/src/pages/${f}.tsx" >> "$BACKUP_DIR/sha256sums.txt"
done
echo "Backed up to $BACKUP_DIR"
```

---

## Smoke Test Routes

```bash
for r in governance paper-proposals paper-review proposal-alerts; do
  curl -s -o /dev/null -w "$r: %{http_code}\n" "http://127.0.0.1:7777/v2/$r"
done
```

---

## Rollback (if needed)

```bash
# Rollback all Phase 4 files
git checkout HEAD -- apps/command-center-v2/src/pages/{GovernanceHub,PaperProposals,PaperReview,ProposalAlerts,PaperGovernance,LearningGovernance,Approvals}.tsx
cd apps/command-center-v2 && npm run build
```

Or from backup:
```bash
BACKUP_DIR="docs/ui_redesign/designer_workspace/backups/phase4_apply_YYYYMMDD_HHMM"
for f in GovernanceHub PaperProposals PaperReview ProposalAlerts PaperGovernance LearningGovernance Approvals; do
  [ -f "$BACKUP_DIR/${f}.tsx" ] && cp "$BACKUP_DIR/${f}.tsx" "apps/command-center-v2/src/pages/${f}.tsx"
done
cd apps/command-center-v2 && npm run build
```

---

## Post-Apply Verification Checklist

- [ ] Build passes (`npm run build` exits 0)
- [ ] `/v2/governance` loads with 3 tabs
- [ ] `/v2/governance?tab=paper` shows PaperGovernance with StateCards
- [ ] `/v2/governance?tab=learning` shows LearningGovernance with StatusBadges
- [ ] `/v2/governance?tab=approvals` shows Approvals with decision controls
- [ ] `/v2/paper-proposals` loads with proposal cards
- [ ] `/v2/paper-proposals` Approve/Reject buttons work (test with a READY proposal)
- [ ] `/v2/paper-proposals` Enrich All workflow triggers correctly
- [ ] `/v2/paper-review` loads with 2 tabs
- [ ] `/v2/proposal-alerts` loads with alert table
- [ ] Redirects work: `/v2/approvals` -> `/v2/governance`, `/v2/proposals` -> `/v2/paper-proposals`
