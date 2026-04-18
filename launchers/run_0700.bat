@echo off
:: ============================================================
:: Trade AI v11 — Run 0700 (Pre-Market Update — MAIN RUN)
:: Schedule: 7:00 AM ET, weekdays
::
:: HOW TO SCHEDULE:
::   1. Open Task Scheduler (search "Task Scheduler" in Start)
::   2. Click "Create Basic Task..."
::   3. Name: "Trade AI 0700"
::   4. Trigger: Daily, 7:00 AM
::   5. Action: Start a program
::   6. Program: Full path to THIS file
::      e.g. C:\TradeAI\launchers\run_0700.bat
::   7. "Start in": C:\TradeAI   (your project root)
::   8. Finish. Done.
:: ============================================================

cd /d "%~dp0.."
set LOGFILE=logs\run_0700_%date:~-4%%date:~4,2%%date:~7,2%.log

echo [%date% %time%] Starting run 0700 >> %LOGFILE%

if not exist venv\Scripts\activate.bat (
    echo [ERROR] venv not found. Run assets\setup_local_project.bat first. >> %LOGFILE%
    exit /b 1
)

call venv\Scripts\activate.bat
python scripts\trade_ai_orchestrator.py --run-label 0700 >> %LOGFILE% 2>&1

echo [%date% %time%] Run 0700 complete >> %LOGFILE%
