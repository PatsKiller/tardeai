# Runner Methodology — Stage 9
States: NOT_ELIGIBLE, ELIGIBLE, ACTIVE, REDUCE, EXIT, INVALIDATED, DATA_BLOCKED.
Data stale/gap→DATA_BLOCKED; scores insufficient→NOT_ELIGIBLE; RRS>=80 or halt→EXIT; RES<50→
INVALIDATED(if active)/NOT_ELIGIBLE; RES>=75 & RRS<=35→ACTIVE(if active)/ELIGIBLE; RRS>60→REDUCE;
else demand-intact ACTIVE/ELIGIBLE. No broker action. Tested transitions.
