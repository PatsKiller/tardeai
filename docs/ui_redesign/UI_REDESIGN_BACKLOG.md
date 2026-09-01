# UI Redesign Backlog

Status:      HISTORICAL
as_of:       2026-05-25T11:12:43-04:00
Measured at: efcc51365 / not measured

Generated: 2026-05-25

---

## Phase 0: Route Cleanup (COMPLETE)

### 0.1 Remove duplicate /v2/alerts route
- **Description:** The second `alerts` route definition (pointing to Inbox) is dead code because React Router matches the first definition (AlertsDashboard). Remove the dead route.
- **Files:** `apps/command-center-v2/src/App.tsx`
- **Risk:** None -- dead code removal
- **Acceptance Criteria:** Only one `alerts` route exists. AlertsDashboard renders at /v2/alerts. Build succeeds.

### 0.2 Capture desktop screenshots
- **Description:** Capture 1920x1080 screenshots of all 47 routes for design baseline.
- **Files:** `docs/ui_redesign/screenshots/`, `docs/ui_redesign/SCREENSHOT_INDEX.md`
- **Risk:** None
- **Acceptance Criteria:** 47 PNG files in screenshots/, SCREENSHOT_INDEX.md updated with all routes.

### 0.3 Update manifest and Drive sync
- **Description:** Update HANDOFF_MANIFEST.md with screenshot count, Drive sync status. Upload to Google Drive.
- **Files:** `docs/ui_redesign/HANDOFF_MANIFEST.md`
- **Risk:** None
- **Acceptance Criteria:** Manifest reflects current state. Archive uploaded to Drive.

---

## Phase 1: Navigation Restructure

### 1.1 Create Trading nav group
- **Description:** Add a new "Trading" nav group containing Trade AI, Prospects, Strategy Desk, Incubator, and ATM Mode. These are currently scattered in Admin.
- **Files:** `apps/command-center-v2/src/components/Shell.tsx` (nav config)
- **Risk:** Low -- nav-only change, no route changes
- **Acceptance Criteria:** Trading group appears in sidebar with all 5 items. All routes still resolve correctly.

### 1.2 Create Learning & Improvement nav group
- **Description:** Add "Learning & Improvement" group containing Self-Improvement, Agent Calibration, Weekly Learning. These are currently buried in Admin.
- **Files:** `apps/command-center-v2/src/components/Shell.tsx`
- **Risk:** Low
- **Acceptance Criteria:** Learning group in sidebar. Self-Improvement is prominent, not hidden.

### 1.3 Reduce Admin/Governance nav group
- **Description:** After extracting Trading and Learning items, Admin should contain only ~6 items: Governance Hub, Strategy Admin, Forecast, Correlation, Broker Recon, Plan vs Performance.
- **Files:** `apps/command-center-v2/src/components/Shell.tsx`
- **Risk:** Low -- users may need to find relocated items
- **Acceptance Criteria:** Admin has <= 6 items. No routes broken.

### 1.4 Move Backtesting to Reports group
- **Description:** Backtesting is analytical/reporting, not admin config. Move to Reports nav group.
- **Files:** `apps/command-center-v2/src/components/Shell.tsx`
- **Risk:** Low
- **Acceptance Criteria:** Backtesting appears under Reports in sidebar.

### 1.5 Add Paper Trading nav group
- **Description:** Create dedicated "Paper Trading" group: Proposals, Paper Review, Paper Status, Execution Quality.
- **Files:** `apps/command-center-v2/src/components/Shell.tsx`
- **Risk:** Low
- **Acceptance Criteria:** Paper Trading group in sidebar with 4 items.

---

## Phase 2: Hub Consolidation

### 2.1 Trade AI + Prospects tab merge
- **Description:** Evaluate merging Prospects as a tab within Trade AI to reduce top-level navigation items while keeping both datasets accessible.
- **Files:** `apps/command-center-v2/src/pages/TradeAI.tsx`, `apps/command-center-v2/src/pages/Prospects.tsx`
- **Risk:** Medium -- shared state management, potential data loading complexity
- **Acceptance Criteria:** Single entry point for trade opportunity flow. Both datasets accessible. No data loss.

### 2.2 Agent Pipeline + Agent Collaboration evaluation
- **Description:** Assess whether Agent Pipeline and Agent Collaboration should merge or remain separate. Agent Collaboration is decision-ops; Agent Pipeline is monitoring.
- **Files:** `apps/command-center-v2/src/pages/AgentPipeline.tsx`, `apps/command-center-v2/src/pages/AgentCollaboration.tsx`
- **Risk:** Medium -- different user intents, may confuse if merged poorly
- **Acceptance Criteria:** Clear recommendation with rationale. If merged, both use cases served.

