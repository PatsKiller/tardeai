# Agent Pages — Detailed Function Matrix

Status:      ACTIVE
as_of:       2026-06-02T21:03:40-04:00
Measured at: efcc51365 / not measured

> **⚠️ Model policy (validated 2026-06-02):** gemma3:12b = primary chat, gemma3:4b = fallback, gemma3:27b = overnight; **qwen3-embedding:8b = embeddings (active)**; **qwen3:14b (chat) is DISABLED + uninstalled.** Any reference below to qwen3:14b as an active chat/generation model is superseded — see `MASTER_SYSTEM_DOCUMENTATION.md` §12.


5 agent pages, no overlap. Each serves a distinct operational purpose.

---

## 1. Agent Lifecycle (`/v2/agent-lifecycle`)
**Menu:** Learning & Improvement → Agent Lifecycle
**Purpose:** How agents should be managed — 7-stage operational model with functional panels
**Lines:** 504 | **APIs:** 6

### API Endpoints
| Method | Endpoint | Data |
|---|---|---|
| GET | `/api/v2/command` | agent_health array (status, age, runs) |
| GET | `/api/v2/agent-calibration/agents` | Per-agent accuracy cards |
| GET | `/api/v2/agent-health` | Confidence, analyses, error counts |
| GET | `/api/v2/agent-lifecycle/requirements` | DEFINE stage requirement intake forms |
| POST | `/api/v2/agent-lifecycle/requirements` | Create new requirement |
| GET | `/api/v2/agent-lifecycle/quality-scores` | Live 5-dimension scores per agent |
| GET | `/api/v2/self-improvement/status` | Lessons learned for IMPROVE stage |

### Functions on Page
| Function | What it does |
|---|---|
| **Per-Agent Lifecycle State Grid** | 8 agent cards showing computed lifecycle stage (DEFINE/EVALUATE/MONITOR) with green/yellow/red dot and reason |
| **Agent Filter Dropdown** | Filters all sections to one agent |
| **7-Stage Pipeline Bar** | Clickable color bar — click to expand any stage |
| **DEFINE panel** | "Create Requirement" button → modal form (use-case, expected output, failure conditions, acceptance criteria). Lists existing requirements per agent |
| **RequirementModal** | Form with agent selector + 4 textareas. Saves via POST to agent_requirements table |
| **DESIGN panel** | Visualizes 7 agent chains (portfolio_allocation: maria→steph→risk→tax). Shows 4 escalation rules (agent_conflict, roth_conversion, income_critical, ssdi_impact) |
| **BUILD panel** | Shows 3 config files (agents.yaml, agent_raci.yaml, agent_runtime.json). "Open Config →" navigates to /strategy-admin |
| **EVALUATE panel** | CRITICAL GATE. Per-agent accuracy cards with pass/fail (60% threshold). Shows correct/wrong/total counts. "Full Calibration →" links to /agent-calibration |
| **DEPLOY panel** | Per-agent running/stopped/degraded status with freshness age and run count. Click → /agent-dashboard/:id |
| **MONITOR panel** | Per-agent confidence %, error rate, analysis count, last run date. "Full Pipeline →" links to /agent-pipeline |
| **IMPROVE panel** | Latest intelligence from self-improvement. Stale agent list. "Loop to Define →" restarts the cycle |
| **Quality Model — Live Scores** | 5 dimensions (Accuracy, Consistency, Grounding, Safety, Explainability) with live % per agent. Color: green ≥80%, yellow ≥60%, red <60% |
| **System Connection Cards** | 3 cards: Evaluation→Deployment gate, Monitoring→Improvement, Improvement→Design. Each with navigation button |

### Navigation Links
| Button | Destination |
|---|---|
| Open Config → | `/strategy-admin` |
| Full Calibration → | `/agent-calibration` |
| Full Pipeline → | `/agent-pipeline` |
| View Lessons → | `/self-improvement` |
| Agent chip click | `/agent-dashboard/:id` |
| Calibration → | `/agent-calibration` |
| Agent Pipeline → | `/agent-pipeline` |
| Self-Improvement → | `/self-improvement` |

---

## 2. Agent Pipeline (`/v2/agent-pipeline`)
**Menu:** System & Pipeline → Agent Pipeline
**Purpose:** What agents are doing right now — operational queue and intelligence view
**Lines:** 302 | **APIs:** 3

### API Endpoints
| Method | Endpoint | Data |
|---|---|---|
| GET | `/api/v2/agent-pipeline?limit=50` | Jobs, results, handoffs, events, proposals, debates, summary |
| GET | `/api/v2/system-health` | LLM provider status + budget |
| GET | `/api/v2/agent-health` | Per-agent health, confidence, last_run |

