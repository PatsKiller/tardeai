# F6 — UTC scheduling proposals for LLM-heavy jobs

**Status:** docs-only proposals · **no cron/systemd install from this wave**  
**Dated audit:** [`docs/audits/overnight/F6_UTC_CRON_PROPOSALS_2026-08-31.md`](../audits/overnight/F6_UTC_CRON_PROPOSALS_2026-08-31.md)

Operator-facing summary:

- Official DeepSeek peak is **UTC** Mon–Fri `01:00–04:00` and `06:00–10:00`; **half-rate elsewhere**.
- Host crontab is Eastern wall-clock; overnight LLM lines often land in UTC peak under EDT and only survive via `run_with_deepseek_offpeak.sh` PEAK_SKIP.
- F6 proposes **32** UTC (or explicit ET-TZ ownership) retargets. **Operator-only to install.**
- DST risk: ET `20:00` is UTC `00:00` in EDT but UTC `01:00` (Peak A) in EST.

Related: `DEEPSEEK_BULK_WINDOW_ET_2026-08-19.md`, `MATURATION_G1_I0_A1_B1_2026-08-21.md`.
