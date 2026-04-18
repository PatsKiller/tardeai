@echo off
cd /d "C:\Users\john\OneDrive\AI_Skilss\live_skills\trade-ai-v12-rebuild"
call venv\Scripts\activate.bat
echo [%date% %time%] Fidelity 8PM reprice starting >> logs\reprice_fidelity.log
python scripts\portfolio_repricer.py >> logs\reprice_fidelity.log 2>&1
echo [%date% %time%] Done >> logs\reprice_fidelity.log
