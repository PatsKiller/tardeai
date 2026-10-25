import { useEffect, useState } from 'react'
import { assetUrl, designRequest, type DesignAsset, type DesignImage } from '../../lib/designApprovals'

/** One private mockup, loaded through the authenticated design asset route (never a public URL). */
export default function DesignThumb({ page, version, width, image }: { page: string; version: string; width: number; image: DesignImage | null }) {
  const [src, setSrc] = useState<string | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    if (!image) return
    const controller = new AbortController()
    designRequest<DesignAsset>(assetUrl(page, version, image.path), undefined, controller.signal)
      .then(asset => setSrc(asset.image)).catch(err => { if (!controller.signal.aborted) setError(err.message) })
    return () => controller.abort()
  }, [page, version, image?.path])
  return <figure className="design-thumb" style={{ margin: 0 }}>
    {!image ? <span>No {width} px mockup was proposed.</span>
      : src ? <img src={src} alt={`${page} ${version} mockup at ${width} px`} loading="lazy" />
        : <span role="status">{error || `Loading the ${width} px mockup…`}</span>}
    <span>{width} px</span>
  </figure>
}