### Functions on Page
| Function | What it does |
|---|---|
| **Urgent Stop Banner** | Red alert if stop triggers detected. Shows symbols. "Review →" links to /risk |
| **Metrics Strip** | 5 KPIs: Queued (with backlog alert >200), Processing, Completed (24h), Failed (alert >10), Events (pending count) |
| **LLM Budget Panel** | Spend vs daily budget bar. Provider status: Local qwen3:14b ON/OFF, Claude ✓/✗, Grok ✓/✗, OpenAI ✓/✗ |
| **Agent Health Strip** | Per-agent dots with freshness age. Click → /agent-dashboard/:id. Red border if any agent stale. Stale count badge |
| **Tab: Intelligence** (default) | Per-symbol consensus view. Groups agent results by symbol, shows all agent votes side-by-side (maria HOLD, risk SELL, steph SELL). Color-coded recommendations |
| **Handoffs & Escalations** | Agent-to-agent handoffs with AgentChip → AgentChip flow. Escalation badges. 24h window |
| **Active Events** | Non-done events. Stop triggers in red. Portfolio fresh needed, RSI extreme, content gaps. Status badges |
| **Tab: Jobs** | Full job table: Symbol, Agent, Type, Status, Priority, Source, Age, Duration. Filter chips (all/queued/processing/completed/failed). Paginated |
| **Tab: Events** | Full event table: Type, Symbol, Priority (urgent/high/normal), Status, Agents, Age |

### Navigation Links
| Button | Destination |
|---|---|
| Review → (stop trigger) | `/risk` |
| Agent chip click | `/agent-dashboard/:id` |

---

## 3. Agent Calibration (`/v2/agent-calibration`)
**Menu:** Learning & Improvement → Agent Calibration
**Purpose:** How accurate are agents — quality scoring and evaluation
**Lines:** 430 | **APIs:** 4

### API Endpoints
| Method | Endpoint | Data |
|---|---|---|
| GET | `/api/v2/agent-calibration/status` | Freshness: last calibration, last recommendation, last outcome link |
| GET | `/api/v2/agent-calibration/agents` | Per-agent accuracy cards with correct/wrong/calibration error |
| GET | `/api/v2/agent-calibration/windows` | Rolling calibration windows per agent |
| GET | `/api/v2/agent-calibration/events` | Individual scored events (recommendation vs outcome) |

### Functions on Page
| Function | What it does |
|---|---|
| **Summary KPIs** | Recommendations count, Linked to Outcomes count, Scored Events count, Link Rate % |
| **Freshness Strip** | Last Calibration age, Last Recommendation age, Last Outcome Link age. Color-coded (green/yellow/red) |
| **Tab: Overview** | |
| — Calibrated Agents | Per-agent cards: accuracy ring (%), correct/wrong bar, calibration error, overconf/underconf scores, sample size status. "PROPOSAL ALLOWED" or "INSIGHT ONLY" badge. "View scored events →" link |
| — Not Yet Calibrated | Agents without enough data: name + rec count + "needs outcome links" |
| **Tab: Event Log** | Table: Agent, Symbol, Call, Confidence, Outcome, P&L, Calibration Error, When, Detail. 60 rows max |
| **Tab: Disagreements** | Agent-vs-agent disagreements on same symbol. Shows who said what and who was right |
| **Tab: Weight Proposals** | Proposed weight adjustments based on calibration data |
| **Refresh Button** | Manual refetch of all 4 APIs |

### Navigation Links
| Action | Destination |
|---|---|
| View scored events → | Switches to Events tab filtered by agent |

---

## 4. Agent Collaboration (`/v2/agent-collaboration`)
**Menu:** Command → Agent Collaboration
**Purpose:** How agents work together — RACI, missions, multi-agent outcomes
**Lines:** 1403 | **APIs:** 2

### API Endpoints
| Method | Endpoint | Data |
|---|---|---|
| GET | `/api/v2/agent-collaboration` | Missions, summary, RACI data, handoffs |
| GET | `/api/v2/agent-detail/raci?agent=X` | Per-agent RACI process ownership |

### Functions on Page
| Function | What it does |
|---|---|
| **Summary KPIs** | Needs John (ready count), Blocked, Waiting on Agent, Stale, System Trust (from Aegis) |
| **Tab: Missions** | |
| — Status Filters | All, Ready, Blocked, Waiting, Stale, Running, Completed. Count badges |
| — Type Filters | All Types, Risk, Proposals, Research, System, Alerts, Ticker |
| — Time Filters | All Time, 24h, 7 Days, 30 Days |
| — Mission Queue (left pane) | Scrollable list of missions. Each shows: title, severity badge, status badge, agent chips, item count, blocked count, next action text, age |
| — Mission Inspector (right pane) | Selected mission detail: severity, status, owner, collaboration timeline (Detected→Collaboration→Ready), RACI roles, agent contributions, "WHAT JOHN SHOULD DO" action card with Open Page button, Request Immediate Review button |
| **Tab: Collaboration Flow** | Visual flow of agent-to-agent handoffs and escalations |
| **Tab: RACI Map** | Full RACI matrix across all processes and agents |
| **Tab: Outcome Quality** | Quality scores for multi-agent decision outcomes |

