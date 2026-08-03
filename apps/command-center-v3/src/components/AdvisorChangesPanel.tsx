// Advisory-only changelog for rotation / LLM second-opinion — folded into Rotation hub.

const card: React.CSSProperties = {
  background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16,
  display: 'flex', flexDirection: 'column', gap: 6,
}

type Change = {
  title: string
  pill: string
  pillColor: string
  source: string
  improves: string
  validate: string
}

const CHANGES: Change[] = [
  {
    title: 'Grounded Rotation Advisor',
    pill: 'active', pillColor: '#22c55e',
    source: 'scripts/rotation_llm_advisor.py',
    improves: 'Grounds every rotation review in real holdings + symbol cards before a single word of advice is written.',
    validate: 'Run with --question and confirm answer_mode reports a grounded review.',
  },
  {
    title: 'Local LLM Validation',
    pill: 'active', pillColor: '#22c55e',
    source: 'scripts/rotation_llm_advisor.py',
    improves: 'Checks the local model answer for unsupported claims and surfaces issues instead of trusting it blindly.',
    validate: 'Inspect local_answer_validation.ok and the issues list in the JSON output.',
  },
  {
    title: 'Cloud Second Opinion',
    pill: 'active', pillColor: '#f59e0b',
    source: 'scripts/rotation_dual_llm_advisor.py',
    improves: 'Builds a copy-paste prompt for a free cloud second opinion. No API key is used.',
    validate: 'Run with --print-grok-prompt and paste the result into a cloud LLM via free/OAuth login.',
  },
  {
    title: 'Fidelity Fund Code Mapping',
    pill: 'active', pillColor: '#60a5fa',
    source: 'config/fidelity_fund_code_map.json',
    improves: 'Maps Fidelity fund codes to underlying tickers so look-through review is account-aware and accurate.',
    validate: 'Confirm fund codes resolve to symbols in the rotation summary data_quality counts.',
  },
  {
    title: 'Symbol Card Quality',
    pill: 'active', pillColor: '#a855f7',
    source: 'scripts/validate_symbol_card_quality.py',
    improves: 'Flags missing sector, analyst upside, and stale cards so reviews are not grounded in thin data.',
    validate: 'Run the validator and compare against missing_sector / data_quality in the summary.',
  },
  {
    title: 'Safety / No Broker Action',
    pill: 'enforced', pillColor: '#ef4444',
    source: 'scripts/rotation_dual_llm_advisor.py',
    improves: 'Every surface is advisory only — review, watch, second opinion. Nothing executes, buys, or sells.',
    validate: 'Confirm advisory_only is true in the JSON and no order/execution path exists.',
  },
]

export default function AdvisorChangesPanel() {
  return (
    <div>
      <div style={{ fontSize: 12, color: 'var(--text2)', marginBottom: 14 }}>
        What each rotation advisor piece improves and how to validate it.
      </div>
      <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 12, marginBottom: 22 }}>
        {CHANGES.map((c) => (
          <div key={c.title} style={card}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>{c.title}</span>
              <span style={{ flex: 1 }} />
              <span style={{
                fontSize: 9, fontWeight: 800, padding: '2px 8px', borderRadius: 4, letterSpacing: 0.4,
                background: `${c.pillColor}1f`, color: c.pillColor, border: `1px solid ${c.pillColor}44`,
              }}>{c.pill}</span>
            </div>
            <div style={{ fontSize: 9.5, fontFamily: 'monospace', color: '#60a5fa' }}>{c.source}</div>
            <div style={{ fontSize: 11, color: 'var(--text2)', lineHeight: 1.5 }}>
              <b style={{ color: 'var(--text3)' }}>Improves: </b>{c.improves}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text2)', lineHeight: 1.5 }}>
              <b style={{ color: 'var(--text3)' }}>Validate: </b>{c.validate}
            </div>
          </div>
        ))}
      </section>
      <section style={card}>
        <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Validation commands</div>
        <pre style={{
          fontSize: 10.5, fontFamily: 'monospace', background: 'var(--bg2)', color: 'var(--text1)',
          padding: 12, borderRadius: 8, whiteSpace: 'pre-wrap', overflow: 'auto', margin: 0,
        }}>{`python3 scripts/rotation_dual_llm_advisor.py \\
  --question "Should I trim XLB for SPCX? How much should I trim?" \\
  --cards data/runtime/symbol_cards_latest.json \\
  --json | jq -r '.answer_mode'
python3 scripts/rotation_dual_llm_advisor.py \\
  --question "Should I trim XLB for SPCX? How much should I trim?" \\
  --cards data/runtime/symbol_cards_latest.json \\
  --print-grok-prompt`}</pre>
        <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 8 }}>
          Cloud LLM is free / OAuth / manual-paste only — no API key is used in any of the above.
        </div>
      </section>
    </div>
  )
}