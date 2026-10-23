// A small, safe markdown renderer for the Work pipeline drawer and the Playbook tab (operator 2026-10-23: the board
// carries problem / definition of done / agent prompt / operator commands / proof, and the playbook). React elements
// only, never innerHTML: fenced code, headings, bullet and numbered lists, block quotes, tables (kept monospace),
// paragraphs; inline `code`, **bold** and http(s) links. Anything else renders as plain text.
import type { CSSProperties, ReactNode } from 'react'
import { FONT, RADIUS, TOKENS, TYPE } from '../lib/designTokens'

const code: CSSProperties = { fontFamily: FONT.mono, fontSize: TYPE.sm, background: TOKENS.bg[2], borderRadius: RADIUS.sm, padding: '0 3px', overflowWrap: 'anywhere' }
const pre: CSSProperties = { fontFamily: FONT.mono, fontSize: TYPE.sm, background: TOKENS.bg[2], border: `1px solid ${TOKENS.borderSubtle}`, borderRadius: RADIUS.sm, padding: 8, margin: '4px 0', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', color: TOKENS.text[1] }

export function inline(text: string, key = 'i'): ReactNode[] {
  const out: ReactNode[] = []
  const re = /(`[^`]+`)|(\*\*[^*]+\*\*)|\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g
  let last = 0
  let m: RegExpExecArray | null
  let n = 0
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const k = `${key}-${n++}`
    if (m[1]) out.push(<code key={k} style={code}>{m[1].slice(1, -1)}</code>)
    else if (m[2]) out.push(<b key={k} style={{ color: TOKENS.text[0] }}>{inline(m[2].slice(2, -2), k)}</b>)
    else out.push(<a key={k} href={m[4]} target="_blank" rel="noreferrer" style={{ color: TOKENS.info }}>{m[3]}</a>)
    last = m.index + m[0].length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

type Block = { kind: 'code' | 'h' | 'ul' | 'ol' | 'quote' | 'table' | 'p'; lines: string[]; level?: number }

export function blocks(md: string): Block[] {
  const lines = md.replace(/\r\n/g, '\n').split('\n')
  const out: Block[] = []
  let i = 0
  while (i < lines.length) {
    const ln = lines[i]
    if (ln.trimStart().startsWith('```')) {
      const body: string[] = []
      i++
      while (i < lines.length && !lines[i].trimStart().startsWith('```')) body.push(lines[i++])
      i++
      out.push({ kind: 'code', lines: body })
      continue
    }
    if (!ln.trim()) { i++; continue }
    const h = /^(#{1,6})\s+(.*)$/.exec(ln)
    if (h) { out.push({ kind: 'h', lines: [h[2]], level: h[1].length }); i++; continue }
    const take = (test: (s: string) => boolean, kind: Block['kind']) => {
      const body: string[] = []
      while (i < lines.length && lines[i].trim() && test(lines[i])) body.push(lines[i++])
      out.push({ kind, lines: body })
    }
    if (/^\s*>/.test(ln)) { take(s => /^\s*>/.test(s), 'quote'); continue }
    if (/^\s*\|/.test(ln)) { take(s => /^\s*\|/.test(s), 'table'); continue }
    if (/^\s*[-*]\s+/.test(ln)) { take(s => /^\s*([-*]\s+|\s{2,}\S)/.test(s), 'ul'); continue }
    if (/^\s*\d+\.\s+/.test(ln)) { take(s => /^\s*(\d+\.\s+|\s{2,}\S)/.test(s), 'ol'); continue }
    take(s => !/^\s*(```|#{1,6}\s|>|\||[-*]\s+|\d+\.\s+)/.test(s), 'p')
  }
  return out
}

function listItems(lines: string[], marker: RegExp): string[][] {
  const items: string[][] = []
  for (const ln of lines) {
    if (marker.test(ln) && !/^\s{2,}/.test(ln.replace(marker, ''))) items.push([ln.replace(marker, '')])
    else if (items.length) items[items.length - 1].push(ln.trim())
    else items.push([ln])
  }
  return items
}

export default function MiniMarkdown({ text, testId }: { text?: string | null; testId?: string }) {
  if (!text) return null
  return <div data-testid={testId} style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: TYPE.base, color: TOKENS.text[1], minWidth: 0, overflowWrap: 'anywhere' }}>
    {blocks(text).map((b, j) => {
      const k = `b${j}`
      switch (b.kind) {
        case 'code': return <pre key={k} style={pre}>{b.lines.join('\n')}</pre>
        case 'table': return <pre key={k} style={pre}>{b.lines.join('\n')}</pre>
        case 'h': return <div key={k} style={{ fontWeight: 700, color: TOKENS.text[0], fontSize: (b.level ?? 3) <= 2 ? TYPE.md : TYPE.base, marginTop: 4 }}>{inline(b.lines[0], k)}</div>
        case 'quote': return <blockquote key={k} style={{ margin: 0, padding: '2px 0 2px 10px', borderLeft: `3px solid ${TOKENS.border}`, color: TOKENS.text[1] }}>
          <MiniMarkdown text={b.lines.map(l => l.replace(/^\s*>\s?/, '')).join('\n')} />
        </blockquote>
        case 'ul': return <ul key={k} style={{ margin: 0, paddingLeft: 18 }}>{listItems(b.lines, /^\s*[-*]\s+/).map((it, x) => <li key={x}>{inline(it.join(' '), `${k}-${x}`)}</li>)}</ul>
        case 'ol': return <ol key={k} style={{ margin: 0, paddingLeft: 20 }}>{listItems(b.lines, /^\s*\d+\.\s+/).map((it, x) => <li key={x}>{it.map((l, y) => /^\s*>/.test(l) ? <blockquote key={y} style={{ margin: '2px 0', paddingLeft: 8, borderLeft: `3px solid ${TOKENS.border}` }}>{inline(l.replace(/^\s*>\s?/, ''), `${k}-${x}-${y}`)}</blockquote> : <span key={y}>{y ? ' ' : ''}{inline(l, `${k}-${x}-${y}`)}</span>)}</li>)}</ol>
        default: return <p key={k} style={{ margin: 0 }}>{inline(b.lines.join(' '), k)}</p>
      }
    })}
  </div>
}
