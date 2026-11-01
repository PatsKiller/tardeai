/** Design home/v006: Protect / Hedge / Rotate under the verdict, the collapsed three-row digest, the issuer-segment
 *  section, and tap-to-explain (i) buttons whose texts come from config/market_risk_glossary.json through the API.
 *  Shared by the YELLOW summary card and the ORANGE/RED banner. Tokens only. Every link opens an existing page
 *  (stop review, Defense desk, Rotation desk, Best opportunities); there is no order, size, stop level or "buy"
 *  anywhere (MBI_BEHAVIOR = 0). */
import { createContext, useContext, useEffect, useId, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { RADIUS, TOKENS, TYPE, chipStyle, numStyle, toneVars } from '../../lib/designTokens'
import { SUMMARY_PHONE_MAX_PX, type ActionableModel, type GlossaryTerm } from '../../lib/marketRisk'

const GlossaryContext = createContext<Record<string, GlossaryTerm>>({})

export function GlossaryProvider({ terms, children }: { terms: Record<string, GlossaryTerm>; children: ReactNode }) {
  return <GlossaryContext.Provider value={terms}>{children}</GlossaryContext.Provider>
}

const SHEET_CSS = `
[data-mr-sheet]{position:fixed;z-index:1000;background:var(--bg-2);border:1px solid var(--border-color);color:var(--text-0);box-sizing:border-box;padding:14px 16px 18px;left:50%;top:30%;transform:translateX(-50%);width:min(420px,calc(100vw - 32px));border-radius:${RADIUS.lg}}
@media(max-width:${SUMMARY_PHONE_MAX_PX}px){[data-mr-sheet]{left:0;right:0;top:auto;bottom:0;transform:none;width:100%;border-radius:var(--radius-lg) var(--radius-lg) 0 0;padding-bottom:22px}}
`

/** A tap-friendly (i): 16 px glyph, 44 × 44 hit area, opens a short sheet (phone) or dialog (desktop). Not hover. */
export function Explain({ term }: { term: string }) {
  const g = useContext(GlossaryContext)[term]
  const [open, setOpen] = useState(false)
  const btn = useRef<HTMLButtonElement>(null)
  const closeBtn = useRef<HTMLButtonElement>(null)
  const titleId = useId()
  useEffect(() => {
    if (!open) return
    closeBtn.current?.focus()
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { setOpen(false); btn.current?.focus() } }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])
  if (!g) return null
  const close = () => { setOpen(false); btn.current?.focus() }
  return (
    <>
      <button ref={btn} type="button" data-testid="mr-explain" data-term={term} aria-label={`What is ${g.label.replace(/\?$/, '')}?`} aria-haspopup="dialog"
        onClick={e => { e.preventDefault(); e.stopPropagation(); setOpen(true) }}
        style={{ position: 'relative', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 44, height: 44, margin: '-14px -14px', padding: 0, border: 0, background: 'transparent', cursor: 'pointer', verticalAlign: 'middle', flex: '0 0 auto' }}>
        <span aria-hidden="true" style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: 16, height: 16, borderRadius: '50%', border: `1px solid ${TOKENS.text[3]}`, color: TOKENS.text[2], fontSize: 10, fontWeight: 700, fontStyle: 'italic', fontFamily: 'Georgia, serif', lineHeight: 1 }} data-mr-i="" />
      </button>
      {open && (
        <>
          <style>{SHEET_CSS}</style>
          <div data-testid="mr-explain-scrim" onClick={close} style={{ position: 'fixed', inset: 0, zIndex: 999, background: 'rgba(0,0,0,.55)' }} />
          <div data-mr-sheet="" data-testid="mr-explain-sheet" role="dialog" aria-modal="true" aria-labelledby={titleId}>
            <div id={titleId} style={{ fontSize: TYPE.md + 1, fontWeight: 700, marginBottom: 6, textTransform: 'none', letterSpacing: 0 }}>{g.label}</div>
            <p style={{ margin: '0 0 12px', fontSize: TYPE.md, lineHeight: 1.5, color: TOKENS.text[1], textTransform: 'none', letterSpacing: 0, fontWeight: 400 }}>{g.text}</p>
            <button ref={closeBtn} type="button" data-testid="mr-explain-close" onClick={close}
              style={{ minHeight: 44, width: '100%', borderRadius: RADIUS.md, border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[1], color: TOKENS.text[0], fontWeight: 700, fontSize: TYPE.md, cursor: 'pointer' }}>Close</button>
          </div>
        </>
      )}
    </>
  )
}

