# Trade AI v12 -- Trading Intelligence Platform
# ==============================================
#
# Owner: John W. Whiting
# Server: ms01-openclaw (Linux)
# Status: Paper trading validation (6-month window)
#
# DOCUMENTATION INDEX
# -------------------
# Start here. Command Center is /v3/ on port 7777.
#
#   AGENTS.md                                              -- operator policy
#   docs/ops/FEATURE_TO_LIVE_DEPLOY_RUNBOOK.md             -- merge and promote
#   docs/ops/ROLLBACK_COMMANDS.md                          -- rollback
#   docs/architecture/V3_3_IMPLEMENTATION_STATUS_2026-09-27.md
#   docs/architecture/TRADE_AI_MASTER_AGENTIC_FINANCIAL_SYSTEM_ARCHITECTURE_v3_3.md
#
# Older architecture files v2_0 and v3_0 through v3_2 are superseded by v3_3.
# docs/ARCHITECTURE_OVERVIEW.md is not in this tree.
#
# TOPIC INTELLIGENCE (NEW 2026-05-09)
# -----------------------------------
#   17 research topics with closed-loop LLM curation
#   scripts/topic_ingestion.py            -- 4-source search cascade
#   scripts/topic_curator.py              -- Post-ingestion: rate, extract, link, improve
#   Command Center: /v2/topic-monitor     -- Admin page
#   Telegram: topic status|add|url|run    -- Mobile management
#   docs/RESTORE_GUIDE.md                 -- Disaster recovery procedures
#   docs/DOCX_UPDATE_PROTOCOL.md          -- DOCX maintenance protocol
#
# STRATEGY & AGENT DOCS
# ---------------------
#   docs/project/TRADE_AI_STRATEGY_PLAYBOOK_v1.0.md  -- 20 strategy playbooks
#   docs/project/agents_bible.md                      -- Agent behavior rules
#   docs/project/SKILL.md                             -- Agent skills inventory
#   docs/project/project_openclaw.md                  -- OpenClaw gateway config
#   docs/project/Trade_AI_v12_Reference_Architecture.docx -- Canonical DOCX
#
# ARCHIVE
# -------
#   docs/archive/       -- Historical session handoffs (pre-bible era)
#   docs/_archive/      -- Superseded system bibles and session docs
#
# QUICK START
# -----------
#   1. Activate venv:     source .venv/bin/activate
#   2. Start server:      python scripts/portfolio_server.py
#   3. Open dashboard:    http://localhost:7777/v2/
#   4. Check health:      curl http://localhost:7777/api/v2/system-health
#   5. See cheat sheet:   docs/CHEAT_SHEET.md
