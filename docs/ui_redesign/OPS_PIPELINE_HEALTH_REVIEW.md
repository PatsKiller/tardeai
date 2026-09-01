# Ops / Pipeline / Health Page Family Review

Status:      HISTORICAL
as_of:       2026-05-25T10:45:00-04:00
Measured at: efcc51365 / not measured

Generated: 2026-05-25

---

## Current Pages in This Family

### 1. `/v2/system-health` -- SystemHealth
- **API:** `/api/v2/system-health`, `/api/v2/finviz-screeners`
- **Purpose:** System health dashboard + Finviz screener status
- **Nav:** Pipeline & Health > System Health

### 2. `/v2/pipeline` -- PipelineHub (tabs)
- **Tab 1: PipelineHealthMaster** -- `/api/v2/pipeline-health-master`
- **Tab 2: PipelineController** -- `/api/v2/pipeline-controller/status`, `/stages`, `/failures`, `/runs`, `/discovery-source-health`, `/paper-validation-status`, `/system-facts`
- **Nav:** Pipeline & Health > Pipeline Stages

### 3. `/v2/agent-pipeline` -- AgentPipeline
- **API:** `/api/v2/agent-pipeline?limit=50`, `/api/v2/system-health`, `/api/v2/agent-health`
- **Purpose:** Agent action feed with system health side panel
- **Nav:** Pipeline & Health > Agent Pipeline

### 4. `/v2/ops` -- OpsHub (tabs)
- **Tab 1: SystemHub** -- general system overview
- **Tab 2: Ops** -- `/api/v2/ops/summary`, `/api/v2/ops/audit`, `/api/v2/tasks/history`, `/api/v2/ops/llm-audit`, `/api/v2/ops/cron-health`
- **Tab 3: LLMQueue** -- `/api/v2/queue/summary`, `/pending`, `/completed`, `/failed`
- **Tab 4: Orchestration** -- `/api/v2/orchestration`
- **Nav:** Admin > Operations

### 5. `/v2/agent-collaboration` -- AgentCollaboration
- **API:** `/api/v2/agent-collaboration`
- **Purpose:** Multi-agent collaboration view (debates, consensus)
- **Nav:** Pipeline & Health > Agent Collaboration

---

## Overlap Analysis

| Data Domain | Pages Showing It |
|------------|-----------------|
| System health | SystemHealth, AgentPipeline, OpsHub (SystemHub tab) |
| Pipeline stages | PipelineHub, OpsHub (implied) |
| Cron jobs | OpsHub (Ops tab) |
| LLM queue | OpsHub (LLM Queue tab) |
| Agent actions | AgentPipeline |
| Agent health | AgentPipeline, Overview |
| Orchestration | OpsHub (Orchestration tab) |

## Consolidation Recommendations

### Option A: Keep 3 pages (recommended)
1. **Ops Center** = OpsHub (keep as-is: SystemHub + Ops + LLM Queue + Orchestration)
2. **Pipeline** = PipelineHub + merge SystemHealth into it as a tab
3. **Agents** = Merge AgentPipeline + AgentCollaboration into an "Agent Operations" hub

### Option B: Keep 2 pages (aggressive)
1. **Operations** = OpsHub + SystemHealth + Orchestration
2. **Pipeline & Agents** = PipelineHub + AgentPipeline + AgentCollaboration

### Key Concern
SystemHealth is in "Pipeline & Health" nav but OpsHub has a "System Hub" tab.
The user must currently check TWO different pages for system status.

## Action Items
- [ ] Move SystemHealth content into PipelineHub as a tab, OR into OpsHub
- [ ] Consider merging AgentPipeline + AgentCollaboration
- [ ] Clarify in nav: "System" vs "Pipeline" vs "Ops" distinction
