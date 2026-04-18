@echo off
cd /d "C:\Users\john\OneDrive\AI_Skilss\live_skills\trade-ai-v12-rebuild"
if not exist logs mkdir logs
echo [%DATE% %TIME%] Portfolio Live Monitor starting >> logs\monitor_starts.log
call venv\Scripts\activate.bat
python scripts\portfolio_live_monitor.py >> logs\portfolio_monitor_%DATE:~-4,4%%DATE:~-10,2%%DATE:~-7,2%.log 2>&1
echo [%DATE% %TIME%] Portfolio Live Monitor exited >> logs\monitor_starts.log
