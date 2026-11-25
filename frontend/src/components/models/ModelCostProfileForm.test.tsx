/**
 * ModelCostProfileForm tests.
 *
 * The assertion this component exists for: the figures that decide what
 * printing costs can be *entered*. Before T147 they were columns the engine
 * read and nothing could write, so every item in every tenant was costed as
 * though nothing is purged and nothing ever fails — the superseded model's
 * answer, reached by having no form at all.
 *
 * The rest follows from that: a blank field must not erase a figure recorded
 * earlier, an observed figure must not be typeable over (FR-004), every figure
 * must show where it came from (FR-001), and a viewer must meet the controls
 * present and disabled rather than gone (FR-007c).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { ModelCostProfileForm } from './ModelCostProfileForm'
import { pricingApi } from '@/lib/api/pricing'
import type { CostProfileFieldOrigin, ModelCostProfile } from '@/types/pricing'

vi.mock('@/lib/api/printers', () => ({
  getActivePrinters: vi.fn().mockResolvedValue([
    { id: 'printer-x1', name: 'Bambu X1C' },
    { id: 'printer-a1', name: 'Bambu A1 Mini' },
  ]),
}))

vi.mock('@/lib/api/pricing', () => ({
  pricingApi: {
    getModelCostProfile: vi.fn(),
    updateModelCostProfile: vi.fn(),
  },
}))

const mocked = vi.mocked(pricingApi)
const MODEL_ID = 'model-1'

const PROFILE_FIELDS = [
  'print_time_minutes',
  'prints_per_plate',
  'waste_grams',
  'expected_yield',
  'labor_hours_per_plate',
  'labor_hours_per_item',
  'finishing_hours_per_item',
  'packing_hours_per_item',
] as const

function origins(overrides: Record<string, Partial<CostProfileFieldOrigin>> = {}) {
  return PROFILE_FIELDS.map((field_name) => ({
    field_name,
    source: 'assumed' as const,
    as_of: null,
    is_stale: false,
    editable: true,
    ...(overrides[field_name] ?? {}),
  }))
}

/** The golden case's item: 3 g purge, 92% yield, 15 min at risk, 5 min packing. */
function configured(overrides: Partial<ModelCostProfile> = {}): ModelCostProfile {
  return {
    model_id: MODEL_ID,
    print_time_minutes: 570,
    planned_printer_id: null,
    planned_printer_name: null,
    prints_per_plate: 1,
    waste_grams: '3.00',
    expected_yield: '0.9200',
    failure_mode: 'per_part',
    labor_hours_per_plate: '0.250',
    labor_hours_per_item: '0.000',
    finishing_hours_per_item: '0.000',
    packing_hours_per_item: '0.083',
    origins: origins({
      waste_grams: { source: 'measured', as_of: '2026-10-01' },
      expected_yield: { source: 'observed', as_of: '2026-10-10', editable: false },
    }),
    incomplete_reasons: [],
    ...overrides,
  }
}

/** An item nobody has measured: every figure at its migration default. */
function unmeasured(): ModelCostProfile {
  return {
    model_id: MODEL_ID,
    print_time_minutes: null,
    planned_printer_id: null,
    planned_printer_name: null,
    prints_per_plate: 1,
    waste_grams: '0.00',
    expected_yield: '1.0000',
    failure_mode: 'per_part',
    labor_hours_per_plate: '0.000',
    labor_hours_per_item: '0.000',
    finishing_hours_per_item: '0.000',
    packing_hours_per_item: '0.000',
    origins: origins(),
    incomplete_reasons: [
      'No print time recorded, so machine occupancy and overhead cannot be costed (FR-010)',
    ],
  }
}

function renderForm(node: ReactNode) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>)
}

