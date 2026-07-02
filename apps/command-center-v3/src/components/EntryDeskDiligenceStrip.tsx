type SourceKind = 'PROPOSAL' | 'WATCHLIST' | 'DRAFT'

const C = {
  dim: 'var(--text3)',
  green: '#22c55e',
  amber: '#f59e0b',
  red: '#ef4444',
  blue: '#60a5fa',
  purple: '#a78bfa',
}

export type WatchlistDiligence = {
  analysisStage?: string | null
  maria?: string | null
  steph?: string | null
  risk?: string | null
  tax?: string | null
  synthesis?: string | null
  researchCard?: string | null
  synthesisStatus?: string | null
  grokRec?: string | null
  chatgptRec?: string | null
  decisionSafety?: string | null
  modelsAgree?: boolean | null
  actionable?: boolean | null
  entryPlannedAt?: string | null
  catalyst?: string | null
  entryModel?: string | null
  narrativeSnip?: string | null
  conflictsSnip?: string | null
  unresolved?: string[] | null
  dataIDoubt?: string | null
}

type Props = {
  source: SourceKind
  symbol: string
  diligence?: WatchlistDiligence | null
  analystRating?: string | null
}

function statusColor(s?: string | null) {
  const v = String(s ?? '').toLowerCase()
  if (v === 'completed' || v === 'pass' || v === 'ready' || v === 'safe') return C.green
  if (v === 'processing' || v === 'pending' || v === 'queued') return C.amber
  if (v === 'failed' || v === 'block' || v === 'rejected' || v === 'unsafe' || v === 'blocked') return C.red
  return C.dim
}

function recColor(rec?: string | null) {
  const r = String(rec ?? '').toUpperCase()
  if (r.includes('STRONG') && r.includes('BUY') || r === 'BUY' || r === 'ADD' || r === 'ADD_ON_PULLBACK') return C.green
  if (r === 'HOLD' || r === 'RESEARCH_MORE') return C.amber
  if (r === 'AVOID' || r === 'IGNORE' || r === 'SELL') return C.red
  return C.dim
}

function Pill({ text, color }: { text: string; color: string }) {
  return (
    <span style={{
      fontSize: 8.5, fontWeight: 800, padding: '2px 6px', borderRadius: 4,
      background: `${color}18`, color, border: `1px solid ${color}33`,
    }}>
      {text}
    </span>
  )
}

