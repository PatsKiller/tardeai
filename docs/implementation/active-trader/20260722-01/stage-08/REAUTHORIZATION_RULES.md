# Reauthorization Rules — Stage 8
A new session 2FA/verification is required for: a changed authority draft hash; an account not in
the signed envelope; a larger quantity/risk envelope; an environment change. An action targeting an
unauthorized account or symbol returns REAUTHORIZATION_REQUIRED (never a silent add). Binding to the
same hash requires no reauthorization. All tested.
