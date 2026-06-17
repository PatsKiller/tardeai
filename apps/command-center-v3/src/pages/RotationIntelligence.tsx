import { useEffect, useState } from 'react'

// ── Types ──────────────────────────────────────────────────────────────────
type RotationPair = {
  action_class?: string
  from_symbol?: string
  to_symbol?: string
  from_account?: string
  to_account?: string
  score?: number
  review_amount?: number
  rationale?: string
}

type RotationData = {
  ok?: boolean
  advisory_only?: boolean
  error?: string
  summary?: {
    trim_review?: number
    add_review?: number
    rotation_ideas?: number
    watch?: number
  }
  data_quality?: Record<string, any>
  missing_sector?: number
  missing_analyst_upside?: number
  top_rotation_ideas?: RotationPair[]
  top_pairs?: RotationPair[]
  top_candidates?: any[]
  research_candidates?: any[]
  research_rotation_ideas?: RotationPair[]
  generated_at?: string
}

type ValidationObj = { ok?: boolean; issues?: string[] }
type AskResult = {
  ok?: boolean
  error?: string
  stderr_tail?: string
  advisory_only?: boolean
  backend?: string
  answer_mode?: string
  answer?: string
  grounded_answer?: string
  local_answer_validation?: ValidationObj
  local_answer_raw?: string
  grok_oauth_prompt_path?: string
  grok_second_opinion?: { mode?: string;[k: string]: any }
  rotation_summary?: any
  grounding_report?: any
}

type GrokPromptResult = {
  ok?: boolean
  advisory_only?: boolean
  grok_available?: boolean
  grok_answer?: string
  prompt_text?: string
  prompt_path?: string
  note?: string
  error?: string
}

// ── Style helpers ───────────────────────────────────────────────────────────
const ACCENT = '#60a5fa'
const card: React.CSSProperties = {
  background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10, padding: 16,
}
const btn = (active: boolean): React.CSSProperties => ({
  padding: '6px 14px', fontSize: 12, borderRadius: 6, cursor: active ? 'not-allowed' : 'pointer',
  border: `1px solid ${ACCENT}55`, background: active ? 'var(--bg2)' : 'rgba(96,165,250,.15)',
  color: active ? 'var(--text3)' : ACCENT, fontWeight: 700,
})

const ACTION_BADGE: Record<string, { label: string; c: string }> = {
  WATCH: { label: 'WATCH', c: '#f59e0b' },
  ADD_REVIEW: { label: 'ADD REVIEW', c: '#22c55e' },
  TRIM_REVIEW: { label: 'TRIM REVIEW', c: '#ef4444' },
  ROTATE_REVIEW: { label: 'ROTATE REVIEW', c: '#60a5fa' },
  RESEARCH_MORE: { label: 'RESEARCH MORE', c: '#6b7280' },
}

