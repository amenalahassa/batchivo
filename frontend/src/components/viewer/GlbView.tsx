/**
 * An AI 3D draft (GLB) drawn in the viewer canvas (spec 008, clarification Q4).
 *
 * Loaded only through `React.lazy` from `components/genai/MeshPreview`, so
 * three.js stays in the viewer chunk (spec 004, FR-024). The draft's size is
 * shown for information only: an AI draft never sets a model's dimensions
 * (spec 008, FR-019).
 */
import { useEffect, useState } from 'react'

import { Skeleton } from '@/components/ui/skeleton'
import { parseGlb } from './glb'
import { ViewerCanvas } from './ViewerCanvas'

export default function GlbView({ blob }: { blob: Blob }) {
  const [parsed, setParsed] = useState<Awaited<ReturnType<typeof parseGlb>> | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let alive = true
    setParsed(null)
    setFailed(false)
    blob
      .arrayBuffer()
      .then(parseGlb)
      .then((result) => alive && setParsed(result))
      .catch(() => alive && setFailed(true))
    return () => {
      alive = false
    }
  }, [blob])

  if (failed) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        The 3D draft could not be shown
      </div>
    )
  }
  if (!parsed) return <Skeleton className="h-full w-full" aria-label="Loading 3D draft" />
  const { size, center } = parsed
  return (
    <div className="relative h-full w-full">
      <ViewerCanvas
        bed={null}
        target={[center.x, center.y, center.z]}
        extent={Math.max(size.x, size.y, size.z)}
      >
        <primitive object={parsed.scene} />
      </ViewerCanvas>
      <span className="absolute bottom-1 left-1 rounded bg-background/80 px-1 text-xs text-muted-foreground">
        About {size.x.toFixed(1)} × {size.y.toFixed(1)} × {size.z.toFixed(1)} (draft, not to scale)
      </span>
    </div>
  )
}
