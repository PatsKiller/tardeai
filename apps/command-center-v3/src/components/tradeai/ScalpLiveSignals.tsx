/** Scalp live signal screen — moved from the retired Trading → Scalp tab to Active Trader → Scalp
 *  (operator-approved tabs 8 → 4, 2026-10-22). Same data (/api/v2/scalp/live + the Grok/ChatGPT
 *  subject-intel map), same ranking and per-symbol dedupe; colours now come from design tokens.
 *  Advisory only: no order, approval or 2FA control lives here. */
import { useApi } from '../../hooks/useApi'
import { useTerminalUi } from '../../lib/terminalUi'
import { hubPanel } from '../../lib/terminalHubChrome'
import { RADIUS, TOKENS, TYPE, toneVars } from '../../lib/designTokens'
import type { DrillContext } from '../DetailDrawer'

const SUCCESS = toneVars('success').color
const WARNING = toneVars('warning').color
const DANGER = toneVars('danger').color

// GO / WAIT / MANUAL_REVIEW / NO-GO decision color
const decisionColor = (d?: string) => d === 'GO' ? SUCCESS : d === 'WAIT' ? WARNING : d === 'MANUAL_REVIEW' ? 'var(--squeeze)' : DANGER

/** Rank for scalp signal selection: GO > WAIT > others. */
export function scalpDecisionRank(decision?: string): number {
  const d = String(decision || '').toUpperCase().replace(/_/g, '-')
  if (d === 'GO') return 3
  if (d === 'WAIT') return 2
  return 1
}

/** Grade rank: A > B > C > D > F > unknown. */
export function scalpGradeRank(grade?: string): number {
  const g = String(grade || '').toUpperCase()
  if (g === 'A') return 5
  if (g === 'B') return 4
  if (g === 'C') return 3
  if (g === 'D') return 2
  if (g === 'F') return 1
  return 0
}

/** True when `a` is the better row for dedupe (decision → grade → score). */
function isBetterScalpSignal(a: any, b: any): boolean {
  const da = scalpDecisionRank(a?.decision)
  const db = scalpDecisionRank(b?.decision)
  if (da !== db) return da > db
  const ga = scalpGradeRank(a?.grade)
  const gb = scalpGradeRank(b?.grade)
  if (ga !== gb) return ga > gb
  return (Number(a?.score) || 0) > (Number(b?.score) || 0)
}

/**
 * Client-side dedupe of /api/v2/scalp/live signals by uppercase symbol.
 * Keeps the best-ranked row per symbol. Display-only — does not change backend contracts.
 */
export function dedupeScalpSignalsBySymbol(sigs: any[]): { unique: any[]; rawCount: number } {
  const best = new Map<string, any>()
  for (const row of sigs) {
    const sym = String(row?.symbol || '').toUpperCase()
    if (!sym) continue
    const normalized = { ...row, symbol: sym }
    const prev = best.get(sym)
    if (!prev || isBetterScalpSignal(normalized, prev)) best.set(sym, normalized)
  }
  return { unique: [...best.values()], rawCount: sigs.length }
}

