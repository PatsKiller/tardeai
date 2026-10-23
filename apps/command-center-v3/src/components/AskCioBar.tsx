/**
 * Ask the CIO — the global ask bar in the header of every page (⌘K / Ctrl-K focuses it).
 *
 * Same brain as the CIO Telegram bot: POST /api/v2/cio/ask runs the shared converse path, so the answer here is the
 * answer Telegram gives. Quantities are optional. The answer opens inline; the thread lives on My questions.
 */
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { FONT, RADIUS, SHADOW, TOKENS, TYPE, chipStyle } from '../lib/designTokens'
import { ASK_PATHS, TOOLTIPS, isAskShortcut, statusLabel, statusTone, trackedChips, unwrap, validateQuestion } from '../lib/askCioModel'
import type { AskStatus, TrackedRow } from '../lib/askCioModel'
import { useApi } from '../hooks/useApi'
import { askCio, askErrorText, type AskResult } from '../lib/askCioApi'

export default function AskCioBar() {
  const [q, setQ] = useState('')
  const [deep, setDeep] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [res, setRes] = useState<AskResult | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const nav = useNavigate()
  const trackedRes = useApi<unknown>(ASK_PATHS.tracked, 60_000)
  const chips = trackedChips(unwrap<{ tracked: TrackedRow[] }>(trackedRes.data)?.tracked)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isAskShortcut(e)) {
        e.preventDefault()
        inputRef.current?.focus()
        inputRef.current?.select()
      } else if (e.key === 'Escape' && (res || err)) {
        setRes(null)
        setErr(null)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [res, err])

  async function submit(e?: React.FormEvent) {
    e?.preventDefault()
    const v = validateQuestion(q)
    if (!v.ok) { setErr(v.reason); return }
    setBusy(true); setErr(null); setRes(null)
    try {
      const r = await askCio(v.question, { deep })
      setRes(r)
      setQ('')
    } catch (ex) {
      setErr(askErrorText(ex))
    } finally {
      setBusy(false)
    }
  }

  const status = (res?.thread?.status ?? 'quick') as AskStatus
  return (
    <div data-testid="ask-cio-bar" style={{ position: 'relative', padding: '6px 16px', borderBottom: `1px solid ${TOKENS.border}`, background: TOKENS.bg[1] }}>
      <form onSubmit={submit} style={{ display: 'flex', gap: 8, alignItems: 'center', maxWidth: 1100 }} title={TOOLTIPS.bar}>
        <span style={{ ...chipStyle('ai'), flex: '0 0 auto' }}>Ask the CIO</span>
        <input
          ref={inputRef}
          data-testid="ask-cio-input"
          aria-label="Ask the CIO"
          value={q}
          onChange={e => setQ(e.target.value)}
          placeholder="e.g. 100 or 1,000 TSLA given the SpaceX merger talk?  (⌘K)"
          disabled={busy}
          style={{ flex: 1, minWidth: 0, fontSize: TYPE.base, padding: '6px 10px', borderRadius: RADIUS.md, border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[0], color: TOKENS.text[0], fontFamily: FONT.sans }}
        />
        <label title={TOOLTIPS.deep} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: TYPE.sm, color: TOKENS.text[2], whiteSpace: 'nowrap' }}>
          <input type="checkbox" data-testid="ask-cio-deep" checked={deep} onChange={e => setDeep(e.target.checked)} disabled={busy} />
          Deep
        </label>
        <button type="submit" data-testid="ask-cio-submit" disabled={busy || !q.trim()}
          style={{ fontSize: TYPE.sm, fontWeight: 700, padding: '6px 12px', borderRadius: RADIUS.md, border: `1px solid ${TOKENS.border}`, background: TOKENS.primary, color: TOKENS.bg[0], cursor: busy ? 'wait' : 'pointer' }}>
          {busy ? 'Asking…' : 'Ask'}
        </button>
        {chips.length > 0 && (
          <span data-testid="ask-cio-tracked" title="Tracked from your questions (watchlist, catalyst watch, re-answer on material change)"
            style={{ display: 'inline-flex', gap: 4, alignItems: 'center', overflow: 'hidden', maxWidth: 320, whiteSpace: 'nowrap' }}>
            {chips.map(c => (
              <Link key={c.key} to={`/cio/questions/${c.thread_id}`} style={{ ...chipStyle('info', 'outline'), textDecoration: 'none' }}>{c.label}</Link>
            ))}
          </span>
        )}
        <Link to="/cio/questions" data-testid="ask-cio-my-questions" style={{ fontSize: TYPE.sm, color: TOKENS.info, whiteSpace: 'nowrap' }}>My questions</Link>
      </form>
      {(res || err) && (
        <div data-testid="ask-cio-answer" role="dialog" aria-label="CIO answer"
          style={{ position: 'absolute', zIndex: 40, left: 16, right: 16, top: '100%', maxWidth: 1100, maxHeight: '60vh', overflowY: 'auto', marginTop: 4, padding: 12, borderRadius: RADIUS.lg, border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[2], boxShadow: SHADOW[3] }}>
          {err && <div data-testid="ask-cio-error" style={{ color: TOKENS.danger, fontSize: TYPE.base }}>{err}</div>}
          {res && (
            <>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}>
                <span style={chipStyle(statusTone(status))}>{statusLabel(status)}</span>
                <button type="button" data-testid="ask-cio-open-thread" onClick={() => { const t = res.thread_id; setRes(null); nav(`/cio/questions/${t}`) }}
                  style={{ fontSize: TYPE.sm, color: TOKENS.info, background: 'transparent', border: 'none', cursor: 'pointer', padding: 0 }}>
                  Open thread →
                </button>
                <button type="button" aria-label="Close" onClick={() => setRes(null)}
                  style={{ marginLeft: 'auto', fontSize: TYPE.sm, color: TOKENS.text[2], background: 'transparent', border: 'none', cursor: 'pointer' }}>
                  Close (Esc)
                </button>
              </div>
              <pre data-testid="ask-cio-answer-text" style={{ margin: 0, whiteSpace: 'pre-wrap', fontFamily: FONT.sans, fontSize: TYPE.base, color: TOKENS.text[0], lineHeight: 1.5 }}>{res.answer_text}</pre>
            </>
          )}
        </div>
      )}
    </div>
  )
}
