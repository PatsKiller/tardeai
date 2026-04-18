@echo off
echo Stopping portfolio server on port 7777...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :7777 ^| findstr LISTENING') do (
    echo Found PID: %%a
    taskkill /F /PID %%a >nul 2>&1
    echo Stopped PID %%a
)
timeout /t 2 /nobreak >nul
echo Starting portfolio server...
start "Portfolio Server" cmd /k venv\Scripts\python.exe scripts\portfolio_server.py
echo Portfolio server started on port 7777
echo.
echo Open: http://localhost:7777/reports/command_center.html
