/** Investment Opportunity modal (operator 2026-10-08): everything needed to decide from the dashboard —
 *  market data, technicals + chart, Street view, risk/reward ladder, portfolio context + stance, conviction
 *  breakdown, CIO thesis / AI brief, what the company does, catalysts and latest news (operator 2026-10-08). Curated assessment from CIO memory; live values read at request time.
 *  Data: GET /api/v3/opportunities/{symbol}. Read-only; stance is a label, never an instruction. */
import { useState, type ReactNode } from 'react'
import { useApi } from '../../hooks/useApi'
import { RADIUS, TOKENS, numStyle } from '../../lib/designTokens'
import Modal from '../primitives/Modal'
import OpportunityChart, { type ChartLevel } from './OpportunityChart'
import { big, condLabel, convictionColor, money, num, pct, STANCE_COLOR, typeLabel, vol } from './format'

const MUTED = 'var(--text3)'
const TEXT = 'var(--text0)'
const TEXT2 = 'var(--text2)'

function Section({ title, children, note }: { title: string; children: ReactNode; note?: ReactNode }) {
  return (
    <section style={{ border: '1px solid var(--border)', borderRadius: RADIUS.md, padding: 12, background: 'var(--bg0)' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 8 }}>
        <div style={{ fontSize: 10, fontWeight: 800, color: TEXT2, textTransform: 'uppercase', letterSpacing: '.06em' }}>{title}</div>
        {note && <div style={{ fontSize: 10, color: MUTED }}>{note}</div>}
      </div>
      {children}
    </section>
  )
}

function Row({ k, v, tone, hint }: { k: string; v: ReactNode; tone?: string; hint?: string }) {
  return (
    <div title={hint} style={{ display: 'flex', justifyContent: 'space-between', gap: 10, fontSize: 12, padding: '2px 0' }}>
      <span style={{ color: MUTED }}>{k}</span>
      <span style={{ ...numStyle, color: tone || TEXT, fontWeight: 700, textAlign: 'right' }}>{v}</span>
    </div>
  )
}

function Pill({ text, color }: { text: string; color: string }) {
  return <span style={{ fontSize: 10, fontWeight: 800, padding: '2px 8px', borderRadius: RADIUS.pill, border: `1px solid ${color}`, color, whiteSpace: 'nowrap' }}>{text}</span>
}

function FactorBar({ label, score, detail, weight }: { label: string; score: number; detail?: string; weight?: number }) {
  const c = convictionColor(score)
  return (
    <div title={detail} style={{ marginBottom: 6 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11 }}>
        <span style={{ color: TEXT2 }}>{label}{weight != null ? <span style={{ color: MUTED }}> · {Math.round(weight * 100)}%</span> : null}</span>
        <span style={{ ...numStyle, color: TEXT, fontWeight: 800 }}>{Math.round(score)}</span>
      </div>
      <div style={{ height: 6, background: TOKENS.bg[2], borderRadius: RADIUS.sm }}>
        <div style={{ width: `${Math.max(0, Math.min(100, score))}%`, height: 6, background: c, borderRadius: RADIUS.sm }} />
      </div>
      {detail && <div style={{ fontSize: 10, color: MUTED, marginTop: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{detail}</div>}
    </div>
  )
}

function ago(iso?: string | null): string {
  if (!iso) return ''
  const ms = Date.now() - new Date(iso).getTime()
  if (!Number.isFinite(ms)) return ''
  const h = Math.floor(ms / 3_600_000)
  return h < 1 ? 'just now' : h < 48 ? `${h}h ago` : `${Math.floor(h / 24)}d ago`
}

function sourceLabel(src?: string | null): string {
  const s = String(src || '')
  if (s.startsWith('google_news:')) return s.slice('google_news:'.length)
  return ({ yahoo_rss: 'Yahoo', benzinga_rss: 'Benzinga', benzinga_api: 'Benzinga', seeking_alpha: 'Seeking Alpha', motley_fool: 'Motley Fool' } as Record<string, string>)[s] || s.replace(/_/g, ' ')
}

function Headline({ title, url, meta, tag, tagColor }: { title: string; url?: string | null; meta: string; tag?: string; tagColor?: string }) {
  return (
    <div style={{ padding: '5px 0', borderTop: '1px solid var(--border)' }}>
      <div style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
        {tag && <span style={{ fontSize: 10, fontWeight: 800, color: tagColor || TOKENS.info, textTransform: 'uppercase', whiteSpace: 'nowrap' }}>{tag}</span>}
        {url
          ? <a href={url} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: TEXT, textDecoration: 'none', lineHeight: 1.35 }}>{title}</a>
          : <span style={{ fontSize: 12, color: TEXT, lineHeight: 1.35 }}>{title}</span>}
      </div>
      <div style={{ fontSize: 10, color: MUTED, marginTop: 1 }}>{meta}</div>
    </div>
  )
}

