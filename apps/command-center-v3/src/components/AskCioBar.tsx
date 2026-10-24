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
import type { AnswerVersion, TrackedRow } from '../lib/askCioModel'
import { useApi } from '../hooks/useApi'
import { askCio, askErrorText, type AskResult } from '../lib/askCioApi'
import AskCioAnswer from './AskCioAnswer'
import { ASK_UPDATED_EVENT, answerForAsk, askUpdate, keepNewestAnswer, matchingThread, newerHeaderAnswer, publishAskUpdate, readableAnswerForAsk, statusForAsk, threadVersionKey } from '../lib/askCioPresentation'

export default function AskCioBar() {
  const [q, setQ] = useState('')
  const [deep, setDeep] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [res, setRes] = useState<AskResult | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const [listening, setListening] = useState(false)
  const recRef = useRef<any>(null)
  // Voice-to-text: the browser's own speech recognition (Chrome, Edge, Android, iOS Safari). Hidden where unsupported.
  const SpeechRec = typeof window !== 'undefined' ? ((window as any).SpeechRecognition || (window as any).webkitSpeechRecognition) : null
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

  function toggleMic() {
    if (listening) { recRef.current?.stop(); return }
    if (!SpeechRec) return
    const rec = new SpeechRec()
    rec.lang = navigator.language || 'en-US'
    rec.interimResults = true
    rec.continuous = false
    const base = q ? q.trimEnd() + ' ' : ''
    rec.onresult = (ev: any) => {
      let text = ''
      for (let i = 0; i < ev.results.length; i++) text += ev.results[i][0].transcript
      setQ(base + text)
    }
    rec.onerror = (ev: any) => { setErr(ev.error === 'not-allowed' ? 'Microphone blocked — allow it for this site in the browser settings.' : `Voice input: ${ev.error}`) }
    rec.onend = () => { setListening(false); inputRef.current?.focus() }
    recRef.current = rec
    setErr(null)
    setListening(true)
    rec.start()
  }

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

  return (
    <div data-testid="ask-cio-bar" style={{ position: 'relative', padding: '6px 16px', borderBottom: `1px solid ${TOKENS.border}`, background: TOKENS.bg[1] }}>
      <form onSubmit={submit} style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', maxWidth: 1100 }} title={TOOLTIPS.bar}>
        <span style={{ ...chipStyle('ai'), flex: '0 0 auto' }}>Ask the CIO</span>
        <input
          ref={inputRef}
          data-testid="ask-cio-input"
          aria-label="Ask the CIO"
          value={q}
          onChange={e => setQ(e.target.value)}
          placeholder="e.g. 100 or 1,000 TSLA given the SpaceX merger talk?  (⌘K)"
          disabled={busy}
          style={{ flex: '1 1 240px', minWidth: 0, fontSize: TYPE.base, padding: '6px 10px', borderRadius: RADIUS.md, border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[0], color: TOKENS.text[0], fontFamily: FONT.sans }}
        />
        {SpeechRec && (
          <button type="button" data-testid="ask-cio-mic" onClick={toggleMic} disabled={busy}
            aria-label={listening ? 'Stop dictation' : 'Dictate your question'} aria-pressed={listening} title={TOOLTIPS.mic}
            style={{ flex: '0 0 auto', minWidth: 34, minHeight: 30, display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: RADIUS.md,
              border: `1px solid ${listening ? TOKENS.danger : TOKENS.border}`, background: listening ? TOKENS.bg[2] : 'transparent',
              color: listening ? TOKENS.danger : TOKENS.text[2], cursor: 'pointer' }}>
            <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0" /><path d="M12 18v3" />
            </svg>
          </button>
        )}
        <label title={TOOLTIPS.deep} style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: TYPE.sm, color: TOKENS.text[2], whiteSpace: 'nowrap' }}>
          <input type="checkbox" data-testid="ask-cio-deep" checked={deep} onChange={e => setDeep(e.target.checked)} disabled={busy} />
          Deep
        </label>
        <button type="submit" title={TOOLTIPS.ask} data-testid="ask-cio-submit" disabled={busy || !q.trim()}
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
        <Link to="/cio/questions" title={TOOLTIPS.myQuestions} data-testid="ask-cio-my-questions" style={{ fontSize: TYPE.sm, color: TOKENS.info, whiteSpace: 'nowrap' }}>My questions</Link>
      </form>
      {(res || err) && (
        <div data-testid="ask-cio-answer" role="dialog" aria-label="CIO answer"
          style={{ position: 'absolute', zIndex: 40, left: 16, right: 16, top: '100%', maxWidth: 1100, maxHeight: '60vh', overflowY: 'auto', marginTop: 4, padding: 12, borderRadius: RADIUS.lg, border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[2], boxShadow: SHADOW[3] }}>
          {err && <div data-testid="ask-cio-error" style={{ color: TOKENS.danger, fontSize: TYPE.base }}>{err}</div>}
          {res && (
            <>
              <LiveAnswer key={`${res.thread_id}:${res.ask_id}`} result={res}>
                <button type="button" data-testid="ask-cio-open-thread" onClick={() => { const t = res.thread_id; setRes(null); nav(`/cio/questions/${t}`) }}
                  style={{ fontSize: TYPE.sm, color: TOKENS.info, background: 'transparent', border: 'none', cursor: 'pointer', padding: 0 }}>
                  Open thread →
                </button>
                <button type="button" aria-label="Close" onClick={() => setRes(null)}
                  style={{ marginLeft: 'auto', fontSize: TYPE.sm, color: TOKENS.text[2], background: 'transparent', border: 'none', cursor: 'pointer' }}>
                  Close (Esc)
                </button>
              </LiveAnswer>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function LiveAnswer({ result, children }: { result: AskResult; children: React.ReactNode }) {
  const [pending, setPending] = useState(result.thread?.status === 'deep_pending')
  const api = useApi<unknown>(ASK_PATHS.thread(result.thread_id), pending ? 5_000 : 30_000)
  const live = matchingThread(api.data, result.thread_id)
  const [retained, setRetained] = useState<AnswerVersion | null>(null)
  const candidate = newerHeaderAnswer(result, live)
  const newer = keepNewestAnswer(retained, candidate)
  const initial = matchingThread({ thread: result.thread }, result.thread_id)
  const baseline = readableAnswerForAsk(initial, result.ask_id)
  const liveVersion = answerForAsk(live, result.ask_id)
  const regressed = Boolean(newer && liveVersion && liveVersion.version < newer.version)
  const keepStatus = newer && (!liveVersion || liveVersion.version < newer.version)
  const status = keepStatus ? newer!.status : statusForAsk(live ?? initial, result.ask_id)
  const previous = useRef(initial ? threadVersionKey(initial) : 'none')
  useEffect(() => { setPending(status === 'deep_pending') }, [status])
  useEffect(() => { if (candidate) setRetained(previous => keepNewestAnswer(previous, candidate)) }, [candidate])
  useEffect(() => {
    if (!live || regressed) return
    const key = threadVersionKey(live)
    if (previous.current !== key) publishAskUpdate({ threadId: result.thread_id, source: 'header' })
    previous.current = key
  }, [live, regressed, result.thread_id])
  useEffect(() => {
    const refresh = (event: Event) => { const change = askUpdate(event); if (change?.threadId === result.thread_id && change.source !== 'header') api.refetch() }
    window.addEventListener(ASK_UPDATED_EVENT, refresh)
    return () => window.removeEventListener(ASK_UPDATED_EVENT, refresh)
  }, [result.thread_id, api.refetch])
  return <>
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 8 }}><span style={chipStyle(statusTone(status))}>{statusLabel(status)}</span>{children}</div>
    <AskCioAnswer text={newer?.summary ?? result.answer_text} sources={newer?.sources ?? baseline?.sources} testId="ask-cio-answer-text" />
    {Boolean(api.data) && !live && <div role="status" style={{ color: TOKENS.warning, fontSize: TYPE.sm, marginTop: 8 }}>The update could not be matched to this question — showing its saved answer.</div>}
    {regressed && <div role="status" style={{ color: TOKENS.warning, fontSize: TYPE.sm, marginTop: 8 }}>The latest response contains an older version — keeping the newer saved answer.</div>}
    {api.stale && <div role="status" style={{ color: TOKENS.warning, fontSize: TYPE.sm, marginTop: 8 }}>Answer refresh unavailable — showing the last saved answer. {newer?.produced_at || baseline?.produced_at || ''}</div>}
  </>
}
