/**
 * ReplicateSettings Component (spec 008, T028)
 *
 * The "AI" settings panel: the shop's Replicate token, which token is in use,
 * the monthly budget in USD, usage by month and per-capability model overrides.
 *
 * Money stays a decimal string from the API to the screen and back: it is never
 * converted to a JavaScript number. A full token is never displayed or logged.
 */

import { useState } from 'react'
import { AlertCircle, CheckCircle2, Loader2, Sparkles, TestTube2 } from 'lucide-react'

import { Alert, AlertDescription } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  genaiError,
  useCapabilities,
  useReplicateSettings,
  useReplicateUsage,
  useTestReplicate,
  useUpdateReplicateSettings,
} from '@/hooks/useGenAI'
import type {
  Capability,
  CapabilityInfo,
  PriceUnit,
  ReplicateModelOverride,
  ReplicateSettings as ReplicateSettingsData,
  ReplicateSettingsUpdate,
} from '@/types/genai'

/** A budget in USD: whole dollars, or up to two decimals. */
const BUDGET_PATTERN = /^\d+(\.\d{1,2})?$/
/** A model price in USD: up to six decimals, as the API stores it. */
const PRICE_PATTERN = /^\d+(\.\d{1,6})?$/
const MODEL_REF_PATTERN = /^[A-Za-z0-9][\w.-]*\/[A-Za-z0-9][\w.-]*$/
const VERSION_ID_PATTERN = /^[0-9a-f]{64}$/

const PRICE_UNIT_LABELS: Record<PriceUnit, string> = {
  per_output: 'per output',
  per_run: 'per run',
  per_second: 'per second',
}

/** `$` + the decimal string, untouched. */
function usd(amount: string | null | undefined): string {
  return amount == null ? '—' : `$${amount}`
}

function ErrorLine({ error }: { error: unknown }) {
  const detail = genaiError(error)
  if (!detail) return null
  return (
    <p role="alert" className="text-sm text-destructive">
      {detail.message}
    </p>
  )
}

// ---------------------------------------------------------------------- token

function TokenSection({ settings }: { settings: ReplicateSettingsData }) {
  const update = useUpdateReplicateSettings()
  const test = useTestReplicate()
  const [token, setToken] = useState('')

  const source = settings.token_source
  const sourceLabel =
    source === 'tenant'
      ? 'Your own token'
      : source === 'platform'
        ? 'Platform token, provided by Batchivo'
        : 'Not connected'

  const platformNote = !settings.platform_token_available
    ? 'No platform token is configured on this server.'
    : settings.platform_token_allowed
      ? 'The platform token is available to this shop.'
      : 'A platform token exists, but it is not enabled for this shop.'

  const save = () => {
    const value = token.trim()
    if (!value) return
    update.mutate({ api_token: value }, { onSuccess: () => setToken('') })
  }

  const remove = () => update.mutate({ api_token: '' })

  const testResult = test.data
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Sparkles className="h-5 w-5" />
          Replicate connection
        </CardTitle>
        <CardDescription>
          Generative AI runs on Replicate with your token, or with the platform's when Batchivo
          provides one.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted-foreground">Token in use:</span>
          <Badge variant={source === 'none' ? 'secondary' : 'default'}>{sourceLabel}</Badge>
        </div>
        <p className="text-sm text-muted-foreground">{platformNote}</p>

        <div className="space-y-2">
          <Label htmlFor="replicate-token">Your Replicate token</Label>
          {settings.is_configured && settings.token_masked ? (
            <p className="text-sm">
              Saved token:{' '}
              <code className="rounded bg-muted px-2 py-1">{settings.token_masked}</code>
            </p>
          ) : (
            <p className="text-sm text-muted-foreground">No token of your own is saved.</p>
          )}
          <div className="flex flex-wrap gap-2">
            <Input
              id="replicate-token"
              type="password"
              autoComplete="off"
              placeholder={settings.is_configured ? 'Paste a new token to replace it' : 'r8_…'}
              value={token}
              onChange={(e) => setToken(e.target.value)}
              className="max-w-sm"
            />
            <Button onClick={save} disabled={!token.trim() || update.isPending}>
              Save token
            </Button>
            {settings.is_configured && (
              <Button variant="outline" onClick={remove} disabled={update.isPending}>
                Remove token
              </Button>
            )}
          </div>
          <ErrorLine error={update.error} />
        </div>

        <div className="space-y-2">
          <Button variant="outline" onClick={() => test.mutate()} disabled={test.isPending}>
            {test.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
            ) : (
              <TestTube2 className="mr-2 h-4 w-4" />
            )}
            Test connection
          </Button>
          {testResult && (
            <Alert variant={testResult.success ? 'default' : 'destructive'}>
              {testResult.success ? (
                <CheckCircle2 className="h-4 w-4" />
              ) : (
                <AlertCircle className="h-4 w-4" />
              )}
              <AlertDescription>
                {testResult.success
                  ? `Connected${testResult.account ? ` as ${testResult.account}` : ''}.`
                  : testResult.message}
              </AlertDescription>
            </Alert>
          )}
          <ErrorLine error={test.error} />
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------- budget & usage

