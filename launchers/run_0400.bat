@echo off
cd /d "C:\Users\john\OneDrive\AI_Skilss\live_skills\trade-ai-v12-rebuild"
chcp 65001 > nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set LOGFILE=logs\run_0400_%date:~10,4%%date:~4,2%%date:~7,2%.log
echo [%date% %time%] Starting Trade AI 0400 > %LOGFILE%
call venv\Scripts\activate.bat >> %LOGFILE% 2>&1
python scripts\trade_ai_orchestrator.py --run-label 0400 >> %LOGFILE% 2>&1
echo [%date% %time%] Done >> %LOGFILE%
