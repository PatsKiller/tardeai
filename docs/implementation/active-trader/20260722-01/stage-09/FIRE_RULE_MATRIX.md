# Fire Rule Matrix — Stage 9
States: NO_FIRE, FIRE_SHADOW, BLOCKED, EXPIRED, STALE, DATA_GAP.
Order: sequence-gap/overflow→DATA_GAP; stale→STALE; prime!=PRIMED→NO_FIRE; halt/!cap/!risk→BLOCKED;
missing microstructure→NO_FIRE (not error); else FIRE_SHADOW iff price>=session_high & OFI>0 &
tape_buy>=0.58. Requires a price event PLUS flow confirmation. Tested.
