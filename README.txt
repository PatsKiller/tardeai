# Trade AI v12 -- Trading Intelligence Platform
# ==============================================
#
# Owner: John W. Whiting
# Server: ms01-openclaw (Linux)
# Status: Paper trading validation (6-month window)
#
# DOCUMENTATION INDEX
# -------------------
# All documentation lives in docs/. The addendum model is deprecated.
# These are the authoritative documents:
#
#   docs/MASTER_SYSTEM_DOCUMENTATION.md   -- Complete system reference
#   docs/ARCHITECTURE_OVERVIEW.md         -- Executive architecture summary
#   docs/ARCHITECTURE_INFOGRAM.md         -- Visual architecture diagrams
#   docs/CHEAT_SHEET.md                   -- Operator quick reference
#   docs/COST_MODEL.md                    -- Cloud operating cost estimates (incl. topic intelligence)
#   docs/GPU_OLLAMA_SETUP.md              -- GPU/LLM hardware config
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
