/**
 * My questions — every question asked of the CIO (Command Center and Telegram), as threads.
 *
 * A thread holds the question, follow-ups (either channel), every answer version (quick → deep, and re-answers when
 * something material changed), sources, sizing context for quantities the operator named, and what the question is
 * tracking. Follow up here or reply in Telegram: same thread. READ_ONLY_ADVISORY.
 */
import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useApi } from '../hooks/useApi'
import { FONT, RADIUS, TOKENS, TYPE, chipStyle } from '../lib/designTokens'
import {
  ASK_PATHS, CHANNEL_LABEL, TOOLTIPS, currentVersion, entityLabel, filterSummaries, isPending, relativeAge,
  sizingLine, sortSummaries, statusLabel, statusTone, unwrap, validateQuestion,
  type AnswerVersion, type Thread, type ThreadSummary, type Turn,
} from '../lib/askCioModel'
import { askCio, askErrorText, requestDeep, untrackEntity } from '../lib/askCioApi'

const card = { border: `1px solid ${TOKENS.border}`, borderRadius: RADIUS.lg, background: TOKENS.bg[1], padding: 12 } as const
const btn = { fontSize: TYPE.sm, padding: '4px 10px', borderRadius: RADIUS.md, border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[2], color: TOKENS.text[0], cursor: 'pointer' } as const

export default function MyQuestions() {
  const { threadId } = useParams()
  const list = useApi<unknown>(ASK_PATHS.list, 30_000)
  const rows = useMemo(() => sortSummaries(unwrap<{ threads: ThreadSummary[] }>(list.data)?.threads ?? []), [list.data])
  const [filter, setFilter] = useState('')
  const shown = filterSummaries(rows, filter)
  return (
    <div data-testid="my-questions" style={{ display: 'flex', gap: 16, alignItems: 'flex-start', flexWrap: 'wrap' }}>
      <section style={{ ...card, flex: '1 1 300px', maxWidth: 420 }}>
        <h2 style={{ margin: '0 0 8px', fontSize: TYPE.md }}>My questions</h2>
        <input aria-label="Filter questions" placeholder="Filter by ticker or words" value={filter} onChange={e => setFilter(e.target.value)}
          style={{ width: '100%', boxSizing: 'border-box', fontSize: TYPE.base, padding: '5px 8px', borderRadius: RADIUS.md, border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[0], color: TOKENS.text[0], marginBottom: 8 }} />
        {list.loading && !rows.length && <div style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>Loading…</div>}
        {list.error && <div style={{ fontSize: TYPE.sm, color: TOKENS.danger }}>Could not load questions: {list.error}</div>}
        {!list.loading && !rows.length && !list.error && (
          <div style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>No questions yet. Use the Ask the CIO bar above (⌘K), or message the CIO bot on Telegram.</div>
        )}
        <ul data-testid="my-questions-list" style={{ listStyle: 'none', margin: 0, padding: 0, display: 'grid', gap: 6 }}>
          {shown.map(r => (
            <li key={r.thread_id}>
              <Link to={`/cio/questions/${r.thread_id}`} data-testid={`q-${r.thread_id}`}
                style={{ display: 'block', padding: 8, borderRadius: RADIUS.md, textDecoration: 'none', color: TOKENS.text[0],
                  border: `1px solid ${r.thread_id === threadId ? TOKENS.primary : TOKENS.border}`, background: TOKENS.bg[0] }}>
                <div style={{ fontSize: TYPE.base, fontWeight: 600 }}>{r.title ?? '(untitled)'}</div>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 4, alignItems: 'center' }}>
                  <span style={chipStyle(statusTone(r.status))}>{statusLabel(r.status)}</span>
                  {r.entities.map(e => (
                    <span key={e.key} style={chipStyle(e.tracking === 'tracked' ? 'info' : 'neutral', 'outline')}>{entityLabel(e)}</span>
                  ))}
                  <span style={{ fontSize: TYPE.xs, color: TOKENS.text[3] }}>{r.channels.map(c => CHANNEL_LABEL[c] ?? c).join(' · ')} · {relativeAge(r.updated_at)}</span>
                </div>
              </Link>
            </li>
          ))}
        </ul>
      </section>
      <section style={{ flex: '3 1 520px', minWidth: 0 }}>
        {threadId ? <ThreadView threadId={threadId} onChanged={() => list.refetch()} /> : (
          <div style={{ ...card, fontSize: TYPE.base, color: TOKENS.text[2] }}>Pick a question to see its thread, answers, sources and what it is tracking.</div>
        )}
      </section>
    </div>
  )
}

