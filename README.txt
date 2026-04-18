# Live P&L Repricer v2 + Monitor Launcher
===========================================

## THE FIX FOR "No module named pandas"
The monitor was launched with bare "python" (system Python, no venv).
Fix: use the new launcher bat which activates venv first.

## DEPLOY (run from project root)

Step 1 - Copy all files:
  copy "%USERPROFILE%\Downloads\portfolio_repricer.py" scripts\portfolio_repricer.py
  copy "%USERPROFILE%\Downloads\portfolio_live_monitor.py" scripts\portfolio_live_monitor.py
  copy "%USERPROFILE%\Downloads\run_portfolio_monitor.bat" launchers\run_portfolio_monitor.bat
  copy "%USERPROFILE%\Downloads\run_reprice_fidelity.bat" launchers\run_reprice_fidelity.bat
  copy "%USERPROFILE%\Downloads\SKILL_updated.md" SKILL_updated.md

Step 2 - Start monitor NOW (uses venv, no more pandas error):
  .\launchers\run_portfolio_monitor.bat

Step 3 - Register Task Scheduler tasks (PowerShell as Admin):
  copy "%USERPROFILE%\Downloads\setup_monitor_task.ps1" .
  copy "%USERPROFILE%\Downloads\setup_reprice_task.ps1" .
  powershell -ExecutionPolicy Bypass -File setup_monitor_task.ps1
  powershell -ExecutionPolicy Bypass -File setup_reprice_task.ps1

## FULL SCHEDULE AFTER DEPLOY
  9:30 AM       Task: PortfolioLiveMonitor starts (venv, Mon-Fri)
  Every 30 min  Finviz prices fetched for 44 symbols
  Every 30 min  finviz_quote_cache.json delta-updated
  Every 30 min  holdings.json repriced, portfolio_live.html regenerated
  4:31 PM       Monitor self-terminates
  8:00 PM       Task: PortfolioRepriceFidelity (Yahoo cache for 10 Fidelity funds)
