/**
 * Settings > API tokens (spec 010, US1).
 *
 * Lists tokens with their status and last use, creates one (name, scopes,
 * expiry), shows the secret once, and revokes after a confirmation.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { ApiTokensSettings } from './ApiTokensSettings'
import { apiTokensApi } from '@/lib/api/apiTokens'
import type { ApiToken, ApiTokenCreated } from '@/types/apiToken'

vi.mock('@/lib/api/apiTokens', () => ({
  apiTokensApi: { list: vi.fn(), create: vi.fn(), revoke: vi.fn() },
}))
vi.mock('@/components/ui/select', () => ({
  Select: ({
    children,
    onValueChange,
    value,
  }: {
    children: ReactNode
    onValueChange?: (v: string) => void
    value?: string
  }) => (
    <select aria-label="Expiry" value={value ?? ''} onChange={(e) => onValueChange?.(e.target.value)}>
      {children}
    </select>
  ),
  SelectTrigger: () => null,
  SelectValue: () => null,
  SelectContent: ({ children }: { children: ReactNode }) => <>{children}</>,
  SelectItem: ({ value, children }: { value: string; children: ReactNode }) => (
    <option value={value}>{children}</option>
  ),
}))

const api = vi.mocked(apiTokensApi)

function token(overrides: Partial<ApiToken> = {}): ApiToken {
  return {
    id: 't1',
    name: 'Claude Code',
    token_prefix: 'bvt_abcdefgh',
    scopes: ['read', 'write'],
    created_at: '2026-11-20T10:00:00Z',
    expires_at: '2027-02-18T10:00:00Z',
    last_used_at: null,
    revoked_at: null,
    status: 'active',
    ...overrides,
  }
}

const SECRET = 'bvt_abcdefgh_' + 's'.repeat(43)

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ApiTokensSettings />
    </QueryClientProvider>
  )
}

describe('ApiTokensSettings', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('lists tokens with prefix, scopes, last use and status, never a secret', async () => {
    api.list.mockResolvedValue({
      items: [
        token(),
        token({ id: 't2', name: 'Old', status: 'expired', last_used_at: '2026-11-21T09:00:00Z' }),
        token({ id: 't3', name: 'Gone', status: 'revoked', revoked_at: '2026-11-22T09:00:00Z' }),
      ],
      total: 3,
    })
    renderPanel()

    const row = await screen.findByTestId('api-token-row-t1')
    expect(within(row).getByText('Claude Code')).toBeInTheDocument()
    expect(within(row).getByText('bvt_abcdefgh…')).toBeInTheDocument()
    expect(within(row).getByText('read · write')).toBeInTheDocument()
    expect(within(row).getByText('Never used')).toBeInTheDocument()
    expect(within(row).getByText('active')).toBeInTheDocument()
    expect(within(row).getByRole('button', { name: 'Revoke' })).toBeInTheDocument()

    const expired = screen.getByTestId('api-token-row-t2')
    expect(within(expired).getByText('expired')).toBeInTheDocument()
    expect(within(expired).queryByRole('button', { name: 'Revoke' })).toBeNull()
    expect(within(screen.getByTestId('api-token-row-t3')).getByText('revoked')).toBeInTheDocument()
  })

  it('shows an empty state', async () => {
    api.list.mockResolvedValue({ items: [], total: 0 })
    renderPanel()
    expect(await screen.findByText('You have no API tokens yet.')).toBeInTheDocument()
  })

  it('pre-ticks read, never print, and validates name and scopes', async () => {
    api.list.mockResolvedValue({ items: [], total: 0 })
    const user = userEvent.setup()
    renderPanel()
    await user.click(await screen.findByRole('button', { name: /create token/i }))

    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('checkbox', { name: 'Read' })).toBeChecked()
    expect(within(dialog).getByRole('checkbox', { name: 'Print' })).not.toBeChecked()

    await user.click(within(dialog).getByRole('button', { name: 'Create token' }))
    expect(within(dialog).getByRole('alert')).toHaveTextContent('Give the token a name')

    await user.type(within(dialog).getByLabelText('Name'), 'Agent')
    await user.click(within(dialog).getByRole('checkbox', { name: 'Read' }))
    await user.click(within(dialog).getByRole('button', { name: 'Create token' }))
    expect(within(dialog).getByRole('alert')).toHaveTextContent('at least one scope')
    expect(api.create).not.toHaveBeenCalled()
  })

  it('creates a token, shows the secret once, then forgets it', async () => {
    api.list.mockResolvedValue({ items: [], total: 0 })
    const created: ApiTokenCreated = { ...token({ name: 'Agent', scopes: ['print', 'read'] }), token: SECRET }
    api.create.mockResolvedValue(created)
    const user = userEvent.setup()
    renderPanel()
    await user.click(await screen.findByRole('button', { name: /create token/i }))

    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('Name'), '  Agent  ')
    await user.click(within(dialog).getByRole('checkbox', { name: 'Print' }))
    await user.selectOptions(within(dialog).getByLabelText('Expiry'), '30')
    const before = Date.now()
    await user.click(within(dialog).getByRole('button', { name: 'Create token' }))

    await waitFor(() => expect(api.create).toHaveBeenCalledTimes(1))
    const input = api.create.mock.calls[0][0]
    expect(input.name).toBe('Agent')
    expect(input.scopes).toEqual(['read', 'print'])
    const days = (new Date(input.expires_at).getTime() - before) / (24 * 3600 * 1000)
    expect(days).toBeGreaterThan(29.9)
    expect(days).toBeLessThan(30.1)

    const secretInput = await screen.findByLabelText('New API token')
    expect(secretInput).toHaveValue(SECRET)
    expect(screen.getByText(/will not be shown again/i)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'I have stored it' }))
    await waitFor(() => expect(screen.queryByLabelText('New API token')).toBeNull())
    expect(screen.queryByDisplayValue(SECRET)).toBeNull()
  })

  it('refuses a custom date beyond one year', async () => {
    api.list.mockResolvedValue({ items: [], total: 0 })
    const user = userEvent.setup()
    renderPanel()
    await user.click(await screen.findByRole('button', { name: /create token/i }))
    const dialog = await screen.findByRole('dialog')
    await user.type(within(dialog).getByLabelText('Name'), 'Agent')
    await user.selectOptions(within(dialog).getByLabelText('Expiry'), 'custom')
    const date = within(dialog).getByLabelText('Expiry date')
    await user.type(date, '2099-01-01')
    await user.click(within(dialog).getByRole('button', { name: 'Create token' }))
    expect(within(dialog).getByRole('alert')).toHaveTextContent('one year')
    expect(api.create).not.toHaveBeenCalled()
  })

  it('revokes only after confirmation', async () => {
    api.list.mockResolvedValue({ items: [token()], total: 1 })
    api.revoke.mockResolvedValue(token({ status: 'revoked' }))
    const user = userEvent.setup()
    renderPanel()

    await user.click(await screen.findByRole('button', { name: 'Revoke' }))
    const confirm = await screen.findByRole('alertdialog')
    expect(within(confirm).getByText(/cannot be undone/i)).toBeInTheDocument()
    expect(api.revoke).not.toHaveBeenCalled()

    await user.click(within(confirm).getByRole('button', { name: 'Revoke token' }))
    await waitFor(() => expect(api.revoke).toHaveBeenCalledWith('t1'))
  })
})
