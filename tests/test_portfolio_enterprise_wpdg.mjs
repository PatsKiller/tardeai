/** Static checks for Portfolio enterprise WP-D–G. */
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const hub = readFileSync(join(ROOT, 'apps/command-center-v3/src/pages/PortfolioHub.tsx'), 'utf8')
const health = readFileSync(join(ROOT, 'apps/command-center-v3/src/components/PortfolioDeskHealth.tsx'), 'utf8')
const forecast = readFileSync(join(ROOT, 'apps/command-center-v3/src/components/ForecastPanel.tsx'), 'utf8')
const tax = readFileSync(join(ROOT, 'apps/command-center-v3/src/components/TaxPanel.tsx'), 'utf8')
const csv = readFileSync(join(ROOT, 'apps/command-center-v3/src/lib/exportHoldingsCsv.ts'), 'utf8')
const table = readFileSync(join(ROOT, 'apps/command-center-v3/src/components/HoldingsTableView.tsx'), 'utf8')
const redeploy = readFileSync(join(ROOT, 'apps/command-center-v3/src/components/RedeployPanel.tsx'), 'utf8')

function ok(c, m) { if (!c) { console.error('FAIL', m); process.exitCode = 1 } else console.log('ok', m) }

// WP-D lazy
ok(hub.includes("enabled: needHoldingsDesk"), 'holdings-desk gated APIs')
ok(hub.includes("enabled: needForecast"), 'forecast gated')
ok(hub.includes("enabled: needTax"), 'tax gated')
ok(hub.includes("enabled: needLookthrough"), 'lookthrough gated')
ok(hub.includes("enabled: needReturns"), 'returns gated')
ok(hub.includes("enabled: needDividends"), 'dividends gated')

// WP-E panels
ok(hub.includes('ForecastPanel'), 'ForecastPanel mounted')
ok(hub.includes('TaxPanel'), 'TaxPanel mounted')
ok(forecast.includes('forecast-panel'), 'forecast testid')
ok(tax.includes('tax-panel'), 'tax testid')
ok(hub.includes('lookthrough-panel') || hub.includes('No look-through snapshot'), 'lookthrough empty UX')
ok(hub.includes('System → Pipeline') || hub.includes('/system?tab=pipeline'), 'lookthrough ops link')

// WP-F
ok(csv.includes('holdingsToCsv'), 'csv helper')
ok(csv.includes('downloadHoldingsCsv'), 'csv download')
ok(health.includes('desk-health-export-csv'), 'export control')
ok(health.includes('desk-health-stop-audit'), 'stop audit control')
ok(hub.includes('downloadHoldingsCsv'), 'export wired')
ok(hub.includes('onOpenStopAudit'), 'audit wired')
ok(redeploy.includes('useNavigate'), 'redeploy SPA navigate')
ok(!redeploy.includes('window.location.assign'), 'no hard redeploy navigation')

// WP-G
ok(table.includes('role="table"'), 'table role')
ok(table.includes('aria-label="Portfolio holdings"'), 'table aria-label')
ok(table.includes("e.key === 's'") || table.includes('e.key === "s"'), 'S key opens stops')
ok(table.includes('aria-rowindex'), 'row indices')

if (process.exitCode) process.exit(1)
console.log('\nWP-D–G static checks passed')
