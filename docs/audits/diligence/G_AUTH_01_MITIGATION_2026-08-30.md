# G-AUTH-01 mitigation (2026-08-30)

Daily rebalancer now **drops** AVOID-contradicting orders from the actionable list by default (`drop_orders_against_avoid` / `flag_orders_against_avoid(..., drop_contradictions=True)`), appends refusal receipts to `data/cio/cio_avoid_refusals.jsonl`, and continues for remaining orders. READ_ONLY_ADVISORY · MBI=0 · no broker write · no notify-on. Gap register ownership remains PR-G.
