/** Communications message drawer (operator 2026-10-19: "broken HTML", "no analyst ratings", "should be larger",
 *  "what do the buttons do?"). The decision facts first (entry / stop / target / R:R / conviction / Street view),
 *  then the message rendered as the formatted text Telegram showed, then plainly-explained lifecycle actions. */
import { Fragment, useEffect, type ReactNode } from 'react'
import { RADIUS, numStyle } from '../../lib/designTokens'
import { SymbolLink } from '../opportunity/OpportunityContext'
import { FAMILY_ICON, familyFor, familyStyle, type Family } from '../decision/DecisionParts'
import { PriceTag, alertType, catalystOf } from '../decision/FeedCards'
import { ItemBadges, ttlLabel } from './CommsHubParts'

const MUTED = 'var(--text3)'
const TEXT = 'var(--text0)'
const TEXT2 = 'var(--text2)'
const BORDER = 'var(--border)'

const usd = (v: any) => (v == null || !Number.isFinite(Number(v)) ? '—' : `$${Number(v).toFixed(2)}`)

function fmtWhen(s?: string | null) {
  if (!s) return '—'
  try { return new Date(s).toLocaleString() } catch { return String(s) }
}

// ── Telegram HTML → React (allowlist; never innerHTML) ──────────────────────
// Telegram's parse_mode=HTML subset. Anything else renders as its text content only.
const TAGS: Record<string, string> = { b: 'strong', strong: 'strong', i: 'em', em: 'em', u: 'u', ins: 'u', s: 's', strike: 's', del: 's', code: 'code', pre: 'pre', blockquote: 'blockquote', a: 'a', br: 'br' }

function safeHref(h: string | null): string | null {
  if (!h) return null
  try {
    const u = new URL(h, window.location.origin)
    return u.protocol === 'https:' || u.protocol === 'http:' ? u.href : null
  } catch { return null }
}

function renderNode(n: Node, key: string): ReactNode {
  if (n.nodeType === Node.TEXT_NODE) return n.textContent
  if (n.nodeType !== Node.ELEMENT_NODE) return null
  const el = n as Element
  const kids = Array.from(el.childNodes).map((c, i) => renderNode(c, `${key}.${i}`))
  const tag = TAGS[el.tagName.toLowerCase()]
  if (!tag) return <Fragment key={key}>{kids}</Fragment>
  if (tag === 'br') return <br key={key} />
  if (tag === 'a') {
    const href = safeHref(el.getAttribute('href'))
    return href ? <a key={key} href={href} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--info-color)' }}>{kids}</a> : <Fragment key={key}>{kids}</Fragment>
  }
  if (tag === 'blockquote') {
    return <blockquote key={key} style={{ margin: '6px 0', padding: '6px 10px', borderLeft: `3px solid ${BORDER}`, background: 'var(--bg2)', borderRadius: RADIUS.sm, color: TEXT2 }}>{kids}</blockquote>
  }
  if (tag === 'pre' || tag === 'code') {
    return <code key={key} style={{ fontFamily: "'JetBrains Mono', ui-monospace, Consolas, monospace", fontSize: '0.92em', background: 'var(--bg2)', padding: '0 3px', borderRadius: RADIUS.sm }}>{kids}</code>
  }
  const Tag = tag as any
  return <Tag key={key}>{kids}</Tag>
}

/** Parse a Telegram-HTML message body into React nodes. DOMParser documents are inert (no script runs). */
export function TelegramHtml({ body }: { body: string }) {
  let nodes: ReactNode = body
  try {
    const doc = new DOMParser().parseFromString(`<div>${body}</div>`, 'text/html')
    const root = doc.body.firstElementChild
    if (root) nodes = Array.from(root.childNodes).map((c, i) => renderNode(c, String(i)))
  } catch { /* fall back to the raw text */ }
  return <div data-testid="comms-message-body" style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', fontSize: 13, lineHeight: 1.55, color: TEXT }}>{nodes}</div>
}

// ── Lifecycle actions, explained ────────────────────────────────────────────
/** What each button does to the message (communication_events), in the operator's words. None touches trading. */
export const MESSAGE_ACTIONS: { action: string; extra: Record<string, any>; label: string; help: string }[] = [
  { action: 'acknowledge', extra: {}, label: 'Acknowledge', help: 'Marks it as seen by you (name + time recorded). It stays in the feed and still expires on its normal timer.' },
  { action: 'retain', extra: { retain_hours: 168 }, label: 'Keep 7 more days', help: 'Keeps it in the feed for at least 7 days from now, even if its timer runs out sooner. Revives it if already expired. Afterwards it expires normally.' },
  { action: 'retain', extra: {}, label: 'Keep until I release', help: 'Pins it: it never expires or gets cleaned up until you press Release.' },
  { action: 'expire', extra: {}, label: 'Dismiss now', help: 'Removes it from the live feed now. Still visible under the Expired filter for 24h, then archived and cleaned up.' },
]