describe('ModelCostProfileForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocked.getModelCostProfile.mockResolvedValue(configured())
    mocked.updateModelCostProfile.mockResolvedValue(configured())
  })

  it('loads the figures already recorded', async () => {
    renderForm(<ModelCostProfileForm modelId={MODEL_ID} />)

    await waitFor(() => {
      expect(screen.getByLabelText(/Plate print time/)).toHaveValue('570')
    })
    expect(screen.getByLabelText(/Purge and priming/)).toHaveValue('3.00')
    expect(screen.getByLabelText(/Plate setup/)).toHaveValue('0.250')
    expect(screen.getByLabelText(/Packing per part/)).toHaveValue('0.083')
  })

  it('sends only the figures the operator filled in', async () => {
    // FR-002's practical form: a blank field is "not entered", so saving a
    // finishing time must not erase the purge weight measured last week.
    mocked.getModelCostProfile.mockResolvedValue(
      configured({ waste_grams: '', finishing_hours_per_item: '' }),
    )
    renderForm(<ModelCostProfileForm modelId={MODEL_ID} />)

    await waitFor(() => {
      expect(screen.getByLabelText(/Finishing per part/)).toHaveValue('')
    })
    await userEvent.type(screen.getByLabelText(/Finishing per part/), '0.100')
    await userEvent.click(screen.getByRole('button', { name: /Save cost profile/ }))

    await waitFor(() => {
      expect(mocked.updateModelCostProfile).toHaveBeenCalled()
    })
    const [, changes] = mocked.updateModelCostProfile.mock.calls[0]
    expect(changes.finishing_hours_per_item).toBe('0.100')
    expect(changes).not.toHaveProperty('waste_grams')
  })

  it('shows where each figure came from', async () => {
    // FR-001: a cost nobody can weigh is a cost nobody can defend.
    renderForm(<ModelCostProfileForm modelId={MODEL_ID} />)

    await waitFor(() => {
      expect(screen.getByLabelText(/Purge and priming/)).toBeInTheDocument()
    })
    // One badge per numeric figure; the failure mode has none, because it is a
    // declaration about how a yield is read rather than a measurement. Six are
    // still defaults, one was measured by hand and one is observed.
    expect(screen.getAllByTestId('provenance-assumed')).toHaveLength(
      PROFILE_FIELDS.length - 2,
    )
    expect(screen.getByTestId('provenance-measured')).toBeInTheDocument()
    expect(screen.getByTestId('provenance-observed')).toBeInTheDocument()
  })

  it('will not let an observed figure be typed over', async () => {
    // FR-004: an observed figure is refreshed from its source. The API refuses
    // it either way; disabling the input is so nobody types into a field that
    // cannot accept it and loses the work at submit.
    renderForm(<ModelCostProfileForm modelId={MODEL_ID} />)

    await waitFor(() => {
      expect(screen.getByLabelText(/Success rate/)).toBeDisabled()
    })
    expect(screen.getByLabelText(/Purge and priming/)).toBeEnabled()
  })

  it('explains what the failure mode changes, because picking wrong is silent', async () => {
    // FR-015a-e. The same yield under per-plate costs a batched plate more, and
    // nothing about the number itself says so.
    renderForm(<ModelCostProfileForm modelId={MODEL_ID} />)

    await waitFor(() => {
      expect(screen.getByTestId('failure-mode-select')).toBeInTheDocument()
    })
    expect(screen.getByText(/a single\s+failure costs the whole plate/)).toBeInTheDocument()
    expect(screen.getByText(/never measured under it/)).toBeInTheDocument()
  })

  describe('an item nobody has measured', () => {
    beforeEach(() => {
      mocked.getModelCostProfile.mockResolvedValue(unmeasured())
    })

    it('says it is not fully costed rather than implying it is', async () => {
      // FR-019. A missing print time removes the machine and overhead lines
      // without a word, which is how a nine-hour print came out cheap.
      renderForm(<ModelCostProfileForm modelId={MODEL_ID} />)

      await waitFor(() => {
        expect(screen.getByTestId('profile-incomplete')).toBeInTheDocument()
      })
      expect(screen.getByTestId('profile-incomplete')).toHaveTextContent(/print time/i)
    })

    it('leaves the print time blank rather than showing a zero', async () => {
      renderForm(<ModelCostProfileForm modelId={MODEL_ID} />)

      await waitFor(() => {
        expect(screen.getByLabelText(/Plate print time/)).toHaveValue('')
      })
    })
  })

  describe('validation', () => {
    it('refuses a success rate outside the open unit interval', async () => {
      // A yield of zero means nothing succeeds, which has no cost per part.
      mocked.getModelCostProfile.mockResolvedValue(
        configured({
          expected_yield: '',
          origins: origins({ waste_grams: { source: 'measured', as_of: '2026-10-01' } }),
        }),
      )
      renderForm(<ModelCostProfileForm modelId={MODEL_ID} />)

      await waitFor(() => {
        expect(screen.getByLabelText(/Success rate/)).toHaveValue('')
      })
      await userEvent.type(screen.getByLabelText(/Success rate/), '1.5')
      await userEvent.click(screen.getByRole('button', { name: /Save cost profile/ }))

      await waitFor(() => {
        expect(screen.getByText(/above 0 and up to 1/)).toBeInTheDocument()
      })
      expect(mocked.updateModelCostProfile).not.toHaveBeenCalled()
    })

    it('refuses a plate that holds no parts', async () => {
      // Dividing per-plate labour across zero parts has no answer (FR-013).
      renderForm(<ModelCostProfileForm modelId={MODEL_ID} />)

      await waitFor(() => {
        expect(screen.getByLabelText(/Parts per plate/)).toHaveValue('1')
      })
      await userEvent.clear(screen.getByLabelText(/Parts per plate/))
      await userEvent.type(screen.getByLabelText(/Parts per plate/), '0')
      await userEvent.click(screen.getByRole('button', { name: /Save cost profile/ }))

      await waitFor(() => {
        expect(screen.getByText(/at least one/)).toBeInTheDocument()
      })
      expect(mocked.updateModelCostProfile).not.toHaveBeenCalled()
    })
  })

  describe('a viewer', () => {
    it('reads every figure with the controls disabled, not gone', async () => {
      // FR-007c: a figure whose editor vanished is a figure nobody can explain.
      renderForm(<ModelCostProfileForm modelId={MODEL_ID} canEdit={false} />)

      await waitFor(() => {
        expect(screen.getByLabelText(/Purge and priming/)).toHaveValue('3.00')
      })
      expect(screen.getByLabelText(/Purge and priming/)).toBeDisabled()
      expect(screen.getByTestId('failure-mode-select')).toBeDisabled()
      expect(
        screen.queryByRole('button', { name: /Save cost profile/ }),
      ).not.toBeInTheDocument()
    })
  })
})

