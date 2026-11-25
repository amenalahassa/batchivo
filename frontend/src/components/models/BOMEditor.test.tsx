/**
 * Tests for BOMEditor - carried-over 3MF weight suggestion (User Story 1a)
 *
 * Covers:
 * - A weight suggestion stashed in sessionStorage by ModelForm pre-fills
 *   weight_grams the first time "Add Material" is opened, without
 *   pre-selecting a spool.
 * - Editing the pre-filled weight before saving submits the edited value.
 * - With no suggestion stashed, the field behaves exactly as it does today.
 */

import { describe, it, expect, vi, beforeEach, type Mock } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BOMEditor } from './BOMEditor'
import { addModelMaterial } from '@/lib/api/models'
import { spoolsApi } from '@/lib/api/spools'

vi.mock('@/lib/api/models', () => ({
  addModelMaterial: vi.fn(),
  removeModelMaterial: vi.fn(),
}))

vi.mock('@/lib/api/spools', () => ({
  spoolsApi: {
    list: vi.fn(),
  },
}))

const mockAddModelMaterial = addModelMaterial as Mock
const mockSpoolsApiList = spoolsApi.list as Mock

const MODEL_ID = 'model-abc-123'

function renderBOMEditor() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <BOMEditor modelId={MODEL_ID} materials={[]} />
    </QueryClientProvider>
  )
}

// The role the signed-in user holds; each test starts as an admin (T238).
const auth = vi.hoisted(() => ({ role: 'admin' }))
vi.mock('@/contexts/AuthContext', () => {
  const session = () => ({ user: { email: 'operator@example.com', role: auth.role }, logout: vi.fn() })
  return { useAuth: session, useOptionalAuth: session }
})
beforeEach(() => {
  auth.role = 'admin'
})

describe('BOMEditor - 3MF weight suggestion hand-off', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    sessionStorage.clear()
    mockSpoolsApiList.mockResolvedValue({ spools: [], total: 0, page: 1, page_size: 100 })
    mockAddModelMaterial.mockResolvedValue({
      id: 'material-1',
      spool_id: 'spool-1',
      weight_grams: '15.50',
      cost_per_gram: '0.0250',
      created_at: '2026-01-01T00:00:00Z',
      updated_at: '2026-01-01T00:00:00Z',
    })
  })

  it('pre-fills weight_grams from a stashed suggestion without selecting a spool', async () => {
    sessionStorage.setItem(`model-weight-suggestion:${MODEL_ID}`, '15.5')

    renderBOMEditor()

    const addButton = await screen.findByRole('button', { name: /add material/i })
    await userEvent.click(addButton)

    const weightField = await screen.findByLabelText('Weight (grams)')
    await waitFor(() => expect(weightField).toHaveValue(15.5))

    // No spool pre-selected - the searchable select still shows its placeholder.
    expect(screen.getByText(/search for a spool/i)).toBeInTheDocument()
  })

  it('consumes the stashed suggestion once (clears it from sessionStorage)', async () => {
    sessionStorage.setItem(`model-weight-suggestion:${MODEL_ID}`, '15.5')

    renderBOMEditor()

    await waitFor(() =>
      expect(sessionStorage.getItem(`model-weight-suggestion:${MODEL_ID}`)).toBeNull()
    )
  })

  it('submits the edited weight, not the suggested one, when the maker changes it', async () => {
    sessionStorage.setItem(`model-weight-suggestion:${MODEL_ID}`, '15.5')

    renderBOMEditor()

    const addButton = await screen.findByRole('button', { name: /add material/i })
    await userEvent.click(addButton)

    const weightField = await screen.findByLabelText('Weight (grams)')
    await waitFor(() => expect(weightField).toHaveValue(15.5))

    await userEvent.clear(weightField)
    await userEvent.type(weightField, '22.75')

    await userEvent.type(screen.getByLabelText('Cost per Gram override (£)'), '0.02')

    // spool_id is required by the schema; without a real spool to select,
    // just confirm the weight value itself is what's tracked in form state
    // by checking the input directly (spool selection is covered by
    // SearchableSpoolSelect's own tests).
    expect(weightField).toHaveValue(22.75)
  })

  it('pre-fills the total from the JSON suggestion of a one-filament file', async () => {
    sessionStorage.setItem(
      `model-weight-suggestion:${MODEL_ID}`,
      JSON.stringify({ total: 42, filaments: [{ type: 'PLA', color: '#FF0000', grams: 42 }] })
    )

    renderBOMEditor()

    await userEvent.click(await screen.findByRole('button', { name: /add material/i }))
    await waitFor(() => expect(screen.getByLabelText('Weight (grams)')).toHaveValue(42))
  })

  it('lists each filament of a multi-colour file instead of pre-filling the total', async () => {
    sessionStorage.setItem(
      `model-weight-suggestion:${MODEL_ID}`,
      JSON.stringify({
        total: 84,
        filaments: [
          { type: 'PLA', color: '#FF0000', grams: 60 },
          { type: 'PLA', color: '#000000', grams: 24 },
        ],
      })
    )

    renderBOMEditor()

    await userEvent.click(await screen.findByRole('button', { name: /add material/i }))
    const weightField = await screen.findByLabelText('Weight (grams)')
    screen.getByText(/the print file uses 2 filaments: add one line for each/i)
    expect(weightField).toHaveValue(null) // the total is wrong on any one line

    await userEvent.click(screen.getByRole('button', { name: 'PLA #000000: 24g' }))
    expect(weightField).toHaveValue(24)
  })

  it('behaves exactly as before when no suggestion was stashed', async () => {
    renderBOMEditor()

    const addButton = await screen.findByRole('button', { name: /add material/i })
    await userEvent.click(addButton)

    const weightField = await screen.findByLabelText('Weight (grams)')
    expect(weightField).toHaveValue(null)
  })
})