function Fact({ label, value, sub, color, tip }: { label: string; value: ReactNode; sub?: ReactNode; color?: string; tip: string }) {
  return (
    <div title={tip} style={{ background: 'var(--bg2)', border: `1px solid ${BORDER}`, borderRadius: RADIUS.md, padding: '8px 10px', minWidth: 0 }}>
      <div style={{ fontSize: 10, color: MUTED, textTransform: 'uppercase', letterSpacing: '.06em', fontWeight: 700 }}>{label}</div>
      <div style={{ ...numStyle, fontSize: 18, fontWeight: 800, color: color || TEXT, lineHeight: 1.25 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: TEXT2, marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

export function MessageDrawer({ e, id, onClose, onAction }: {
  e: any; id: string; onClose: () => void
  onAction: (action: string, extra: Record<string, any>, label: string, help: string) => void
}) {
  useEffect(() => {
    const k = (ev: KeyboardEvent) => { if (ev.key === 'Escape') onClose() }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose])

  const fam: Family = familyFor(e?.priority, e?.category)
  const st = familyStyle(fam)
  const syms: string[] = e?.symbols || []
  const l = e?.levels || {}
  const a = e?.analyst
  const px = e?.market?.price
  const pctFrom = (v: any) => (px && v != null ? `${((Number(v) / Number(px) - 1) * 100).toFixed(1)}% from price` : undefined)
  const catalyst = catalystOf(e?.sanitized_body)
  const acked = e?.lifecycle_status === 'acknowledged' || e?.acknowledged_at

  return (
    <div onClick={onClose} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.5)', zIndex: 900 }}>
      <div data-testid="comms-drawer" role="dialog" aria-modal="true" onClick={(ev) => ev.stopPropagation()}
        style={{ position: 'absolute', right: 0, top: 0, bottom: 0, width: 'min(920px, 96vw)', background: 'var(--bg1)', borderLeft: `4px solid ${st.border}`, display: 'flex', flexDirection: 'column' }}>
        {/* header */}
        <div style={{ padding: '14px 18px 10px', borderBottom: `1px solid ${BORDER}` }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 20 }}>{FAMILY_ICON[fam]}</span>
            {syms.length > 0 && <span style={{ fontSize: 24, fontWeight: 900, color: TEXT }}><SymbolLink symbol={syms[0]} />{syms.length > 1 && <span style={{ fontSize: 12, color: MUTED }}> +{syms.slice(1).join(', ')}</span>}</span>}
            {syms.length > 0 && <PriceTag m={e?.market} />}
            <span style={{ fontSize: 15, fontWeight: 800, color: st.color }}>{alertType(e?.headline || e?.short_summary, syms)}</span>
            <span style={{ flex: 1 }} />
            <span style={{ fontSize: 12, color: MUTED }}>{ttlLabel(e?.ttl_remaining_s, e?.legal_hold)}</span>
            <button type="button" onClick={onClose} aria-label="Close" style={{ fontSize: 12, border: `1px solid ${BORDER}`, background: 'transparent', color: TEXT2, cursor: 'pointer', padding: '3px 10px', borderRadius: RADIUS.sm }}>Close ✕</button>
          </div>
          {e?.actionable && e?.action_hint && <div style={{ fontSize: 15, fontWeight: 700, color: TEXT, marginTop: 4 }}>▶ {e.action_hint}</div>}
          <div style={{ marginTop: 6 }}><ItemBadges e={e || {}} />{acked && <span style={{ fontSize: 11, color: 'var(--success-color)', marginLeft: 6 }}>✓ acknowledged{e?.acknowledged_by ? ` by ${e.acknowledged_by}` : ''}</span>}{e?.legal_hold && <span style={{ fontSize: 11, color: 'var(--info-color)', marginLeft: 6 }}>📌 kept until released</span>}</div>
        </div>

        {/* body */}
        <div style={{ flex: 1, overflowY: 'auto', padding: '14px 18px' }}>
          {!e && <div style={{ color: MUTED }}>Loading message {id}…</div>}
          {e && (
            <>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8, marginBottom: 12 }}>
                {(l.entry_zone?.[0] != null || l.entry_ref != null) && (
                  <Fact label="Entry" tip="CIO entry zone for this setup; the line below compares it with the live quote" value={l.entry_zone?.[0] != null ? `${usd(l.entry_zone[0])}–${usd(l.entry_zone[1])}` : usd(l.entry_ref)} sub={px != null && l.entry_zone?.[0] != null ? (px >= l.entry_zone[0] && px <= l.entry_zone[1] ? 'price is inside the zone' : px > l.entry_zone[1] ? 'price is above the zone' : 'price is below the zone') : undefined} />
                )}
                {l.invalidation_level != null && <Fact label="Stop" tip="CIO invalidation level: a close below it kills the setup. % is the distance from the live quote" value={usd(l.invalidation_level)} sub={pctFrom(l.invalidation_level)} color="var(--danger-color)" />}
                {l.target != null && <Fact label="Target" tip="CIO primary target. % is the distance from the live quote" value={usd(l.target)} sub={pctFrom(l.target)} color="var(--success-color)" />}
                {l.rr != null && <Fact label="Reward : risk" tip="Reward to target divided by risk to stop, from the CIO plan" value={`${Number(l.rr).toFixed(1)} : 1`} />}
                <Fact label="CIO conviction" tip="CIO conviction 0-100 for this ticker: the same number Home and the opportunity view show" value={l.conviction != null ? `${Math.round(l.conviction)}/100` : '—'} sub={l.conviction == null ? 'not scored by the CIO' : l.low_conviction ? `below the floor ${l.conviction_floor}` : l.rank ? `rank #${l.rank}` : undefined} color={l.low_conviction ? 'var(--warning-color)' : undefined} />
                <Fact label="Analysts" tip="Street consensus from the Yahoo analyst targets store (rating, analyst count, mean and range of price targets); marked stale after 30 days" value={a ? (a.rating || 'No rating') : '—'}
                  color={a && /buy/i.test(a.rating || '') ? 'var(--success-color)' : a && /sell|underperform/i.test(a.rating || '') ? 'var(--danger-color)' : undefined}
                  sub={a ? <>
                    {a.analyst_count ? `${a.analyst_count} analysts · ` : ''}{a.target_mean != null ? `mean ${usd(a.target_mean)}${a.upside_pct != null ? ` (${a.upside_pct >= 0 ? '+' : ''}${a.upside_pct}%)` : ''}` : ''}
                    {a.target_low != null && <div>range {usd(a.target_low)}–{usd(a.target_high)}</div>}
                    <div style={{ color: a.stale ? 'var(--warning-color)' : MUTED }}>as of {a.as_of ? new Date(a.as_of).toLocaleDateString() : '—'}{a.stale ? ' · stale' : ''}</div>
                  </> : 'no Street coverage on file'} />
              </div>
              {catalyst && <div style={{ fontSize: 13, color: TEXT, marginBottom: 12 }}><span style={{ color: MUTED, fontWeight: 700 }}>Catalyst </span>{catalyst}</div>}

              <div style={{ fontSize: 10, color: MUTED, fontWeight: 800, letterSpacing: '.06em', textTransform: 'uppercase', marginBottom: 6 }}>Full message</div>
              <div style={{ border: `1px solid ${BORDER}`, borderRadius: RADIUS.md, padding: '12px 14px', background: 'var(--bg0, transparent)' }}>
                <TelegramHtml body={e.sanitized_body || e.short_summary || ''} />
              </div>

              <details style={{ marginTop: 12, fontSize: 12, color: TEXT2 }}>
                <summary style={{ cursor: 'pointer', color: MUTED }}>Message details (scores, source, timing)</summary>
                <div style={{ lineHeight: 1.7, marginTop: 6 }}>
                  {[
                    ['Message priority', e.priority_score ?? '—'],
                    ['Confidence · Risk · Reward · Time sensitivity', [e.confidence, e.risk_score, e.reward_score, e.time_sensitivity].map((v: any) => (v == null ? '—' : Number(v).toFixed(2))).join(' · ')],
                    ['Status', e.lifecycle_status || '—'],
                    ['Expires', `${fmtWhen(e.expires_at)}${e.retain_until ? ` · kept until ${fmtWhen(e.retain_until)}` : ''}`],
                    ['Actionable since', e.actionable ? fmtWhen(e.actionable_since) : 'not actionable'],
                    ['Source', e.producer || '—'],
                    ['Created', fmtWhen(e.created_at)],
                    ['Classified by rule', e.classified_by || '—'],
                    ['Message id', id],
                  ].map(([k, v]) => <div key={String(k)}><span style={{ color: MUTED }}>{k}: </span><span style={{ color: TEXT }}>{String(v)}</span></div>)}
                </div>
              </details>
            </>
          )}
        </div>

        {/* actions */}
        {e && (
          <div data-testid="comms-drawer-actions" style={{ borderTop: `1px solid ${BORDER}`, padding: '10px 18px 14px', background: 'var(--bg1)' }}>
            <div style={{ fontSize: 11, color: MUTED, marginBottom: 8 }}>
              These only change how long this message stays in your feed. None of them places, sizes, stops or cancels an order. Each asks you to confirm first.
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 8 }}>
              {(e.legal_hold
                ? [...MESSAGE_ACTIONS.filter((x) => x.label !== 'Keep until I release'), { action: 'release', extra: {}, label: 'Release', help: 'Un-pins it: it goes back to expiring on its normal timer.' }]
                : MESSAGE_ACTIONS
              ).filter((x) => !(x.action === 'acknowledge' && acked)).map((x) => (
                <button key={x.label} type="button" onClick={() => onAction(x.action, x.extra, x.label, x.help)}
                  style={{ textAlign: 'left', padding: '8px 10px', border: `1px solid ${x.action === 'expire' ? 'var(--danger-color)' : BORDER}`, borderRadius: RADIUS.md, background: 'var(--bg2)', color: TEXT, cursor: 'pointer' }}>
                  <div style={{ fontSize: 13, fontWeight: 800 }}>{x.label}</div>
                  <div style={{ fontSize: 11, color: TEXT2, marginTop: 2, lineHeight: 1.35 }}>{x.help}</div>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