function BudgetSection({ settings }: { settings: ReplicateSettingsData }) {
  const update = useUpdateReplicateSettings()
  const { months } = useReplicateUsage(6)
  const [budget, setBudget] = useState(settings.monthly_budget ?? '')
  const [invalid, setInvalid] = useState<string | null>(null)

  const save = () => {
    const value = budget.trim()
    if (!BUDGET_PATTERN.test(value)) {
      setInvalid('Enter an amount in dollars, with at most two decimals (for example 25.00).')
      return
    }
    setInvalid(null)
    update.mutate({ monthly_budget: value })
  }

  const clear = () => {
    setInvalid(null)
    update.mutate({ clear_budget: true }, { onSuccess: () => setBudget('') })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Budget and usage</CardTitle>
        <CardDescription>
          A monthly cap in {settings.currency}. A request that would pass it is refused.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid gap-2 text-sm sm:grid-cols-3">
          <div>
            <span className="text-muted-foreground">Spent this month: </span>
            <span className="font-medium">{usd(settings.month_to_date)}</span>{' '}
            <span className="text-muted-foreground">{settings.currency}</span>
          </div>
          <div>
            <span className="text-muted-foreground">Jobs this month: </span>
            <span className="font-medium">{settings.jobs_this_month}</span>
          </div>
          <div>
            <span className="text-muted-foreground">Running: </span>
            <span className="font-medium">
              {settings.active_jobs} / {settings.concurrency_limit}
            </span>
          </div>
        </div>

        <div className="space-y-2">
          <Label htmlFor="replicate-budget">Monthly budget (USD)</Label>
          <p className="text-sm text-muted-foreground">
            Current budget:{' '}
            {settings.monthly_budget
              ? `${usd(settings.monthly_budget)} ${settings.currency}`
              : 'No limit'}
          </p>
          <div className="flex flex-wrap gap-2">
            <Input
              id="replicate-budget"
              inputMode="decimal"
              placeholder="25.00"
              value={budget}
              onChange={(e) => setBudget(e.target.value)}
              className="max-w-[12rem]"
            />
            <Button onClick={save} disabled={update.isPending}>
              Save budget
            </Button>
            <Button variant="outline" onClick={clear} disabled={update.isPending}>
              No limit
            </Button>
          </div>
          {invalid && (
            <p role="alert" className="text-sm text-destructive">
              {invalid}
            </p>
          )}
          <ErrorLine error={update.error} />
        </div>

        <div className="space-y-2">
          <h3 className="text-sm font-medium">Usage by month</h3>
          {months.length === 0 ? (
            <p className="text-sm text-muted-foreground">No usage yet.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Month</TableHead>
                  <TableHead>Cost (USD)</TableHead>
                  <TableHead>Jobs</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {months.map((row) => (
                  <TableRow key={row.month}>
                    <TableCell>{row.month}</TableCell>
                    <TableCell>{usd(row.cost)}</TableCell>
                    <TableCell>{row.jobs}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------- overrides

interface OverrideDraft {
  model_ref: string
  model_version: string
  price_unit: PriceUnit | ''
  price_usd: string
  typical_seconds: string
}

/** The reason a draft is refused, or null when it may be sent. */
function overrideProblem(draft: OverrideDraft): string | null {
  const ref = draft.model_ref.trim()
  const version = draft.model_version.trim()
  if (!MODEL_REF_PATTERN.test(ref)) return 'The model must read owner/name.'
  if (version.toLowerCase() === 'latest') {
    return '"latest" is not allowed: pin a version id (64 hex characters) or use "official".'
  }
  if (version !== 'official' && !VERSION_ID_PATTERN.test(version)) {
    return 'The version must be a 64-character version id, or "official".'
  }
  const price = draft.price_usd.trim()
  if (price && !PRICE_PATTERN.test(price)) {
    return 'The price must be an amount in dollars, with at most six decimals.'
  }
  if (price && !draft.price_unit) return 'Choose what the price is charged per.'
  const seconds = draft.typical_seconds.trim()
  if (price && draft.price_unit === 'per_second' && seconds) {
    if (!/^\d+$/.test(seconds) || +seconds < 1 || +seconds > 3600) {
      return 'The run time is a whole number of seconds, from 1 to 3600.'
    }
  }
  return null
}

function OverrideEditor({
  capability,
  current,
  onDone,
}: {
  capability: CapabilityInfo
  current: ReplicateModelOverride | undefined
  onDone: () => void
}) {
  const update = useUpdateReplicateSettings()
  const [draft, setDraft] = useState<OverrideDraft>({
    model_ref: current?.model_ref ?? capability.model_ref,
    model_version: current?.model_version ?? capability.model_version,
    price_unit: current?.price_unit ?? '',
    price_usd: current?.price_usd ?? '',
    typical_seconds: current?.typical_seconds ? String(current.typical_seconds) : '',
  })
  const [problem, setProblem] = useState<string | null>(null)

  const set = (field: keyof OverrideDraft) => (value: string) =>
    setDraft((d) => ({ ...d, [field]: value }))

  const save = () => {
    const reason = overrideProblem(draft)
    setProblem(reason)
    if (reason) return
    const price = draft.price_usd.trim()
    const override: ReplicateModelOverride = {
      model_ref: draft.model_ref.trim(),
      model_version: draft.model_version.trim(),
      price_unit: price && draft.price_unit ? draft.price_unit : null,
      price_usd: price || null,
      typical_seconds:
        price && draft.price_unit === 'per_second' && draft.typical_seconds.trim()
          ? Number(draft.typical_seconds.trim())
          : null,
    }
    const payload: ReplicateSettingsUpdate = {
      model_overrides: {
        [capability.capability]: override,
      } as ReplicateSettingsUpdate['model_overrides'],
    }
    update.mutate(payload, { onSuccess: onDone })
  }

  return (
    <div className="space-y-3 rounded-md border p-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-1">
          <Label htmlFor="override-model">Model</Label>
          <Input
            id="override-model"
            placeholder="owner/name"
            value={draft.model_ref}
            onChange={(e) => set('model_ref')(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="override-version">Version</Label>
          <Input
            id="override-version"
            placeholder="64-character id, or official"
            value={draft.model_version}
            onChange={(e) => set('model_version')(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="override-unit">Price unit</Label>
          <select
            id="override-unit"
            className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            value={draft.price_unit}
            onChange={(e) => set('price_unit')(e.target.value)}
          >
            <option value="">Default price</option>
            {(Object.keys(PRICE_UNIT_LABELS) as PriceUnit[]).map((unit) => (
              <option key={unit} value={unit}>
                {PRICE_UNIT_LABELS[unit]}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="override-price">Price (USD)</Label>
          <Input
            id="override-price"
            inputMode="decimal"
            placeholder="0.04"
            value={draft.price_usd}
            onChange={(e) => set('price_usd')(e.target.value)}
          />
        </div>
        {draft.price_unit === 'per_second' && (
          <div className="space-y-1">
            <Label htmlFor="override-seconds">Typical run time (seconds)</Label>
            <Input
              id="override-seconds"
              inputMode="numeric"
              placeholder="20"
              value={draft.typical_seconds}
              onChange={(e) => set('typical_seconds')(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Used to estimate a job. Left empty, the estimate assumes the longest a job can run.
            </p>
          </div>
        )}
      </div>
      {problem && (
        <p role="alert" className="text-sm text-destructive">
          {problem}
        </p>
      )}
      <ErrorLine error={update.error} />
      <div className="flex gap-2">
        <Button size="sm" onClick={save} disabled={update.isPending}>
          Save override
        </Button>
        <Button size="sm" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </div>
  )
}

function OverridesSection({ settings }: { settings: ReplicateSettingsData }) {
  const { capabilities } = useCapabilities()
  const clearMutation = useUpdateReplicateSettings()
  const [editing, setEditing] = useState<Capability | null>(null)

  const clear = (capability: Capability) =>
    clearMutation.mutate({
      model_overrides: { [capability]: null } as ReplicateSettingsUpdate['model_overrides'],
    })

  return (
    <Card>
      <CardHeader>
        <CardTitle>Models</CardTitle>
        <CardDescription>
          The model each capability runs, and its price. Override one to pin another model version;
          a version must be pinned, never "latest".
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Capability</TableHead>
              <TableHead>Model</TableHead>
              <TableHead>Price (USD)</TableHead>
              <TableHead className="text-right">Override</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {capabilities.map((cap) => {
              const override = settings.model_overrides[cap.capability]
              return (
                <TableRow key={cap.capability} data-testid={`override-row-${cap.capability}`}>
                  <TableCell className="font-medium">{cap.label}</TableCell>
                  <TableCell>
                    <div className="break-all font-mono text-xs">{cap.model_ref}</div>
                    <div className="break-all font-mono text-xs text-muted-foreground">
                      {cap.model_version}
                    </div>
                    {override && <Badge variant="outline">Overridden</Badge>}
                  </TableCell>
                  <TableCell>
                    {usd(cap.price.amount_usd)} {PRICE_UNIT_LABELS[cap.price.unit]}
                    {cap.price.assumed && (
                      <span className="block text-xs text-muted-foreground">assumed</span>
                    )}
                  </TableCell>
                  <TableCell className="space-x-2 text-right">
                    <Button
                      size="sm"
                      variant="outline"
                      aria-label={`Override ${cap.label}`}
                      onClick={() => setEditing(cap.capability)}
                    >
                      Override
                    </Button>
                    {override && (
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={`Clear override for ${cap.label}`}
                        onClick={() => clear(cap.capability)}
                        disabled={clearMutation.isPending}
                      >
                        Clear
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
        <ErrorLine error={clearMutation.error} />
        {editing &&
          (() => {
            const cap = capabilities.find((c) => c.capability === editing)
            if (!cap) return null
            return (
              <div className="space-y-2">
                <h3 className="text-sm font-medium">Override {cap.label}</h3>
                <OverrideEditor
                  key={editing}
                  capability={cap}
                  current={settings.model_overrides[editing]}
                  onDone={() => setEditing(null)}
                />
              </div>
            )
          })()}
      </CardContent>
    </Card>
  )
}

// ---------------------------------------------------------------------- panel

export function ReplicateSettings() {
  const { settings, isLoading, error } = useReplicateSettings()

  if (isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin" />
        </CardContent>
      </Card>
    )
  }

  if (error || !settings) {
    return (
      <Alert variant="destructive">
        <AlertCircle className="h-4 w-4" />
        <AlertDescription>
          {genaiError(error)?.message ?? 'The AI settings could not be loaded.'}
        </AlertDescription>
      </Alert>
    )
  }

  return (
    <div className="space-y-6">
      <TokenSection settings={settings} />
      <BudgetSection settings={settings} />
      <OverridesSection settings={settings} />
    </div>
  )
}