const blk: CSSProperties = { display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0, padding: '8px 12px 6px', borderRadius: RADIUS.md, background: TOKENS.bg[0], border: `1px solid ${TOKENS.border}` }
const h4: CSSProperties = { margin: 0, minHeight: 28, display: 'flex', alignItems: 'center', gap: 6, fontSize: TYPE.base, letterSpacing: '.05em', textTransform: 'uppercase', color: TOKENS.text[2], fontWeight: 700 }
const sub: CSSProperties = { fontSize: TYPE.sm, color: TOKENS.text[3], lineHeight: 1.5 }
const tap: CSSProperties = { minHeight: 44, display: 'inline-flex', alignItems: 'center', color: TOKENS.info, fontWeight: 700, fontSize: TYPE.base + 1, textDecoration: 'none', whiteSpace: 'nowrap' }
const signed = (n: number | null): CSSProperties => ({ ...numStyle, color: n == null ? TOKENS.text[3] : n < 0 ? toneVars('danger').color : toneVars('success').color })

/** The (i) glyph is CSS content so it never joins the surrounding text (copy, tests, screen readers use aria-label). */
export const EXPLAIN_CSS = `[data-mr-i]::before{content:"i"}`

const ACTIONS_CSS = `${EXPLAIN_CSS}
[data-mr-actions]{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(0,1fr) minmax(0,1fr);gap:10px;margin:2px 0 8px}
@media(max-width:${SUMMARY_PHONE_MAX_PX}px){[data-mr-actions]{grid-template-columns:1fr}}
`

function Protect({ m }: { m: ActionableModel }) {
  const p = m.protect
  if (!p) return null
  return (
    <div data-testid="mr-protect" style={blk}>
      <h4 style={h4}><span style={{ color: TOKENS.text[0] }}>Protect</span> · your largest review items <Explain term="protect" /></h4>
      {!p.items.length && <div style={{ fontSize: TYPE.base + 1, color: TOKENS.text[2] }}>Nothing to review in your largest positions.</div>}
      {p.items.map((it, i) => (
        <div key={`${it.symbol}-${it.account}`} data-testid="mr-protect-item" style={{ display: 'flex', flexDirection: 'column', gap: 2, padding: '6px 0', borderTop: i ? `1px solid ${TOKENS.borderSubtle}` : 0, fontSize: TYPE.base + 1, lineHeight: 1.45 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '2px 8px', alignItems: 'baseline' }}>
            <b>{it.symbol}</b><span style={{ color: TOKENS.text[2] }}>· {it.account}</span><span style={numStyle}>{it.usd}</span>{it.pct && <span style={{ color: TOKENS.text[3] }}>({it.pct})</span>}
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0 8px', alignItems: 'center' }}>
            <span data-testid="mr-protect-consideration" style={{ flex: '1 1 220px', minWidth: 0 }}>{it.consideration}</span>
            <Link to={it.to} data-testid="mr-protect-link" style={{ ...tap, marginLeft: 'auto' }}>{it.linkLabel}</Link>
          </div>
        </div>
      ))}
      <div style={sub}>{p.more ? `${p.more} · ` : ''}Advisory only — each link opens the existing stop review; no order, size or stop level.</div>
    </div>
  )
}

function Hedge({ m }: { m: ActionableModel }) {
  const h = m.hedge
  if (!h) return null
  return (
    <div data-testid="mr-hedge" style={blk}>
      <h4 style={h4}><span style={{ color: TOKENS.text[0] }}>Hedge</span> · needed for your book? <Explain term="hedge_verdict" /></h4>
      <div style={{ fontSize: TYPE.base + 1, lineHeight: 1.45, color: TOKENS.text[1] }}>
        <span data-testid="mr-hedge-verdict" data-tone={h.tone} style={{ ...chipStyle(h.tone, 'soft'), marginRight: 6 }}>{h.verdict.toUpperCase()}</span>{h.line}
      </div>
      {h.lane && <div data-testid="mr-hedge-lane" style={{ fontSize: TYPE.base, color: TOKENS.text[2] }}>{h.lane}</div>}
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginTop: 'auto' }}><Link to="/defense" data-testid="mr-hedge-link" style={tap}>Defense desk →</Link></div>
    </div>
  )
}

function Rotate({ m }: { m: ActionableModel }) {
  const r = m.rotate
  if (!r) return null
  return (
    <div data-testid="mr-rotate" style={blk}>
      <h4 style={h4}><span style={{ color: TOKENS.text[0] }}>Rotate</span> · where money is moving <Explain term="rotate_rs" /></h4>
      {r.none && <div style={{ fontSize: TYPE.base + 1, color: TOKENS.text[2] }}>{r.none}</div>}
      {r.rows.map((g, i) => (
        <div key={g.key} data-testid="mr-rotate-row" data-key={g.key} style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'baseline', gap: '2px 8px', padding: '5px 0', borderTop: i ? `1px solid ${TOKENS.borderSubtle}` : 0, fontSize: TYPE.base + 1 }}>
          <b style={{ minWidth: 96 }}>{g.label}</b>
          <span style={signed(g.rs1n)}>{g.rs1}</span><span style={{ color: TOKENS.text[3] }}>1d</span>
          <span style={signed(g.rs5n)}>{g.rs5}</span><span style={{ color: TOKENS.text[3] }}>5d</span>
          <span style={{ color: TOKENS.text[3] }}>{g.desk ? `· ${g.desk} ` : ''}· you hold <span style={numStyle}>{g.usd}</span></span>
        </div>
      ))}
      <div style={sub}>{r.foot}</div>
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginTop: 'auto' }}>
        <Link to="/rotation" data-testid="mr-rotate-link" style={tap}>Rotation desk →</Link>
        <Link to="/watch?tab=opportunities&preset=top5" data-testid="mr-opportunities-link" style={tap}>Best opportunities →</Link>
      </div>
    </div>
  )
}

