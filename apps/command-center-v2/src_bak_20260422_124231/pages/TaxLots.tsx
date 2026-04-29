import { useState } from 'react'
import PageHeader from '../components/PageHeader'
import DetailDrawer, { DrawerStat, DrawerSection } from '../components/DetailDrawer'
import MetricTile from '../components/MetricTile'
import DataGrid from '../components/DataGrid'
import { useApi } from '../hooks/useApi'
import { fmt$, fmtPct, deltaColor } from '../lib/format'

interface Lot { symbol: string; account: string; shares: number; cost_basis: number; current_value: number; unrealized_gain: number; gain_pct: number; acquired: string; holding_period: string }
interface TaxData { count: number; lots: Lot[] }

export default function TaxLots() {
  const { data: t } = useApi<TaxData>('/api/v2/tax-lots')
  const [selectedLot, setSelectedLot] = useState<Lot | null>(null)
  if (!t) return <div style={{ color: 'var(--text3)', padding: 40 }}>Loading...</div>

  const totalGain = t.lots.reduce((s, l) => s + l.unrealized_gain, 0)
  const totalBasis = t.lots.reduce((s, l) => s + l.cost_basis, 0)
  const totalValue = t.lots.reduce((s, l) => s + l.current_value, 0)
  const gains = t.lots.filter(l => l.unrealized_gain > 0)
  const losses = t.lots.filter(l => l.unrealized_gain < 0)

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
      <PageHeader title="Tax & Lots" subtitle={`${t.count} lots across all accounts`} />
      <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        <MetricTile label="Total Basis" value={fmt$(totalBasis)} />
        <MetricTile label="Current Value" value={fmt$(totalValue)} />
        <MetricTile label="Unrealized" value={`${totalGain >= 0 ? '+' : ''}${fmt$(totalGain)}`} deltaColor={deltaColor(totalGain)} />
        <MetricTile label="Gains" value={String(gains.length)} deltaColor="var(--green)" />
        <MetricTile label="Losses" value={String(losses.length)} deltaColor="var(--red)" />
      </div>
      <DataGrid columns={columns} data={t.lots} rowKey={r => r.symbol + r.account + r.acquired} maxHeight={450}
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
                {selectedLot.unrealized_gain < -100 ? (
                  <div style={{ color: 'var(--amber)' }}>Harvest candidate: {fmt$(Math.abs(selectedLot.unrealized_gain))} unrealized loss available for tax-loss harvesting.</div>
                ) : selectedLot.unrealized_gain > 1000 ? (
                  <div style={{ color: 'var(--green)' }}>Significant unrealized gain. Consider holding period for favorable tax treatment.</div>
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
