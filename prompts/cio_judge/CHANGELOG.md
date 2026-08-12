# cio_judge prompt changelog

## v1 — 2026-08-12 (active)

- Initial rubric-locked judge for thesis_use, synthesis, options, recommendation, evidence, tone
- Explicit READ_ONLY / non-action / no-length-reward rules
- Critical defects: execution_language, invented_numbers, missing_recommendation, thesis_footer_only, truncated_options
- Model: DeepSeek V4 Flash via governed bridge (advisory_desk FAST path)
- Status: SHADOW scoring until human gold-set calibration freezes promotion use
