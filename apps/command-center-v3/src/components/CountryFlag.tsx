import { useState, type CSSProperties } from 'react'
import { resolveCountry, type CountryInput } from '../lib/country'

export interface CountryFlagProps extends CountryInput {
  /** Display width in px (flagcdn aspect ~ 4:3). Default 20 for table cells. */
  size?: number
}

/**
 * HQ country flag as a PNG image (not emoji — Linux often renders 🇨🇳 as "CN").
 * Tooltip shows the English country name only.
 */
export default function CountryFlag({ size = 20, ...input }: CountryFlagProps) {
  const ctry = resolveCountry(input)
  const [imgFailed, setImgFailed] = useState(false)

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

  const code = ctry.code.toLowerCase()
  const retina = size * 2

  if (imgFailed) {
    return (
      <span title={ctry.name} style={{ ...wrapStyle, fontSize: size * 0.45, fontWeight: 800, color: 'var(--text3)', letterSpacing: -0.5 }}>
        {ctry.code}
      </span>
    )
  }

  return (
    <img
      src={`https://flagcdn.com/w${retina}/${code}.png`}
      srcSet={`https://flagcdn.com/w${retina}/${code}.png 2x`}
      width={size}
      height={Math.round(size * 0.75)}
      alt=""
      title={ctry.name}
      loading="lazy"
      decoding="async"
      onError={() => setImgFailed(true)}
      style={{
        width: size,
        height: Math.round(size * 0.75),
        borderRadius: 2,
        objectFit: 'cover',
        display: 'block',
        boxShadow: '0 0 0 1px rgba(0,0,0,.25)',
      }}
    />
  )
}