import { useState } from 'react'
import { EnsembleValidationCard, normalizeEnsembleResult } from './EnsembleValidationCard'
import { EvidenceBlock } from './EvidenceBlock'
import AgentConsensusPanel from './AgentConsensusPanel'
import { desk, sectionLabel } from '../lib/proposalDeskTheme'


const MUTED = desk.textDim
const TEXT0 = desk.text
const TEXT1 = 'var(--text1)'
const GREEN = desk.green
const AMBER = desk.amber
const BLUE = desk.blue
const RED = desk.red
const PURPLE = desk.purple
const sec = { ...sectionLabel, fontSize: 11, fontWeight: 800, letterSpacing: '0.4px', marginBottom: 4 }
const body = { fontSize: 10, color: TEXT1, lineHeight: 1.45 }

function voteColor(vote: string | null | undefined) {
  const v = String(vote || '').toUpperCase()
  if (v === 'BLOCK' || v === 'REJECT') return RED
  if (v === 'APPROVE_TEST') return GREEN
  if (v === 'CAUTIOUS_TEST' || v === 'WAIT_FOR_DATA') return AMBER
  if (!v || v === 'PENDING') return MUTED
  return TEXT0
}

function cloudColor(status: string | null | undefined) {
  const s = String(status || '').toLowerCase()
  if (s === 'agree') return GREEN
  if (s === 'caution') return AMBER
  if (s === 'disagree') return RED
  if (s === 'running') return AMBER
  return MUTED
}

function criticColor(verdict: string | null | undefined) {
  const v = String(verdict || '').toUpperCase()
  if (v === 'BLOCK') return RED
  if (v === 'DOWNGRADE') return AMBER
  if (v === 'CONFIRM' || v === 'PASS') return GREEN
  return TEXT1
}

const TEAL = '#2dd4bf'
function gradeColor(g: string | null | undefined) {
  const v = String(g || '').toUpperCase()
  if (v.includes('INCOMPLETE') || v.includes('FAIL') || v.startsWith('D') || v.startsWith('F')) return RED
  if (v.startsWith('A')) return GREEN
  if (v.startsWith('B')) return TEAL
  if (v.startsWith('C')) return AMBER
  return MUTED
}
function GradePill({ grade, prefix }: { grade: string; prefix?: string }) {
  const c = gradeColor(grade)
  return (
    <span style={{ fontSize: 12, fontWeight: 900, padding: '1px 7px', borderRadius: 5, background: `${c}22`, color: c, border: `1px solid ${c}`, letterSpacing: '.3px' }}>
      {prefix}{grade}
    </span>
  )
}

const VOTE_BUCKETS = [
  { key: 'strong_buy', label: 'Strong buy', color: '#16a34a' },
  { key: 'buy', label: 'Buy', color: '#4ade80' },
  { key: 'hold', label: 'Hold', color: '#94a3b8' },
  { key: 'sell', label: 'Sell', color: '#fb923c' },
  { key: 'strong_sell', label: 'Strong sell', color: '#ef4444' },
] as const

const SOURCE_LABELS: Record<string, string> = {
  yahoo: 'Yahoo',
  finviz: 'Finviz',
  pro_analyst: 'Pro-analyst',
  finnhub: 'Finnhub',
}

function coverageColor(cov: string | null | undefined) {
  const c = String(cov || '').toLowerCase()
  if (c === 'broad') return GREEN
  if (c === 'moderate') return BLUE
  if (c === 'thin') return AMBER
  return MUTED
}

function fmtRating(r: string | null | undefined) {
  return String(r || '—').replace(/_/g, ' ')
}