export default function ScalpLiveSignals({ onDrill, focusSymbol }: { onDrill: (c: DrillContext) => void; focusSymbol?: string }) {
  const [terminalUi] = useTerminalUi()
  const { data: scalpData, error } = useApi<any>('/api/v2/scalp/live', 120_000)
  const { data: scalpExt } = useApi<any>('/api/v2/hermes/subject-intel-map?type=scalp', 120_000)
  const scalpExtMap: Record<string, any[]> = scalpExt?.map ?? {}
  const focus = (focusSymbol || '').toUpperCase()
  if (!scalpData) {
    return <div data-testid="scalp-live" style={{ padding: 14, color: TOKENS.text[2], fontSize: TYPE.sm }}>{error ? `Live scalp signals unavailable: ${String(error)}` : 'Loading live scalp signals…'}</div>
  }
        // ── Live scalp signals: unwrap {timestamp,data:{...}} and present clearly + actionably ──
        const GC = (g?: string) => { const u = (g || '').toUpperCase(); return u === 'A' ? SUCCESS : u === 'B' ? SUCCESS : u === 'C' ? WARNING : u === 'D' || u === 'F' ? DANGER : TOKENS.text[3] }
        // Social Scout pill — operator-awareness ONLY. Distinct violet (var(--social-scout)), never
        // green/GO. No execution/validate/buy affordance: it is a watch/surface state, never tradeable.
        const SCOUT_COLOR = 'var(--social-scout)'
        const ScoutPill = ({ d }: { d: any }) => {
          if (d.scout_status !== 'SOCIAL_SCOUT' || !d.operator_pill) return null
          const hints = (d.operator_tooltip_hints || []).join(' · ')
          const tip = `${d.operator_subtitle || 'Not quite there yet'}${hints ? ' — ' + hints : ''}\n`
            + 'Awareness only — not a GO, not validation-fast-path eligible, not a standard momentum_scalp trade.'
          return (
            <span title={tip} style={{ fontSize: TYPE.xs, fontWeight: 700, padding: '1px 6px', borderRadius: RADIUS.sm,
              background: 'var(--social-scout-dim)', color: SCOUT_COLOR, border: `1px solid ${SCOUT_COLOR}`,
              whiteSpace: 'nowrap', cursor: 'help', marginRight: 6 }}>{d.operator_pill}</span>
          )
        }
        const raw: any[] = scalpData.signals ?? []
        const expanded = raw.map((s: any) => ({ ...(s.data || s), _ts: s.timestamp })).filter((d: any) => d.symbol)
        // API can emit the same symbol twice; dedupe by symbol keeping best rank (GO>WAIT>others, grade, score).
        const { unique: sigs, rawCount: rawSignalCount } = dedupeScalpSignalsBySymbol(expanded)
        const n = sigs.length
        const byG: Record<string, number> = {}; sigs.forEach((d: any) => { const g = (d.grade || '?').toUpperCase(); byG[g] = (byG[g] || 0) + 1 })
        const byD = { GO: 0, WAIT: 0, 'NO-GO': 0 } as Record<string, number>
        sigs.forEach((d: any) => { const k = (d.decision || '').toUpperCase().replace('_', '-'); if (byD[k] != null) byD[k]++ })
        const catalyst = sigs.filter((d: any) => d.catalyst_verified).length
        const scouts = sigs.filter((d: any) => d.scout_status === 'SOCIAL_SCOUT').length
        const avgScore = n ? Math.round(sigs.reduce((a: number, d: any) => a + (d.score || 0), 0) / n) : 0
        // "prime" actionable scalp = GO + grade A + catalyst verified (the criteria that actually matter)
        const prime = sigs.filter((d: any) => (d.decision || '').toUpperCase() === 'GO' && (d.grade || '').toUpperCase() === 'A' && d.catalyst_verified)
        const ordered = [...sigs].sort((a: any, b: any) => {
          const da = scalpDecisionRank(a.decision), db = scalpDecisionRank(b.decision)
          if (da !== db) return db - da
          const ga = scalpGradeRank(a.grade), gb = scalpGradeRank(b.grade)
          if (ga !== gb) return gb - ga
          return (Number(b.score) || 0) - (Number(a.score) || 0)
        })
        const Tip = ({ t, children }: { t: string; children: any }) => (
          <span title={t} style={{ cursor: 'help', borderBottom: '1px dotted var(--text3)' }}>{children}</span>
        )
        const Metric = ({ label, value, color, tip }: { label: string; value: any; color?: string; tip: string }) => (
          <div title={tip} style={{ background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: RADIUS.md, padding: '8px 10px', cursor: 'help', minWidth: 100, flex: '1 1 100px' }}>
            <div style={{ fontSize: TYPE.xs, color: TOKENS.text[3], textTransform: 'uppercase', letterSpacing: 0.4 }}>{label} ⓘ</div>
            <div style={{ fontSize: 17, fontWeight: 700, color: color || TOKENS.text[0], marginTop: 2 }}>{value}</div>
          </div>
        )
        return (
        <div data-testid="scalp-live" className={terminalUi ? 'cc-panel' : undefined} style={terminalUi ? hubPanel(terminalUi) : { background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: RADIUS.md, padding: 16 }}>
          <div style={{ fontSize: terminalUi ? 11 : 13, fontWeight: 700, color: TOKENS.text[0], marginBottom: 4 }}>Scalp Live — Signal Screen</div>
          <div style={{ fontSize: 10, color: TOKENS.text[3], marginBottom: 12 }}>Live scalp candidates, graded. Prime setups = GO · grade A · catalyst-verified (with high RVOL). These are advisory — execution is gated.</div>

          {n === 0 ? <div style={{ color: TOKENS.text[3], fontSize: 11 }}>No live scalp signals.</div> : (<>

          {/* Prime-setup alert */}
          <div style={{ background: prime.length ? toneVars('success').bg : 'var(--bg2)', border: `1px solid ${prime.length ? toneVars('success').border : TOKENS.border}`, borderRadius: RADIUS.md, padding: '8px 12px', marginBottom: 12 }}>
            {prime.length ? (<>
              <div style={{ fontSize: 12, fontWeight: 700, color: SUCCESS }}>✦ {prime.length} prime setup{prime.length > 1 ? 's' : ''} — GO · A · catalyst</div>
              <div style={{ fontSize: 10, color: TOKENS.text[2], marginTop: 4, display: 'flex', flexWrap: 'wrap', gap: 10 }}>
                {prime.slice(0, 8).map((d: any, i: number) => (
                  <span key={i} onClick={() => onDrill({ title: `${d.symbol} — Scalp Signal`, subtitle: `GO · A · score ${d.score} · RVOL ${d.rvol}`, endpoint: '/api/v2/scalp/live', rows: [d], subjectType: 'scalp', subjectKey: d.symbol })} style={{ cursor: 'pointer', textDecoration: 'underline dotted' }}>
                    <b style={{ fontFamily: 'monospace' }}>{d.symbol}</b> {d.change_percent ? `${d.change_percent}` : ''} {d.rvol ? `RVOL ${d.rvol}` : ''}
                  </span>
                ))}
              </div>
            </>) : <div style={{ fontSize: 11, color: TOKENS.text[3] }}>No prime setups right now (need GO + grade A + verified catalyst). Watching {n} candidates.</div>}
          </div>

          {/* Summary band */}
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 12 }}>
            <Metric tip="Live scalp candidates on the screen." label="Signals" value={n} />
            <Metric tip="Candidates graded GO — passed the scalp decision gate." label="GO" value={byD.GO} color={byD.GO > 0 ? SUCCESS : undefined} />
            <Metric tip="Top-grade setups. Grade reflects setup quality (float/RVOL/catalyst/structure)." label="Grade A" value={byG['A'] || 0} color={(byG['A'] || 0) > 0 ? SUCCESS : undefined} />
            <Metric label="Catalyst ✓" value={`${catalyst}/${n}`} tip="Signals with a verified catalyst. A real catalyst is required for a prime scalp." />
            <Metric tip="Partial social setups meeting ≥2 of 5 scout pillars — interesting, not there yet. Awareness only: never GO, never validation-eligible, never a standard momentum_scalp." label="Social Scouts" value={scouts} color={scouts > 0 ? 'var(--social-scout)' : undefined} />
            <Metric tip="Mean composite score across candidates (higher = stronger setup)." label="Avg Score" value={avgScore} />
          </div>

          {/* Decision + grade distribution bars */}
          <div style={{ marginBottom: 14, display: 'flex', gap: 18, flexWrap: 'wrap' }}>
            <div style={{ flex: '1 1 240px' }}>
              <div style={{ fontSize: TYPE.xs, color: TOKENS.text[3], marginBottom: 4 }}><Tip t="GO = actionable, WAIT = watch, NO-GO = rejected.">DECISION ⓘ</Tip></div>
              <div style={{ display: 'flex', height: 20, borderRadius: RADIUS.sm, overflow: 'hidden', border: '1px solid var(--border)' }}>
                {(['GO', 'WAIT', 'NO-GO'] as const).map(k => byD[k] > 0 && (
                  <div key={k} title={`${k}: ${byD[k]}`} style={{ width: `${(byD[k] / n) * 100}%`, background: decisionColor(k === 'NO-GO' ? 'NO' : k), display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: TYPE.xs, fontWeight: 700, color: TOKENS.bg[0] }}>{(byD[k] / n) > 0.08 ? byD[k] : ''}</div>
                ))}
              </div>
            </div>
            <div style={{ flex: '1 1 240px' }}>
              <div style={{ fontSize: TYPE.xs, color: TOKENS.text[3], marginBottom: 4 }}><Tip t="Setup-quality grade distribution. A is best.">GRADE ⓘ</Tip></div>
              <div style={{ display: 'flex', height: 20, borderRadius: RADIUS.sm, overflow: 'hidden', border: '1px solid var(--border)' }}>
                {['A', 'B', 'C', 'D', 'F', '?'].map(k => (byG[k] || 0) > 0 && (
                  <div key={k} title={`${k}: ${byG[k]}`} style={{ width: `${(byG[k] / n) * 100}%`, background: GC(k), display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: TYPE.xs, fontWeight: 700, color: TOKENS.bg[0] }}>{(byG[k] / n) > 0.08 ? `${k}:${byG[k]}` : ''}</div>
                ))}
              </div>
            </div>
          </div>

          {/* Signals table — GO + best grade first */}
          <div style={{ display: 'flex', fontSize: TYPE.xs, color: TOKENS.text[3], padding: '0 6px 4px', textTransform: 'uppercase', letterSpacing: 0.3 }}>
            <span style={{ flex: '0 0 66px' }}>Symbol</span>
            <span style={{ flex: '0 0 48px' }}>Grade</span>
            <span style={{ flex: '0 0 56px' }}>Decision</span>
            <span style={{ flex: '0 0 50px' }}>Score</span>
            <span style={{ flex: '0 0 60px' }}><Tip t="Relative volume vs average. Scalps want high RVOL (5x+).">RVOL</Tip></span>
            <span style={{ flex: '0 0 60px' }}>Chg %</span>
            <span style={{ flex: '0 0 54px' }}><Tip t="Catalyst verified?">Catalyst</Tip></span>
            <span style={{ flex: '1 1 auto' }}>Source</span>
          </div>
          {ordered.slice(0, 30).map((d: any) => {
            const isGo = (d.decision || '').toUpperCase() === 'GO'
            return (
            <div key={d.symbol} onClick={() => onDrill({ title: `${d.symbol} — Scalp Signal`, subtitle: `${d.decision ?? '—'} · grade ${d.grade ?? '—'} · score ${d.score ?? '—'} · RVOL ${d.rvol ?? '—'}${d.critic_verdict ? ' · ' + d.critic_verdict : ''}`, endpoint: '/api/v2/scalp/live', rows: [d], subjectType: 'scalp', subjectKey: d.symbol })}
              style={{ display: 'flex', alignItems: 'center', padding: '6px 6px', borderBottom: '1px solid var(--border)', cursor: 'pointer', fontSize: 11, background: isGo ? toneVars('success').bg : undefined, outline: focus && d.symbol === focus ? `1px solid ${TOKENS.info}` : undefined }}>
              <span style={{ flex: '0 0 66px', fontWeight: 600, color: TOKENS.text[0], fontFamily: 'monospace' }}>{d.symbol}
                {(scalpExtMap[d.symbol] || []).map((e: any, j: number) => <span key={j} title={`${e.lane === 'grok' ? 'Grok' : e.lane === 'chatgpt' ? 'ChatGPT' : e.lane}: ${e.recommendation || ''}\n${e.at ? new Date(e.at).toLocaleString() : ''}`} style={{ marginLeft: 4, fontSize: TYPE.xs, fontWeight: 700, color: e.lane === 'grok' ? TOKENS.info : TOKENS.ai, cursor: 'help' }}>✦</span>)}</span>
              <span style={{ flex: '0 0 48px' }}><span style={{ fontSize: TYPE.xs, fontWeight: 700, padding: '1px 6px', borderRadius: RADIUS.sm, background: GC(d.grade), color: TOKENS.bg[0] }}>{d.grade ?? '—'}</span></span>
              <span style={{ flex: '0 0 56px', fontWeight: 600, color: decisionColor((d.decision || '').toUpperCase().startsWith('NO') ? 'NO' : (d.decision || '').toUpperCase()), fontSize: 10 }}>{d.decision ?? '—'}</span>
              <span style={{ flex: '0 0 50px', color: TOKENS.text[2] }}>{d.score ?? '—'}</span>
              <span style={{ flex: '0 0 60px', color: (d.rvol || 0) >= 5 ? SUCCESS : (d.rvol || 0) >= 2 ? WARNING : TOKENS.text[3] }}>{d.rvol != null ? `${d.rvol}x` : '—'}</span>
              <span style={{ flex: '0 0 60px', color: TOKENS.text[2] }}>{d.change_percent || '—'}</span>
              <span style={{ flex: '0 0 54px', textAlign: 'center' }}>{d.catalyst_verified ? <span style={{ color: SUCCESS }}>✓</span> : <span style={{ color: TOKENS.text[3] }}>—</span>}</span>
              <span style={{ flex: '1 1 auto', fontSize: TYPE.xs, color: TOKENS.text[3], display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 4 }}><ScoutPill d={d} />{d.source ?? '—'}</span>
            </div>
          )})}
          <div style={{ fontSize: 10, color: TOKENS.text[3], marginTop: 8 }} data-testid="scalp-dedupe-footer">
            Deduped {rawSignalCount} → {n} unique symbols.
            {' · '}Source: /api/v2/scalp/live · click any row for the full signal. Hover ⓘ for definitions. Advisory only — scalp execution is gated.
          </div>
          </>)}
        </div>
        )
}
