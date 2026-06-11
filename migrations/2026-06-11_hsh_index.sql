-- hermes_score_history pairing index: the calibration LATERAL ran 48+ min over 226K rows without it
CREATE INDEX IF NOT EXISTS idx_hsh_sym_at ON hermes_score_history (symbol, scored_at);