function AnalystSourceRow({ src, compact = false }: { src: any; compact?: boolean }) {
  const label = SOURCE_LABELS[src.source] || src.source || '—'
  const rating = fmtRating(src.rating)
  const ratingColor = String(src.rating || '').includes('buy') ? GREEN
    : String(src.rating || '').includes('sell') ? RED : TEXT0

  if (src.source === 'pro_analyst') {
    return (
      <div style={{ fontSize: 11.5, padding: '5px 0', borderBottom: '1px solid rgba(148,163,184,.08)' }}>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'baseline' }}>
          <b style={{ color: PURPLE, minWidth: 72 }}>{label}</b>
          <span style={{ color: TEXT1 }}>
            Internal <b style={{ color: src.internal_direction === 'bearish' ? RED : src.internal_direction === 'bullish' ? GREEN : TEXT0 }}>{src.internal_direction || '—'}</b>
            {' vs '}Street <b>{src.street_direction || '—'}</b>
            {src.divergence ? <span style={{ color: src.divergence === 'mixed' || src.divergence === 'divergent' ? AMBER : MUTED }}> · {src.divergence}</span> : null}
          </span>
          {src.confidence && <span style={{ color: String(src.confidence).toLowerCase() === 'low' ? AMBER : MUTED }}>conf {src.confidence}</span>}
        </div>
        {src.target != null && (
          <div style={{ fontSize: 11, color: MUTED, marginTop: 2, fontFamily: 'monospace' }}>
            Target ${src.target}
            {src.upside_pct != null && <span style={{ color: src.upside_pct >= 0 ? GREEN : RED, marginLeft: 6 }}>{src.upside_pct >= 0 ? '+' : ''}{src.upside_pct}%</span>}
            {src.opinions != null ? ` · ${src.opinions} analyst${src.opinions === 1 ? '' : 's'}` : ''}
          </div>
        )}
        {src.latest_event && (
          <div style={{ fontSize: 11, color: AMBER, marginTop: 3 }}>
            Latest: {src.latest_event_type ? `${src.latest_event_type.replace(/_/g, ' ')} — ` : ''}{String(src.latest_event).slice(0, compact ? 100 : 180)}
            {src.latest_event_at ? <span style={{ color: MUTED }}> · {String(src.latest_event_at).slice(0, 10)}</span> : null}
          </div>
        )}
      </div>
    )
  }

  return (
    <div style={{ fontSize: 11.5, padding: '5px 0', borderBottom: '1px solid rgba(148,163,184,.08)' }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'baseline' }}>
        <b style={{ color: label === 'Yahoo' ? BLUE : TEXT0, minWidth: 72 }}>{label}</b>
        <span style={{ color: ratingColor, fontWeight: 700, fontFamily: 'monospace' }}>{rating}</span>
        {src.opinions != null && <span style={{ color: MUTED }}>{src.opinions} analyst{src.opinions === 1 ? '' : 's'}</span>}
        {src.recom_score != null && <span style={{ color: MUTED, fontFamily: 'monospace' }}>score {Number(src.recom_score).toFixed(2)}</span>}
        {src.mean != null && <span style={{ color: MUTED, fontFamily: 'monospace' }}>mean {src.mean}</span>}
      </div>
      {(src.target != null || src.upside_pct != null) && (
        <div style={{ fontSize: 11, color: MUTED, marginTop: 2, fontFamily: 'monospace' }}>
          {src.target != null && <>Target <b style={{ color: BLUE }}>${src.target}</b></>}
          {src.upside_pct != null && (
            <span style={{ color: src.upside_pct >= 0 ? GREEN : RED, marginLeft: src.target != null ? 6 : 0 }}>
              {src.upside_pct >= 0 ? '+' : ''}{src.upside_pct}% vs current
            </span>
          )}
          {(src.target_low != null || src.target_high != null) && (
            <span style={{ marginLeft: 6 }}>range ${src.target_low ?? '—'} – ${src.target_high ?? '—'}</span>
          )}
        </div>
      )}
    </div>
  )
}

