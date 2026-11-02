"""Issuer segment look-through (DSN-20261101-issuer-segment-lookthrough), P1: shadow only.

``edgar_fetch``    companyconcept -> newest 10-K/10-Q accession -> the filing's XBRL instance + label linkbase.
``xbrl_segments``  pure parser of segment-axis revenue facts.
``mapping``        deterministic segment -> group table (config/issuer_segment_map.json).
``classifier``     the model-classified path: a stub that never calls a model (P3 builds it).
``shadow``         runs the above and writes a shadow receipt to a temp/runtime path; never a store.

Nothing here is read by scripts/lib/market_risk/; config/issuer_segments.json stays the only live source.
"""
