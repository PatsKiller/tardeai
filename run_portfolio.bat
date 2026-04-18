@echo off
cd /d C:\Users\john\OneDrive\AI_Skilss\live_skills\trade-ai-v12-rebuild
call venv\Scripts\activate.bat
python scripts\portfolio_orchestrator.py --project-root . --run-label morning --run-type daily
copy data\portfolios\reports\portfolio_live.html reports\portfolio_live.html /y >nul
venv\Scripts\python.exe -c "import urllib.request,json; urllib.request.urlopen(urllib.request.Request('http://localhost:7777/api/clear-pending',data=b'{}',headers={'Content-Type':'application/json'},method='POST'))" >nul 2>&1
