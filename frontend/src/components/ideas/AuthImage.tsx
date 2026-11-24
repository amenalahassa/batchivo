/**
 * An idea image, loaded with the operator's session (spec 007, clarification Q1).
 *
 * Idea images are never served to anyone without a sign-in, so a plain
 * `<img src>` cannot load them: the image is fetched as a blob with the
 * authenticated client and shown through an object URL, revoked on unmount.
 */
import { useEffect, useState } from 'react'
import { ImageOff } from 'lucide-react'

import { Skeleton } from '@/components/ui/skeleton'
import { useIdeaImage } from '@/hooks/useIdeas'
import { cn } from '@/lib/utils'

interface AuthImageProps {
  path: string | null | undefined
  alt: string
  className?: string
}

export function AuthImage({ path, alt, className }: AuthImageProps) {
  const { blob, isLoading, isError } = useIdeaImage(path)
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
        className={cn(
          'flex items-center justify-center bg-muted text-muted-foreground',
          className
        )}
      >
        <ImageOff className="h-5 w-5" aria-hidden />
        <span className="sr-only">Image missing</span>
      </div>
    )
  }
  if (isLoading || !url) return <Skeleton className={className} aria-label={`Loading ${alt}`} />
  return <img src={url} alt={alt} className={cn('object-cover', className)} />
}
