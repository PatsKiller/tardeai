# Job Schedule Audit & Contention Map

**361 active cron jobs** · 73 LLM-touching  
_Source: `python3 scripts/job_schedule_audit.py --json`_  

## By tier

| Tier | Jobs |
|------|-----:|
| T1 | 22 |
| T2 | 18 |
| T3 | 42 |
| INFRA | 279 |

## LLM contention by hour (jobs that can fire each hour)

| Hour (ET) | LLM jobs | |
|-----------|--------:|--|
| 00:00 | 13 | █████████████ |
| 01:00 | 9 | █████████ |
| 02:00 | 12 | ████████████ |
| 03:00 | 9 | █████████ |
| 04:00 | 17 | █████████████████ |
| 05:00 | 14 | ██████████████ |
| 06:00 | 14 | ██████████████ ⚠ OVERLOAD (market window) |
| 07:00 | 13 | █████████████ ⚠ OVERLOAD (market window) |
| 08:00 | 15 | ███████████████ ⚠ OVERLOAD (market window) |
| 09:00 | 16 | ████████████████ ⚠ OVERLOAD (market window) |
| 10:00 | 13 | █████████████ ⚠ OVERLOAD (market window) |
| 11:00 | 12 | ████████████ ⚠ OVERLOAD (market window) |
| 12:00 | 22 | ██████████████████████ |
| 13:00 | 18 | ██████████████████ |
| 14:00 | 21 | █████████████████████ |
| 15:00 | 15 | ███████████████ |
| 16:00 | 25 | █████████████████████████ |
| 17:00 | 12 | ████████████ |
| 18:00 | 14 | ██████████████ |
| 19:00 | 11 | ███████████ |
| 20:00 | 17 | █████████████████ |
| 21:00 | 11 | ███████████ |
| 22:00 | 11 | ███████████ |
| 23:00 | 11 | ███████████ |

## Cloud-OAuth offload candidates (currently local, should move to free Grok/ChatGPT lanes)

- `llm_intelligence_enrichment.py`
- `proposal_enrichment_loop.py`
- `safe_flock.sh`
- `safe_flock.sh`
- `llm_priority_guard.sh`
- `safe_flock.sh`
- `llm_priority_guard.sh`
- `llm_priority_guard.sh`
- `llm_priority_guard.sh`
- `llm_priority_guard.sh`
- `llm_priority_guard.sh`
- `hermes_subject_enhance.py`
- `llm_priority_guard.sh`
- `run_inference_cycle.sh`
- `run_inference_cycle.sh`
- `run_inference_cycle.sh`
- `run_inference_cycle.sh`
- `run_inference_cycle.sh`
- `run_inference_cycle.sh`
- `hermes_autonomous_self_tune.py`
- `register_analyst_sources.py`
- `llm_priority_guard.sh`
- `llm_intelligence_enrichment.py`

> Read-only schedule audit. T3 LLM jobs should defer during 06:00-12:00 ET (the market window) and/or offload to the free cloud-OAuth lanes so T1 scalp/proposal work gets the GPU. No broker writes; operator/2FA untouched.

