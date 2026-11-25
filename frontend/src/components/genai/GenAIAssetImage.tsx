/**
 * A stored generation input or output, loaded with the operator's session (spec 008).
 *
 * Generations are never public: the file is fetched as a blob and shown
 * through an object URL, revoked on unmount (as `ideas/AuthImage`).
 */
import { useEffect, useState } from 'react'
import { ImageOff } from 'lucide-react'

import { Skeleton } from '@/components/ui/skeleton'
import { useGenAIBlob } from '@/hooks/useGenAI'
import { cn } from '@/lib/utils'

interface GenAIAssetImageProps {
  path: string | null | undefined
  alt: string
  className?: string
}

export function GenAIAssetImage({ path, alt, className }: GenAIAssetImageProps) {
  const { blob, isLoading, isError } = useGenAIBlob(path)
  const [url, setUrl] = useState<string | null>(null)

  useEffect(() => {
    if (!blob) {
      setUrl(null)
      return
    }
    const objectUrl = URL.createObjectURL(blob)
    setUrl(objectUrl)
    return () => URL.revokeObjectURL(objectUrl)
  }, [blob])

  if (!path) return null
  if (isError) {
    return (
      <div
        role="img"
        aria-label={`${alt} (image missing)`}
        className={cn('flex items-center justify-center bg-muted text-muted-foreground', className)}
      >
        <ImageOff className="h-5 w-5" aria-hidden />
      </div>
    )
  }
  if (isLoading || !url) return <Skeleton className={className} aria-label={`Loading ${alt}`} />
  return <img src={url} alt={alt} className={cn('object-contain', className)} />
}