/** Expanded: the three blocks. Collapsed: one ≥44 px row each (design home/v006 B). */
export function ActionsTop({ m, open }: { m: ActionableModel; open: boolean }) {
  if (!m.protect && !m.hedge && !m.rotate) return null
  if (open) {
    return (
      <GlossaryProvider terms={m.glossary}>
        <style>{ACTIONS_CSS}</style>
        <div data-mr-actions="" data-testid="mr-actions"><Protect m={m} /><Hedge m={m} /><Rotate m={m} /></div>
      </GlossaryProvider>
    )
  }
  const row: CSSProperties = { display: 'flex', alignItems: 'center', gap: 8, minHeight: 44, padding: '4px 12px', boxSizing: 'border-box', fontSize: TYPE.base + 1, lineHeight: 1.35, color: TOKENS.text[0], textDecoration: 'none' }
  const lab: CSSProperties = { fontSize: TYPE.sm, fontWeight: 800, letterSpacing: '.05em', color: TOKENS.text[2], minWidth: 58, textTransform: 'uppercase' }
  const go: CSSProperties = { marginLeft: 'auto', color: TOKENS.info, fontWeight: 700 }
  const p0 = m.protect?.items[0]
  return (
    <div data-testid="mr-actions-digest" style={{ display: 'flex', flexDirection: 'column', margin: '4px 0 6px', borderRadius: RADIUS.md, background: TOKENS.bg[0], border: `1px solid ${TOKENS.border}` }}>
      {p0 && (
        <Link to={p0.to} data-testid="mr-digest-protect" style={row}>
          <span style={lab}>Protect</span><span><b>{p0.symbol}</b> · {p0.account} (<span style={numStyle}>{p0.usd}</span>) — {p0.consideration.split('; ')[0]}</span><span style={go}>→</span>
        </Link>
      )}
      {m.hedge && (
        <Link to="/defense" data-testid="mr-digest-hedge" style={{ ...row, borderTop: `1px solid ${TOKENS.borderSubtle}` }}>
          <span style={lab}>Hedge</span><span><b style={{ color: toneVars(m.hedge.tone).color }}>{m.hedge.verdict}</b> — {m.hedge.short}</span><span style={go}>→</span>
        </Link>
      )}
      {m.rotate && (
        <Link to="/rotation" data-testid="mr-digest-rotate" style={{ ...row, borderTop: `1px solid ${TOKENS.borderSubtle}` }}>
          <span style={lab}>Rotate</span><span>{m.rotate.short} <span style={{ color: TOKENS.text[3] }}>(1d/5d vs SPY)</span></span><span style={go}>→</span>
        </Link>
      )}
    </div>
  )
}

/** Section 6: multi-segment issuers (approved split, or "pending approval"). */
export function Segments({ m }: { m: ActionableModel }) {
  if (!m.segments.length) return null
  const tones = ['warning', 'success', 'info', 'elevated'] as const
  return (
    <div data-testid="mr-segments">
      <h3 style={{ margin: '0 0 6px', fontSize: TYPE.base, color: TOKENS.text[2], textTransform: 'uppercase', letterSpacing: '.05em', fontWeight: 700 }}>Multi-segment issuer</h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {m.segments.map(sg => (
          <div key={sg.symbol} data-testid="mr-segment-row" data-status={sg.status} style={{ ...blk, padding: '9px 12px', fontSize: TYPE.base + 1, lineHeight: 1.45 }}>
            <b>{sg.symbol} <Explain term="look_through" /></b>
            {sg.status === 'approved' && sg.split.length > 0 && (
              <div aria-hidden="true" style={{ display: 'flex', height: 8, borderRadius: RADIUS.sm, overflow: 'hidden', margin: '2px 0' }}>
                {sg.split.map((x, i) => <span key={x.label} style={{ flex: x.pct, background: toneVars(tones[i % tones.length]).color }} />)}
              </div>
            )}
            <div style={{ color: sg.status === 'approved' ? TOKENS.text[1] : toneVars('warning').color, fontWeight: sg.status === 'approved' ? 400 : 600 }}>{sg.line}</div>
          </div>
        ))}
      </div>
    </div>
  )
}
