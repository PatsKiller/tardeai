<!-- Recovered verbatim from the operator's own message in the session
     transcript. Everything below the rule is the brief as sent: not
     summarised, not reordered, not corrected. Provenance header added by
     the rules-install package; it is the only text here that is not the
     operator's. -->

# S0 operator loop

**Status:** recovered verbatim
**Source:** session transcript, operator message 020

---

re-run the critique on SPCX  Claude Code — S0 operator loop. Not a wave letter. Notify stays OFF.

CURRENT latest promoted pin. Exact-main after.
READ_ONLY_ADVISORY.
PINS:
- CIO_SITUATION_NOTIFY stays 0. INTERDICT on. telegram_sent false.
- No new Telegram send() / digest cron. No 3E delivery.
- MBI=0. ROTATE advisory-only. Council DISPUTED stands.
- No --backend live. No cap raise. No R1 allowlist widen.
- Do not rewrite CASH/dust checkpoint history.

WHY
The event spine is live. Operator questions are not.
S0_OPERATOR_CONVERSE exists but free-text / new-ticker questions
do not reliably mint a plan, load registry[symbol], or persist
an operator_turn_id. That is why the desk looks like “only SCHD.”

DO

1) S0 mint
   Operator input (slash, ack/defer/reject, or converse payload
   already in store — do not build a new chat transport) maps to
   S0_OPERATOR_CONVERSE with symbols extracted.
   If an open plan exists for that symbol+kind: attach the turn
   to that plan_id. Do not mint a duplicate S1/S6.
   If none: mint ONE S0 draft, thesis_version=current desk pin.
   TEST / CASH / dust: refuse mint.

2) Rehydrate before research
   On every S0 (and on detector wakes): load by symbol/plan_id
     desk pin, symbol thesis if any, open plans, CASE_SUMMARY,
     latest artifact+outcome, last operator defer/ack, lesson.
   Pass that bundle into ResearchNeedDecision@v2.
   If reuse or corpus_hit: no enqueue.

3) operator_turn_id
   Registry + jsonl: turn_id, plan_id, symbol, text_hash,
   intent (question|ack|defer|reject), created_at.
   Next wake for that symbol must see the last turn.
   Product shows “operator last: defer ‘wait for price buffer’”
   when present (SCHD already has this pattern — generalize).

4) Thread / plan attach
   Ack/defer/reject without a plan_id attaches to the newest
   open plan for the mentioned symbol. If none: S0 mint.
   Do not start a second SCHD S6.

5) Symbol thesis honesty
   Coverage card: held non-dust with/without symbol thesis.
   Do not auto-mint 20 theses. Missing = RESEARCH_REQUIRED /
   DESK_PIN_ONLY, not a silent desk@v5 stamp on every name.

6) Product
   Command Center / /v3/cio: S0 rows visible.
   Receipt would_send false. Policy default SUPPRESSED for S0
   unless already COMMAND_CENTER_ONLY.

TESTS
- “what about RTX” with no plan → one S0, registry load, no Telegram.
- Second turn same symbol → same plan_id, new operator_turn_id.
- SCHD defer still honored; no second S6.
- Dust/TEST refuse mint.
- Dry eligible count does not explode to 36 Flash jobs.

DOCS docs/ops/CIO_S0_OPERATOR_LOOP_{date}.md
Scoreboard S0=mint+rehydrate+turn_id, telegram_sent=false.

VERIFY /health /v3/cio 200, cash class unchanged,
cio_run DETERMINISTIC, telegram_sent false, 0 paid calls.

STOP. No notify-on. No Grok hop unless a separate prompt says so.
