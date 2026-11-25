/**
 * An AI 3D draft (GLB) with a 3D preview and a download (spec 008, clarification Q4).
 *
 * The file is fetched with the operator's session. The preview itself is
 * `components/viewer/GlbView`, loaded through `React.lazy` so three.js stays
 * in the viewer chunk (spec 004, FR-024).
 */
import { lazy, Suspense, useEffect, useMemo } from 'react'
import { Box, Download } from 'lucide-react'

import { buttonVariants } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useGenAIBlob } from '@/hooks/useGenAI'
import { cn } from '@/lib/utils'

const GlbView = lazy(() => import('@/components/viewer/GlbView'))

interface MeshPreviewProps {
  path: string | null | undefined
  filename?: string | null
  className?: string
}

export function MeshPreview({ path, filename, className }: MeshPreviewProps) {
  const { blob, isLoading, isError } = useGenAIBlob(path)
  const downloadUrl = useMemo(() => (blob ? URL.createObjectURL(blob) : null), [blob])
  useEffect(
    () => () => {
      if (downloadUrl) URL.revokeObjectURL(downloadUrl)
    },
    [downloadUrl]
  )

  if (!path) return null
  return (
    <div className={cn('space-y-2', className)}>
      <div className="aspect-square w-full overflow-hidden rounded-md border bg-muted">
        {isError ? (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            <Box className="mr-2 h-4 w-4" aria-hidden />
            The 3D draft could not be loaded
          </div>
        ) : isLoading || !blob ? (
          <Skeleton className="h-full w-full" aria-label="Loading 3D draft" />
        ) : (
          <Suspense fallback={<Skeleton className="h-full w-full" aria-label="Loading 3D draft" />}>
            <GlbView blob={blob} />
          </Suspense>
        )}
      </div>
      <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
        <span>AI 3D draft (GLB)</span>
        {downloadUrl && (
          <a
            href={downloadUrl}
            download={filename || 'ai-draft.glb'}
            className={buttonVariants({ variant: 'outline', size: 'sm' })}
          >
            <Download className="mr-1 h-3 w-3" aria-hidden />
            Download
          </a>
        )}
      </div>
    </div>
  )
}
