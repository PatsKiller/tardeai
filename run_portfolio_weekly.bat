@echo off
REM Trade AI v12 — Portfolio Intelligence Weekly Technical Scan
REM Runs every Sunday 8:00 PM
REM Light: Finviz technical pull + signal change alerts
REM Escalates to full Sonnet briefing if critical signals detected

cd /d C:\Users\john\OneDrive\AI_Skilss\live_skills\trade-ai-v12-rebuild
call venv\Scripts\activate.bat

echo.
echo ============================================================
echo  Portfolio Intelligence — Weekly Technical Scan
echo  %DATE% %TIME%
echo ============================================================
echo.

python scripts\portfolio_orchestrator.py --project-root . --run-label weekly --run-type weekly

echo.
echo Weekly scan complete.
pause