const money = (v?: number) =>
  typeof v === 'number'
    ? v.toLocaleString(undefined, { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
    : 'review range unavailable'

function ActionBadge({ cls }: { cls?: string }) {
  const m = ACTION_BADGE[(cls || '').toUpperCase()] ?? { label: cls || 'REVIEW', c: '#6b7280' }
  return (
    <span style={{
      fontSize: 9, fontWeight: 800, padding: '2px 8px', borderRadius: 4, letterSpacing: 0.4,
      background: `${m.c}1f`, color: m.c, border: `1px solid ${m.c}44`,
    }}>{m.label}</span>
  )
}

function SummaryCard({ label, value, color }: { label: string; value: React.ReactNode; color?: string }) {
  return (
    <div style={{ ...card, textAlign: 'center', padding: '14px 10px' }}>
      <div style={{ fontSize: 24, fontWeight: 800, color: color ?? 'var(--text0)' }}>{value}</div>
      <div style={{ fontSize: 9, color: 'var(--text3)', textTransform: 'uppercase', letterSpacing: 0.4, marginTop: 2 }}>{label}</div>
    </div>
  )
}

// ── Page ────────────────────────────────────────────────────────────────────
export default function RotationIntelligence() {
  const [data, setData] = useState<RotationData | null>(null)
  const [summaryWarn, setSummaryWarn] = useState<string>('')
  const [question, setQuestion] = useState('Should I trim XLB for SPCX? How much should I trim?')
  const [busy, setBusy] = useState<string>('')   // which action is running
  const [result, setResult] = useState<AskResult | null>(null)
  const [askError, setAskError] = useState<string>('')
  const [grokPrompt, setGrokPrompt] = useState<GrokPromptResult | null>(null)
  const [copied, setCopied] = useState(false)

  async function loadSummary() {
    setSummaryWarn('')
    try {
      const res = await fetch('/api/v2/rotation/summary')
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const json = await res.json()
      // ROUTES auto-wraps as { ok, data: {...} } — unwrap .data
      const inner: RotationData = json?.data ?? json
      if (inner && inner.ok === false) {
        setSummaryWarn(`Rotation summary unavailable: ${inner.error ?? 'review data not ready'}`)
      }
      setData(inner ?? null)
    } catch (err) {
      setSummaryWarn(`Rotation summary unavailable: ${err instanceof Error ? err.message : String(err)}`)
    }
  }

  async function ask(backend: 'grounded' | 'local' | 'dual_oauth') {
    setBusy(backend === 'grounded' ? 'Ask Local (grounded)' : backend === 'local' ? 'Validate with local model' : 'Run Dual Review')
    setAskError('')
    if (backend !== 'local') setResult(null)   // keep grounded result on screen while local validation runs
    try {
      const res = await fetch('/api/v2/rotation/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, backend }),
      })
      // RAW advisor JSON (not wrapped). Parse defensively — a slow local-model call can return an
      // empty/truncated body; never surface "Unexpected end of JSON input".
      const text = await res.text()
      let json: AskResult
      try {
        json = text ? JSON.parse(text) : { ok: false, error: 'Empty response — the local model likely timed out under GPU load. Try again, or use Build Grok OAuth Prompt (instant).' }
      } catch {
        json = { ok: false, error: 'Advisor returned a non-JSON / truncated response (local model busy). Use Build Grok OAuth Prompt for an instant result.' }
      }
      if (json && json.ok === false) {
        setAskError(`Advisor error: ${json.error ?? `HTTP ${res.status}`}`)
      }
      setResult(json)
      if (json?.grok_oauth_prompt_path) {
        setGrokPrompt(prev => ({ ...(prev ?? {}), prompt_path: json.grok_oauth_prompt_path }))
      }
    } catch (err) {
      setAskError(`Advisor request failed: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setBusy('')
    }
  }

  // Inline free/OAuth Grok second opinion (runs via the local OAuth proxy — no API key, no paid API).
  // Falls back to the manual paste prompt if the proxy is not authenticated.
  async function runGrokReview() {
    setBusy('Run Grok Review')
    setAskError('')
    try {
      const res = await fetch('/api/v2/rotation/grok-review', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      })
      const text = await res.text()   // RAW (not wrapped); parse defensively
      let json: GrokPromptResult
      try { json = text ? JSON.parse(text) : { ok: false, error: 'Empty response — Grok proxy may be busy. Try again.' } }
      catch { json = { ok: false, error: 'Non-JSON response — try again.' } }
      if (json && json.ok === false) setAskError(`Grok review error: ${json.error ?? `HTTP ${res.status}`}`)
      setGrokPrompt(json)
    } catch (err) {
      setAskError(`Grok review request failed: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setBusy('')
    }
  }

  // prefill from ?question= on mount
  useEffect(() => {
    try {
      const q = new URLSearchParams(window.location.search).get('question')
      if (q) setQuestion(q)
    } catch { /* noop */ }
    loadSummary()
  }, [])

  const s = data?.summary ?? {}
  const dq = data?.data_quality ?? {}
  const missingAnalyst = data?.missing_analyst_upside ?? dq.rows_missing_analyst_upside ?? dq.missing_analyst_upside ?? dq.rows_without_analyst_upside
  const ideas = data?.top_rotation_ideas ?? []
  const pairs = (data?.top_pairs ?? []).filter((p: any) => p?.from_symbol || p?.to_symbol)
  const noIdeas = ideas.length === 0 && pairs.length === 0
  const candidates = (data?.top_candidates ?? []) as any[]
  const researchIdeas = (data?.research_rotation_ideas ?? []) as any[]
  const researchCands = (data?.research_candidates ?? []) as any[]

  const grokAnswer = grokPrompt?.grok_answer
  const grokNote = grokPrompt?.note
  const promptText = grokPrompt?.prompt_text
  const promptPath = grokPrompt?.prompt_path || result?.grok_oauth_prompt_path
  const hasGrok = Boolean(grokAnswer || promptText || promptPath)

  async function copyPrompt() {
    if (!promptText) return
    try {
      await navigator.clipboard.writeText(promptText)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch { /* clipboard unavailable */ }
  }

  return (
    <div style={{ padding: 4 }}>
      {/* A. Header */}
      <header style={{ marginBottom: 18 }}>
        <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text0)' }}>Rotation Intelligence</div>
        <div style={{ fontSize: 12, color: 'var(--text2)', marginTop: 3 }}>
          Grounded local review + free/OAuth Grok second opinion
        </div>
        <div style={{ fontSize: 10, color: '#f59e0b', marginTop: 5, fontWeight: 600 }}>
          Advisory only · human review required · no broker action
        </div>
      </header>

      {/* B. Summary cards */}
      {summaryWarn && (
        <div style={{
          marginBottom: 14, padding: '8px 12px', borderRadius: 8, fontSize: 11,
          background: 'rgba(245,158,11,.08)', border: '1px solid rgba(245,158,11,.3)', color: '#f59e0b',
        }}>
          {summaryWarn} — page remains usable; counts shown as “—”.
        </div>
      )}
      <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 10, marginBottom: 20 }}>
        <SummaryCard label="Trim Review" value={s.trim_review ?? '—'} color="#ef4444" />
        <SummaryCard label="Add Review" value={s.add_review ?? '—'} color="#22c55e" />
        <SummaryCard label="Rotation Ideas" value={s.rotation_ideas ?? '—'} color={ACCENT} />
        <SummaryCard label="Watch" value={s.watch ?? '—'} color="#f59e0b" />
        <SummaryCard label="Missing Sector" value={data?.missing_sector ?? '—'} color="#a855f7" />
        <SummaryCard label="Missing Analyst Upside" value={missingAnalyst ?? '—'} color="#a855f7" />
      </section>

      {/* C. Ask Advisor */}
      <section style={{ ...card, marginBottom: 20 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 8 }}>Ask the Rotation Advisor</div>
        <textarea
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          rows={3}
          style={{
            width: '100%', boxSizing: 'border-box', marginBottom: 12, padding: 10, fontSize: 12,
            background: 'var(--bg2)', color: 'var(--text0)', border: '1px solid var(--border)', borderRadius: 8, resize: 'vertical',
          }}
        />
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          <button disabled={!!busy} onClick={() => ask('grounded')} style={btn(!!busy)}>Ask Local</button>
          <button disabled={!!busy} onClick={runGrokReview} style={btn(!!busy)}>Run Grok Review</button>
          <button disabled={!!busy || !result} onClick={() => ask('local')} style={btn(!!busy || !result)} title={!result ? 'Ask Local first, then optionally validate with the local model' : ''}>Validate with local model</button>
          <button disabled={!!busy} onClick={() => ask('dual_oauth')} style={btn(!!busy)}>Run Dual Review</button>
          <button disabled={!!busy} onClick={loadSummary} style={btn(!!busy)}>Refresh Summary</button>
          {busy && <span style={{ fontSize: 11, color: ACCENT }}>Running {busy}…{(busy.includes('local model') || busy === 'Run Dual Review') ? ' (local model — can take 1–3 min under GPU load)' : ''}</span>}
        </div>
        <div style={{ fontSize: 9.5, color: 'var(--text3)', marginTop: 8 }}>
          <b>Ask Local</b> returns the grounded review instantly. <b>Run Grok Review</b> gets a second opinion inline via the free Grok OAuth proxy. <b>Validate with local model</b> / <b>Run Dual Review</b> run the local model (1–3 min under GPU load).
          Grok runs on a free / OAuth session — <b>no API key, no paid API</b> (manual-paste fallback if the proxy is offline). The advisor reviews holdings and offers a second opinion; it never places, buys, or sells anything.
        </div>
        {askError && (
          <div style={{ marginTop: 10, fontSize: 11, color: '#ef4444' }}>
            {askError}
            {result?.stderr_tail && (
              <pre style={{ marginTop: 4, fontSize: 9, color: 'var(--text3)', whiteSpace: 'pre-wrap' }}>{result.stderr_tail}</pre>
            )}
          </div>
        )}
      </section>

      {/* D. Result panel */}
      {result && (result.answer || result.grounded_answer || result.answer_mode || result.local_answer_validation || result.rotation_summary) && (
        <section style={{ ...card, marginBottom: 20 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)' }}>Advisor Review</div>
            {result.answer_mode && (
              <span style={{ fontSize: 9, fontWeight: 800, padding: '2px 8px', borderRadius: 4, background: 'rgba(96,165,250,.15)', color: ACCENT }}>
                mode: {result.answer_mode}
              </span>
            )}
            {result.backend && <span style={{ fontSize: 9, color: 'var(--text3)' }}>backend: {result.backend}</span>}
          </div>

          {result.answer && (
            <div style={{ fontSize: 12, color: 'var(--text1)', lineHeight: 1.6, whiteSpace: 'pre-wrap', marginBottom: 12 }}>{result.answer}</div>
          )}

          {result.grounded_answer && result.grounded_answer !== result.answer && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text3)', marginBottom: 3 }}>Grounded answer</div>
              <div style={{ fontSize: 12, color: 'var(--text1)', lineHeight: 1.6, whiteSpace: 'pre-wrap' }}>{result.grounded_answer}</div>
            </div>
          )}

          {result.local_answer_validation && (
            <div style={{ marginBottom: 12, padding: '8px 11px', borderRadius: 8, background: 'var(--bg2)' }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: result.local_answer_validation.ok ? '#22c55e' : '#f59e0b' }}>
                Local answer validation: {result.local_answer_validation.ok ? 'OK' : 'issues flagged'}
              </div>
              {(result.local_answer_validation.issues ?? []).length > 0 && (
                <ul style={{ margin: '6px 0 0', paddingLeft: 18, fontSize: 10.5, color: 'var(--text2)' }}>
                  {(result.local_answer_validation.issues ?? []).map((iss, i) => <li key={i}>{iss}</li>)}
                </ul>
              )}
            </div>
          )}

          {result.grok_second_opinion?.mode && (
            <div style={{ marginBottom: 12, fontSize: 11, color: 'var(--text2)' }}>
              Grok second opinion mode: <b style={{ color: '#f59e0b' }}>{result.grok_second_opinion.mode}</b> (free / OAuth / manual-paste)
            </div>
          )}

          {result.rotation_summary && (
            <div style={{ marginBottom: 12 }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text3)', marginBottom: 3 }}>Rotation summary</div>
              <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontSize: 11, color: 'var(--text2)' }}>
                {typeof result.rotation_summary === 'object'
                  ? Object.entries(result.rotation_summary).filter(([, v]) => typeof v !== 'object').map(([k, v]) => (
                    <span key={k}>{k.replace(/_/g, ' ')}: <b style={{ color: 'var(--text1)' }}>{String(v)}</b></span>
                  ))
                  : <span>{String(result.rotation_summary)}</span>}
              </div>
            </div>
          )}

          {result.local_answer_raw && (
            <details style={{ marginBottom: 10 }}>
              <summary style={{ fontSize: 10.5, color: 'var(--text3)', cursor: 'pointer' }}>Local answer (raw)</summary>
              <pre style={{ marginTop: 6, fontSize: 10, color: 'var(--text2)', whiteSpace: 'pre-wrap', background: 'var(--bg2)', padding: 10, borderRadius: 8 }}>{result.local_answer_raw}</pre>
            </details>
          )}

          {result.grounding_report && (
            <details>
              <summary style={{ fontSize: 10.5, color: 'var(--text3)', cursor: 'pointer' }}>Grounding report (JSON)</summary>
              <pre style={{ marginTop: 6, fontSize: 9.5, color: 'var(--text2)', whiteSpace: 'pre-wrap', background: 'var(--bg2)', padding: 10, borderRadius: 8, maxHeight: 320, overflow: 'auto' }}>
                {JSON.stringify(result.grounding_report, null, 2)}
              </pre>
            </details>
          )}
        </section>
      )}

      {/* E. Grok second opinion (inline free/OAuth) — manual paste is the fallback */}
      {hasGrok && (
        <section style={{ ...card, marginBottom: 20, borderColor: 'rgba(245,158,11,.3)' }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#f59e0b', marginBottom: 6 }}>Grok Second Opinion <span style={{ fontSize: 10, fontWeight: 400, color: 'var(--text3)' }}>· free / OAuth · no API key</span></div>
          {grokAnswer ? (
            <>
              <div style={{ fontSize: 12.5, color: 'var(--text0)', whiteSpace: 'pre-wrap', lineHeight: 1.55, background: 'var(--bg2)', border: '1px solid var(--border)', borderRadius: 8, padding: 12 }}>{grokAnswer}</div>
              <div style={{ fontSize: 9.5, color: 'var(--text3)', marginTop: 6 }}>{grokNote ?? 'Free/OAuth Grok via the local proxy. Grounding remains authoritative — this is advisory only.'}</div>
              <details style={{ marginTop: 8 }}>
                <summary style={{ fontSize: 10, color: 'var(--text3)', cursor: 'pointer' }}>view / copy the prompt that was sent</summary>
                {promptPath && <div style={{ fontSize: 9.5, color: 'var(--text3)', margin: '6px 0' }}>Prompt file: <span style={{ fontFamily: 'monospace', color: 'var(--text2)' }}>{promptPath}</span></div>}
                {promptText && <>
                  <button onClick={copyPrompt} style={{ ...btn(false), marginBottom: 8, borderColor: '#f59e0b55', background: 'rgba(245,158,11,.15)', color: '#f59e0b' }}>{copied ? 'Copied ✓' : 'Copy Grok Prompt'}</button>
                  <textarea readOnly value={promptText} rows={8} style={{ width: '100%', boxSizing: 'border-box', padding: 10, fontSize: 10, fontFamily: 'monospace', background: 'var(--bg2)', color: 'var(--text1)', border: '1px solid var(--border)', borderRadius: 8, resize: 'vertical' }} />
                </>}
              </details>
            </>
          ) : (
            <>
              <div style={{ fontSize: 10.5, color: 'var(--text2)', marginBottom: 10 }}>{grokNote ?? 'Grok proxy offline — paste this into Grok using free/OAuth login. No API key is used.'}</div>
              {promptPath && <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10 }}>Prompt file: <span style={{ fontFamily: 'monospace', color: 'var(--text2)' }}>{promptPath}</span></div>}
              {promptText ? (
                <>
                  <button onClick={copyPrompt} style={{ ...btn(false), marginBottom: 10, borderColor: '#f59e0b55', background: 'rgba(245,158,11,.15)', color: '#f59e0b' }}>{copied ? 'Copied ✓' : 'Copy Grok Prompt'}</button>
                  <textarea readOnly value={promptText} rows={10} style={{ width: '100%', boxSizing: 'border-box', padding: 10, fontSize: 10.5, fontFamily: 'monospace', background: 'var(--bg2)', color: 'var(--text1)', border: '1px solid var(--border)', borderRadius: 8, resize: 'vertical' }} />
                </>
              ) : (
                <pre style={{ fontSize: 10.5, fontFamily: 'monospace', background: 'var(--bg2)', color: 'var(--text1)', padding: 10, borderRadius: 8, whiteSpace: 'pre-wrap' }}>cat "{promptPath}"</pre>
              )}
            </>
          )}
        </section>
      )}

      {/* F. Rotation Ideas */}
      <section>
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 10 }}>Rotation Ideas</div>
        {noIdeas ? (
          <div style={{ ...card, fontSize: 11.5, color: 'var(--text2)' }}>
            No model-supported rotation ideas. Continue WATCH / RESEARCH_MORE.
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 12 }}>
            {[...ideas, ...pairs].map((idea, idx) => (
              <article key={`${idea.from_symbol}-${idea.to_symbol}-${idx}`} style={card}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                  <ActionBadge cls={idea.action_class} />
                  <span style={{ flex: 1 }} />
                  {idea.score != null && <span style={{ fontSize: 10, color: 'var(--text3)' }}>score {idea.score}</span>}
                </div>
                <div style={{ fontSize: 15, fontWeight: 800, color: 'var(--text0)', fontFamily: 'monospace', marginBottom: 4 }}>
                  {idea.from_symbol ?? '—'} → {idea.to_symbol ?? '—'}
                </div>
                {(idea.from_account || idea.to_account) && (
                  <div style={{ fontSize: 9.5, color: 'var(--text3)', marginBottom: 6 }}>
                    {(idea.from_account ?? 'n/a').replace(/_/g, ' ')} → {(idea.to_account ?? 'n/a').replace(/_/g, ' ')}
                  </div>
                )}
                {idea.rationale && <div style={{ fontSize: 11, color: 'var(--text2)', lineHeight: 1.5, marginBottom: 6 }}>{idea.rationale}</div>}
                <div style={{ fontSize: 10.5, color: 'var(--text3)' }}>
                  Suggested review amount: <b style={{ color: 'var(--text1)' }}>{money(idea.review_amount)}</b>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      {/* Review candidates (per-symbol, not pairs) */}
      {candidates.length > 0 && (
        <section>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>Review Candidates</div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10 }}>Per-symbol review candidates from the grounded scorer — not buy/sell instructions. Each is a WATCH / review item only.</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 10 }}>
            {candidates.slice(0, 24).map((c: any, idx: number) => {
              const ev = c.evidence ?? {}
              return (
                <article key={`${c.symbol}-${c.account_key}-${idx}`} style={card}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                    <span style={{ fontSize: 14, fontWeight: 800, color: 'var(--text0)', fontFamily: 'monospace' }}>{c.symbol ?? '—'}</span>
                    <span style={{ flex: 1 }} />
                    <ActionBadge cls={c.recommendation} />
                  </div>
                  <div style={{ fontSize: 9.5, color: 'var(--text3)', marginBottom: 6 }}>
                    {(c.sector ?? '—')} · {(c.account_type ?? c.account_key ?? '—').toString().replace(/_/g, ' ')}
                  </div>
                  <div style={{ display: 'flex', gap: 10, fontSize: 10, color: 'var(--text2)', flexWrap: 'wrap' }}>
                    {c.current_value != null && <span>value {money(c.current_value)}</span>}
                    {c.trim_score != null && <span>trim {c.trim_score}</span>}
                    {c.add_score != null && <span>add {c.add_score}</span>}
                    {c.confidence != null && <span>conf {c.confidence}</span>}
                  </div>
                  {(ev.positive_upside_pct != null || ev.concentration_pct != null) && (
                    <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 4 }}>
                      {ev.positive_upside_pct != null && <>upside {ev.positive_upside_pct}% </>}
                      {ev.concentration_pct != null && <>· conc {ev.concentration_pct}%</>}
                    </div>
                  )}
                </article>
              )
            })}
          </div>
          {candidates.length > 24 && <div style={{ fontSize: 9, color: 'var(--text3)', marginTop: 6 }}>+{candidates.length - 24} more</div>}
        </section>
      )}

      {/* G. Rebalance from research (rotate into non-held names) — advisory */}
      {(researchIdeas.length > 0 || researchCands.length > 0) && (
        <section>
          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text0)', marginBottom: 4 }}>Rebalance from Research <span style={{ fontSize: 10, fontWeight: 400, color: '#f59e0b' }}>· advisory · not a model-supported signal</span></div>
          <div style={{ fontSize: 10, color: 'var(--text3)', marginBottom: 10 }}>Ideas to rotate from a trim-worthy holding into a high-conviction <b>research name you don't hold</b>. Review only — confirm sizing, tax, and account fit yourself; nothing is placed.</div>

          {researchIdeas.length > 0 && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 12, marginBottom: 14 }}>
              {researchIdeas.map((idea: any, idx: number) => (
                <article key={`${idea.from_symbol}-${idea.to_symbol}-${idx}`} style={{ ...card, borderColor: 'rgba(96,165,250,.3)' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                    <ActionBadge cls={idea.action_class} />
                    <span style={{ flex: 1 }} />
                    {idea.score != null && <span style={{ fontSize: 10, color: 'var(--text3)' }}>trim {idea.score}</span>}
                  </div>
                  <div style={{ fontSize: 15, fontWeight: 800, color: 'var(--text0)', fontFamily: 'monospace', marginBottom: 6 }}>{idea.from_symbol ?? '—'} → <span style={{ color: '#22c55e' }}>{idea.to_symbol ?? '—'}</span></div>
                  {idea.rationale && <div style={{ fontSize: 11, color: 'var(--text2)', lineHeight: 1.5 }}>{idea.rationale}</div>}
                </article>
              ))}
            </div>
          )}

          {researchCands.length > 0 && (
            <>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text2)', marginBottom: 6 }}>Research candidates to rotate into (not held)</div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(240px, 1fr))', gap: 10 }}>
                {researchCands.map((c: any, idx: number) => (
                  <article key={`${c.symbol}-${idx}`} style={card}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                      <span style={{ fontSize: 14, fontWeight: 800, color: 'var(--text0)', fontFamily: 'monospace' }}>{c.symbol}</span>
                      {c.hermes_rank != null && <span style={{ fontSize: 9.5, color: '#a855f7' }}>★#{c.hermes_rank}</span>}
                      <span style={{ flex: 1 }} />
                      {c.analyst_rating && <ActionBadge cls={String(c.analyst_rating).includes('buy') ? 'ADD_REVIEW' : 'WATCH'} />}
                    </div>
                    <div style={{ fontSize: 9.5, color: 'var(--text3)', marginBottom: 6 }}>{c.sector ?? '—'}</div>
                    <div style={{ display: 'flex', gap: 10, fontSize: 10, color: 'var(--text2)', flexWrap: 'wrap' }}>
                      {c.analyst_upside_pct != null && <span>upside {c.analyst_upside_pct}%</span>}
                      {c.analyst_rating && <span>{String(c.analyst_rating).replace(/_/g, ' ')}</span>}
                      {c.score != null && <span>score {Math.round(c.score)}</span>}
                    </div>
                    {c.description && <div style={{ fontSize: 9.5, color: 'var(--text3)', marginTop: 5, lineHeight: 1.4 }}>{c.description}</div>}
                  </article>
                ))}
              </div>
            </>
          )}
        </section>
      )}

      {data?.generated_at && (
        <div style={{ fontSize: 8, color: 'var(--text3)', marginTop: 4 }}>
          Source: /api/v2/rotation/summary · generated {data.generated_at} · advisory only, no broker action
        </div>
      )}
    </div>
  )
}
