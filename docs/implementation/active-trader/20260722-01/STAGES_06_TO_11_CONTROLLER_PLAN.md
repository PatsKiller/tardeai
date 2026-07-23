# Stages 6–11 Controller Plan — run 20260722-01
Single authorization, six separately-gated stage transactions. Moomoo lockout honored: NO login,
NO live data — fixtures/replay only throughout. Each stage: plan→implement→test→safety→artifacts→
commit→push→Drive+SHA256→checkpoint→email→next. Permitted terminal states:
S6/S7/S8 GREEN_CLOSED; S9 GREEN_IMPLEMENTED_DATA_VALIDATION_PENDING;
S10 GREEN_IMPLEMENTED_PROMOTION_BLOCKED; S11 GREEN_CLOSED. Stage 5 gates preserved.
