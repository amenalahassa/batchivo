/** Marks a picture or a file made by generative AI (spec 008, FR-017). */
import { Sparkles } from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

export function AIBadge({ className, label = 'AI' }: { className?: string; label?: string }) {
  return (
    <Badge
      variant="secondary"
      className={cn('gap-1', className)}
      title="Made with generative AI"
      aria-label={`${label}: made with generative AI`}
    >
      <Sparkles className="h-3 w-3" aria-hidden />
      {label}
    </Badge>
  )
}
