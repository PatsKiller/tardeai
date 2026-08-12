# Alex enrichment — prompt curation, versioning, evaluation

## Layout

```
prompts/cio_alex_enrich/
  active.json              # live pin + file names + compatible_thesis
  v1_system.md / v1_user_template.md   # baseline (rollback)
  v2_system.md / v2_user_template.md / v2_fewshot.md  # Desk OS v2 curated (active)
  CHANGELOG.md
```

Loader: `scripts/lib/cio_prompt_loader.py` → `load_active_prompt()`  
Eval: `scripts/lib/cio_prompt_eval.py` → structural_check + heuristic quality + probe CLI  

## Techniques applied (v2)

1. Deterministic Desk Context injection (thesis, risk_posture_structured, learning, domains)
2. Hard output contract + self-check
3. Role + stance priming
4. Forbidden list (detector echo, invention, execution language)
5. Contrast few-shot (S5/S6)
6. Mandatory fit/tension language
7. Non-action first-class under defensive_observe
8. Dual-surface: same JSON for Telegram + plan page
9. Operator dispositions as dynamic constraints
10. Prompt version + content hash on every plan
11. Rubric + structural gate (critical fails block notify)

## Plan provenance fields

- `prompt_version` e.g. `cio_alex_enrich@v2`
- `prompt_content_hash` sha256 of system+user+fewshot
- `prompt_alias` e.g. `v2`
- `eval_structural_score` 0–100
- `eval_quality_total` 1–5 heuristic (operator `/cio rate` remains ground truth)

## Commands

```bash
# Active prompt
PYTHONPATH=scripts python3 -c "from scripts.lib.cio_prompt_loader import load_active_prompt; print(load_active_prompt()['prompt_version'])"

# Structural / quality on a plan
PYTHONPATH=scripts python3 -m scripts.lib.cio_prompt_eval structural --plan plan_05a414a3d105
PYTHONPATH=scripts python3 -m scripts.lib.cio_prompt_eval score --plan plan_05a414a3d105
PYTHONPATH=scripts python3 -m scripts.lib.cio_prompt_eval probe

# Re-enrich probe set under active prompt (template if LLM blocked)
CIO_LLM_FORCE_TEMPLATE=1 PYTHONPATH=scripts python3 -c "
from scripts.lib.cio_plans import CIOPlanStore
from scripts.lib.cio_plan_enrichment import enrich_plan
s=CIOPlanStore()
for pid in ['plan_1b8d534354fb','plan_05a414a3d105','plan_51e03253ba2d']:
    p=s.get_plan(pid)
    enrich_plan(dict(p), source=p.get('situation_type') or 'S0', force_template=True)
    q=s.get_plan(pid)
    print(pid, q.get('prompt_version'), q.get('eval_structural_score'), q.get('eval_quality_total'))
"
```

## Promotion workflow

1. Author `vN_*.md` under `prompts/cio_alex_enrich/`
2. Probe offline on S5 / S6 SCHD / S1 SPCX
3. Require structural 100% critical-pass + mean quality ≥ 3.5
4. Flip `active.json` (never edit published files in place)
5. Re-enrich open material plans
6. Rollback = repoint `active.json` to previous alias

## Rubric weights

| Dimension | Weight |
|-----------|--------|
| Thesis use | 25% |
| Multi-domain synthesis | 20% |
| Options | 15% |
| Recommendation | 15% |
| Evidence discipline | 15% |
| Tone | 10% |

Target promotion: mean ≥ 3.5/5, no dimension &lt; 2, no critical structural fails.
