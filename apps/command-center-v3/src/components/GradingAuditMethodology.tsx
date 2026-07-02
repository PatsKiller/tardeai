import { desk, sectionLabel } from '../lib/proposalDeskTheme'

const card = {
  background: desk.bg,
  border: `1px solid ${desk.border}`,
  borderRadius: desk.radiusXl,
  padding: 14,
} as const

type Layer = {
  id: string
  title: string
  summary: string
  backend: string
  blocksRoute?: string
}

const LAYERS: Layer[] = [
  {
    id: 'signal',
    title: '1 · Signal grade (birth certificate)',
    summary: 'Frozen at scan time from trade_ai_scans score: A+ ≥48, A ≥40, B ≥30, C below. Does NOT update when price moves — use thesis band + Litmus for live R:R.',
    backend: 'trade_ai_scans.grade · incubator_llm_screener',
  },
  {
    id: 'diligence',
    title: '2 · Broker diligence (7 stages)',
    summary: 'Enrich → Agents → Stage 2b → Intel → Cloud → Trade plan → Broker gate. Any stage BLOCK disables auto-route. Trade plan BLOCK = no support/resistance/confluence anchor (pure 2×risk geometry).',
    backend: 'broker_promote_oversight · broker_trade_plan_gate',
    blocksRoute: 'Trade plan gambling-blocked · oversight BLOCK · sizing violations',
  },
  {
    id: 'agents',
    title: '3 · Local agents (Maria · Risk · Steph)',
    summary: 'On-prem gemma3:4b via watchlist_agent_jobs. Right agents for swing/pullback: Maria=catalyst, Risk=technicals, Steph=portfolio fit. deterministic_fallback = LLM did not run — low confidence. Advisory only; BLOCK/REJECT votes hard-stop.',
    backend: 'queue_proposal_agent_reviews · proposal_agent_reviews',
    blocksRoute: 'Incomplete required agents · BLOCK vote',
  },
  {
    id: 'stage2b',
    title: '4 · Stage 2b (local LLM thesis)',
    summary: 'qwen3 four-chunk: analysis → decision → risk → catalyst. Mature-LLM button runs through decision chunk. Cannot override risk gate or trade-plan BLOCK.',
    backend: 'proposal_llm_reviewer · mature_llm_stage_2b',
  },
  {
    id: 'cloud',
    title: '5 · Cloud OAuth (Grok + ChatGPT)',
    summary: 'Second opinion — needs OAuth keys. Reviews static thesis unless you Validate first (live quote). DISAGREE warns but does not alone block unless REQUIRE_CLOUD_LIVE=1.',
    backend: 'inference_ensemble · broker_promote_oversight cloud lanes',
  },
  {
    id: 'technical',
    title: '6 · Technical assessment (live)',
    summary: 'Narrative grade from Finviz enrichment (same as Entry helper): verdict + action line + score/100. STRONG ≥80 · OK ≥60 · MIXED ≥40 · WEAK ≥20 · INCOMPLETE below. Re-graded every 2h and on price refresh — not frozen at scan birth.',
    backend: 'proposal_enrichment_bridge · enrich_proposal_technicals cron',
  },
  {
    id: 'litmus',
    title: '7 · Litmus validate (pre-route facts)',
    summary: 'Operator facts check: live quote, thesis band zone, live R:R, sizing caps. GO / CAUTION / NO-GO — advisory label, no order submit.',
    backend: 'broker_trade_litmus',
  },
  {
    id: 'journal',
    title: '8 · Journal grade (after close)',
    summary: 'Execution quality on closed trades — separate from proposal queue grades. Feeds RAG for future agent reviews.',
    backend: 'trade_journal · backtest replay',
  },
]

const GRADE_TABLE = [
  { label: 'Signal A+/A/B', meaning: 'Scanner conviction at birth', live: 'No — refresh prices + Validate' },
  { label: 'Technical grade', meaning: 'TECH_STRONG/OK/MIXED/WEAK/INCOMPLETE — scored 0–100 from RSI, MA trend, ATR%, RVOL, ADX (Finviz)', live: 'Yes — every 2h cron + ↻ Refresh prices' },
  { label: 'Thesis zone', meaning: 'comfortable / approaching / at_risk / invalid', live: 'Yes — 30s list poll + price refresh' },
  { label: 'Live R:R', meaning: 'Reward vs risk at current price', live: 'Yes — after refresh-prices' },
  { label: 'Oversight PASS/WARN/BLOCK', meaning: 'Agents + intel + cloud + trade plan', live: 'Yes — on detail load' },
  { label: 'Litmus GO/CAUTION/NO-GO', meaning: 'Operator pre-route sanity', live: 'On demand — Validate button' },
]

