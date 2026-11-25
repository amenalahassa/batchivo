/**
 * PlatformGenaiCard Component (spec 008, T029)
 *
 * Platform admin switch: may this shop use the platform's Replicate token?
 */

import { Loader2, Sparkles } from 'lucide-react'

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { genaiError, usePlatformGenai, useSetPlatformGenai } from '@/hooks/useGenAI'

interface PlatformGenaiCardProps {
  tenantId: string
}

export function PlatformGenaiCard({ tenantId }: PlatformGenaiCardProps) {
  const { platform, isLoading, error } = usePlatformGenai(tenantId)
  const setPlatform = useSetPlatformGenai(tenantId)

  const switchId = `platform-genai-${tenantId}`
  const allTenants = platform?.all_tenants ?? false
  const failure = genaiError(error ?? setPlatform.error)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Sparkles className="h-5 w-5" />
          Generative AI
        </CardTitle>
        <CardDescription>
          Whether this shop may run generative AI on the platform's Replicate token.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading ? (
          <Loader2 className="h-5 w-5 animate-spin" />
        ) : platform ? (
          <>
            <div className="flex items-center justify-between gap-4">
              <Label htmlFor={switchId}>Allow the platform Replicate token</Label>
              <Switch
                id={switchId}
                checked={allTenants || platform.platform_token_allowed}
                disabled={allTenants || setPlatform.isPending}
                onCheckedChange={(checked) => setPlatform.mutate(checked)}
              />
            </div>
            {!platform.platform_token_available && (
              <p className="text-sm text-muted-foreground">
                No platform token is configured on this server.
              </p>
            )}
            {allTenants && (
              <p className="text-sm text-muted-foreground">
                Every shop is allowed the platform token on this install.
              </p>
            )}
          </>
        ) : null}
        {failure && (
          <p role="alert" className="text-sm text-destructive">
            {failure.message}
          </p>
        )}
      </CardContent>
    </Card>
  )
}
