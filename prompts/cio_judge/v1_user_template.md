# cio_judge@v1 user template

THESIS:
{{thesis_block}}

SITUATION:
type: {{situation_type}}
symbol: {{symbol}}
plan_id: {{plan_id}}
thesis_version: {{thesis_version}}
prompt_version: {{prompt_version}}

EVIDENCE (source of truth — inventing beyond this is a defect):
{{evidence_pack}}

ADVISORY TEXT TO SCORE:
{{advisory_text}}

Return JSON only:
{
  "plan_id": "...",
  "prompt_version": "...",
  "scores": {
    "thesis_use": 1,
    "synthesis": 1,
    "options": 1,
    "recommendation": 1,
    "evidence": 1,
    "tone": 1
  },
  "rationales": {
    "thesis_use": "one line",
    "synthesis": "one line",
    "options": "one line",
    "recommendation": "one line",
    "evidence": "one line",
    "tone": "one line"
  },
  "critical_defects": [],
  "summary": "one sentence overall judgment"
}
