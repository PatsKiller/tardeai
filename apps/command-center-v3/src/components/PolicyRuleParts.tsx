import { Fragment, type CSSProperties, type ReactNode } from 'react'
import ReadableTime from './ReadableTime'
import { RADIUS } from '../lib/designTokens'
import type { Policy, Rule } from '../lib/operatorApprovals'

/** Fields the Rulebook read model adds on top of the shared Policy/Rule types. */
export type RulebookRule = Rule & { subsection?: string | null; number?: string | null }
export type RulebookAudit = Policy['audit'] & { reason?: string | null; last_run?: string | null }
export type RulebookPolicy = Omit<Policy, 'counts' | 'audit' | 'rules'> & {
  rules: RulebookRule[]
  counts: Record<string, number | null>
  counts_measured?: boolean
  section_counts?: Record<string, number>
  section_status?: Record<string, string>
  policy_version?: string | null
  last_reviewed?: string | null
  audit: RulebookAudit
}

const SAFE_HREF = /^(https?:\/\/|\/(?!\/)|#)/i

/** Inline markdown → text elements: **bold**, *italic*, `code`, [label](url). Never injects HTML. */
export function inlineMarkdown(text: string, keyPrefix = 'm'): ReactNode[] {
  const out: ReactNode[] = []
  const pattern = /(`[^`]+`)|(\*\*[^*]+?\*\*)|(\[[^\]]+\]\([^)\s]+\))|(\*[^*\s][^*]*?\*)/g
  let last = 0
  let match: RegExpExecArray | null
  let n = 0
  while ((match = pattern.exec(text))) {
    if (match.index > last) out.push(text.slice(last, match.index))
    const token = match[0]
    const key = `${keyPrefix}-${n++}`
    if (match[1]) out.push(<code key={key} style={{ fontSize: '0.92em', background: 'var(--bg-2)', padding: '0 4px', borderRadius: RADIUS.sm }}>{token.slice(1, -1)}</code>)
    else if (match[2]) out.push(<strong key={key}>{inlineMarkdown(token.slice(2, -2), key)}</strong>)
    else if (match[3]) {
      const split = token.indexOf('](')
      const label = token.slice(1, split), href = token.slice(split + 2, -1)
      out.push(SAFE_HREF.test(href)
        ? <a key={key} href={href} target={href.startsWith('http') ? '_blank' : undefined} rel="noopener noreferrer">{inlineMarkdown(label, key)}</a>
        : <Fragment key={key}>{inlineMarkdown(label, key)}</Fragment>)
    } else out.push(<em key={key}>{inlineMarkdown(token.slice(1, -1), key)}</em>)
    last = match.index + token.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

const textStyle: CSSProperties = { overflowWrap: 'anywhere', font: '15px/1.65 Georgia, serif', margin: 0 }

/** A rule's text as readable prose: nested "- " lines become a list, blank-line breaks become paragraphs. */
export function RuleMarkdown({ text, testId }: { text: string; testId?: string }) {
  const blocks: { kind: 'p' | 'li'; text: string }[] = []
  for (const line of text.split('\n')) {
    if (!line.trim()) continue
    if (line.startsWith('- ')) blocks.push({ kind: 'li', text: line.slice(2) })
    else blocks.push({ kind: 'p', text: line })
  }
  const nodes: ReactNode[] = []
  let list: ReactNode[] = []
  const flush = () => { if (list.length) { nodes.push(<ul key={`ul-${nodes.length}`} style={{ margin: '6px 0 0', paddingLeft: 20 }}>{list}</ul>); list = [] } }
  blocks.forEach((block, i) => {
    if (block.kind === 'li') list.push(<li key={i}>{inlineMarkdown(block.text, `li${i}`)}</li>)
    else { flush(); nodes.push(<p key={i} style={{ ...textStyle, marginTop: i ? 6 : 0 }}>{inlineMarkdown(block.text, `p${i}`)}</p>) }
  })
  flush()
  return <div className="rule-body" data-testid={testId} style={textStyle}>{nodes}</div>
}

const TILES: { key: string; label: string; measured: boolean }[] = [
  { key: 'RULES', label: 'Rules', measured: false },
  { key: 'ENFORCED', label: 'Enforced', measured: true },
  { key: 'TESTED', label: 'Tested only', measured: true },
  { key: 'WRITTEN-only', label: 'Written only', measured: false },
  { key: 'VIOLATED', label: 'Violated', measured: true },
]

/** Count tiles. A measured tile with no audit result says "Audit not run", never 0. */
export function PolicyCountTiles({ data }: { data: RulebookPolicy }) {
  const counts = data.counts || {}
  const total = typeof counts.RULES === 'number' ? counts.RULES : data.total_rules
  const notRun = data.counts_measured === false
  return <>
    <div className="counts" data-testid="rulebook-counts" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 130px), 1fr))' }}>
      {TILES.map(tile => {
        const value = tile.key === 'RULES' ? total : counts[tile.key]
        const gap = value == null || (tile.measured && notRun)
        return <div key={tile.key} className="panel" data-testid={`rulebook-count-${tile.key}`}>
          <span>{tile.label}</span>
          {gap ? <strong style={{ fontSize: 15 }} className="warning">Audit not run</strong> : <strong>{value}</strong>}
        </div>
      })}
    </div>
    {notRun && <p className="warning" data-testid="rulebook-audit-gap" style={{ margin: '0 0 8px' }}>
      {data.audit.reason || 'The enforcement audit has not run against this policy version.'}
      {data.audit.last_run && <> Last run: <ReadableTime value={data.audit.last_run} />.</>}
    </p>}
  </>
}

/** The aside's "Last audit" line: a verified run time, the last unverified run, or "Not run" with the reason. */
export function AuditLastLine({ audit }: { audit: RulebookAudit }) {
  if (audit.last_audit) return <p data-testid="rulebook-last-audit">Last audit: <ReadableTime value={audit.last_audit} /></p>
  return <p className="warning" data-testid="rulebook-last-audit">
    Last audit: Not run{audit.last_run ? <> (last run <ReadableTime value={audit.last_run} />, not this version)</> : null}
  </p>
}

/** Section option label: name, rule count, and the worst measured status when an audit has run. */
export function sectionOption(data: RulebookPolicy, section: string) {
  const count = data.section_counts?.[section]
  const status = data.section_status?.[section]
  const dot = status === 'VIOLATED' ? '● Violated · ' : status === 'WRITTEN-only' ? '○ ' : status ? '✓ ' : ''
  return `${dot}${section}${count != null ? ` (${count})` : ''}`
}
