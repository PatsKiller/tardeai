# cio_alex_enrich@v2 — user message template

DESK CONTEXT (deterministic — do not invent beyond this):
{{desk_context}}

SITUATION:
type={{situation_type}} symbols={{symbols}} plan_id={{plan_id}} fire={{fire}}{{mat_tag}}

EVIDENCE DOMAINS: {{domains}}
EVIDENCE FACTS:
{{evidence_facts}}

ALLOWED NUMBERS (only these): {{numbers}}
OPTION_IDS (preserve): {{option_ids}}

RECENT OPERATOR DISPOSITIONS (honor unless new evidence overrides):
{{learning_block}}

TASK:
{{task}}

Produce ONE JSON object with keys:
summary, thesis_alignment, multi_domain_summary, recommendation, options, risks, revisit_hint, cited_fields, thesis_version={{pin}}

Self-check: thesis pin cited; fit/tension stated; ≥2 domains if available; options have complete pros/cons; no invented numbers; no execution language.