function ThreadView({ threadId, onChanged }: { threadId: string; onChanged: () => void }) {
  const res = useApi<unknown>(ASK_PATHS.thread(threadId), 15_000)
  const t = unwrap<{ thread: Thread }>(res.data)?.thread ?? null
  const [msg, setMsg] = useState<string | null>(null)
  const refresh = () => { res.refetch(); onChanged() }
  if (res.loading && !t) return <div style={card}>Loading thread…</div>
  if (!t) return <div style={{ ...card, color: TOKENS.danger }}>Thread not found{res.error ? `: ${res.error}` : ''}.</div>
  return (
    <div data-testid="ask-thread" style={{ display: 'grid', gap: 12 }}>
      <div style={card}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <h2 style={{ margin: 0, fontSize: TYPE.md, flex: '1 1 auto' }}>{t.title}</h2>
          <span style={chipStyle(statusTone(t.status), 'soft', 'md')}>{statusLabel(t.status)}</span>
          <span style={{ fontSize: TYPE.xs, color: TOKENS.text[3], fontFamily: FONT.mono }}>{t.thread_id}</span>
        </div>
        <div style={{ fontSize: TYPE.sm, color: TOKENS.text[2], marginTop: 4 }}>
          Asked {relativeAge(t.created_at)} · channels: {t.channels.map(c => CHANNEL_LABEL[c] ?? c).join(', ')}
          {t.reanswers ? ` · re-answered ${t.reanswers}× on new information` : ''} · reply in Telegram to this thread to follow up there.
        </div>
        <div data-testid="ask-tracking" style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 8 }}>
          {t.entities.map(e => (
            <span key={e.key} style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
              <span style={chipStyle(e.tracking?.state === 'tracked' ? 'info' : 'neutral', 'outline', 'md')}>
                {entityLabel(e)} · {e.tracking?.state === 'tracked' ? 'tracked' : e.tracking?.state === 'untracked' ? 'untracked' : 'not tracked'}
              </span>
              {e.tracking?.state === 'tracked' && (
                <button type="button" data-testid={`untrack-${e.symbol ?? e.key}`} title={TOOLTIPS.untrack} style={btn}
                  onClick={async () => {
                    try { await untrackEntity(t.thread_id, e.key); setMsg(`Stopped tracking ${entityLabel(e)}.`); refresh() } catch (ex) { setMsg(askErrorText(ex)) }
                  }}>Untrack</button>
              )}
            </span>
          ))}
        </div>
        {msg && <div style={{ fontSize: TYPE.sm, color: TOKENS.text[1], marginTop: 6 }}>{msg}</div>}
      </div>
      {t.turns.map(turn => <TurnCard key={turn.ask_id} turn={turn} />)}
      <FollowUp thread={t} onDone={refresh} />
    </div>
  )
}

function TurnCard({ turn }: { turn: Turn }) {
  const cur = currentVersion(turn)
  const older = (turn.answers ?? []).filter(a => a !== cur).sort((a, b) => b.version - a.version)
  const [showOld, setShowOld] = useState(false)
  return (
    <div data-testid={`turn-${turn.turn_kind}`} style={card}>
      <div style={{ fontSize: TYPE.sm, color: TOKENS.text[2], marginBottom: 6 }}>
        {turn.turn_kind === 'reanswer' ? 'Re-answered after a material change' : turn.turn_kind === 'follow_up' ? 'Follow-up' : 'You asked'}
        {' · '}{CHANNEL_LABEL[turn.channel] ?? turn.channel} · {relativeAge(turn.asked_at)}
      </div>
      {turn.turn_kind !== 'reanswer' && <div style={{ fontSize: TYPE.base, fontWeight: 600, marginBottom: 8 }}>{turn.question}</div>}
      {cur ? <AnswerBlock a={cur} /> : <div style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }}>No answer recorded yet.</div>}
      {older.length > 0 && (
        <button type="button" style={{ ...btn, marginTop: 8 }} onClick={() => setShowOld(s => !s)}>
          {showOld ? 'Hide' : 'Show'} earlier versions ({older.length})
        </button>
      )}
      {showOld && older.map(a => <div key={a.version} style={{ marginTop: 8, opacity: 0.8 }}><AnswerBlock a={a} /></div>)}
    </div>
  )
}