export default function GradingAuditMethodology() {
  return (
    <details style={card}>
      <summary style={{
        fontSize: 12, fontWeight: 700, color: desk.text, cursor: 'pointer',
        display: 'flex', alignItems: 'center', gap: 8, listStyle: 'none',
      }}>
        <span>How grading &amp; audit works</span>
        <span style={{ fontSize: 9, color: desk.textDim, fontWeight: 500 }}>7 layers · what blocks auto-route</span>
      </summary>

      <div style={{ marginTop: 12, display: 'grid', gap: 8 }}>
        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 6,
          padding: '8px 10px', borderRadius: desk.radiusLg, background: desk.bgInset,
          border: `1px solid ${desk.borderSubtle}`, fontSize: 9,
        }}>
          {GRADE_TABLE.map(row => (
            <div key={row.label}>
              <div style={{ fontWeight: 800, color: desk.text }}>{row.label}</div>
              <div style={{ color: desk.textMuted, lineHeight: 1.4 }}>{row.meaning}</div>
              <div style={{ color: desk.blue, marginTop: 2 }}>Live? {row.live}</div>
            </div>
          ))}
        </div>

        {LAYERS.map(layer => (
          <div key={layer.id} style={{
            padding: '10px 12px', borderRadius: desk.radiusLg,
            background: desk.bgInset, border: `1px solid ${desk.borderSubtle}`,
          }}>
            <div style={{ fontSize: 11, fontWeight: 700, color: desk.text, marginBottom: 4 }}>{layer.title}</div>
            <div style={{ fontSize: 10, color: 'var(--text1)', lineHeight: 1.5 }}>{layer.summary}</div>
            {layer.blocksRoute && (
              <div style={{ fontSize: 9, color: desk.red, marginTop: 4 }}>Blocks auto-route: {layer.blocksRoute}</div>
            )}
            <div style={{ fontSize: 9, color: desk.textDim, marginTop: 4, fontFamily: desk.mono }}>{layer.backend}</div>
          </div>
        ))}

        <div style={{
          padding: '10px 12px', borderRadius: desk.radiusLg,
          background: desk.amberDim, border: '1px solid rgba(245,158,11,.22)',
          fontSize: 10, color: 'var(--text1)', lineHeight: 1.5,
        }}>
          <div style={{ ...sectionLabel, color: desk.amber, marginBottom: 4 }}>Agents &amp; LLM maturity</div>
          <b>Right agents?</b> Maria + Risk + Steph are correct for swing/pullback proposals. Aegis is desk supervisor (optional).
          <br />
          <b>Strong enough?</b> Local gemma3:4b is fast triage — not institutional depth. Cloud OAuth (Grok/ChatGPT) adds reasoning but needs Validate first so they see live price.
          <br />
          <b>Backend maturity:</b> Gates (trade plan, sizing, oversight) are production-grade and hard-block live routes. Agent job queue has backlog risk (144+ queued) — sync on detail load now backfills completed jobs.
          <br />
          <b>ATM vs broker proposals:</b> ATM entries (GOOGL, TECH) and protection rows (AGNC) share this queue when kind=all. ATM protection uses negative IDs — no cloud oversight, auto-apply gated separately.
          <br />
          <span style={{ color: desk.text }}>None of these layers approve live trades alone</span> — oversight BLOCK + trade-plan gate + Litmus NO-GO + 2FA route win.
        </div>

        <div style={{ fontSize: 9, color: desk.textDim, lineHeight: 1.45 }}>
          Path B: queue agents → stage 2b → refresh prices → validate (Litmus) → re-run cloud if split → auto route (2FA).
          Trade-plan BLOCK? Run materialize_watchlist_strategy_cards + bridge refresh so stop/target anchor to support/resistance — not pure 2×risk math.
        </div>
      </div>
    </details>
  )
}