const CATALYST_COLOR: Record<string, string> = {
  analyst_upgrade: TOKENS.success, earnings_beat: TOKENS.success, guidance_raise: TOKENS.success,
  analyst_downgrade: TOKENS.danger, earnings_miss: TOKENS.danger, guidance_cut: TOKENS.danger,
}

export default function OpportunityModal({ symbol, onClose }: { symbol: string; onClose: () => void; onOpenSymbol?: (s: string) => void }) {
  const { data, loading, error } = useApi<any>(`/api/v3/opportunities/${encodeURIComponent(symbol)}`, 120_000)
  const d = data?.data && data.data.symbol ? data.data : data
  const a = d?.assessment || {}
  const rr = a.risk_reward || {}
  const m = d?.market || {}
  const t = d?.technical || {}
  const an = d?.analyst || {}
  const pos = d?.position || {}
  const prof = d?.profile || {}
  const th = d?.thesis || null
  const [fullSummary, setFullSummary] = useState(false)
  const summary = String(th?.summary || '')
  const SUMMARY_MAX = 420
  const cut = summary.length > SUMMARY_MAX && !fullSummary ? summary.slice(0, summary.lastIndexOf(' ', SUMMARY_MAX)) + '…' : summary
  // date-only → local midnight (new Date('2026-11-09') is UTC midnight and renders a day early in ET)
  const earnAt = prof.next_earnings_date ? new Date(String(prof.next_earnings_date).slice(0, 10) + 'T00:00:00') : null
  const earnDays = earnAt && Number.isFinite(earnAt.getTime()) ? Math.ceil((earnAt.getTime() - Date.now()) / 86_400_000) : null
  const news: any[] = d?.news || []
  const cats: any[] = d?.catalysts || []
  const levels: ChartLevel[] = []
  const add = (price: any, title: string, kind: ChartLevel['kind']) => { if (price != null && Number.isFinite(Number(price))) levels.push({ price: Number(price), title, kind }) }
  add(t.support_1, 'S1', 'support'); add(t.support_2, 'S2', 'support'); add(t.resistance_1, 'R1', 'resistance'); add(t.resistance_2, 'R2', 'resistance')
  if (rr.entry_zone) { add(rr.entry_zone[0], 'Zone low', 'entry'); add(rr.entry_zone[1], 'Zone high', 'entry') } else add(rr.entry_ref, 'Entry', 'entry')
  add(rr.invalidation_level, 'Invalidation', 'invalidation')
  for (const tg of rr.targets || []) add(tg.px, tg.tier, 'target')

  const title = (
    <div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 22, fontWeight: 900, color: TEXT }}>{symbol}</span>
        <span style={{ fontSize: 13, color: TEXT2 }}>{prof.company || a.company || ''}</span>
        <span style={{ ...numStyle, fontSize: 18, fontWeight: 800, color: TEXT }}>{money(m.price)}</span>
        <span style={{ ...numStyle, fontSize: 13, color: Number(m.day_change_pct) >= 0 ? TOKENS.success : TOKENS.danger }}>{pct(m.day_change_pct, 2)}</span>
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6, alignItems: 'center' }}>
        {a.conviction != null && <Pill text={`Conviction ${Math.round(a.conviction)}/100`} color={convictionColor(a.conviction)} />}
        {a.rank != null && <Pill text={`Rank #${a.rank}`} color={TOKENS.info} />}
        {a.stance && <Pill text={String(a.stance).replace('_', '-')} color={STANCE_COLOR[a.stance] || TOKENS.neutral} />}
        <Pill text={typeLabel(a.type)} color={TOKENS.ai} />
        <Pill text={condLabel(a.technical_condition)} color={TOKENS.neutral} />
        {a.cap_band && <Pill text={`${a.cap_band} cap · ${big(a.market_cap_usd)}`} color={TOKENS.neutral} />}
        {(prof.sector || a.sector) && <span style={{ fontSize: 11, color: MUTED }}>{prof.sector || a.sector}{prof.industry ? ` · ${prof.industry}` : ''}</span>}
      </div>
    </div>
  )

  return (
    <Modal open onClose={onClose} title={title} testId="opportunity-modal">
      {loading && !d && <div style={{ color: MUTED, fontSize: 12 }}>Loading {symbol}…</div>}
      {error && !d && <div style={{ color: TOKENS.danger, fontSize: 12 }}>Could not load {symbol}: {String(error)}</div>}
      {d && (
        <div style={{ display: 'grid', gap: 10 }}>
          {/* What the company does */}
          <Section title="About" note={earnDays != null && earnDays >= 0 ? `next earnings ${earnAt?.toLocaleDateString()} · in ${earnDays}d` : undefined}>
            <div style={{ fontSize: 12, color: TEXT, lineHeight: 1.45 }} data-testid="opportunity-about">
              {prof.description || <span style={{ color: MUTED }}>No company profile on file for {symbol}.</span>}
            </div>
          </Section>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 10 }}>
            {/* Risk / Reward — the headline */}
            <Section title="Risk / Reward" note={rr.entry_source ? `levels: ${rr.entry_source.replace(/_/g, ' ')}` : undefined}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 6 }}>
                <span style={{ ...numStyle, fontSize: 26, fontWeight: 900, color: rr.rr != null ? convictionColor(Math.min(100, rr.rr * 25)) : MUTED }}>{rr.rr != null ? `${Number(rr.rr).toFixed(1)}x` : '—'}</span>
                <span style={{ fontSize: 11, color: MUTED }}>{rr.rr != null ? 'reward-to-risk (primary target)' : (rr.rr_flag || 'no levels yet')}</span>
              </div>
              <Row k="Current price" v={money(rr.current_price ?? m.price)} />
              <Row k="Suggested entry" v={rr.entry_zone ? `${money(rr.entry_zone[0])} – ${money(rr.entry_zone[1])}` : money(rr.entry_ref)} />
              <Row k="Invalidation level" v={money(rr.invalidation_level)} tone={TOKENS.warning} hint={rr.invalidation_source} />
              <Row k="Risk / share" v={`${money(rr.risk_per_share)} · ${pct(rr.risk_pct ? -rr.risk_pct : null)}`} tone={TOKENS.danger} />
              {(rr.targets || []).map((tg: any) => (
                <Row key={tg.tier} k={`${tg.tier}${tg.primary ? ' ★' : ''} · ${tg.label}`} v={`${money(tg.px)} · ${pct(tg.reward_pct)}`} tone={TOKENS.success} hint={tg.source} />
              ))}
            </Section>

            {/* Conviction */}
            <Section title="Conviction" note={a.coverage != null ? `evidence coverage ${Math.round(a.coverage * 100)}%` : undefined}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 8 }}>
                <span style={{ ...numStyle, fontSize: 26, fontWeight: 900, color: convictionColor(a.conviction) }}>{a.conviction != null ? Math.round(a.conviction) : '—'}</span>
                <span style={{ fontSize: 11, color: MUTED }}>/ 100{a.rank ? ` · rank #${a.rank}` : ' · not ranked (thin evidence)'}</span>
              </div>
              {Object.entries(a.factors || {}).map(([k, f]: any) => <FactorBar key={k} label={f.label || k} score={f.score} detail={f.detail} weight={f.weight} />)}
              {(a.factors_missing || []).length > 0 && <div style={{ fontSize: 10, color: MUTED }}>No data (weight re-spread): {(a.factors_missing || []).join(', ')}</div>}
            </Section>

            {/* Portfolio context + stance */}
            <Section title={pos.owned ? 'Your position' : 'Portfolio context'}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
                <Pill text={String(a.stance || '—').replace('_', '-')} color={STANCE_COLOR[a.stance] || TOKENS.neutral} />
                <span style={{ fontSize: 11, color: TEXT2 }}>{a.stance_rationale}</span>
              </div>
              {pos.owned ? (
                <>
                  <Row k="Position size" v={`${num(pos.shares, 4)} sh · ${money(pos.market_value, 0)}`} />
                  <Row k="Portfolio weight" v={pos.weight_pct != null ? `${Number(pos.weight_pct).toFixed(2)}%` : '—'} />
                  <Row k="Average cost" v={money(pos.avg_cost)} />
                  <Row k="Unrealized G/L" v={`${money(pos.unrealized_pl, 0)} · ${pct(pos.unrealized_pl_pct)}`} tone={Number(pos.unrealized_pl) >= 0 ? TOKENS.success : TOKENS.danger} />
                  <Row k="Realized G/L" v={pos.realized_pl != null ? money(pos.realized_pl, 0) : 'pending'} hint={pos.pending?.realized_pl} />
                  <Row k="Days held" v={pos.days_held != null ? String(pos.days_held) : 'pending'} hint={pos.pending?.days_held} />
                  <Row k="Accounts" v={(pos.accounts || []).join(', ') || '—'} />
                </>
              ) : (
                <div style={{ fontSize: 11, color: MUTED }}>
                  Not owned{pos.last_sell_date ? ` · last sold ${pos.last_sell_date}` : ''}{d.reentry_state ? ` · re-entry desk: ${d.reentry_state}` : ''}
                </div>
              )}
            </Section>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 10 }}>
            <Section title="Catalysts" note={cats.length ? `${cats.length} in 90d` : undefined}>
              <div data-testid="opportunity-catalysts">
                {earnDays != null && earnDays >= 0 && (
                  <Headline title={`Earnings ${earnAt?.toLocaleDateString()}`} meta={`scheduled · in ${earnDays} days`} tag="upcoming" tagColor={TOKENS.warning} />
                )}
                {cats.map((c: any, i: number) => (
                  <Headline key={i} title={c.headline} url={c.source_url} tag={String(c.catalyst_type || '').replace(/_/g, ' ')}
                    tagColor={CATALYST_COLOR[c.catalyst_type] || TOKENS.info}
                    meta={`${c.at ? new Date(c.at).toLocaleDateString() : ''}${c.at ? ` · ${ago(c.at)}` : ''}${c.verified ? '' : ' · low confidence'}`} />
                ))}
                {!cats.length && earnDays == null && <div style={{ fontSize: 11, color: MUTED }}>No catalysts recorded for {symbol} in 90 days.</div>}
              </div>
            </Section>
            <Section title="Latest news" note={news[0]?.published_at ? `newest ${ago(news[0].published_at)}` : undefined}>
              <div data-testid="opportunity-news">
                {news.map((n: any, i: number) => (
                  <Headline key={i} title={n.title} url={n.url} meta={`${sourceLabel(n.source)} · ${ago(n.published_at)}`} />
                ))}
                {!news.length && <div style={{ fontSize: 11, color: MUTED }}>{cats.length ? 'No other headlines in 45 days — the catalysts are the latest news.' : `No news collected for ${symbol} in 45 days. Ranked names now get a news fetch twice a day.`}</div>}
              </div>
            </Section>
          </div>

          {/* Technical + chart */}
          <Section title="Technical" note={t.as_of ? `indicators ${new Date(t.as_of).toLocaleDateString()}` : undefined}>
            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 2fr) minmax(220px, 1fr)', gap: 12 }}>
              <OpportunityChart bars={d.chart?.bars || []} kind={d.chart?.kind || 'none'} levels={levels} />
              <div>
                <Row k="Trend" v={t.trend ? t.trend[0].toUpperCase() + t.trend.slice(1) : '—'} tone={t.trend === 'bullish' ? TOKENS.success : t.trend === 'bearish' ? TOKENS.danger : TEXT} />
                <Row k="Support 1 / 2" v={`${money(t.support_1)} / ${money(t.support_2)}`} tone={TOKENS.success} hint={t.levels_source} />
                <Row k="Resistance 1 / 2" v={`${money(t.resistance_1)} / ${money(t.resistance_2)}`} tone={TOKENS.danger} hint={t.levels_source} />
                <Row k="RSI (14)" v={num(t.rsi, 1)} tone={Number(t.rsi) >= 70 ? TOKENS.warning : Number(t.rsi) <= 30 ? TOKENS.info : TEXT} />
                <Row k="MACD" v={`${t.macd_signal || '—'}${t.macd_histogram_direction ? ` · hist ${t.macd_histogram_direction}` : ''}`} />
                <Row k="MA alignment" v={t.ma_alignment || '—'} />
                <Row k="20 / 50 / 200-day" v={`${money(t.sma_20)} / ${money(t.sma_50)} / ${money(t.sma_200)}`} />
              </div>
            </div>
          </Section>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 10 }}>
            <Section title="Market data" note={m.quote_as_of ? `quote ${new Date(m.quote_as_of).toLocaleString()}` : undefined}>
              <Row k="Current price" v={money(m.price)} />
              <Row k="Previous close" v={money(m.prev_close)} />
              <Row k="Daily change" v={pct(m.day_change_pct, 2)} tone={Number(m.day_change_pct) >= 0 ? TOKENS.success : TOKENS.danger} />
              <Row k="Weekly change" v={pct(m.change_1w_pct)} tone={Number(m.change_1w_pct) >= 0 ? TOKENS.success : TOKENS.danger} />
              <Row k="Monthly change" v={pct(m.change_1m_pct)} tone={Number(m.change_1m_pct) >= 0 ? TOKENS.success : TOKENS.danger} />
              <Row k="52-week high / low" v={`${money(m.high_52w)} / ${money(m.low_52w)}`} hint={m.range_source} />
              <Row k="Avg daily volume (30d)" v={vol(m.avg_volume_30d)} />
              <Row k="Relative volume" v={m.relative_volume != null ? `${Number(m.relative_volume).toFixed(2)}x` : '—'} />
            </Section>

            <Section title="Wall Street" note={an.as_of ? `${an.source === 'pro_analyst_pills' ? 'pills' : 'Yahoo'} ${new Date(an.as_of).toLocaleDateString()}` : undefined}>
              <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 6 }}>
                <span style={{ ...numStyle, fontSize: 13, color: TEXT2 }}>{money(m.price)} → {money(an.target_mean)}</span>
                <span style={{ ...numStyle, fontSize: 22, fontWeight: 900, color: Number(an.upside_pct) >= 0 ? TOKENS.success : TOKENS.danger }}>{pct(an.upside_pct)}</span>
              </div>
              {an.upside_flag && <div style={{ fontSize: 10, color: TOKENS.warning, marginBottom: 4 }}>{an.upside_flag}</div>}
              <Row k="Consensus" v={an.consensus && String(an.consensus).toLowerCase() !== 'none' ? String(an.consensus).replace(/_/g, ' ').toUpperCase() : '—'} />
              <Row k="Analysts" v={an.analyst_count ?? '—'} />
              <Row k="Average target" v={money(an.target_mean)} />
              <Row k="High / low target" v={`${money(an.target_high)} / ${money(an.target_low)}`} />
            </Section>

            <Section title="CIO investment summary" note={th?.updated_at ? `thesis ${new Date(th.updated_at).toLocaleDateString()}` : undefined}>
              {d.brief?.bullets?.length ? (
                <ul style={{ margin: 0, paddingLeft: 16, fontSize: 12, color: TEXT, lineHeight: 1.45 }}>
                  {d.brief.bullets.map((b: any, i: number) => <li key={i}><b style={{ color: TEXT2 }}>{b.label}:</b> {b.text}</li>)}
                </ul>
              ) : th ? (
                <div style={{ fontSize: 12, color: TEXT, lineHeight: 1.45 }}>
                  <div style={{ marginBottom: 6 }}>
                    {cut}
                    {summary.length > SUMMARY_MAX && (
                      <button onClick={() => setFullSummary(v => !v)} style={{ marginLeft: 6, fontSize: 11, color: TOKENS.info, background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>
                        {fullSummary ? 'less' : 'more'}
                      </button>
                    )}
                  </div>
                  {(th.counter_evidence || []).length > 0 && <div style={{ color: TEXT2 }}><b>Risks:</b> {(th.counter_evidence || []).slice(0, 3).join(' · ')}</div>}
                  {(th.invalidation_conditions || []).length > 0 && <div style={{ color: TEXT2, marginTop: 4 }}><b>Invalidation:</b> {(th.invalidation_conditions || []).slice(0, 3).join(' · ')}</div>}
                  <div style={{ fontSize: 10, color: MUTED, marginTop: 6 }}>AI investment brief arrives with the next release; showing the CIO research thesis.</div>
                </div>
              ) : <div style={{ fontSize: 11, color: MUTED }}>No CIO thesis on file for {symbol} yet.</div>}
            </Section>
          </div>

          <div style={{ fontSize: 10, color: MUTED, display: 'flex', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
            <span>{d.assessment_source === 'cio_memory' ? `Curated in CIO memory ${d.curated_as_of ? new Date(d.curated_as_of).toLocaleString() : ''}` : 'Not yet curated — assessed on demand'}{(d.history || []).length ? ` · ${d.history.length} assessment versions` : ''}</span>
            <span>Read-only analysis · levels are references, not orders</span>
          </div>
        </div>
      )}
    </Modal>
  )
}
