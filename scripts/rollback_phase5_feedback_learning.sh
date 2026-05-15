#!/usr/bin/env bash
# rollback_phase5_feedback_learning.sh — Disable Phase 5 feedback without removing data.
set -uo pipefail
PROJ=/home/johnclaw/trade-ai-v12-rebuild/trade-ai-v12-rebuild

case "${1:-}" in
    --dry-run) echo "DRY RUN — Phase 5 tables would remain but no new data collected."
               DB_PASS=$(grep '^DB_PASSWORD=' "$PROJ/.env" | cut -d= -f2-)
               PGPASSWORD="$DB_PASS" psql -h localhost -U trade_ai -d trade_ai -c "
               SELECT 'llm_feedback_observations' AS t, COUNT(*) FROM llm_feedback_observations
               UNION ALL SELECT 'llm_learning_recommendations', COUNT(*) FROM llm_learning_recommendations
               UNION ALL SELECT 'llm_prompt_experiments', COUNT(*) FROM llm_prompt_experiments;" 2>/dev/null || echo "(tables may not exist)" ;;
    --status) echo "Phase 5 status:"; echo "  To collect: .venv/bin/python scripts/collect_phase5_feedback_observations.py --dry-run"
              echo "  To recommend: .venv/bin/python scripts/generate_phase5_learning_recommendations.py --dry-run"
              echo "  To review: .venv/bin/python scripts/report_phase5_human_review_queue.py" ;;
    --disable) echo "Phase 5 disabled. Tables preserved. Do not run collector/recommender." ;;
    *) echo "Usage: $0 [--dry-run|--status|--disable]" ;;
esac
