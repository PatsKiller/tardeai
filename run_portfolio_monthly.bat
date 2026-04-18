@echo off
cd /d C:\Users\john\OneDrive\AI_Skilss\live_skills\trade-ai-v12-rebuild
call venv\Scripts\activate.bat

echo [MONTHLY] Starting Portfolio Intelligence monthly run...
echo [MONTHLY] %date% %time%

echo [MONTHLY] Step 1/4 - Portfolio analysis...
python scripts\portfolio_orchestrator.py --project-root . --run-label morning --run-type monthly
copy data\portfolios\reports\portfolio_live.html reports\portfolio_live.html /y >nul

echo [MONTHLY] Step 2/4 - AI analysis sections...
python scripts\portfolio_ai_analyst.py --project-root .

echo [MONTHLY] Step 3/4 - YAML Config Advisor (Opus review)...
python scripts\portfolio_yaml_advisor.py

echo [MONTHLY] Step 4/4 - Copying dashboard...
copy data\portfolios\reports\portfolio_live.html reports\portfolio_live.html /y >nul

echo [MONTHLY] Complete. Open Command Center AI Analyst tab to review YAML suggestions.
echo [MONTHLY] Done: %date% %time%
