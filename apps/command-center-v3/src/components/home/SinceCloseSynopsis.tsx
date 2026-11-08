/** LQ-20261107-1253 amendment 5 — "CIO bottom line": posture and risk chips, AS OF badge, the verdict at 17 px, then the
 *  labelled rows. Null rows are not drawn. Advisory only. */
import { RADIUS, TOKENS, FONT, toneVars } from '../../lib/designTokens'
import type { SynopsisModel } from '../../lib/synopsis'
import type { StampWire } from '../../lib/sinceCloseStamp'
import { AsOfBadge } from './SinceCloseStamp'

const warn = toneVars('warning')
const info = toneVars('info')

const chip = (t: ReturnType<typeof toneVars>) => ({ fontSize: 11, fontWeight: 800, letterSpacing: '.05em', textTransform: 'uppercase' as const, padding: '2px 8px', borderRadius: RADIUS.md, color: t.color, background: t.bg, border: `1px solid ${t.border}` })

export default function SinceCloseSynopsis({ s, stamp, nowMs }: { s: SynopsisModel; stamp: StampWire | null; nowMs: number }) {
  return (
    <div data-testid="since-close-synopsis" data-state={s.state} style={{ background: TOKENS.bg[0], border: `1px solid ${s.state === 'ok' ? TOKENS.border : warn.border}`, borderRadius: RADIUS.md, padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 6, minWidth: 0 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <b style={{ fontSize: 11, letterSpacing: '.06em', textTransform: 'uppercase', color: TOKENS.text[3] }}>CIO bottom line</b>
        {s.posture && <span data-testid="syn-posture" style={chip(info)}>{s.posture}</span>}
        {s.risk && <span data-testid="syn-risk" style={chip(warn)}>{s.risk}</span>}
        <AsOfBadge stamp={stamp} nowMs={nowMs} />
      </div>
      {s.notice && <div data-testid="syn-notice" role="status" style={{ fontSize: 13, fontWeight: 700, color: warn.color }}>⚠ {s.notice}</div>}
      {s.verdict && <p data-testid="syn-verdict" style={{ margin: 0, fontSize: 17, fontWeight: 700, lineHeight: 1.35, color: TOKENS.text[0], overflowWrap: 'anywhere' }}>{s.verdict}</p>}
      {s.rows.length > 0 && (
        <dl style={{ margin: 0, display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '3px 10px', fontSize: 13 }}>
          {s.rows.map(r => (
            <div key={r.key} data-testid={`syn-row-${r.key}`} style={{ display: 'contents' }}>
              <dt style={{ color: TOKENS.text[3], fontFamily: FONT.mono, whiteSpace: 'nowrap' }}>{r.label}</dt>
              <dd style={{ margin: 0, color: TOKENS.text[1], minWidth: 0, overflowWrap: 'anywhere' }}>{r.text}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )
}
