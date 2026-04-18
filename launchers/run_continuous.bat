@echo off
REM run_continuous.bat v3 - Trade AI v12
cd /d "C:\Users\john\OneDrive\AI_Skilss\live_skills\trade-ai-v12-rebuild"
if not exist logs mkdir logs
echo [%DATE% %TIME%] Task started >> logs\scheduler_starts.log
echo    Dir: %CD% User: %USERNAME% >> logs\scheduler_starts.log
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo [%DATE% %TIME%] ERROR venv >> logs\scheduler_starts.log
    exit /b 1
)
echo [%DATE% %TIME%] venv OK launching >> logs\scheduler_starts.log
python scripts\continuous_runner.py --project-root "C:\Users\john\OneDrive\AI_Skilss\live_skills\trade-ai-v12-rebuild"
echo [%DATE% %TIME%] exited %ERRORLEVEL% >> logs\scheduler_starts.log
