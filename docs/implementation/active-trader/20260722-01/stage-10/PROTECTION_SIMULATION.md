# Protection Simulation — Stage 10
Protect(order, confirmed) sets protection_state PENDING/CONFIRMED; filled quantity is protected
immediately (model). Missing/unconfirmed protection blocks additional entries in the higher-level
flow (Stage 3 duplicate-fill + Stage 9/8 gates). No broker-resident guarantee is claimed — that is
BF-1 (UNPROVEN) and blocks any live scalp. Simulation only.
