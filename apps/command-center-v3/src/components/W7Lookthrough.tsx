import DeskPage from './DeskPage'
import { Link } from 'react-router-dom'
import { useW7Pages, W7Gap, W7Load, W7Panel, W7PolicyLimits, grid, line, linkStyle, mono, pct, usd, when } from './W7PagePanels'
import { TOKENS } from '../lib/designTokens'
import W7DetailSheet, { useW7Detail } from './W7DetailSheet'

export function W7LookthroughView({ data, account, selectAccount }: { data: any, account: string | null, selectAccount: (v: string | null) => void }) {
  const detail = useW7Detail()
  const model = data.lookthrough || {}, selected = account ? model.by_account?.[account] : model
  if (!selected) return <W7Gap>The selected account has no published look-through basis. Choose another account.</W7Gap>
  const v = selected
  const contributorKey = (row: any) => `exposure:${row.sector || ''}:${row.name}`
  const exposure = [...(v.sectors || []), ...(v.industries || [])].find((r: any) => contributorKey(r) === detail.selected)
  const underlying = (v.top_underlying || []).find((r: any) => `stock:${r.symbol}` === detail.selected)
  const contributors = (row: any) => <button key={`${row.sector || ''}-${row.name}`} onClick={() => detail.open(contributorKey(row))} style={{ border: 0, borderTop: `1px solid ${TOKENS.borderSubtle}`, background: 'transparent', color: TOKENS.text[0], minHeight: 44, width: '100%', padding: '10px 0', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', gap: 8, textAlign: 'left' }}>
    <span>{row.name}{row.sector ? <small style={{ display: 'block', color: TOKENS.text[2] }}>{row.sector}</small> : null}</span><span style={mono}>{usd(row.value_usd)} →</span>
  </button>
  return <div data-testid="lookthrough-panel" style={{ display: 'grid', gap: 12 }}>
    <p style={{ margin: 0, color: TOKENS.text[2] }}>What you own inside funds — by sector, industry, theme and stock.</p>
    <div style={{ ...line, alignItems: 'center' }}>
      <label>Account <select aria-label="Look-through account" value={account || ''} onChange={e => selectAccount(e.target.value || null)} style={{ background: TOKENS.bg[1], color: TOKENS.text[0], border: `1px solid ${TOKENS.border}`, padding: 8, minHeight: 44, maxWidth: '100%' }}>
        <option value="">All accounts</option>{(model.accounts || []).map((a: any) => <option key={a.id} value={a.id}>{a.label}</option>)}
      </select></label><span style={{ color: TOKENS.text[2] }}>Positions · {when(v.as_of)}</span>
      <span style={{ color: TOKENS.text[2] }}>Quotes · {when(v.quote_as_of)}</span>
      <span>Looked through {usd(v.looked_through_usd)} of {usd(v.portfolio_total_usd)}</span>
    </div>
    <W7Panel title="Portfolio concentration policy"><W7PolicyLimits policy={data.concentration_policy} />
      {account && <p style={{ color: TOKENS.text[2] }}>The allocation below uses the selected account. Policy limits apply across all accounts.</p>}
    </W7Panel>
    <div style={grid}>
      <W7Panel title="Sectors">{v.sectors?.length ? v.sectors.map(contributors) : <W7Gap>No underlying sector classifications are available.</W7Gap>}</W7Panel>
      <W7Panel title="Industries" testId="lookthrough-industries">
        {v.industries?.length ? v.industries.map(contributors) : <W7Gap>No underlying company facts are available.</W7Gap>}
        {v.unclassified_industry_usd > 0 && <W7Gap>{usd(v.unclassified_industry_usd)} has no industry classification in CIO memory.</W7Gap>}
      </W7Panel>
      <W7Panel title="Coverage" testId="lookthrough-coverage">
        <div style={{ ...mono, fontSize: 24 }}>{pct(v.fund_coverage_pct)}</div><p>of fund value has published underlying holdings.</p>
        <div style={line}><span>Fund holdings opened</span><span>{usd(v.fund_covered_usd)} / {usd(v.fund_value_usd)}</span></div>
        <div style={line}><span>Look-through vs portfolio</span><span>{usd(v.looked_through_usd)} / {usd(v.portfolio_total_usd)}</span></div>
        {(v.funds_without_holdings || []).map((g: any) => <W7Gap key={`${g.account}-${g.symbol}`}>{g.symbol} · {usd(g.value_usd)} · {g.reason}</W7Gap>)}
        {(v.account_gaps || []).map((g: any) => <W7Gap key={g.account}>{g.label || 'Account sync gap'} · {usd(g.value_usd)} · {g.reason} · {when(g.as_of)}</W7Gap>)}
        {(v.gaps || []).map((g: any, i: number) => <W7Gap key={i}>{g.label} · {usd(g.value_usd)} · {g.reason}</W7Gap>)}
      </W7Panel>
    </div>
    <div style={grid}>
      <W7Panel title="Top underlying stocks">
        <p style={{ color: TOKENS.text[2] }}>{account ? 'Direct + through funds · share of the selected account' : 'Direct + through funds · share of the whole portfolio'}</p>
        {(v.top_underlying || []).map((s: any) => <button key={s.symbol} onClick={() => detail.open(`stock:${s.symbol}`)} style={{ padding: '10px 0', minHeight: 44, width: '100%', background: 'transparent', border: 0, color: TOKENS.text[0], borderTop: `1px solid ${TOKENS.borderSubtle}`, display: 'flex', justifyContent: 'space-between', gap: 10, cursor: 'pointer' }}><b style={mono}>{s.symbol}</b><span style={mono}>{usd(s.value_usd)} · {pct(s.portfolio_pct)} →</span></button>)}
        {!v.top_underlying?.length && <W7Gap>No underlying holdings have been resolved.</W7Gap>}
      </W7Panel>
      <W7Panel title="Themes">
        <p style={{ color: TOKENS.text[2] }}>Share of looked-through value; themes may overlap.</p>
        {(v.themes || []).map((t: any) => <div key={t.name} style={line}><span>{t.name}</span><span style={mono}>{pct(t.looked_through_pct)}</span></div>)}
        {!v.themes?.length && <W7Gap>No theme memberships have been published.</W7Gap>}
      </W7Panel>
      <W7Panel title="Theme gaps vs your targets">
        {(v.theme_gaps || []).map((g: any) => <div key={g.name} style={line}><span>{g.name}</span><span style={mono}>{pct(g.current_pct)} → {pct(g.target_pct)}</span><small style={{ flexBasis: '100%' }}>{usd(g.gap_usd)} below target · ideas for review</small></div>)}
        {!v.theme_gaps?.length && <p>No measured target gaps are published.</p>}
        {v.narrative?.text ? <><p>{v.narrative.text}</p><p style={{ color: TOKENS.text[2] }}>CIO narrative · {when(v.narrative.as_of)}</p></> : <W7Gap>{v.narrative?.reason}</W7Gap>}
        <Link style={linkStyle} to="/rotation">Review rotation ideas →</Link>
      </W7Panel>
    </div>
    {(exposure || underlying) && <W7DetailSheet title={exposure?.name || `${underlying.symbol} · underlying holdings`} onClose={detail.close}>
      {exposure && (exposure.members || []).map((m: any) => <div key={m.symbol} style={line}><b>{m.symbol}</b><span>{usd(m.value_usd)}</span>{m.sources?.length > 0 && <p style={{ flexBasis: '100%', margin: 0 }}>{m.sources.map((s: any) => `${s.symbol}${s.proxy ? ` via ${s.proxy} proxy` : ''} · ${s.account_label || 'Account name unavailable'} · ${usd(s.value_usd)}`).join('; ')}</p>}</div>)}
      {underlying && (underlying.sources || []).map((s: any, i: number) => <div key={i} style={line}><span>{s.symbol}{s.proxy ? ` via ${s.proxy} proxy` : ''} · {s.account_label || 'Account name unavailable'}</span><span>{usd(s.value_usd)}</span><small style={{ flexBasis: '100%' }}>{s.source}</small></div>)}
      <Link style={{ ...linkStyle, width: '100%', justifyContent: 'center', background: TOKENS.bg[2], marginTop: 20 }} to={underlying ? `/portfolio?tab=Holdings&symbol=${encodeURIComponent(underlying.symbol)}` : '/portfolio?tab=Holdings'}>Review positions →</Link>
    </W7DetailSheet>}
  </div>
}

export default function W7Lookthrough({ account, selectAccount }: { account: string | null, selectAccount: (v: string | null) => void }) {
  const { data, loading, error } = useW7Pages()
  return <DeskPage title="Look-through" purpose="What you own inside funds — by sector, industry, theme and stock." sources={[
    { id: 'holdings', label: 'Holdings', asOf: data?.portfolio?.positions_as_of, laneIds: ['schwab-position-sync', 'snaptrade-sync'], gap: data?.portfolio?.gap?.reason },
    { id: 'weights', label: 'Fund holdings', laneIds: ['portfolio-lookthrough-themes'], gap: 'Fund weights retain their original publication evidence.' },
  ]} decisionGap="Review dollar-sized coverage and target gaps below.">{data ? <W7LookthroughView data={data} account={account} selectAccount={selectAccount} /> : <W7Load loading={loading} error={error} />}</DeskPage>
}

export function W7Allocation({ account, selectAccount }: { account: string | null, selectAccount: (v: string | null) => void }) {
  const { data, loading, error } = useW7Pages()
  if (!data) return <W7Load loading={loading} error={error} />
  const model = data.lookthrough || {}, view = account ? model.by_account?.[account] : model
  return <W7Panel title="Sector allocation" testId="allocation-sector-summary">
    <label>Account <select aria-label="Allocation account" value={account || ''} onChange={e => selectAccount(e.target.value || null)} style={{ maxWidth: '100%', minHeight: 44, padding: 8, background: TOKENS.bg[2], color: TOKENS.text[0] }}><option value="">All accounts</option>{(model.accounts || []).map((a: any) => <option key={a.id} value={a.id}>{a.label}</option>)}</select></label>
    {(view?.sectors || []).map((s: any) => <div key={s.name} style={{ marginTop: 12 }}><div style={line}><span>{s.name}</span><span>{usd(s.value_usd)} · {pct(s.portfolio_pct)}</span></div><div style={{ height: 8, background: TOKENS.bg[3] }}><div style={{ height: 8, width: `${Math.min(100, Math.max(0, s.portfolio_pct || 0))}%`, background: TOKENS.info }} /></div></div>)}
    {!view?.sectors?.length && <W7Gap>No sectors have been classified on the current portfolio basis.</W7Gap>}
    <p><Link style={linkStyle} to="/portfolio?tab=Look-through">Industries, coverage, themes and underlying holdings → Look-through</Link></p>
  </W7Panel>
}
