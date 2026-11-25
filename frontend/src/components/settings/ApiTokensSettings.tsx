/**
 * ApiTokensSettings — personal API tokens for scripts and AI agents (spec 010).
 *
 * Create a token (name, scopes, mandatory expiry of at most one year), see its
 * secret once, list tokens with their last use and status, revoke one.
 */

import { useState } from 'react'
import { AlertCircle, Check, Copy, KeyRound, Loader2, Plus } from 'lucide-react'

import { useApiTokens } from '@/hooks/useApiTokens'
import type { ApiToken, ApiTokenCreated, ApiTokenScope, ApiTokenStatus } from '@/types/apiToken'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

const SCOPES: { value: ApiTokenScope; label: string; help: string }[] = [
  { value: 'read', label: 'Read', help: 'Read ideas, models, notes, printers, spools and jobs' },
  { value: 'write', label: 'Write', help: 'Create and change ideas, models and notes' },
  { value: 'genai', label: 'AI generation', help: 'Start and adopt AI generations' },
  {
    value: 'print',
    label: 'Print',
    help: 'Prepare and start prints on your printers (always asks before starting)',
  },
]

type ExpiryChoice = '30' | '90' | '365' | 'custom'

const DAY_MS = 24 * 60 * 60 * 1000

function isoDate(date: Date): string {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

/** Expiry as an ISO datetime: N days from now, or the end of a chosen local day. */
function expiryFromChoice(choice: ExpiryChoice, customDate: string, now = new Date()): string {
  if (choice !== 'custom') return new Date(now.getTime() + Number(choice) * DAY_MS).toISOString()
  const [y, m, d] = customDate.split('-').map(Number)
  return new Date(y, m - 1, d, 23, 59, 59).toISOString()
}

const STATUS_VARIANT: Record<ApiTokenStatus, 'success' | 'secondary' | 'destructive'> = {
  active: 'success',
  expired: 'secondary',
  revoked: 'destructive',
}

function formatDate(value: string | null): string {
  if (!value) return ''
  return new Date(value).toLocaleString()
}

export function ApiTokensSettings() {
  const { tokens, isLoading, error, createToken, isCreating, revokeToken, isRevoking } =
    useApiTokens()
  const [createOpen, setCreateOpen] = useState(false)
  const [created, setCreated] = useState<ApiTokenCreated | null>(null)
  const [toRevoke, setToRevoke] = useState<ApiToken | null>(null)

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4">
        <div className="space-y-1.5">
          <CardTitle className="flex items-center gap-2">
            <KeyRound className="h-5 w-5" />
            API tokens
          </CardTitle>
          <CardDescription>
            Personal tokens let scripts and AI agents (such as Claude Code through the Batchivo MCP
            server) work with your shop, with your permissions and only the scopes you choose.
          </CardDescription>
        </div>
        <Button onClick={() => setCreateOpen(true)} className="gap-2">
          <Plus className="h-4 w-4" />
          Create token
        </Button>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="flex items-center gap-2 text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading tokens…
          </div>
        ) : error ? (
          <div className="flex items-center gap-2 text-destructive">
            <AlertCircle className="h-4 w-4" /> Could not load your tokens.
          </div>
        ) : tokens.length === 0 ? (
          <p className="text-sm text-muted-foreground">You have no API tokens yet.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Token</TableHead>
                <TableHead>Scopes</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Expires</TableHead>
                <TableHead>Last used</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-24" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {tokens.map((token) => (
                <TableRow key={token.id} data-testid={`api-token-row-${token.id}`}>
                  <TableCell className="font-medium">{token.name}</TableCell>
                  <TableCell className="font-mono text-xs">{token.token_prefix}…</TableCell>
                  <TableCell>{token.scopes.join(' · ')}</TableCell>
                  <TableCell>{formatDate(token.created_at)}</TableCell>
                  <TableCell>{formatDate(token.expires_at)}</TableCell>
                  <TableCell>{token.last_used_at ? formatDate(token.last_used_at) : 'Never used'}</TableCell>
                  <TableCell>
                    <Badge variant={STATUS_VARIANT[token.status]} className="capitalize">
                      {token.status}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    {token.status === 'active' && (
                      <Button variant="outline" size="sm" onClick={() => setToRevoke(token)}>
                        Revoke
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>

      <CreateTokenDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        isCreating={isCreating}
        onCreate={async (input) => {
          const result = await createToken(input)
          setCreateOpen(false)
          setCreated(result)
        }}
      />

      <SecretDialog created={created} onClose={() => setCreated(null)} />

      <AlertDialog open={toRevoke !== null} onOpenChange={(open) => !open && setToRevoke(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Revoke “{toRevoke?.name}”?</AlertDialogTitle>
            <AlertDialogDescription>
              Every script or agent using this token stops working at once. This cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              disabled={isRevoking}
              onClick={async () => {
                if (toRevoke) await revokeToken(toRevoke.id)
                setToRevoke(null)
              }}
            >
              Revoke token
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </Card>
  )
}

interface CreateTokenDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  isCreating: boolean
  onCreate: (input: { name: string; scopes: ApiTokenScope[]; expires_at: string }) => Promise<void>
}

function CreateTokenDialog({ open, onOpenChange, isCreating, onCreate }: CreateTokenDialogProps) {
  const [name, setName] = useState('')
  // `read` is pre-ticked; `print` never is (it is a separate opt-in, FR-015).
  const [scopes, setScopes] = useState<ApiTokenScope[]>(['read'])
  const [expiry, setExpiry] = useState<ExpiryChoice>('90')
  const [customDate, setCustomDate] = useState('')
  const [formError, setFormError] = useState<string | null>(null)

  const today = new Date()
  const minDate = isoDate(new Date(today.getTime() + DAY_MS))
  const maxDate = isoDate(new Date(today.getTime() + 364 * DAY_MS))

  const reset = () => {
    setName('')
    setScopes(['read'])
    setExpiry('90')
    setCustomDate('')
    setFormError(null)
  }

  const toggleScope = (scope: ApiTokenScope, checked: boolean) => {
    setScopes((current) =>
      checked ? [...current, scope] : current.filter((value) => value !== scope)
    )
  }

  const submit = async () => {
    const trimmed = name.trim()
    if (trimmed.length < 1 || trimmed.length > 100) {
      setFormError('Give the token a name (1 to 100 characters).')
      return
    }
    if (scopes.length === 0) {
      setFormError('Choose at least one scope.')
      return
    }
    if (expiry === 'custom' && (!customDate || customDate < minDate || customDate > maxDate)) {
      setFormError('Choose an expiry date between tomorrow and one year from now.')
      return
    }
    setFormError(null)
    try {
      await onCreate({ name: trimmed, scopes, expires_at: expiryFromChoice(expiry, customDate) })
      reset()
    } catch {
      setFormError('The token could not be created. Check the fields and try again.')
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset()
        onOpenChange(next)
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create an API token</DialogTitle>
          <DialogDescription>
            The token acts as you in this shop, limited to the scopes you choose.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="api-token-name">Name</Label>
            <Input
              id="api-token-name"
              value={name}
              maxLength={100}
              placeholder="Claude Code – modelling PC"
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">Scopes</legend>
            {SCOPES.map((scope) => (
              <div key={scope.value} className="flex items-start gap-2">
                <Checkbox
                  id={`api-token-scope-${scope.value}`}
                  checked={scopes.includes(scope.value)}
                  onCheckedChange={(checked) => toggleScope(scope.value, checked === true)}
                />
                <div className="grid gap-0.5 leading-none">
                  <Label htmlFor={`api-token-scope-${scope.value}`}>{scope.label}</Label>
                  <p className="text-xs text-muted-foreground">{scope.help}</p>
                </div>
              </div>
            ))}
          </fieldset>
          <div className="space-y-2">
            <Label htmlFor="api-token-expiry">Expires</Label>
            <Select value={expiry} onValueChange={(value) => setExpiry(value as ExpiryChoice)}>
              <SelectTrigger id="api-token-expiry" aria-label="Expiry">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="30">In 30 days</SelectItem>
                <SelectItem value="90">In 90 days</SelectItem>
                <SelectItem value="365">In 1 year</SelectItem>
                <SelectItem value="custom">On a date…</SelectItem>
              </SelectContent>
            </Select>
            {expiry === 'custom' && (
              <Input
                type="date"
                aria-label="Expiry date"
                min={minDate}
                max={maxDate}
                value={customDate}
                onChange={(event) => setCustomDate(event.target.value)}
              />
            )}
          </div>
          {formError && (
            <p role="alert" className="text-sm text-destructive">
              {formError}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={isCreating}>
            {isCreating && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Create token
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function SecretDialog({
  created,
  onClose,
}: {
  created: ApiTokenCreated | null
  onClose: () => void
}) {
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    if (!created) return
    try {
      await navigator.clipboard.writeText(created.token)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <Dialog
      open={created !== null}
      onOpenChange={(open) => {
        if (!open) {
          setCopied(false)
          onClose()
        }
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Copy your new token</DialogTitle>
          <DialogDescription>
            This is the only time the token is shown. Store it now, for example in the
            BATCHIVO_API_TOKEN environment variable. It will not be shown again.
          </DialogDescription>
        </DialogHeader>
        {created && (
          <div className="flex items-center gap-2">
            <Input readOnly value={created.token} aria-label="New API token" className="font-mono text-xs" />
            <Button variant="outline" size="icon" onClick={copy} aria-label="Copy token">
              {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
            </Button>
          </div>
        )}
        <DialogFooter>
          <Button
            onClick={() => {
              setCopied(false)
              onClose()
            }}
          >
            I have stored it
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
