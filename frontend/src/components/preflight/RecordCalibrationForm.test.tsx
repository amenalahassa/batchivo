/** Recording a fit clearance (spec 009, US3): the typed value is sent exactly. */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'

import { render, screen, waitFor } from '@/test/test-utils'
import { calibrationsApi } from '@/lib/api/preflight'
import { RecordCalibrationForm } from './RecordCalibrationForm'
import { aCalibration } from './preflightTestData'

vi.mock('@/lib/api/preflight', () => ({
  calibrationsApi: { listForPrinter: vi.fn(), record: vi.fn() },
}))
vi.mock('@/lib/api/spools', () => ({
  materialTypesApi: {
    list: vi.fn().mockResolvedValue([
      { id: 'pla', code: 'PLA', name: 'PLA' },
      { id: 'petg', code: 'PETG', name: 'PETG' },
    ]),
  },
}))

describe('RecordCalibrationForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(calibrationsApi.record).mockResolvedValue(aCalibration())
  })

  it('sends the value as the decimal string typed', async () => {
    render(<RecordCalibrationForm printerId="printer-1" />)
    await screen.findByRole('option', { name: 'PETG' })
    await userEvent.selectOptions(screen.getByLabelText('Material'), 'petg')
    await userEvent.selectOptions(screen.getByLabelText('Fit'), 'press')
    await userEvent.selectOptions(screen.getByLabelText('Orientation'), 'horizontal')
    await userEvent.type(screen.getByLabelText('Clearance per side (mm)'), '0.150')
    await userEvent.click(screen.getByRole('button', { name: 'Record value' }))
    await waitFor(() =>
      expect(calibrationsApi.record).toHaveBeenCalledWith('printer-1', {
        material_type_id: 'petg',
        fit_type: 'press',
        orientation: 'horizontal',
        value_mm: '0.150',
        provenance: 'measured',
        notes: null,
      })
    )
  })

  it.each(['2.5', '0.1234', '-1', 'abc'])('refuses %s', async (value) => {
    render(<RecordCalibrationForm printerId="printer-1" />)
    await screen.findByRole('option', { name: 'PLA' })
    await userEvent.type(screen.getByLabelText('Clearance per side (mm)'), value)
    expect(screen.getByRole('button', { name: 'Record value' })).toBeDisabled()
    expect(screen.getByText(/Between 0 and 2 mm/)).toBeInTheDocument()
  })
})