### Mission Types (7)
| Type | What triggers it |
|---|---|
| Risk & Stops | Stop triggered events |
| Paper Proposals | Pending/approved proposals needing action |
| Aegis Brief Follow-ups | Morning briefs flagging items for Steph review |
| Research Stale Topics | Content older than freshness threshold |
| Debates & Escalations | Agent disagreements on same symbol |
| Agent Telemetry Health | Cron/feed staleness detection |
| Operator Escalations | Human review items from any agent |

---

## 5. Agent Dashboard (`/v2/agent-dashboard/:agentId`)
**Menu:** (Linked from agent chips on other pages)
**Purpose:** Deep dive on a single agent — all data for one agent
**Lines:** 410 | **APIs:** 3

### API Endpoints
| Method | Endpoint | Data |
|---|---|---|
| GET | `/api/v2/agent-dashboard?agent=X` | Full agent profile, analyses, recommendations |
| GET | `/api/v2/agent-detail/raci?agent=X` | RACI process ownership for this agent |
| GET | `/api/v2/agent-detail/escalation-trace?result_id=X` | Escalation chain for a specific result |

### Functions on Page
| Function | What it does |
|---|---|
| **Agent Selector Strip** | Horizontal chips for all agents. Click to switch. Active agent highlighted |
| **Agent Profile Card** | Agent name, role, model used, last run timestamp |
| **Summary KPIs** | Lifetime Analyses, Avg Confidence (all), Avg Confidence (30d), Top Symbols, Active Debates |
| **RACI Process Ownership** | Table: Process, Role (R/A/C/I badge), Co-Actors (agent chips), Trigger, Frequency |
| **Peer Relationships** | Which agents this agent works with most, shared process count |
| **Confidence Distribution (30d)** | Histogram or summary of confidence scores |
| **Decision Mix** | Breakdown of recommendations by type (BUY/HOLD/SELL/TRIM/etc) |
| **Recent Analyses** | Table of recent results with symbol, recommendation, confidence, summary. Expandable rows → escalation trace |
| **Outcome Calibration** | Progress bar: X/20 closed trade outcomes needed for calibration |
| **Active Debates** | Debates involving this agent with consensus and verdict |
| **Outcome Lessons** | Lessons learned from closed positions this agent recommended on |
| **Incoming Events** | Events routed to this agent from event_queue |
| **Handoffs (Out/In)** | Outbound and inbound handoffs with partner agents |

### How to Reach This Page
| From | How |
|---|---|
| Agent Lifecycle | Click any agent chip or lifecycle state card |
| Agent Pipeline | Click any agent chip in health strip or intelligence table |
| Agent Collaboration | Click agent chip in mission inspector |
| Agent Calibration | Click agent name in calibrated agents section |
| AI Analyst / Watchlist | Click agent chip in analysis results |

---

## Cross-Reference Matrix

| Feature | Lifecycle | Pipeline | Calibration | Collaboration | Dashboard |
|---|---|---|---|---|---|
| Agent health dots | Per-agent with lifecycle stage | Per-agent with freshness | — | — | — |
| Accuracy scores | Quality model (5 dims) | — | Full calibration cards | — | Confidence distribution |
| Job queue | — | Full queue + filters | — | — | — |
| LLM budget | — | Budget bar + providers | — | — | — |
| Agent chains / flow | DESIGN panel visualization | — | — | Collaboration Flow tab | — |
| RACI | — | — | — | RACI Map tab | Per-agent RACI table |
| Missions | — | — | — | Mission queue + inspector | — |
| Requirements | DEFINE panel + modal | — | — | — | — |
| Stop triggers | — | Urgent banner | — | Risk mission | — |
| Handoffs | — | Handoffs section | — | Collaboration Flow | Per-agent handoffs |
| Debates | — | — | Disagreements tab | Debates mission | Active Debates section |
| Recommendations | — | Intelligence consensus | Scored events | — | Recent Analyses |
| Escalation trace | — | — | — | Mission inspector | Expandable result rows |
| Quality gate | EVALUATE panel (pass/fail) | — | Accuracy rings | — | Outcome calibration |
| Improvement loop | IMPROVE panel → DEFINE | — | — | — | Outcome Lessons |
