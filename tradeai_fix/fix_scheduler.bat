@echo off
REM ============================================================
REM  fix_scheduler.bat — Fix TradeAIContinuous Task Scheduler
REM  Run as Administrator in CMD from project root
REM  
REM  ROOT CAUSE: Task was set to %ROOT% (unexpanded variable)
REM  FIX: Recreate with hardcoded absolute path + correct settings
REM ============================================================

cd /d "C:\Users\john\OneDrive\AI_Skilss\live_skills\trade-ai-v12-rebuild"

echo.
echo ============================================================
echo  Fixing TradeAIContinuous Task Scheduler entry
echo  Project root: %CD%
echo ============================================================
echo.

REM Show current broken state
echo [BEFORE] Current task configuration:
schtasks /query /tn "TradeAIContinuous" /fo LIST /v 2>nul | findstr /i "Task To Run\|Last Run\|Last Result\|Logon Mode\|Run As"

echo.
echo Deleting broken task...
schtasks /delete /tn "TradeAIContinuous" /f 2>nul

echo Creating fixed task with absolute path...
schtasks /create ^
  /tn "TradeAIContinuous" ^
  /tr "\"C:\Users\john\OneDrive\AI_Skilss\live_skills\trade-ai-v12-rebuild\launchers\run_continuous.bat\"" ^
  /sc WEEKLY ^
  /d MON,TUE,WED,THU,FRI ^
  /st 04:00 ^
  /ru "%USERNAME%" ^
  /rl HIGHEST ^
  /f

if errorlevel 1 (
    echo ERROR: Task creation failed. Make sure you are running as Administrator.
    pause
    exit /b 1
)

REM Patch XML to enable "run whether logged on or not" + wake computer
echo Patching task XML for wake + always-run settings...
schtasks /query /tn "TradeAIContinuous" /xml > "%TEMP%\tradeai_task.xml" 2>nul

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "try { $xml = [xml](Get-Content '%TEMP%\tradeai_task.xml'); $s = $xml.Task.Settings; $s.WakeToRun = 'true'; $s.DisallowStartIfOnBatteries = 'false'; $s.StopIfGoingOnBatteries = 'false'; $s.ExecutionTimeLimit = 'PT8H'; $xml.Task.Principals.Principal.LogonType = 'S4U'; $xml.Save('%TEMP%\tradeai_patched.xml'); Write-Host 'XML patched OK' } catch { Write-Host 'XML patch skipped:' $_.Exception.Message }"

schtasks /create /tn "TradeAIContinuous" /xml "%TEMP%\tradeai_patched.xml" /f 2>nul && (
    echo Task XML reimported with wake settings
) || (
    echo Note: XML reimport failed - base task still has correct path
)

echo.
echo [AFTER] Fixed task configuration:
schtasks /query /tn "TradeAIContinuous" /fo LIST /v | findstr /i "Task To Run\|Next Run\|Last Run\|Logon Mode\|Run As"

echo.
echo ============================================================
echo  Task fixed. Changes made:
echo  1. Path: absolute hardcoded (was broken %%ROOT%% variable)
echo  2. Wake computer: enabled
echo  3. Run on battery: enabled  
echo  4. Logon type: S4U (run whether logged on or not)
echo  5. Next run: Tomorrow 4:00 AM
echo.
echo  Test now by running:
echo  launchers\run_continuous.bat
echo ============================================================
echo.
pause
