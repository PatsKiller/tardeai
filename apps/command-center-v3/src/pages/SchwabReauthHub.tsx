/**
 * SchwabReauthHub — manual OAuth renewal (replaces broken browser auto-2FA).
 *
 * Flow:
 *  1. Request authorize URL from the server
 *  2. Operator logs in on phone / browser (2FA on their device)
 *  3. Paste the dead 127.0.0.1?code=... redirect URL and submit
 *  4. Server exchanges code → seeds token; status refreshes
 */
import { useCallback, useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../hooks/useApi'

type TokenHealth = {
  ok?: boolean
  needs_reauth?: boolean
  degraded?: boolean
  has_token?: boolean
  refresh_valid?: boolean
  days_to_reauth?: number | null
  days_to_true_expiry?: number | null
  refresh_expires_at?: string | null
  next_reauth_due_at?: string | null
  true_expiry?: string | null
  last_true_login?: string | null
  proactive_due?: boolean
  due_now?: boolean
  show_banner?: boolean
  token_key?: string | null
  last_error?: string | null
  message?: string
  live_probe?: { live_ok?: boolean; needs_reauth?: boolean; error?: string | null } | null
}

function fmtTs(v?: string | null): string {
  if (!v) return '—'
  try {
    const d = new Date(v)
    if (Number.isNaN(d.getTime())) return String(v).slice(0, 19)
    return d.toLocaleString()
  } catch {
    return String(v).slice(0, 19)
  }
}

function statusTone(h: TokenHealth | null): { label: string; color: string; bg: string; border: string } {
  if (!h) return { label: 'loading', color: 'var(--text2)', bg: 'var(--bg2)', border: 'var(--border)' }
  if (h.needs_reauth || h.degraded) {
    return { label: 'REAUTH REQUIRED', color: 'var(--red)', bg: 'var(--red-dim)', border: 'var(--red)' }
  }
  if (h.proactive_due || h.due_now || (h.days_to_true_expiry != null && h.days_to_true_expiry <= 1)) {
    return { label: 'RENEWAL WINDOW', color: 'var(--amber)', bg: 'var(--amber-dim)', border: 'var(--amber)' }
  }
  return { label: 'HEALTHY', color: 'var(--green)', bg: 'var(--green-dim)', border: 'var(--green)' }
}

export default function SchwabReauthHub() {
  const { data: health, loading, error, refetch } = useApi<TokenHealth>(
    '/api/v2/brokers/schwab/token-health?probe=0',
    30_000,
  )
  const h = health ?? null
  const tone = statusTone(h)

  const [authUrl, setAuthUrl] = useState<string | null>(null)
  const [accountKey, setAccountKey] = useState<string>('schwab_taxable')
  const [reqBusy, setReqBusy] = useState(false)
  const [reqErr, setReqErr] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const [redirectUrl, setRedirectUrl] = useState('')
  const [submitBusy, setSubmitBusy] = useState(false)
  const [submitErr, setSubmitErr] = useState<string | null>(null)
  const [submitOk, setSubmitOk] = useState<{
    refresh_expires_at?: string
    next_reauth_due_at?: string
    live_ok?: boolean
    message?: string
  } | null>(null)

  const requestUrl = useCallback(async () => {
    setReqBusy(true)
    setReqErr(null)
    setSubmitOk(null)
    setCopied(false)
    try {
      const r = await fetch('/api/v2/brokers/schwab/reauth-url', { cache: 'no-store' })
      const j = await r.json()
      const d = j?.data ?? j
      if (!r.ok || d?.ok === false) {
        setReqErr(d?.error || d?.reason || `HTTP ${r.status}`)
        setAuthUrl(null)
        return
      }
      setAuthUrl(d.authorize_url || null)
      if (d.account_key) setAccountKey(d.account_key)
      if (!d.authorize_url) setReqErr('Server returned no authorize_url')
    } catch (e: any) {
      setReqErr(e?.message || 'request failed')
      setAuthUrl(null)
    } finally {
      setReqBusy(false)
    }
  }, [])

  const copyUrl = useCallback(async () => {
    if (!authUrl) return
    try {
      await navigator.clipboard.writeText(authUrl)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 2000)
    } catch {
      /* ignore */
    }
  }, [authUrl])

  const submitCode = useCallback(async () => {
    const url = redirectUrl.trim()
    if (!url) {
      setSubmitErr('Paste the full 127.0.0.1?code=… URL from your browser address bar')
      return
    }
    setSubmitBusy(true)
    setSubmitErr(null)
    setSubmitOk(null)
    try {
      const r = await fetch('/api/v2/brokers/schwab/exchange-code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ redirect_url: url, account_key: accountKey }),
      })
      const j = await r.json()
      const d = j?.data && j.ok !== false && j.refresh_expires_at == null ? j.data : j
      if (!r.ok || d?.ok === false) {
        setSubmitErr(d?.error || d?.reason || `HTTP ${r.status}`)
        return
      }
      setSubmitOk({
        refresh_expires_at: d.refresh_expires_at,
        next_reauth_due_at: d.next_reauth_due_at,
        live_ok: d.live_ok,
        message: d.message,
      })
      setRedirectUrl('')
      setAuthUrl(null)
      refetch()
    } catch (e: any) {
      setSubmitErr(e?.message || 'submit failed')
    } finally {
      setSubmitBusy(false)
    }
  }, [redirectUrl, accountKey, refetch])

  return (
    <div style={{ maxWidth: 820 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12, marginBottom: 14 }}>
        <div>
          <div style={{ fontSize: 18, fontWeight: 800, color: 'var(--text0)' }}>Schwab Reauth</div>
          <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 3 }}>
            Manual OAuth renewal · no browser auto-login · codes expire ~5 minutes after login
          </div>
        </div>
        <Link to="/system" style={{ fontSize: 11, color: 'var(--text2)' }}>← System</Link>
      </div>

      <div style={{
        padding: 14, borderRadius: 10, marginBottom: 14,
        background: tone.bg, border: `1px solid ${tone.border}`,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
          <span style={{
            fontSize: 11, fontWeight: 800, letterSpacing: 0.4, color: tone.color,
            padding: '3px 9px', borderRadius: 6, border: `1px solid ${tone.border}`,
          }}>{tone.label}</span>
          <span style={{ fontSize: 12, color: 'var(--text1)' }}>
            {loading && !h ? 'Loading token health…' : (h?.message || '—')}
          </span>
          {error && <span style={{ fontSize: 11, color: 'var(--red)' }}>{error}</span>}
          <button
            type="button"
            onClick={() => refetch()}
            style={{
              marginLeft: 'auto', fontSize: 10.5, fontWeight: 700, padding: '4px 10px',
              borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg1)',
              color: 'var(--text1)', cursor: 'pointer',
            }}
          >
            Refresh status
          </button>
        </div>
        <div style={{
          display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
          gap: 8, marginTop: 12, fontSize: 11,
        }}>
          <div><div style={{ color: 'var(--text3)' }}>Token key</div><div style={{ fontFamily: 'monospace', color: 'var(--text0)' }}>{h?.token_key || '—'}</div></div>
          <div><div style={{ color: 'var(--text3)' }}>True expiry</div><div style={{ color: 'var(--text0)' }}>{fmtTs(h?.true_expiry)}</div></div>
          <div><div style={{ color: 'var(--text3)' }}>Days to true expiry</div><div style={{ color: 'var(--text0)' }}>{h?.days_to_true_expiry != null ? h.days_to_true_expiry : '—'}</div></div>
          <div><div style={{ color: 'var(--text3)' }}>Last true login</div><div style={{ color: 'var(--text0)' }}>{fmtTs(h?.last_true_login)}</div></div>
          <div><div style={{ color: 'var(--text3)' }}>DB refresh expires</div><div style={{ color: 'var(--text0)' }}>{fmtTs(h?.refresh_expires_at)}</div></div>
          <div><div style={{ color: 'var(--text3)' }}>Live probe</div><div style={{ color: h?.live_probe?.live_ok ? 'var(--green)' : 'var(--text0)' }}>{h?.live_probe?.live_ok === true ? 'ok' : h?.live_probe?.error || (h?.live_probe ? 'not ok' : '—')}</div></div>
        </div>
        {h?.last_error && (
          <div style={{ marginTop: 10, fontSize: 10.5, color: 'var(--red)' }}>Last error: {h.last_error}</div>
        )}
      </div>

      {submitOk && (
        <div style={{
          padding: 12, borderRadius: 10, marginBottom: 14,
          background: 'var(--green-dim)', border: '1px solid var(--green)',
        }}>
          <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--green)' }}>Token renewed</div>
          <div style={{ fontSize: 11, color: 'var(--text1)', marginTop: 4 }}>
            {submitOk.message || 'New 7-day Schwab login seeded.'}
            {submitOk.live_ok != null && ` · live_probe=${submitOk.live_ok ? 'ok' : 'check'}`}
          </div>
          <div style={{ fontSize: 11, color: 'var(--text2)', marginTop: 6 }}>
            Refresh expires: {fmtTs(submitOk.refresh_expires_at)} · Next reauth due: {fmtTs(submitOk.next_reauth_due_at)}
          </div>
        </div>
      )}

      <section style={{
        background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10,
        padding: 16, marginBottom: 12,
      }}>
        <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)', marginBottom: 6 }}>
          1 · Request renewal URL
        </div>
        <div style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 12, lineHeight: 1.45 }}>
          Builds a fresh Schwab authorize link for account <span style={{ fontFamily: 'monospace' }}>{accountKey}</span>.
          Open it on your phone (or any browser where you can complete Schwab 2FA).
        </div>
        <button
          type="button"
          onClick={() => { void requestUrl() }}
          disabled={reqBusy}
          style={{
            fontSize: 12, fontWeight: 800, padding: '8px 16px', borderRadius: 7, border: 'none',
            cursor: reqBusy ? 'not-allowed' : 'pointer',
            background: reqBusy ? 'var(--bg3)' : 'var(--amber)', color: 'var(--text0)',
          }}
        >
          {reqBusy ? 'Requesting…' : 'Request renewal URL'}
        </button>
        {reqErr && <div style={{ marginTop: 8, fontSize: 11, color: 'var(--red)' }}>{reqErr}</div>}
        {authUrl && (
          <div style={{ marginTop: 12 }}>
            <div style={{
              fontSize: 10.5, wordBreak: 'break-all', padding: '8px 10px', borderRadius: 6,
              background: 'var(--bg0)', border: '1px solid var(--border)', color: 'var(--text0)',
              fontFamily: 'monospace', lineHeight: 1.4,
            }}>
              {authUrl}
            </div>
            <div style={{ display: 'flex', gap: 8, marginTop: 8, flexWrap: 'wrap' }}>
              <button
                type="button"
                onClick={() => { void copyUrl() }}
                style={{
                  fontSize: 11, fontWeight: 700, padding: '6px 12px', borderRadius: 6,
                  border: '1px solid var(--border)', background: 'var(--bg2)', color: 'var(--text0)', cursor: 'pointer',
                }}
              >
                {copied ? 'Copied' : 'Copy link'}
              </button>
              <a
                href={authUrl}
                target="_blank"
                rel="noopener noreferrer"
                style={{
                  fontSize: 11, fontWeight: 700, padding: '6px 12px', borderRadius: 6,
                  border: '1px solid var(--amber)', background: 'var(--amber-dim)',
                  color: 'var(--amber)', textDecoration: 'none',
                }}
              >
                Open in new tab
              </a>
            </div>
          </div>
        )}
      </section>

      <section style={{
        background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10,
        padding: 16, marginBottom: 12,
      }}>
        <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)', marginBottom: 6 }}>
          2 · Log in on your device
        </div>
        <ol style={{ margin: 0, paddingLeft: 18, fontSize: 11.5, color: 'var(--text1)', lineHeight: 1.55 }}>
          <li>Open the authorize link from step 1 on your phone or desktop browser.</li>
          <li>Complete Schwab login and approve 2FA on your authenticator / device.</li>
          <li>
            After approval, the browser redirects to a page that may not load — that is expected.
            The address bar will look like <code style={{ color: 'var(--amber)' }}>https://127.0.0.1/?code=…</code>
          </li>
          <li>Copy the <b>entire</b> address-bar URL (codes expire in about 5 minutes).</li>
        </ol>
      </section>

      <section style={{
        background: 'var(--bg1)', border: '1px solid var(--border)', borderRadius: 10,
        padding: 16, marginBottom: 12,
      }}>
        <div style={{ fontSize: 13, fontWeight: 800, color: 'var(--text0)', marginBottom: 6 }}>
          3 · Paste redirect URL & submit
        </div>
        <div style={{ fontSize: 11, color: 'var(--text2)', marginBottom: 10 }}>
          Paste the full <code>127.0.0.1?code=…</code> URL (or the bare code). Never share this outside this page.
        </div>
        <textarea
          value={redirectUrl}
          onChange={e => setRedirectUrl(e.target.value)}
          placeholder="https://127.0.0.1/?code=...&session=..."
          rows={3}
          style={{
            width: '100%', boxSizing: 'border-box', fontSize: 12, padding: '10px 12px',
            borderRadius: 7, border: '1px solid var(--border)', background: 'var(--bg0)',
            color: 'var(--text0)', fontFamily: 'monospace', resize: 'vertical',
          }}
        />
        <div style={{ display: 'flex', gap: 8, marginTop: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <button
            type="button"
            onClick={() => { void submitCode() }}
            disabled={submitBusy || !redirectUrl.trim()}
            style={{
              fontSize: 12, fontWeight: 800, padding: '8px 18px', borderRadius: 7, border: 'none',
              cursor: (submitBusy || !redirectUrl.trim()) ? 'not-allowed' : 'pointer',
              background: (submitBusy || !redirectUrl.trim()) ? 'var(--bg3)' : 'var(--green)',
              color: 'var(--text0)',
            }}
          >
            {submitBusy ? 'Exchanging…' : 'Submit & renew token'}
          </button>
          {submitErr && <span style={{ fontSize: 11, color: 'var(--red)' }}>{submitErr}</span>}
        </div>
      </section>

      <div style={{ fontSize: 10.5, color: 'var(--text3)', lineHeight: 1.45 }}>
        Browser auto-reauth is disabled. Telegram paste of the same redirect URL still works as a backup.
        Emergency Chromium mode remains available only via <code>schwab_auto_reauth.py --browser --now</code>.
      </div>
    </div>
  )
}
