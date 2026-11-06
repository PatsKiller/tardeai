/**
 * Read-side rich formatting for report bodies (Reports redesign v001, operator 2026-11-06):
 * tickers bold, negative % red, positive % green, "what to look at" sentences italic, bold
 * lead sentences highlighted. Stored report text is never rewritten — this only renders it.
 */
import { useState, type ReactNode } from 'react'
import { tokenize, type Tok } from './reportFormat'
import { pageLink, v3Href, isRiskLine } from './reportLinks'

function renderToks(toks: Tok[], risk: boolean, keyBase: string): ReactNode[] {
  return toks.map((t, i) => {
    const key = `${keyBase}.${i}`
    switch (t.k) {
      case 'text': return <span key={key}>{t.v}</span>
      case 'ticker':
        return risk
          ? <a key={key} className="fx-tk" href={v3Href('/v3/risk', t.v)} onClick={e => e.stopPropagation()}>{t.v}</a>
          : <strong key={key} className="fx-tk">{t.v}</strong>
      case 'pct':
      case 'arrow':
        return <span key={key} className={t.tone === 'neg' ? 'fx-neg' : t.tone === 'pos' ? 'fx-pos' : 'fx-flat'}>{t.v}</span>
      case 'bold': return <strong key={key} className="fx-b">{renderToks(t.v, risk, key)}</strong>
      case 'key': return <mark key={key} className="fx-key">{renderToks(t.v, risk, key)}</mark>
      case 'look': return <em key={key} className="fx-look">{renderToks(t.v, risk, key)}</em>
      case 'code': return <code key={key} className="fx-code">{t.v}</code>
      case 'url': return <a key={key} className="fx-url" href={t.v} target="_blank" rel="noreferrer noopener">{t.v}</a>
      case 'route': {
        const pl = pageLink(t.v)
        return <a key={key} className="fx-route" href={v3Href(t.v.startsWith('/v2') ? pl.route : t.v)} title={t.v}>{pl.label} →</a>
      }
      default: return null
    }
  })
}

/** One line of prose → formatted inline nodes. */
export function RichInline({ text, known }: { text: string; known?: Set<string> }) {
  const clean = text.replace(/\s*→\s*(?=\/v[23]\/)/g, ' ')
  return <>{renderToks(tokenize(clean, known), isRiskLine(clean), 'i')}</>
}

type Block =
  | { t: 'h'; level: number; text: string }
  | { t: 'p'; text: string }
  | { t: 'hr' }
  | { t: 'ul'; items: { text: string; sub: string[] }[] }

const BULLET_RX = /^(\s*)(?:[-•▪◦·*]|\d+[.)])\s+(.*)$/

/** Markdown-ish body → blocks (headers, paragraphs, bullet lists with one nesting level, rules). */
export function toBlocks(md: string): Block[] {
  const out: Block[] = []
  let list: { text: string; sub: string[] }[] | null = null
  const flush = () => { if (list && list.length) out.push({ t: 'ul', items: list }); list = null }
  for (const raw of (md || '').split('\n')) {
    const line = raw.replace(/\s+$/, '')
    if (!line.trim()) { flush(); continue }
    const h = line.match(/^(#{1,6})\s+(.*)$/)
    if (h) { flush(); out.push({ t: 'h', level: h[1].length, text: h[2] }); continue }
    if (/^\s*([-*_])\1{2,}\s*$/.test(line)) { flush(); out.push({ t: 'hr' }); continue }
    if (/^\s*\|/.test(line)) { flush(); out.push({ t: 'p', text: line.replace(/^\s*\||\|\s*$/g, '').split('|').map(s => s.trim()).join(' · ') }); continue }
    const b = line.match(BULLET_RX)
    if (b) {
      const nested = b[1].length >= 2
      if (nested && list && list.length) list[list.length - 1].sub.push(b[2])
      else { if (!list) list = []; list.push({ text: b[2], sub: [] }) }
      continue
    }
    if (list && list.length && /^\s{2,}\S/.test(raw)) { list[list.length - 1].text += ' ' + line.trim(); continue }
    flush()
    const prev = out[out.length - 1]
    if (prev && prev.t === 'p' && !/^\s*\|/.test(line)) prev.text += ' ' + line.trim()
    else out.push({ t: 'p', text: line.trim() })
  }
  flush()
  return out
}

function BulletList({ items, known, max }: { items: { text: string; sub: string[] }[]; known?: Set<string>; max: number }) {
  const [all, setAll] = useState(false)
  const shown = all || items.length <= max ? items : items.slice(0, max)
  return (
    <>
      <ul>
        {shown.map((it, i) => (
          <li key={i}>
            <RichInline text={it.text} known={known} />
            {it.sub.length > 0 && <ul>{it.sub.map((s, j) => <li key={j}><RichInline text={s} known={known} /></li>)}</ul>}
          </li>
        ))}
      </ul>
      {items.length > max && (
        <div className="more">
          <button type="button" className="rp-btn" onClick={() => setAll(v => !v)}>
            {all ? 'Show fewer' : `Show all ${items.length}`}
          </button>
        </div>
      )}
    </>
  )
}

/** A report body (or one section of it) with the rich formatting layer applied. */
export function ReportBody({ md, known, maxBullets = 10 }: { md: string; known?: Set<string>; maxBullets?: number }) {
  const blocks = toBlocks(md)
  return (
    <div className="rp-md">
      {blocks.map((b, i) => {
        if (b.t === 'hr') return <hr key={i} />
        if (b.t === 'h') return b.level <= 3 ? <h3 key={i}><RichInline text={b.text} known={known} /></h3> : <h4 key={i}><RichInline text={b.text} known={known} /></h4>
        if (b.t === 'ul') return <BulletList key={i} items={b.items} known={known} max={maxBullets} />
        return <p key={i}><RichInline text={b.text} known={known} /></p>
      })}
    </div>
  )
}
