@echo off
REM ============================================================
REM  run_continuous.bat — Trade AI v12 Continuous Runner
REM  Task Scheduler: Mon-Fri 4:00 AM
REM  v2: Hardcoded absolute path (no %ROOT% variable)
REM      Writes scheduler_starts.log for diagnosis
REM      Loads .env before launching runner
REM ============================================================

REM Force working directory to project root
cd /d "C:\Users\john\OneDrive\AI_Skilss\live_skills\trade-ai-v12-rebuild"

REM Create logs dir if missing
if not exist logs mkdir logs

REM Log startup immediately — proves task fired even if runner crashes later
echo [%DATE% %TIME%] TradeAIContinuous task started >> logs\scheduler_starts.log
echo    Working dir: %CD% >> logs\scheduler_starts.log
echo    User: %USERNAME% >> logs\scheduler_starts.log

REM Activate venv
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
) else (
    echo [%DATE% %TIME%] ERROR: venv not found >> logs\scheduler_starts.log
    exit /b 1
)

REM Load .env variables (Task Scheduler doesn't inherit user env vars)
if exist .env (
    for /f "usebackq tokens=1,* delims==" %%a in (".env") do (
        if not "%%a"=="" if not "%%b"=="" (
            if not "%%a:~0,1%"=="#" set "%%a=%%b"
        )
    )
)

echo [%DATE% %TIME%] venv activated, launching runner >> logs\scheduler_starts.log

REM Launch runner with explicit absolute project-root
python scripts\continuous_runner.py --project-root "C:\Users\john\OneDrive\AI_Skilss\live_skills\trade-ai-v12-rebuild"

echo [%DATE% %TIME%] runner exited code=%ERRORLEVEL% >> logs\scheduler_starts.log