function AnswerBlock({ a }: { a: AnswerVersion }) {
  return (
    <div>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center', marginBottom: 6, flexWrap: 'wrap' }}>
        <span style={chipStyle(statusTone(a.status))}>v{a.version} · {statusLabel(a.status)}</span>
        {a.confidence?.level && <span style={chipStyle('neutral', 'outline')}>confidence {a.confidence.level}</span>}
        {!!a.mbi_guard?.stripped && <span style={chipStyle('warning', 'outline')} title="Model text proposing a quantity, order or stop was removed (MBI_BEHAVIOR=0)">sizing advice removed</span>}
        <span style={{ fontSize: TYPE.xs, color: TOKENS.text[3] }}>{relativeAge(a.produced_at)}</span>
      </div>
      {a.what_changed && <div data-testid="what-changed" style={{ fontSize: TYPE.sm, color: TOKENS.success, marginBottom: 6 }}>What changed: {a.what_changed}</div>}
      <pre style={{ margin: 0, whiteSpace: 'pre-wrap', fontFamily: FONT.sans, fontSize: TYPE.base, lineHeight: 1.5, color: TOKENS.text[0] }}>{a.summary}</pre>
      {!!a.sizing_context?.length && (
        <div data-testid="sizing-context" title={TOOLTIPS.sizing} style={{ marginTop: 8, fontSize: TYPE.sm, color: TOKENS.text[1] }}>
          <div style={{ fontWeight: 700 }}>Sizing context (quantities you named — not a recommendation)</div>
          <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>{a.sizing_context.map((r, i) => <li key={i}>{sizingLine(r)}</li>)}</ul>
        </div>
      )}
      {!!a.sources?.length && (
        <details style={{ marginTop: 8, fontSize: TYPE.sm }}>
          <summary style={{ cursor: 'pointer', color: TOKENS.text[2] }}>Sources ({a.sources.length})</summary>
          <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
            {a.sources.map((s, i) => (
              <li key={i}>{s.url && /^https?:\/\//i.test(s.url) ? <a href={s.url} target="_blank" rel="noreferrer" style={{ color: TOKENS.info }}>{s.title}</a> : s.title}
                <span style={{ color: TOKENS.text[3] }}> · {s.kind}{s.as_of ? ` · as of ${s.as_of.slice(0, 16).replace('T', ' ')}` : ''}</span></li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

function FollowUp({ thread, onDone }: { thread: Thread; onDone: () => void }) {
  const [q, setQ] = useState('')
  const [deep, setDeep] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const nav = useNavigate()
  const pending = isPending(thread.status)
  async function send(e: React.FormEvent) {
    e.preventDefault()
    const v = validateQuestion(q)
    if (!v.ok) { setErr(v.reason); return }
    setBusy(true); setErr(null)
    try {
      const r = await askCio(v.question, { deep, threadId: thread.thread_id })
      setQ('')
      if (r.thread_id && r.thread_id !== thread.thread_id) nav(`/cio/questions/${r.thread_id}`)
      onDone()
    } catch (ex) { setErr(askErrorText(ex)) } finally { setBusy(false) }
  }
  return (
    <form onSubmit={send} style={{ ...card, display: 'grid', gap: 8 }}>
      <label style={{ fontSize: TYPE.sm, color: TOKENS.text[2] }} htmlFor="ask-follow-up">Follow up in this thread</label>
      <textarea id="ask-follow-up" data-testid="ask-follow-up" value={q} onChange={e => setQ(e.target.value)} rows={2} disabled={busy}
        placeholder="e.g. what would change your view? (you can also reply in Telegram)"
        style={{ fontSize: TYPE.base, padding: 8, borderRadius: RADIUS.md, border: `1px solid ${TOKENS.border}`, background: TOKENS.bg[0], color: TOKENS.text[0], fontFamily: FONT.sans, resize: 'vertical' }} />
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        <label title={TOOLTIPS.deep} style={{ fontSize: TYPE.sm, display: 'flex', gap: 4, alignItems: 'center' }}>
          <input type="checkbox" checked={deep} onChange={e => setDeep(e.target.checked)} disabled={busy} /> Deep
        </label>
        <button type="submit" data-testid="ask-follow-up-send" disabled={busy || !q.trim()} style={btn}>{busy ? 'Asking…' : 'Send'}</button>
        <button type="button" data-testid="ask-request-deep" title={TOOLTIPS.deep} disabled={busy || pending} style={btn}
          onClick={async () => { setBusy(true); try { await requestDeep(thread.thread_id); onDone() } catch (ex) { setErr(askErrorText(ex)) } finally { setBusy(false) } }}>
          {pending ? 'Deep research pending…' : 'Request deep answer'}
        </button>
        {err && <span style={{ fontSize: TYPE.sm, color: TOKENS.danger }}>{err}</span>}
      </div>
    </form>
  )
}
