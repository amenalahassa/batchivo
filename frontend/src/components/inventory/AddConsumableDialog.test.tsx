/**
 * The consumable cost per unit crosses the wire as a decimal string (T210).
 *
 * `current_cost_per_unit` is read by the costing engine for a linked
 * packaging consumable, and the backend schema takes a `Decimal`. This dialog
 * sent it through `parseFloat`, a JSON number, while the type declares it
 * `Money`.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { AddConsumableDialog } from './AddConsumableDialog'
import { consumablesApi } from '@/lib/api/consumables'

// Radix Select's hidden native <select> reports an empty value in jsdom and
// blanks the material type before submit; a native select stands in for it.
vi.mock('@/components/ui/select', () => ({
  Select: ({ children, onValueChange, value }: { children: ReactNode; onValueChange?: (v: string) => void; value?: string }) => (
    <select value={value ?? ''} onChange={(e) => onValueChange?.(e.target.value)}>
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

vi.mock('@/hooks/useSKU', () => ({
  useNextSKU: () => ({ nextSKU: 'COM-001', isLoading: false, refetch: vi.fn() }),
}))

vi.mock('@/lib/api/consumables', () => ({
  consumablesApi: {
    create: vi.fn(),
  },
}))

const api = vi.mocked(consumablesApi)

function renderDialog(node: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>)
}

async function fillRequired() {
  await waitFor(() => expect(screen.getByLabelText(/^sku/i)).toHaveValue('COM-001'))
  fireEvent.change(screen.getByLabelText(/^name/i), { target: { value: 'Magnet 3x1' } })
}

describe('AddConsumableDialog cost per unit', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.create.mockResolvedValue({} as never)
    vi.spyOn(window, 'alert').mockImplementation(() => {})
  })

  it('sends the typed cost as a decimal string, never a number', async () => {
    renderDialog(<AddConsumableDialog open onOpenChange={() => {}} />)
    await fillRequired()

    fireEvent.change(screen.getByLabelText('Cost per Unit'), { target: { value: '0.0450' } })
    fireEvent.click(screen.getByRole('button', { name: /create consumable/i }))

    await waitFor(() => expect(api.create).toHaveBeenCalled())
    const sent = api.create.mock.calls[0][0]
    // A double would have arrived as 0.045, its trailing digit and its type gone.
    expect(sent.current_cost_per_unit).toBe('0.0450')
    expect(typeof sent.current_cost_per_unit).toBe('string')
  })

  it('sends no cost when none was typed', async () => {
    renderDialog(<AddConsumableDialog open onOpenChange={() => {}} />)
    await fillRequired()

    fireEvent.click(screen.getByRole('button', { name: /create consumable/i }))

    await waitFor(() => expect(api.create).toHaveBeenCalled())
    expect(api.create.mock.calls[0][0].current_cost_per_unit).toBeUndefined()
  })
})
