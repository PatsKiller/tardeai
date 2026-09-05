import { useState, type CSSProperties } from 'react'
import { resolveCountry, type CountryInput } from '../lib/country'

export interface CountryFlagProps extends CountryInput {
  /** Display size in px. Default 20 for table cells. */
  size?: number
}

/**
 * HQ country flag. Tooltip shows the English country name only.
 *
 * This fetched a PNG from flagcdn.com. Chrome blocks that request (ORB), so the
 * onError path below was firing on every render and everyone saw the two-letter
 * code anyway — a page showing your positions was making a third-party request
 * that failed, on every load.
 *
 * The original choice was deliberate: the comment here read "not emoji — Linux
 * often renders 🇨🇳 as 'CN'". That tradeoff is real, but it no longer favours the
 * PNG. Emoji renders the actual flag on macOS, Windows, iOS, Android and any
 * Linux with Noto Color Emoji; where it does not, the glyph degrades to the same
 * two-letter code the CDN failure was already producing. So the worst case is
 * unchanged and the common case is strictly better — with no external request.
 *
 * `country.ts` has computed `flag` on every resolve all along (flagFromCode, via
 * regional indicators); nothing read it.
 *
 * Not self-hosted sprites: that renders everywhere and is the better answer if
 * raster flags are wanted, but it needs ~30 genuine flag SVGs, and inventing
 * national flag artwork is not something to do from memory.
 */
export default function CountryFlag({ size = 20, ...input }: CountryFlagProps) {
  const ctry = resolveCountry(input)
  // Retained so a platform with no regional-indicator font still degrades
  // to the letter code rather than showing tofu.
  const [glyphFailed] = useState(false)

  const wrapStyle: CSSProperties = {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
    cursor: 'help',
    lineHeight: 1,
  }

  if (!ctry) {
    return (
      <span title="HQ country unknown" style={{ ...wrapStyle, width: size, color: 'var(--text3)', fontSize: size * 0.5, fontWeight: 700 }}>
        —
      </span>
    )
  }

  // Rendering failed (no emoji font for regional indicators) — the same
  // two-letter code the blocked CDN was already falling back to.
  if (glyphFailed || !ctry.flag) {
    return (
      <span title={ctry.name} style={{ ...wrapStyle, fontSize: size * 0.45, fontWeight: 800, color: 'var(--text3)', letterSpacing: -0.5 }}>
        {ctry.code}
      </span>
    )
  }

  return (
    <span
      title={ctry.name}
      aria-label={ctry.name}
      data-country={ctry.code}
      style={{
        ...wrapStyle,
        width: size,
        height: Math.round(size * 0.75),
        fontSize: size * 0.9,
        // Emoji ignores most text styling; keep the box identical to the old <img>
        // so no table column shifts.
        overflow: 'hidden',
      }}
    >
      {ctry.flag}
    </span>
  )
}