function AnalystVoteBar({ dist }: { dist: Record<string, number> }) {
  const total = VOTE_BUCKETS.reduce((s, b) => s + (Number(dist[b.key]) || 0), 0)
  if (!total) return null
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ display: 'flex', height: 8, borderRadius: 4, overflow: 'hidden', background: 'rgba(15,23,42,.6)' }}>
        {VOTE_BUCKETS.map(b => {
          const n = Number(dist[b.key]) || 0
          if (!n) return null
          return (
            <div key={b.key} title={`${b.label}: ${n}`}
              style={{ width: `${(n / total) * 100}%`, background: b.color, minWidth: n ? 4 : 0 }} />
          )
        })}
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 10px', marginTop: 6, fontSize: 11, color: MUTED }}>
        {VOTE_BUCKETS.map(b => {
          const n = Number(dist[b.key]) || 0
          if (!n) return null
          return (
            <span key={b.key}><span style={{ color: b.color, fontWeight: 700 }}>{n}</span> {b.label}</span>
          )
        })}
      </div>
    </div>
  )
}

function CatalystCritic({ cat, compact }: { cat: any; compact: boolean }) {
  const [open, setOpen] = useState(!compact && ['BLOCK', 'DOWNGRADE'].includes(String(cat.critic_verdict || '').toUpperCase()))
  const reasoning = cat.critic_reasoning ? String(cat.critic_reasoning).trim() : ''
  const previewLen = compact ? 140 : 220
  const preview = reasoning.slice(0, previewLen)
  const hasMore = reasoning.length > previewLen

  return (
    <>
      {cat.critic_verdict && (
        <div style={{ fontSize: 11, color: criticColor(cat.critic_verdict), marginTop: 4, fontWeight: 700 }}>
          Critic: {cat.critic_verdict}
        </div>
      )}
      {reasoning ? (
        <div style={{ marginTop: 6 }}>
          <div style={{ fontSize: 11, color: MUTED, marginBottom: 3 }}>Catalyst review</div>
          <div style={{ ...body, fontSize: 11.5, color: TEXT1 }}>
            {open ? reasoning : (hasMore ? `${preview}…` : reasoning)}
          </div>
          {hasMore && (
            <button type="button" onClick={() => setOpen(v => !v)}
              style={{ marginTop: 4, fontSize: 11, fontWeight: 700, padding: 0, border: 'none', background: 'transparent', color: BLUE, cursor: 'pointer' }}>
              {open ? 'Show less' : 'Show full critic review'}
            </button>
          )}
        </div>
      ) : cat.critic_verdict ? (
        <div style={{ fontSize: 11, color: MUTED, marginTop: 4, fontStyle: 'italic' }}>No critic narrative stored for this scan.</div>
      ) : null}
    </>
  )
}

type Props = {
  intel?: any
  compact?: boolean
  onQueueOversight?: () => void
  onRunCloudOversight?: () => void
  oversightBusy?: boolean
  cloudBusy?: boolean
  /** When the host already renders the blocker/violation list (e.g. the proposal card's route
   *  blocker box), suppress the duplicate ⛔/⚠ list at the bottom of the oversight block. */
  suppressViolationList?: boolean
  /** When the host already shows the strategy purpose elsewhere (card "Strategy" cell),
   *  suppress the duplicate "Strategy: …" line inside "Why purchase". */
  suppressStrategyPurpose?: boolean
  /** When the host card already renders the company description (its "Company" cell), suppress the
   *  duplicate "What the company does" block here. */
  suppressCompanyPurpose?: boolean
  /** Proposal origin (watchlist | scanner | …) — drives the honest "why no momentum technicals" note. */
  sourceKind?: string
  /** When set, AgentConsensus shows per-lane ▶ Grok / ▶ ChatGPT (à la carte). */
  proposalId?: number
  onCloudLaneDone?: (result?: any) => void
}