### 2.3 Pipeline + System Health relationship
- **Description:** Clarify overlap between Pipeline Stages and System Health. Consider System Health as a tab in Pipeline or vice versa.
- **Files:** `apps/command-center-v2/src/pages/PipelineHub.tsx`, `apps/command-center-v2/src/pages/SystemHealth.tsx`
- **Risk:** Low-Medium
- **Acceptance Criteria:** Clear separation of concerns documented and implemented.

### 2.4 Ops as operations center
- **Description:** Position Ops Hub as the parent/overview for the System & Pipeline family with drill-down to Pipeline, System Health, Agent Pipeline.
- **Files:** `apps/command-center-v2/src/pages/OpsHub.tsx`
- **Risk:** Medium -- requires cross-page navigation design
- **Acceptance Criteria:** Ops links to child pages. Clear hierarchy.

---

## Phase 3: Design System

### 3.1 CSS variable audit and standardization
- **Description:** Audit all hardcoded hex values across pages. Replace with CSS custom properties from theme.css. Document the token system.
- **Files:** All page and component files in `apps/command-center-v2/src/`
- **Risk:** Medium -- visual regressions possible
- **Acceptance Criteria:** Zero hardcoded hex values in page components. All colors reference CSS variables. Visual diff shows no unintended changes.

### 3.2 Badge/chip/status pattern library
- **Description:** Standardize the various badge, chip, and status indicator patterns into reusable components.
- **Files:** `apps/command-center-v2/src/components/` (new shared components)
- **Risk:** Low-Medium -- existing inline styles need migration
- **Acceptance Criteria:** Shared Badge, Chip, StatusIndicator components. All pages use shared components.

### 3.3 Drawer/modal pattern standardization
- **Description:** Standardize drawer and modal patterns across pages (e.g., detail panels in Trade AI, governance approvals).
- **Files:** `apps/command-center-v2/src/components/` (new/updated shared components)
- **Risk:** Medium
- **Acceptance Criteria:** Shared Drawer and Modal components with consistent animation, sizing, and close behavior.

### 3.4 Typography scale
- **Description:** Define and apply consistent typography scale (headings, body, captions, labels).
- **Files:** `apps/command-center-v2/src/theme.css`, all pages
- **Risk:** Low-Medium
- **Acceptance Criteria:** Typography tokens defined. All text uses scale. No raw font-size declarations.

---

## Phase 4: Page Redesigns (priority order)

### 4.1 Agent Collaboration -- mission-control cockpit
- **Description:** Redesign Agent Collaboration as a mission-control style cockpit showing agent status, active tasks, collaboration threads, and decision queues.
- **Files:** `apps/command-center-v2/src/pages/AgentCollaboration.tsx`
- **Risk:** High -- complex page with real-time data
- **Acceptance Criteria:** Clear agent status visibility. Task queue actionable. Real-time updates work. No regressions in agent communication.

### 4.2 Ops / Pipeline / System Health -- automation trust
- **Description:** Redesign the ops family to build trust in automation. Clear health indicators, pipeline stage visualization, and quick-action controls.
- **Files:** `apps/command-center-v2/src/pages/OpsHub.tsx`, `PipelineHub.tsx`, `SystemHealth.tsx`
- **Risk:** High -- multiple interconnected pages
- **Acceptance Criteria:** Clear system health at a glance. Pipeline stages visualized with timing. Ops provides overview with drill-down.

### 4.3 Trade AI / Prospects -- market opportunity
- **Description:** Redesign trade opportunity flow to surface actionable intelligence with clear entry/exit signals and risk context.
- **Files:** `apps/command-center-v2/src/pages/TradeAI.tsx`, `Prospects.tsx`
- **Risk:** High -- core trading workflow, must not break paper trading pipeline
- **Acceptance Criteria:** Trade signals clearly prioritized. Risk context visible. Integration with paper proposals maintained.

### 4.4 Governance / Approvals -- policy control
- **Description:** Redesign governance to clearly separate policy rules from pending approvals and audit trail.
- **Files:** `apps/command-center-v2/src/pages/GovernanceHub.tsx`
- **Risk:** Medium -- policy enforcement, must maintain approval workflows
- **Acceptance Criteria:** Pending approvals prominent. Policy rules editable. Audit trail accessible.

### 4.5 Self-Improvement -- enhance only
- **Description:** Light enhancement to Self-Improvement page. This page is already well-designed; focus on polish and consistency with design system.
- **Files:** `apps/command-center-v2/src/pages/SelfImprovement.tsx`
- **Risk:** Low -- enhancement only, no structural changes
- **Acceptance Criteria:** Consistent with design system tokens. No functionality changes. Visual polish applied.
