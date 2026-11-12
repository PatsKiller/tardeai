// LQ-20261107-2228: an errored Finviz health check is UNKNOWN, not the red non-dismissible banner of a real expiry.
// Payloads below are the server's own shapes (scripts/api_v2.py _finviz_credential_health_live), synthetic values.
import { finvizBannerView } from './finvizBannerView.ts'

let pass = 0, fail = 0
const check = (n, c, d = '') => { if (c) { pass++; console.log(`  [PASS] ${n}`) } else { fail++; console.log(`  [FAIL] ${n} ${d}`) } }

const ERRORED = { ok: false, status: 'check_failed', cookie_status: 'unknown', severity: 'amber', show_banner: true,
  message: 'UNKNOWN — health check errored: TimeoutError' }
const EXPIRED = { ok: false, status: 'expired', cookie_status: 'expired', severity: 'red', show_banner: true,
  message: 'Finviz Elite cookie and API token both failing' }
const MISSING = { ok: false, status: 'missing', cookie_status: 'missing', severity: 'red', show_banner: true }
const TOKEN_OK = { ok: true, status: 'token_ok', cookie_status: 'expired', severity: 'amber', show_banner: true }
const HEALTHY = { ok: true, status: 'ok', cookie_status: 'ok', severity: 'ok', show_banner: false }

const e = finvizBannerView(ERRORED, false)
check('errored check: shown', e.show === true)
check('errored check: UNKNOWN', e.unknown === true)
check('errored check: NOT severe (not red, not undismissable) despite ok:false', e.severe === false, JSON.stringify(e))
check('errored check: dismissible', finvizBannerView(ERRORED, true).show === false)
check('errored check stays UNKNOWN with severity forced red', finvizBannerView({ ...ERRORED, severity: 'red' }, false).severe === false)

const x = finvizBannerView(EXPIRED, false)
check('real expiry: severe', x.severe === true && x.unknown === false, JSON.stringify(x))
check('real expiry: stays visible after dismiss', finvizBannerView(EXPIRED, true).show === true)
check('missing cookie: severe, not unknown', finvizBannerView(MISSING, false).severe === true && !finvizBannerView(MISSING, false).unknown)
check('red severity alone: severe', finvizBannerView({ status: 'expired', severity: 'red' }, false).severe === true)

const t = finvizBannerView(TOKEN_OK, false)
check('token_ok: shown, amber (not severe), not unknown', t.show && !t.severe && !t.unknown, JSON.stringify(t))
check('token_ok: dismissible', finvizBannerView(TOKEN_OK, true).show === false)

check('healthy: hidden', finvizBannerView(HEALTHY, false).show === false)
check('no payload: hidden', finvizBannerView(null, false).show === false)
check('cookie_status unknown without check_failed is also UNKNOWN', finvizBannerView({ ok: false, status: 'error', cookie_status: 'unknown', show_banner: true }, false).severe === false)

console.log(`\n${pass} passed, ${fail} failed`)
process.exit(fail ? 1 : 0)
