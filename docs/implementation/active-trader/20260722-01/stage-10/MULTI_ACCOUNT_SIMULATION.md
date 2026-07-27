# Multi-Account Simulation — Stage 10
Primary/fallback with duplicate-exposure prevention: `fallback_new_quantity` =
floor(min(requested, authorized_aggregate - confirmed_filled - confirmed_working, fallback_cap)).
Envelope exhausted -> 0; cap binds; never rounds exposure up. Source finality + confirmed fill
quantity are preconditions (Stage 3 fallback evaluator governs the decision; this stage sizes it).
Unapproved alternates require reauthorization (Stage 8). Tested.
