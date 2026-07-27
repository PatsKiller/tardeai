# Prime Rule Matrix — Stage 9
States: NOT_PRIMED, PRIMED, BLOCKED, STALE, INSUFFICIENT_DATA.
Order: data STALE/gap→STALE; NO_GO/BLOCKED/HALTED/LULD or !capability/!risk→BLOCKED;
missing price/vwap/rvol/spread→INSUFFICIENT_DATA; else PRIMED iff IN_SCOPE & price>=vwap &
rvol>=3.0 & spread<=20bps (seed defaults, unvalidated). Reason trace attached. Tested all states.
