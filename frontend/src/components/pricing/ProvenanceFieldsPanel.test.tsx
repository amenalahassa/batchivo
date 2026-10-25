/**
 * The inputs behind a cost, reachable from the breakdown (T259, US6/AC1).
 *
 * `getProvenance` and `putProvenance` had no caller, so an operator could not
 * see a figure's confidence or re-confirm a stale measurement without
 * changing a value that was still right.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { ProvenanceFieldsPanel } from './ProvenanceFieldsPanel'
import { getProvenance, putProvenance } from '@/lib/api/pricing'
import type { EntityProvenance, FieldOrigin } from '@/types/pricing'

vi.mock('@/lib/api/pricing', () => ({
  pricingApi: {},
  getProvenance: vi.fn(),
  putProvenance: vi.fn(),
}))

const read = vi.mocked(getProvenance)
const write = vi.mocked(putProvenance)

function field(overrides: Partial<FieldOrigin> = {}): FieldOrigin {
  return {
    field_name: 'print_time_minutes',
    source: 'observed',
    as_of: '2026-10-20',
    confidence: '0.8333',
    is_default: false,
    is_stale: false,
    editable: false,
    has_pending_revision: false,
    description: 'Plate print time',
    ...overrides,
  }
}

function provenance(fields: FieldOrigin[]): EntityProvenance {
  return {
    entity_type: 'model',
    entity_id: 'model-1',
    fields,
    observed_count: fields.filter((f) => f.source === 'observed').length,
    total_count: fields.length,
    stale_count: fields.filter((f) => f.is_stale).length,
    staleness_threshold_days: 180,
  }
}

function renderPanel(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>)
}

describe('ProvenanceFieldsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('lists each input with its origin and how far to believe it', async () => {
    read.mockResolvedValue(provenance([field()]))
    renderPanel(<ProvenanceFieldsPanel entityType="model" entityId="model-1" />)

    const row = within(await screen.findByTestId('provenance-field-print_time_minutes'))
    expect(row.getByText('Plate print time')).toBeInTheDocument()
    expect(row.getByTestId('provenance-confidence')).toHaveTextContent('83% confidence')
    expect(read).toHaveBeenCalledWith('model', 'model-1')
  })

  it('re-confirms a stale measurement as it stands, dated today', async () => {
    const user = userEvent.setup()
    read.mockResolvedValue(
      provenance([
        field({
          field_name: 'waste_grams',
          source: 'measured',
          as_of: '2025-01-01',
          confidence: null,
          is_stale: true,
          editable: true,
          description: 'Purge waste',
        }),
      ]),
    )
    write.mockResolvedValue(field({ field_name: 'waste_grams', source: 'measured' }))
    renderPanel(<ProvenanceFieldsPanel entityType="model" entityId="model-1" />)

    await user.click(await screen.findByRole('button', { name: /Still correct/ }))

    await waitFor(() => expect(write).toHaveBeenCalled())
    const [entityType, entityId, fieldName, body] = write.mock.calls[0]
    expect([entityType, entityId, fieldName]).toEqual(['model', 'model-1', 'waste_grams'])
    expect(body.source).toBe('measured')
    expect(body.as_of).toBe(new Date().toISOString().slice(0, 10))
    // Only the origin moves; no value is sent.
    expect(Object.keys(body).sort()).toEqual(['as_of', 'source'])
  })

  it('offers no re-confirmation for an observed figure, which its source refreshes', async () => {
    read.mockResolvedValue(provenance([field()]))
    renderPanel(<ProvenanceFieldsPanel entityType="model" entityId="model-1" />)

    await screen.findByTestId('provenance-field-print_time_minutes')
    expect(screen.queryByRole('button', { name: /Still correct/ })).not.toBeInTheDocument()
  })
})
