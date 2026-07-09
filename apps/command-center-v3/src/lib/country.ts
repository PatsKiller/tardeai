// Reusable country resolution for table flag columns (Market Opportunities,
// and later Watchlist / Universe / Portfolio, etc.).
//
// The "country" we resolve is the HEADQUARTERS country of the *underlying
// business*, not the listing venue. For ADRs that means the home country
// (PBR → Brazil, BABA → China, VALE → Brazil), never the US listing.
//
// Data sources this understands (whatever the API happens to send):
//   - a raw country NAME string  ("China", "United Kingdom")  ← preferred
//   - a flag EMOJI               ("🇨🇳")                        ← what /api/v2/trade-ai
//                                                                currently sends
//   - an ISO-3166 alpha-2 CODE   ("CN")
// Plus a small ADR_OVERRIDES table for well-known ADRs, which takes priority
// (and also covers rows that arrive with no country at all).
//
// Resolution order — see resolveCountry():
//   1. ADR_OVERRIDES[symbol]
//   2. countryName / country field (name → emoji → code, first match wins)
//   3. null (unknown) → caller renders a 🌍 fallback with a "Country unknown" tip

export interface Country {
  code: string // ISO-3166 alpha-2, e.g. "US"
  name: string // English short name, e.g. "United States"
  flag: string // flag emoji, e.g. "🇺🇸"
}

// ISO-3166 alpha-2 → English short name. Flags are DERIVED from the code
// (see flagFromCode), so adding a country is a single line here. Covers the
// countries the backend flag map emits plus common ADR home countries.
const NAMES: Record<string, string> = {
  US: 'United States', CA: 'Canada', MX: 'Mexico', BR: 'Brazil', AR: 'Argentina',
  GB: 'United Kingdom', IE: 'Ireland', FR: 'France', DE: 'Germany', NL: 'Netherlands',
  CH: 'Switzerland', LU: 'Luxembourg', ES: 'Spain', IT: 'Italy',
  SE: 'Sweden', NO: 'Norway', DK: 'Denmark', FI: 'Finland',
  IL: 'Israel', CN: 'China', HK: 'Hong Kong', TW: 'Taiwan', JP: 'Japan',
  KR: 'South Korea', IN: 'India', SG: 'Singapore', AU: 'Australia', MY: 'Malaysia',
  BM: 'Bermuda', KY: 'Cayman Islands',
}

const REGIONAL_A = 0x1f1e6 // 🇦 regional-indicator base
const CP_A = 65 // 'A'

/** Flag emoji from an ISO-2 code via regional-indicator symbols. "" if invalid. */
export function flagFromCode(code: string): string {
  const cc = (code || '').trim().toUpperCase()
  if (!/^[A-Z]{2}$/.test(cc)) return ''
  return String.fromCodePoint(...[...cc].map(ch => REGIONAL_A + ch.charCodeAt(0) - CP_A))
}

/** Reverse: flag emoji → ISO-2 code, or null if the string isn't a 2-letter flag. */
function codeFromFlag(flag: string): string | null {
  const cps = [...(flag || '').trim()]
    .map(c => c.codePointAt(0) || 0)
    .filter(cp => cp >= REGIONAL_A && cp <= 0x1f1ff)
  if (cps.length !== 2) return null
  return cps.map(cp => String.fromCharCode(cp - REGIONAL_A + CP_A)).join('')
}

// Lowercased country name / alias → ISO-2. Built from NAMES + common variants.
const NAME_TO_CODE: Record<string, string> = (() => {
  const m: Record<string, string> = {}
  for (const [code, name] of Object.entries(NAMES)) m[name.toLowerCase()] = code
  Object.assign(m, {
    usa: 'US', 'u.s.': 'US', 'u.s.a.': 'US', 'united states of america': 'US', america: 'US',
    uk: 'GB', 'u.k.': 'GB', 'great britain': 'GB', england: 'GB',
    korea: 'KR', 'republic of korea': 'KR', 'korea, south': 'KR',
    prc: 'CN', "people's republic of china": 'CN',
    holland: 'NL',
  })
  return m
})()

// Well-known ADRs where the listing venue (US) ≠ HQ country. Finviz usually
// already reports the home country, so this is a safety net that also covers
// rows arriving without a country. Keyed by (base) ticker symbol.
const ADR_OVERRIDES: Record<string, string> = {
  // Brazil
  PBR: 'BR', 'PBR.A': 'BR', VALE: 'BR', ITUB: 'BR', BBD: 'BR', ABEV: 'BR', NU: 'BR',
  ERJ: 'BR', GGB: 'BR', STNE: 'BR', XP: 'BR', BSBR: 'BR',
  // China / Hong Kong
  BABA: 'CN', JD: 'CN', PDD: 'CN', BIDU: 'CN', NIO: 'CN', LI: 'CN', XPEV: 'CN',
  TCOM: 'CN', BILI: 'CN', NTES: 'CN', TME: 'CN', YUMC: 'CN', ZTO: 'CN', BEKE: 'CN', VIPS: 'CN',
  // Taiwan
  TSM: 'TW', UMC: 'TW', ASX: 'TW',
  // Europe
  ASML: 'NL', PHG: 'NL', SHEL: 'GB', BP: 'GB', HSBC: 'GB', GSK: 'GB', AZN: 'GB',
  BTI: 'GB', RIO: 'GB', UL: 'GB', SAP: 'DE', SNY: 'FR', NVO: 'DK', NVS: 'CH',
  UBS: 'CH', SPOT: 'SE',
  // Japan
  TM: 'JP', SONY: 'JP', HMC: 'JP', MUFG: 'JP', NMR: 'JP',
  // India
  INFY: 'IN', WIT: 'IN', HDB: 'IN', IBN: 'IN', RDY: 'IN',
  // Others
  SHOP: 'CA', SE: 'SG', GRAB: 'SG', MELI: 'AR', GLOB: 'AR', TEVA: 'IL', CX: 'MX',
}

function build(code: string | null | undefined): Country | null {
  const cc = (code || '').trim().toUpperCase()
  const name = NAMES[cc]
  if (!name) return null
  return { code: cc, name, flag: flagFromCode(cc) }
}

export interface CountryInput {
  symbol?: string
  country?: string // raw name, flag emoji, or ISO-2 code (any of these)
  countryName?: string // raw name, preferred when present
}

/**
 * Resolve the headquarters country for a table row. Returns null when the
 * country can't be determined, so callers can render a neutral fallback
 * (🌍 / "Country unknown") rather than guessing.
 */
export function resolveCountry(input: CountryInput): Country | null {
  const sym = (input.symbol || '').trim().toUpperCase()
  if (sym && ADR_OVERRIDES[sym]) return build(ADR_OVERRIDES[sym])

  // countryName (raw string) is preferred over country (which may be a lossy
  // flag emoji — the backend defaults unknown countries to 🇺🇸).
  for (const raw of [input.countryName, input.country]) {
    const v = (raw || '').trim()
    if (!v) continue
    const fromFlag = codeFromFlag(v)
    if (fromFlag) { const c = build(fromFlag); if (c) return c }
    if (/^[A-Za-z]{2}$/.test(v)) { const c = build(v); if (c) return c }
    const byName = NAME_TO_CODE[v.toLowerCase()]
    if (byName) { const c = build(byName); if (c) return c }
  }
  return null
}

/** Convenience: resolve purely from a ticker symbol (ADR overrides only). */
export function getCountryFromSymbol(symbol: string): Country | null {
  return resolveCountry({ symbol })
}
