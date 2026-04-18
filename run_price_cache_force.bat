@echo off
cd /d C:\Users\john\OneDrive\AI_Skilss\live_skills\trade-ai-v12-rebuild
call venv\Scripts\activate.bat
echo.
echo ============================================================
echo  FORCE rebuilding price cache (re-downloads everything)
echo ============================================================
echo.
python scripts\portfolio_price_cache.py --project-root . --force
