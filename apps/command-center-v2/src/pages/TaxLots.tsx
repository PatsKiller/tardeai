import { useState, useMemo } from 'react'
import PageHeader from '../components/PageHeader'
import DetailDrawer, { DrawerStat, DrawerSection } from '../components/DetailDrawer'
import MetricTile from '../components/MetricTile'
import DataGrid from '../components/DataGrid'
import AccountBadge from '../components/AccountBadge'
import { useApi } from '../hooks/useApi'
import { fmt$, fmtPct, deltaColor } from '../lib/format'

interface Lot { symbol: string; account: string; shares: number; cost_basis: number; current_value: number; unrealized_gain: number; gain_pct: number; acquired: string; holding_period: string }
interface TaxData { count: number; lots: Lot[]; harvest_candidates?: number; data_note?: string }

const ACCT: Record<string, string> = { schwab_taxable: 'Taxable', schwab_roth: 'Roth', schwab_rollover_ira: 'Roll IRA', fidelity_401k: '401k' }

export default function TaxLots() {
  const { data: t } = useApi<TaxData>('/api/v2/tax-lots')
  const [selectedLot, setSelectedLot] = useState<Lot | null>(null)
  const [acctFilter, setAcctFilter] = useState('all')

  // All hooks must be called before any early return (React rules of hooks)
  const accounts = useMemo(() => t ? ['all', ...Array.from(new Set(t.lots.map(l => l.account)))] : ['all'], [t])
  const filtered = useMemo(() => !t ? [] : acctFilter === 'all' ? t.lots : t.lots.filter(l => l.account === acctFilter), [t, acctFilter])

  if (!t) return <div style={{ color: 'var(--text3)', padding: 40 }}>Loading...</div>

  if (t.count === 0) return (
    <>
      <PageHeader title="Tax & Lots" subtitle="Cost basis and tax-loss harvesting" />
      <div style={{ padding: 20, color: 'var(--text3)', fontSize: 11 }}>
        No open tax lots found. Either cost basis data hasn't been imported, or all lots are closed.
        <div style={{ marginTop: 8 }}>To import: Actions page → Import CSV (Fidelity Position Export).</div>
      </div>
    </>
  )

  const totalGain = filtered.reduce((s, l) => s + l.unrealized_gain, 0)
  const totalBasis = filtered.reduce((s, l) => s + l.cost_basis, 0)
  const totalValue = filtered.reduce((s, l) => s + l.current_value, 0)
  const gains = filtered.filter(l => l.unrealized_gain > 0)
  const losses = filtered.filter(l => l.unrealized_gain < 0)
  const harvestable = filtered.filter(l => l.unrealized_gain < -100 && (l.account === 'schwab_taxable' || l.account === 'taxable'))

  const columns = [
    { key: 'symbol', label: 'Symbol', width: 55, render: (r: Lot) => <span style={{ fontWeight: 700 }}>{r.symbol}</span> },
    { key: 'account', label: 'Acct', width: 55, render: (r: Lot) => <span style={{ fontSize: 9, color: 'var(--text3)' }}>{r.account?.replace('schwab_', '').slice(0, 8)}</span> },
    { key: 'shares', label: 'Shares', width: 45, align: 'right' as const, render: (r: Lot) => r.shares.toFixed(1) },
    { key: 'cost_basis', label: 'Basis', width: 60, align: 'right' as const, render: (r: Lot) => fmt$(r.cost_basis) },
    { key: 'current_value', label: 'Value', width: 60, align: 'right' as const, render: (r: Lot) => fmt$(r.current_value) },
    { key: 'unrealized_gain', label: 'Gain $', width: 60, align: 'right' as const, sortKey: (r: Lot) => r.unrealized_gain, render: (r: Lot) => (
      <span style={{ fontWeight: 600, color: deltaColor(r.unrealized_gain) }}>{r.unrealized_gain >= 0 ? '+' : ''}{fmt$(r.unrealized_gain)}</span>
    )},
    { key: 'gain_pct', label: 'Gain %', width: 50, align: 'right' as const, render: (r: Lot) => <span style={{ color: deltaColor(r.gain_pct) }}>{fmtPct(r.gain_pct, 1)}</span> },
    { key: 'acquired', label: 'Acquired', width: 70, render: (r: Lot) => <span style={{ fontSize: 9, color: 'var(--text3)' }}>{r.acquired}</span> },
    { key: 'holding_period', label: 'Period', width: 40, render: (r: Lot) => <span style={{ fontSize: 9, color: r.holding_period === 'long' ? 'var(--green)' : 'var(--amber)' }}>{r.holding_period === 'long' ? 'LT' : 'ST'}</span> },
  ]

  return (
    <>
      <PageHeader title="Tax & Lots" subtitle={`${t.count} open lots across all accounts${t.data_note ? ` · ${t.data_note}` : ''}`} />

      {totalBasis === 0 && totalValue === 0 && (
        <div style={{ padding: '10px 14px', marginBottom: 12, background: 'var(--amber-dim)', border: '1px solid var(--amber)', borderRadius: 8, fontSize: 11, color: 'var(--amber)' }}>
          All lot values showing $0 — cost basis data may not be imported, or live prices aren't loaded. Run daily pipeline to refresh prices. For cost basis, import from Fidelity → Accounts → Tax Lots → Download.
        </div>
      )}

      {t.count > 5000 && (
        <div style={{ padding: '8px 12px', marginBottom: 10, background: 'var(--amber-dim)', border: '1px solid var(--amber)', borderRadius: 8, fontSize: 10, color: 'var(--amber)' }}>
          {t.count.toLocaleString()} lots detected — this may include duplicate imports. Verify data integrity before using for tax-loss harvesting decisions.
        </div>
      )}

      {/* Account filter */}
      <div style={{ display: 'flex', gap: 3, marginBottom: 8 }}>
        {accounts.map(a => (
          <button key={a} onClick={() => setAcctFilter(a)} style={{
            padding: '4px 12px', fontSize: 10, border: `1px solid ${acctFilter === a ? 'var(--accent)' : 'rgba(255,255,255,0.08)'}`, borderRadius: 9999,
            background: acctFilter === a ? 'var(--accent-dim)' : 'rgba(255,255,255,0.04)',
            color: acctFilter === a ? 'var(--accent)' : 'var(--text3)',
            cursor: 'pointer', fontFamily: 'var(--sans)',
          }}>
            {ACCT[a] || (a === 'all' ? 'All Accounts' : a)}
          </button>
        ))}
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        <MetricTile label="Total Basis" value={fmt$(totalBasis)} />
        <MetricTile label="Current Value" value={fmt$(totalValue)} />
        <MetricTile label="Unrealized" value={`${totalGain >= 0 ? '+' : ''}${fmt$(totalGain)}`} deltaColor={deltaColor(totalGain)} />
        <MetricTile label="Gains" value={String(gains.length)} deltaColor="var(--green)" />
        <MetricTile label="Losses" value={String(losses.length)} deltaColor="var(--red)" />
        {harvestable.length > 0 && (
          <MetricTile label="Harvest Candidates" value={String(harvestable.length)} delta="Taxable acct losses >$100" deltaColor="var(--amber)" tooltip="Tax-loss harvesting only applies to Taxable account. IRA/401k/Roth losses have no tax benefit. Watch for 30-day wash sale rule." />
        )}
      </div>

      <DataGrid columns={columns} data={filtered} rowKey={r => r.symbol + r.account + r.acquired} maxHeight={450}
        onRowClick={r => setSelectedLot(r)} />

      {/* Tax lot detail drawer */}
      <DetailDrawer open={!!selectedLot} onClose={() => setSelectedLot(null)}
        title={selectedLot?.symbol || ''} subtitle={`${selectedLot?.holding_period === 'long' ? 'Long-term' : 'Short-term'} | Acquired ${selectedLot?.acquired || '—'}`}>
        {selectedLot && (
          <>
            <DrawerSection title="Lot Detail">
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4 }}>
                <DrawerStat label="Shares" value={selectedLot.shares.toFixed(2)} />
                <DrawerStat label="Acquired" value={selectedLot.acquired || '—'} />
                <DrawerStat label="Cost Basis" value={fmt$(selectedLot.cost_basis)} />
                <DrawerStat label="Current Value" value={fmt$(selectedLot.current_value)} />
                <DrawerStat label="Unrealized Gain" value={`${selectedLot.unrealized_gain >= 0 ? '+' : ''}${fmt$(selectedLot.unrealized_gain)}`} color={deltaColor(selectedLot.unrealized_gain)} />
                <DrawerStat label="Gain %" value={fmtPct(selectedLot.gain_pct, 1)} color={deltaColor(selectedLot.gain_pct)} />
                <DrawerStat label="Holding Period" value={selectedLot.holding_period === 'long' ? 'Long-term' : 'Short-term'} color={selectedLot.holding_period === 'long' ? 'var(--green)' : 'var(--amber)'} />
                <DrawerStat label="Account" value={selectedLot.account?.replace('schwab_', '') || '—'} />
              </div>
            </DrawerSection>
            <DrawerSection title="Tax Action">
              <div style={{ fontSize: 10, color: 'var(--text2)', lineHeight: 1.5 }}>
                {(selectedLot.current_value <= 0.01 && selectedLot.cost_basis > 0) ? (
                  <div style={{ color: 'var(--red)', padding: '8px 10px', background: 'rgba(246,70,93,0.06)', border: '1px solid rgba(246,70,93,0.15)', borderRadius: 6 }}>
                    <strong style={{ fontSize: 12 }}>Worthless Security Detected</strong>
                    <div style={{ marginTop: 6, fontSize: 10 }}>Value: $0 · Cost basis: {fmt$(selectedLot.cost_basis)} · Potential loss: {fmt$(selectedLot.cost_basis)}</div>
                    <div style={{ marginTop: 6, fontSize: 10, lineHeight: 1.6 }}>
                      Standard sell orders won't work for worthless/delisted securities. To claim this loss:
                      <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>
                        <li>Call Fidelity: <strong>1-800-343-3548</strong> — request worthless security disposal</li>
                        <li>Or: Fidelity.com → Accounts → Positions → elect worthless security removal</li>
                        <li>File before <strong>December 31</strong> to claim the loss in the current tax year</li>
                      </ul>
                    </div>
                    {selectedLot.account && !selectedLot.account.includes('taxable') && (
                      <div style={{ marginTop: 6, fontSize: 9, color: 'var(--amber)' }}>Note: This lot is in {selectedLot.account.replace('schwab_', '')} (IRA) — losses in tax-deferred accounts have no direct tax benefit, but removing worthless positions cleans up reporting.</div>
                    )}
                  </div>
                ) : selectedLot.unrealized_gain < -100 && (selectedLot.account === 'schwab_taxable' || selectedLot.account === 'taxable') ? (
                  <div style={{ color: 'var(--amber)' }}>
                    <strong>Harvest candidate</strong>: {fmt$(Math.abs(selectedLot.unrealized_gain))} unrealized loss in Taxable account.
                    <div style={{ marginTop: 4, fontSize: 9 }}>Sell to realize loss for tax offset. Watch 30-day wash sale rule — do not repurchase same/substantially identical security within 30 days.</div>
                  </div>
                ) : selectedLot.unrealized_gain < -100 ? (
                  <div style={{ color: 'var(--text3)' }}>Unrealized loss in {selectedLot.account?.replace('schwab_', '')} — IRA/401k losses have no tax benefit. Consider trimming for rebalancing purposes only.</div>
                ) : selectedLot.unrealized_gain > 1000 ? (
                  <div style={{ color: 'var(--green)' }}>Significant unrealized gain ({fmt$(selectedLot.unrealized_gain)}). {selectedLot.holding_period === 'long' ? 'Long-term: 0% LTCG at 12% bracket.' : 'Short-term: taxed as income. Consider holding 1yr+ for LTCG rate.'}</div>
                ) : (
                  <div>No immediate tax action indicated.</div>
                )}
              </div>
            </DrawerSection>
          </>
        )}
      </DetailDrawer>
    </>
  )
}