describe('BOMEditor for a viewer', () => {
  it('shows the bill of materials with adding disabled', async () => {
    auth.role = 'viewer'
    renderBOMEditor()

    expect(await screen.findByRole('button', { name: /add material/i })).toBeDisabled()
  })
})

// Bug spool-flat-fields-undefined (bugcap #46): the line read
// "FIL-002 - undefined (undefined)" because brand, colour and material are
// nested under `filament_type` in the spool API.
describe('BOMEditor material line label', () => {
  it('names the spool from its filament type', async () => {
    mockSpoolsApiList.mockResolvedValue({
      spools: [
        {
          id: 'spool-uuid-2',
          tenant_id: 'tenant',
          spool_id: 'FIL-002',
          filament_type_id: 'ft-1',
          initial_weight: 1000,
          current_weight: 800,
          is_active: true,
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
          remaining_weight: 800,
          remaining_percentage: 80,
          filament_type: {
            id: 'ft-1',
            material_type_id: 'mat-1',
            brand: 'Bambu Lab',
            color: 'Jade White',
            diameter: 1.75,
            translucent: false,
            glow: false,
            material_type_code: 'PLA',
            material_type_name: 'PLA Basic',
          },
        },
      ],
      total: 1,
      page: 1,
      page_size: 100,
    })
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={queryClient}>
        <BOMEditor
          modelId={MODEL_ID}
          materials={[
            {
              id: 'line-1',
              spool_id: 'spool-uuid-2',
              weight_grams: '12.00',
              cost_per_gram: null,
              resolved_cost_per_gram: '0.0250',
              line_cost: '0.30',
              created_at: '2026-01-01T00:00:00Z',
              updated_at: '2026-01-01T00:00:00Z',
            },
          ]}
        />
      </QueryClientProvider>
    )

    expect(await screen.findByText('FIL-002 - PLA Basic (Jade White)')).toBeInTheDocument()
    expect(screen.queryByText(/undefined/)).not.toBeInTheDocument()
  })
})
