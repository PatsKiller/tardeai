# Replay Determinism Report — Stage 9
run_shadow(inp) is pure: identical DecisionInput → identical prime/fire/res/rrs/runner + identical
journal (tested: full equality across two runs). This is the property that lets Stage 5 replay
reproduce shadow decisions exactly; full live-vs-replay equivalence over captured data is part of the
PENDING Stage 5 five-session gate.