export default function BrokerIntelPanel({
  intel, compact = false, onQueueOversight, onRunCloudOversight, oversightBusy, cloudBusy,
  suppressViolationList = false, suppressStrategyPurpose = false, suppressCompanyPurpose = false, sourceKind = '',
  proposalId, onCloudLaneDone,
}: Props) {
  if (!intel?.ok) {
    return (
      <div style={{ padding: compact ? '6px 0' : '10px 12px', fontSize: 10, color: MUTED, fontStyle: 'italic' }}>
        Decision context not loaded — run Enrich on the paper proposal or refresh.
      </div>
    )
  }

  const co = intel.company || {}
  const cat = intel.catalyst || {}
  const tech = intel.technicals || {}
  const an = intel.analyst
  const why = intel.why_purchase || {}
  const reviews: any[] = intel.agent_reviews || []
  const news: any[] = intel.news || []
  const newsMeta: any = intel.news_meta || {}
  const oversight = intel.oversight || {}
  const ovAgents = oversight.agents || {}
  const localLlm = oversight.local_llm || {}
  const cloud = oversight.cloud_review || {}
  // App-standard scored ensemble (Grok + ChatGPT + Gemma). Present on proposals that carry a
  // structured ensemble verdict; when absent we fall back to the per-lane cloud rendering below.
  const ensembleResult = normalizeEnsembleResult(
    intel.ensemble || oversight.ensemble || cloud.ensemble,
  )
  const lanes = oversight.lanes_available || {}
  const ovViolations: string[] = oversight.violations || []
  const ovWarnings: string[] = oversight.warnings || []
  const ovStatus = oversight.status || (ovViolations.length ? 'BLOCK' : ovWarnings.length ? 'WARN' : reviews.length ? 'PENDING' : null)
  const showOversight = Boolean(ovStatus || reviews.length > 0 || onQueueOversight || onRunCloudOversight
    || proposalId || ovViolations.length || ovWarnings.length)
  const dist = an?.distribution as Record<string, number> | null | undefined
  const hasDist = dist && VOTE_BUCKETS.some(b => Number(dist[b.key]) > 0)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: compact ? 8 : 10 }}>
      {showOversight && (
        <AgentConsensusPanel
          reviews={reviews}
          oversight={oversight}
          localLlm={localLlm}
          cloud={cloud}
          lanes={lanes}
          onQueueOversight={onQueueOversight}
          onRunCloudOversight={onRunCloudOversight}
          oversightBusy={oversightBusy}
          cloudBusy={cloudBusy}
          ovStatus={ovStatus}
          proposalId={proposalId}
          onCloudLaneDone={onCloudLaneDone}
        />
      )}
      {showOversight && ensembleResult && (
        <EnsembleValidationCard result={ensembleResult} onRevalidate={onRunCloudOversight} />
      )}
      {showOversight && !suppressViolationList && ovViolations.map((v, i) => (
        <div key={`v${i}`} style={{ fontSize: 10, color: desk.red, marginTop: 3 }}>⛔ {v}</div>
      ))}
      {showOversight && !suppressViolationList && ovWarnings.map((w, i) => (
        <div key={`w${i}`} style={{ fontSize: 10, color: desk.amber, marginTop: 3 }}>⚠ {w}</div>
      ))}

      {!suppressCompanyPurpose && co.description && (
        <div>
          <div style={sec}>What the company does</div>
          <div style={body}>{co.description}</div>
          {(co.sector || co.industry) && (
            <div style={{ fontSize: 11, color: MUTED, marginTop: 3 }}>{[co.sector, co.industry].filter(Boolean).join(' · ')}</div>
          )}
        </div>
      )}

      {(why.headline || why.approve_case || why.strategy_purpose) && (
        <div style={{ padding: '8px 10px', borderRadius: 8, background: desk.bg, border: `1px solid ${desk.border}`, borderLeft: `3px solid ${desk.green}` }}>
          <div style={sec}>Why purchase</div>
          {why.strategy_purpose && !suppressStrategyPurpose && <div style={{ fontSize: 11, color: MUTED, marginBottom: 4 }}>Strategy: {why.strategy_purpose}</div>}
          <div style={body}>{why.headline || why.approve_case || why.summary}</div>
          {why.rr != null && (
            <div style={{ fontSize: 11, color: MUTED, marginTop: 4, display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
              Plan R:R {why.rr}:1
              {why.screener_grade ? <GradePill grade={`${why.screener_grade} screener`} prefix="" /> : why.signal_grade ? <GradePill grade={`${why.signal_grade} screener`} prefix="" /> : null}
              {why.finviz_grade ? <GradePill grade={`${why.finviz_grade} finviz`} prefix="" /> : null}
            </div>
          )}
          {why.invalidation && <div style={{ fontSize: 11, color: AMBER, marginTop: 4 }}>Invalidate if: {why.invalidation}</div>}
          {why.reject_case && <div style={{ fontSize: 11, color: RED, marginTop: 4 }}>Bear case: {String(why.reject_case).slice(0, 200)}</div>}
        </div>
      )}

      {/* Detail sections tile into the free width (auto-fit) instead of stacking in one tall column. */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 8, alignItems: 'start' }}>
        {(cat.text || cat.critic_verdict || cat.critic_reasoning) && (
          <div style={{ padding: '8px 10px', borderRadius: 8, background: desk.bg, border: `1px solid ${desk.border}`, borderLeft: `3px solid ${desk.amber}` }}>
            {(() => {
              // Confidence-aware badge: a 'verified' flag with ~0% confidence is not really verified
              // (TECH showed ✅ over 'Confidence 0%'). Treat low-confidence as unverified for the badge.
              const _cpct = cat.confidence != null ? (Number(cat.confidence) <= 1 ? Number(cat.confidence) * 100 : Number(cat.confidence)) : null
              const _trusted = !!cat.verified && (_cpct == null || _cpct >= 30)
              return <div style={sec}>Catalyst {_trusted ? '✅' : '⚠️'}{cat.verified && !_trusted ? ' (low-confidence)' : ''}</div>
            })()}
            <div style={body}>{cat.text ? String(cat.text).slice(0, compact ? 220 : 400) : '—'}</div>
            {cat.confidence != null && <div style={{ fontSize: 11, color: MUTED, marginTop: 3 }}>Confidence {Math.round((Number(cat.confidence) <= 1 ? Number(cat.confidence) * 100 : Number(cat.confidence)))}%</div>}
            <CatalystCritic cat={cat} compact={compact} />
          </div>
        )}

      {an && (
        <div style={{ padding: '8px 10px', borderRadius: 8, background: desk.bg, border: `1px solid ${desk.border}` }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 6, marginBottom: 4 }}>
            <div style={{ ...sec, marginBottom: 0 }}>
              Analyst consensus
              {an.quality?.source_count ? ` · ${an.quality.source_count} source${an.quality.source_count === 1 ? '' : 's'}` : ''}
            </div>
            {an.quality?.coverage && (
              <span style={{ fontSize: 11, fontWeight: 800, padding: '2px 7px', borderRadius: 4, background: `${coverageColor(an.quality.coverage)}18`, color: coverageColor(an.quality.coverage) }}>
                {String(an.quality.coverage).toUpperCase()} COVERAGE
              </span>
            )}
          </div>

          <div style={{ fontSize: 11, fontWeight: 700, color: String(an.rating || '').includes('buy') ? GREEN : TEXT0, fontFamily: 'monospace' }}>
            {fmtRating(an.rating)}
            {an.opinions != null ? ` · ${an.opinions} analyst${an.opinions === 1 ? '' : 's'}` : ''}
            {an.mean != null ? ` · score ${an.mean}` : ''}
            {an.primary_source && <span style={{ fontSize: 11, color: MUTED, fontWeight: 500 }}> ({SOURCE_LABELS[an.primary_source] || an.primary_source})</span>}
          </div>
          <div style={{ fontSize: 10, color: TEXT1, marginTop: 5, fontFamily: desk.mono }}>
            {an.target != null && <span>Street mean <b style={{ color: BLUE }}>${an.target}</b></span>}
            {an.upside_pct != null && (
              <span style={{ color: an.upside_pct >= 0 ? GREEN : RED, marginLeft: 8 }}>
                {an.upside_pct >= 0 ? '+' : ''}{an.upside_pct}% vs current
              </span>
            )}
            {an.sources?.[0]?.as_of && (
              <span style={{ color: MUTED, marginLeft: 8, fontSize: 9 }}>
                · Yahoo {an.sources[0].as_of}
                {(() => {
                  const d = new Date(an.sources[0].as_of)
                  const age = Number.isNaN(d.getTime()) ? null : Math.floor((Date.now() - d.getTime()) / 86_400_000)
                  return age != null && age > 7 ? ` (${age}d old)` : ''
                })()}
              </span>
            )}
          </div>
          <div style={{ fontSize: 9, color: MUTED, marginTop: 4, fontStyle: 'italic' }}>
            Street target ≠ plan target on the card header — plan uses technical/R:R levels; street is sell-side consensus.
          </div>
          {(an.target_low != null || an.target_high != null) && (
            <div style={{ fontSize: 11, color: MUTED, marginTop: 4 }}>
              Street range ${an.target_low ?? '—'} – ${an.target_high ?? '—'}
            </div>
          )}

          {(an.quality?.warnings?.length > 0) && (
            <div style={{ marginTop: 6 }}>
              {an.quality.warnings.map((w: string, i: number) => (
                <div key={i} style={{ fontSize: 11, color: AMBER, marginTop: i ? 2 : 0 }}>⚠ {w}</div>
              ))}
            </div>
          )}

          {an.opinions === 1 && (
            <div style={{ fontSize: 11, color: AMBER, marginTop: 6, padding: '5px 8px', borderRadius: 6, background: 'rgba(245,158,11,.08)', border: '1px solid rgba(245,158,11,.2)' }}>
              Single-analyst coverage is unreliable for micro-caps — treat street target as directional only, not a sizing input.
            </div>
          )}

          {(an.sources?.length > 1) && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontSize: 11, color: MUTED, marginBottom: 2 }}>Sources</div>
              {an.sources.map((src: any, i: number) => (
                <AnalystSourceRow key={`${src.source}-${i}`} src={src} compact={compact} />
              ))}
            </div>
          )}

          {hasDist ? (
            <>
              <div style={{ fontSize: 11, color: MUTED, marginTop: 6 }}>Analyst vote distribution{an.sources?.[0]?.distribution_provider ? ` (${an.sources[0].distribution_provider})` : ''}</div>
              <AnalystVoteBar dist={dist!} />
            </>
          ) : (
            <div style={{ fontSize: 11, color: MUTED, marginTop: 6, fontStyle: 'italic' }}>
              Vote breakdown not loaded — rating/target from {an.sources?.length ? an.sources.map((s: any) => SOURCE_LABELS[s.source] || s.source).join(', ') : 'Yahoo'}.
            </div>
          )}
        </div>
      )}
      </div>

      <div style={{
        padding: '8px 10px', borderRadius: desk.radiusLg,
        background: news.length ? desk.bgInset : desk.amberDim,
        border: `1px solid ${news.length ? desk.borderSubtle : 'rgba(245,158,11,.2)'}`,
      }}>
        <div style={sec}>Recent news{newsMeta.window_days ? ` · last ${newsMeta.window_days}d` : ''}</div>
        {news.length > 0 ? news.slice(0, compact ? 2 : 3).map((n, i) => (
          <div key={i} style={{ fontSize: 11, color: TEXT1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', marginTop: i ? 4 : 0 }}>
            <span style={{ color: MUTED }}>{n.source} · </span>{n.title}
            {n.at && <span style={{ color: MUTED, fontSize: 9 }}> · {String(n.at).slice(0, 10)}</span>}
          </div>
        )) : (
          <div style={{ fontSize: 10, color: AMBER, lineHeight: 1.45 }}>
            No headlines in DB for this symbol
            {newsMeta.window_days ? ` (checked ${newsMeta.window_days}-day window)` : ''}.
            {newsMeta.ingest_hint ? ` ${newsMeta.ingest_hint}` : ' Proposal symbols are now pinned first in news_ingestion — refresh after cron or run ingest manually.'}
          </div>
        )}
      </div>
    </div>
  )
}