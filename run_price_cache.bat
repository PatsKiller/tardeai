@echo off
cd /d C:\Users\john\OneDrive\AI_Skilss\live_skills\trade-ai-v12-rebuild
call venv\Scripts\activate.bat
echo.
echo ============================================================
echo  Building Portfolio Price Cache (Jan 2020 to today)
echo  This takes 2-5 minutes on first run, ~30s after that.
echo ============================================================
echo.
python scripts\portfolio_price_cache.py --project-root .
echo.
echo Done. Refresh the dashboard to see updated Period Returns.