describe('ModelCostProfileForm: the planned machine (T243, FR-011)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocked.getModelCostProfile.mockResolvedValue(configured())
    mocked.updateModelCostProfile.mockResolvedValue(configured())
  })

  it('plans the item on a machine', async () => {
    const user = userEvent.setup({ delay: null })
    renderForm(<ModelCostProfileForm modelId={MODEL_ID} />)

    await screen.findByRole('option', { name: 'Bambu X1C' })
    await user.selectOptions(screen.getByLabelText('Planned machine'), 'printer-x1')
    await user.click(screen.getByRole('button', { name: /Save cost profile/ }))

    await waitFor(() => expect(mocked.updateModelCostProfile).toHaveBeenCalled())
    const [, changes] = mocked.updateModelCostProfile.mock.calls[0]
    expect(changes.planned_printer_id).toBe('printer-x1')
  })

  it('clears the plan with null, and leaves it out when untouched', async () => {
    const user = userEvent.setup({ delay: null })
    mocked.getModelCostProfile.mockResolvedValue(
      configured({ planned_printer_id: 'printer-a1', planned_printer_name: 'Bambu A1 Mini' }),
    )
    renderForm(<ModelCostProfileForm modelId={MODEL_ID} />)

    await waitFor(() =>
      expect(screen.getByLabelText('Planned machine')).toHaveValue('printer-a1'),
    )
    await user.click(screen.getByRole('button', { name: /Save cost profile/ }))
    await waitFor(() => expect(mocked.updateModelCostProfile).toHaveBeenCalledTimes(1))
    expect(mocked.updateModelCostProfile.mock.calls[0][1]).not.toHaveProperty('planned_printer_id')

    await user.selectOptions(screen.getByLabelText('Planned machine'), '')
    await user.click(screen.getByRole('button', { name: /Save cost profile/ }))
    await waitFor(() => expect(mocked.updateModelCostProfile).toHaveBeenCalledTimes(2))
    expect(mocked.updateModelCostProfile.mock.calls[1][1].planned_printer_id).toBeNull()
  })

  it('is read-only for a viewer', async () => {
    renderForm(<ModelCostProfileForm modelId={MODEL_ID} canEdit={false} />)
    await screen.findByRole('option', { name: 'Bambu X1C' })
    expect(screen.getByLabelText('Planned machine')).toBeDisabled()
  })
})
