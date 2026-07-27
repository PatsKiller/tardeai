# Smart-Limit Simulation — Stage 10
Bounded price improvement: filled->STOP; stale(>3s)/sequence-broken->CANCEL; flow-reversed->CANCEL;
spread blowout(>40bps)->HOLD; no rate token->WAIT; at max authorized price->HOLD_AT_CAP; else MODIFY
by one tick toward cap. **Not the banned 750ms loop** — min reprice interval >= 1.9s (Stage 5 governor
aligned). All branches tested.
