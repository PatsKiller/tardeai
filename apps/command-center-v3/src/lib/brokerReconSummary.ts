/**
 * WP-T6 — pure multi-broker recon summary helpers.
 */

export type BrokerReconRun = {
  broker?: string
  run_status?: string
  unmatched_broker_orders?: number
  unmatched_local_trades?: number
  orders_seen?: number
  trades_matched?: number
  started_at?: string
}

export type BrokerReconItem = {
  broker?: string
  symbol?: string
  reconciliation_state?: string
  issue_code?: string
}

export type BrokerVenueSummary = {
  broker: string
  unmatched_broker: number
  unmatched_local: number
  status: 'ok' | 'break' | 'unknown'
  latest_run_status?: string
  started_at?: string
  next_action: string
}

export function summarizeReconByBroker(
  runs: BrokerReconRun[] | null | undefined,
  items: BrokerReconItem[] | null | undefined,
): BrokerVenueSummary[] {
  const byBroker = new Map<string, BrokerVenueSummary>()

  for (const run of runs || []) {
    const broker = String(run.broker || 'unknown')
    const umB = Number(run.unmatched_broker_orders ?? 0)
    const umL = Number(run.unmatched_local_trades ?? 0)
    const prev = byBroker.get(broker)
    // Prefer latest run (runs assumed newest-first)
    if (!prev) {
      const status: BrokerVenueSummary['status'] =
        umB + umL > 0 ? 'break' : run.run_status ? 'ok' : 'unknown'
      byBroker.set(broker, {
        broker,
        unmatched_broker: umB,
        unmatched_local: umL,
        status,
        latest_run_status: run.run_status,
        started_at: run.started_at,
        next_action: nextAction(broker, umB, umL, status),
      })
    }
  }

  // Fold item counts for brokers not in runs
  for (const it of items || []) {
    const broker = String(it.broker || 'unknown')
    if (!byBroker.has(broker)) {
      byBroker.set(broker, {
        broker,
        unmatched_broker: 0,
        unmatched_local: 0,
        status: 'unknown',
        next_action: 'Inspect recon items for this venue',
      })
    }
  }

  if (byBroker.size === 0) {
    return [{
      broker: 'none',
      unmatched_broker: 0,
      unmatched_local: 0,
      status: 'unknown',
      next_action: 'No recon runs yet — wait for scheduled broker reconciliation',
    }]
  }

  return [...byBroker.values()].sort((a, b) => {
    const sa = a.unmatched_broker + a.unmatched_local
    const sb = b.unmatched_broker + b.unmatched_local
    return sb - sa || a.broker.localeCompare(b.broker)
  })
}

function nextAction(broker: string, umB: number, umL: number, status: string): string {
  if (status === 'ok' && umB === 0 && umL === 0) {
    return `${broker}: in sync — no action`
  }
  if (umB > 0 && umL > 0) {
    return `${broker}: match ${umB} broker + ${umL} local orphans — open items, then Journal`
  }
  if (umB > 0) return `${broker}: ${umB} unmatched broker order(s) — link to local trade or dismiss`
  if (umL > 0) return `${broker}: ${umL} unmatched local trade(s) — find broker fill or fix import`
  return `${broker}: review latest run status`
}
