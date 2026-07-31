/** Shared analyst-brief card primitive for the Intel section.
 *
 * Every Intel hub (Hermes Briefs, Research Intel, Intelligence Command Center) should
 * read as an analyst report — headline, synthesized thesis, sources, freshness — never
 * raw enum codes or pipeline telemetry as the primary label. This is the one shared card
 * shape so hubs don't each invent their own "report" UI (see intel maturity audit,
 * 2026-07-31). Hubs adapt their own item shape into `IntelBrief` and render this card.
 */
import { useState } from 'react'
import { BB, T, TYPE } from '../../lib/watchTokens'

export type IntelBriefSeverity = 'critical' | 'warning' | 'info'

export interface IntelBriefSource {
  label?: string
  url?: string
}

export interface IntelBrief {
  id: string
  title: string
  symbol?: string | null
  /** Source-system tag shown as a small chip (e.g. "Hermes", "auto-research"). */
  tag?: string
  /** Primary narrative body — thesis, summary, or synthesized insight. */
  body?: string
  severity?: IntelBriefSeverity
  confidence?: number | null
  freshnessLabel?: string
  /** "→ what to do about it" line. */
  actionability?: string
  openQuestion?: string
  sources?: IntelBriefSource[]
  isHeld?: boolean
}

const SEVERITY_COLOR: Record<IntelBriefSeverity, string> = { critical: BB.red, warning: BB.amber, info: T.link }

function confTone(conf?: number | null): string {
  if (conf == null) return 'var(--text3)'
  if (conf >= 0.7) return BB.green
  if (conf >= 0.4) return BB.amber
  return BB.red
}

function domainOf(u?: string): string | null {
  if (!u) return null
  try { return new URL(u).hostname.replace(/^www\./, '') } catch { return null }
}

const BODY_TRUNCATE = 260

export default function IntelBriefCard({ brief, onOpen }: { brief: IntelBrief; onOpen?: (b: IntelBrief) => void }) {
  const [expanded, setExpanded] = useState(false)
  const body = brief.body || ''
  const truncated = !expanded && body.length > BODY_TRUNCATE
  const sources = (brief.sources ?? []).filter(s => s.url || s.label)
  const sevColor = brief.severity ? SEVERITY_COLOR[brief.severity] : null

  return (
    <div style={{ background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 14, marginBottom: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10, flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          {sevColor && <span style={{ width: 7, height: 7, borderRadius: 4, background: sevColor, flexShrink: 0 }} />}
          {brief.symbol && (
            <span style={{ fontFamily: 'var(--mono, monospace)', fontWeight: 800, fontSize: TYPE.sm, color: T.link }}>
              {brief.symbol}
            </span>
          )}
          <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>{brief.title}</span>
          {brief.isHeld && (
            <span style={{ fontSize: TYPE.xs, padding: '1px 6px', borderRadius: 3, background: 'rgba(96,165,250,.15)', color: T.link, fontWeight: 700 }}>HELD</span>
          )}
          {brief.tag && (
            <span style={{ fontSize: TYPE.xs, padding: '1px 6px', borderRadius: 3, background: 'var(--bg2)', color: 'var(--text3)', fontWeight: 700, textTransform: 'uppercase' }}>{brief.tag}</span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
          {brief.confidence != null && (
            <span style={{ fontSize: TYPE.xs, fontWeight: 700, color: confTone(brief.confidence) }}>
              {Math.round(brief.confidence * 100)}% conf
            </span>
          )}
          {brief.freshnessLabel && (
            <span style={{ fontSize: TYPE.xs, color: 'var(--text3)' }}>{brief.freshnessLabel}</span>
          )}
        </div>
      </div>

      {body && (
        <div style={{ fontSize: TYPE.sm, color: 'var(--text2)', marginTop: 8, lineHeight: 1.5 }}>
          {truncated ? `${body.slice(0, BODY_TRUNCATE)}…` : body}
          {body.length > BODY_TRUNCATE && (
            <button
              onClick={() => setExpanded(v => !v)}
              style={{ marginLeft: 6, background: 'none', border: 'none', color: T.link, cursor: 'pointer', fontSize: TYPE.xs, padding: 0 }}
            >
              {expanded ? 'show less' : 'read more'}
            </button>
          )}
        </div>
      )}

      {brief.actionability && (
        <div style={{ fontSize: TYPE.xs, color: sevColor || BB.amber, marginTop: 8 }}>→ {brief.actionability}</div>
      )}

      {brief.openQuestion && (
        <div style={{ fontSize: TYPE.xs, color: 'var(--text3)', marginTop: 6 }}>Open question: {brief.openQuestion}</div>
      )}

      {sources.length > 0 && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
          {sources.slice(0, 5).map((s, i) => {
            const dom = domainOf(s.url) || s.label || 'source'
            return s.url ? (
              <a key={i} href={s.url} target="_blank" rel="noreferrer"
                style={{ fontSize: TYPE.xs, color: T.link, textDecoration: 'none', background: 'var(--bg2)', padding: '2px 8px', borderRadius: 4 }}>
                🔎 {dom}
              </a>
            ) : (
              <span key={i} style={{ fontSize: TYPE.xs, color: 'var(--text3)', background: 'var(--bg2)', padding: '2px 8px', borderRadius: 4 }}>{dom}</span>
            )
          })}
        </div>
      )}

      {onOpen && (
        <div onClick={() => onOpen(brief)} style={{ fontSize: TYPE.xs, color: 'var(--text3)', marginTop: 8, cursor: 'pointer' }}>
          View raw evidence →
        </div>
      )}
    </div>
  )
}
