# JSON contract matrix

| Capability | Status | Evidence |
|------------|--------|----------|
| `response_format=json_object` supported by Flash/Pro | PASS (smoke) | DEEPSEEK_CHAT_SMOKE.json |
| Strict parse (no prose strip) | PASS (unit) | test_parse_strict_json_no_prose_strip |
| Empty content → EMPTY_CONTENT | PASS (unit) | test_parse_strict_json_empty |
| Mismatched returned model fail-closed | PASS (unit) | test_chat_mismatched_returned_model |
| Full Pydantic schemas per process | PARTIAL | process registry output_schema IDs declared; schema modules not fully expanded |
| Truncation / tool reasoning replay suite | NOT DONE | residual |
