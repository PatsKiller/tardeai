@echo off
cd /d C:\Users\john\OneDrive\AI_Skilss\live_skills\trade-ai-v12-rebuild
echo Starting Portfolio Intelligence Dashboard...
echo.
echo  Index:      http://localhost:7777/
echo  Trade AI:   http://localhost:7777/reports/dashboard_live.html
echo  Portfolio:  http://localhost:7777/reports/portfolio_live.html
echo.
echo Press Ctrl+C to stop both servers when done.
echo.
call venv\Scripts\activate.bat

REM Start API proxy in background
start "Portfolio Proxy" /min python scripts\portfolio_proxy.py --root .

REM Give proxy a moment to start
timeout /t 1 /nobreak >nul

REM Open both dashboards in browser
start "" "http://localhost:7777/reports/dashboard_live.html"
start "" "http://localhost:7777/reports/portfolio_live.html"

REM Start file server from project root (Ctrl+C stops everything)
python scripts\portfolio_server.py --root .
