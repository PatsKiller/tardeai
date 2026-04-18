INSTITUTIONAL UPGRADE v1.4 — DASHBOARD SERVER FIX
===================================================
v1.4 fixes:
  - scripts/portfolio_server.py: REWRITTEN
    Serves from project root. Both dashboards at /reports/ path.
    Index page at http://localhost:7777/ with clickable links to both.
  - run_dashboard.bat: updated URLs
    Trade AI:   http://localhost:7777/reports/dashboard_live.html
    Portfolio:  http://localhost:7777/reports/portfolio_live.html
  - scripts/portfolio_orchestrator.py: copies portfolio_live.html to reports/

DEPLOY:
  1. Unzip at project root (overwrites run_dashboard.bat + 6 scripts)
  2. run_portfolio.bat  (generates portfolio_live.html in reports/)
  3. run_dashboard.bat  (starts server + opens both dashboards)

For informational purposes only. Not investment advice.