export default function EntryDeskDiligenceStrip({ source, symbol, diligence, analystRating }: Props) {
  if (source === 'DRAFT') {
    return (
      <div style={{ marginTop: 6, padding: '5px 8px', borderRadius: 6, background: 'rgba(167,139,250,.08)', border: '1px solid rgba(167,139,250,.2)', fontSize: 9, color: C.dim }}>
        <span style={{ color: C.purple, fontWeight: 800 }}>Draft · </span>
        Broker intent (Stage 2c protective or test). No entry diligence chain — operator ticket only.
      </div>
    )
  }

  if (source === 'PROPOSAL') {
    return (
      <div style={{ marginTop: 6, padding: '5px 8px', borderRadius: 6, background: 'rgba(34,197,94,.06)', border: '1px solid rgba(34,197,94,.2)', fontSize: 9, color: C.dim }}>
        <span style={{ color: C.green, fontWeight: 800 }}>Paper proposal · </span>
        Full broker diligence on{' '}
        <a href={`/v3/trading?tab=Proposals&symbol=${symbol}`} style={{ color: C.blue, fontWeight: 700 }}>Proposals</a>
        {' '}— Auto route (2FA) for Schwab submit.
      </div>
    )
  }

  const d = diligence
  const cio = String(d?.synthesis ?? '').toUpperCase()
  const analyst = String(analystRating ?? '').toUpperCase()
  const analystBull = analyst.includes('BUY') || analyst === 'ADD'
  const cioBear = ['AVOID', 'IGNORE', 'SELL'].includes(cio)
  const split = analystBull && cioBear

  return (
    <div style={{ marginTop: 6, padding: '6px 8px', borderRadius: 6, background: 'rgba(15,23,42,.48)', border: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: 5 }}>
        <span style={{ fontSize: 8, fontWeight: 900, color: C.blue, textTransform: 'uppercase', letterSpacing: '.3px' }}>
          CIO synthesis (portfolio mandate) · not Finviz analyst
        </span>
        {d?.actionable != null && (
          <Pill text={d.actionable ? 'CIO actionable' : 'CIO not actionable'} color={d.actionable ? C.green : C.amber} />
        )}
      </div>

      {split && (
        <div style={{ marginBottom: 6, padding: '5px 7px', borderRadius: 5, background: 'rgba(245,158,11,.08)', border: '1px solid rgba(245,158,11,.25)', fontSize: 9, color: C.amber, lineHeight: 1.45 }}>
          <b>Rating split:</b> Finviz analyst says <span style={{ color: C.green, fontWeight: 800 }}>{analystRating}</span> but CIO says <span style={{ color: C.red, fontWeight: 800 }}>{d?.synthesis}</span>.
          CIO applies retirement-income mandate + position context (often AVOID on non-held speculative names). Proposals bridge uses research card / CIO — not Finviz pills alone.
        </div>
      )}

      <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center', marginBottom: 5 }}>
        {d?.researchCard && <Pill text={`research ${d.researchCard}`} color={recColor(d.researchCard)} />}
        {d?.synthesis && <Pill text={`CIO ${d.synthesis}`} color={recColor(d.synthesis)} />}
        {d?.grokRec && <Pill text={`Grok ${d.grokRec}`} color={recColor(d.grokRec)} />}
        {d?.chatgptRec && <Pill text={`GPT ${d.chatgptRec}`} color={recColor(d.chatgptRec)} />}
        {d?.decisionSafety && <Pill text={`safety ${d.decisionSafety}`} color={statusColor(d.decisionSafety)} />}
        {d?.modelsAgree != null && (
          <Pill text={d.modelsAgree ? 'Grok+GPT agree' : 'Grok/GPT split'} color={d.modelsAgree ? C.green : C.amber} />
        )}
        {d?.analysisStage && <Pill text={`stage ${d.analysisStage}`} color={C.blue} />}
        {d?.maria && <Pill text={`Maria ${d.maria}`} color={statusColor(d.maria)} />}
        {d?.steph && <Pill text={`Steph ${d.steph}`} color={statusColor(d.steph)} />}
        {d?.risk && <Pill text={`Risk ${d.risk}`} color={statusColor(d.risk)} />}
      </div>

      {d?.narrativeSnip && (
        <div style={{ fontSize: 9.5, color: 'var(--text2)', lineHeight: 1.5, fontStyle: 'italic', marginBottom: 5 }}>
          {d.narrativeSnip}
        </div>
      )}

      {d?.conflictsSnip && (
        <div style={{ fontSize: 8.5, color: C.amber, marginBottom: 4 }}>Conflicts: {d.conflictsSnip}</div>
      )}

      {d?.unresolved && d.unresolved.length > 0 && (
        <div style={{ fontSize: 8.5, color: C.dim, marginBottom: 4 }}>
          Unresolved: {d.unresolved.join(' · ')}
        </div>
      )}

      {d?.dataIDoubt && d.dataIDoubt !== 'none' && (
        <div style={{ fontSize: 8.5, color: C.red, marginBottom: 4 }}>Data doubt: {d.dataIDoubt}</div>
      )}

      {(d?.catalyst || d?.entryPlannedAt) && (
        <div style={{ marginTop: 2, fontSize: 8.5, color: C.dim, lineHeight: 1.4 }}>
          {d.catalyst && <span>Catalyst: {String(d.catalyst).slice(0, 120)} · </span>}
          {d.entryPlannedAt && <span>Entry plan {String(d.entryPlannedAt).slice(0, 16)}{d.entryModel ? ` (${d.entryModel})` : ''}</span>}
        </div>
      )}

      <div style={{ marginTop: 5, fontSize: 8.5, color: C.dim }}>
        Not in Proposals? Bridge requires research-card/CIO BUY+ and authoritative trade plan — use <b>→ Broker queue</b> to force manual promote.
      </div>
    </div>
  )
}