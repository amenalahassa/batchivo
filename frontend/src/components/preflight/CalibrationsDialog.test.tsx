/** A printer's calibrations and their history (spec 009, US3). */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import userEvent from '@testing-library/user-event'

import { render, screen, within } from '@/test/test-utils'
import { calibrationsApi } from '@/lib/api/preflight'
import { CalibrationsDialog } from './CalibrationsDialog'
import { groupCalibrations } from './preflightLogic'
import { aCalibration } from './preflightTestData'

vi.mock('@/lib/api/preflight', () => ({
  calibrationsApi: { listForPrinter: vi.fn(), record: vi.fn() },
}))
vi.mock('@/lib/api/spools', () => ({
  materialTypesApi: { list: vi.fn().mockResolvedValue([{ id: 'pla', code: 'PLA', name: 'PLA' }]) },
}))

const CURRENT = aCalibration({ id: 'new', value_mm: '0.180', created_at: '2026-11-22T10:00:00Z' })
const OLD = aCalibration({
  id: 'old',
  value_mm: '0.150',
  is_current: false,
  superseded_by_id: 'new',
  superseded_at: '2026-11-22T10:00:00Z',
})
const PRESS = aCalibration({ id: 'press', fit_type: 'press', value_mm: '0.050' })

describe('groupCalibrations', () => {
  it('puts each combination’s current value first with its history', () => {
    const groups = groupCalibrations([OLD, PRESS, CURRENT])
    expect(groups).toHaveLength(2)
    const slide = groups.find((g) => g.current.fit_type === 'slide')!
    expect(slide.current.id).toBe('new')
    expect(slide.history.map((c) => c.id)).toEqual(['old'])
  })
})

describe('CalibrationsDialog', () => {
  beforeEach(() => {
    vi.mocked(calibrationsApi.listForPrinter).mockResolvedValue([OLD, PRESS, CURRENT])
  })

  it('shows current values exactly as stored, and the history on demand', async () => {
    render(<CalibrationsDialog printerId="printer-1" printerName="A1" canWrite={false} open onOpenChange={vi.fn()} />)
    expect(await screen.findByText('0.180 mm')).toBeInTheDocument()
    expect(screen.getByText('0.050 mm')).toBeInTheDocument()
    expect(screen.queryByText('0.150 mm')).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'History (1)' }))
    expect(screen.getByText('0.150 mm')).toBeInTheDocument()
    expect(screen.queryByRole('form', { name: 'Record a calibration' })).not.toBeInTheDocument()
  })

  it('lets a member record a value', async () => {
    render(<CalibrationsDialog printerId="printer-1" printerName="A1" canWrite open onOpenChange={vi.fn()} />)
    const form = await screen.findByRole('form', { name: 'Record a calibration' })
    expect(within(form).getByLabelText('Clearance per side (mm)')).toBeInTheDocument()
  })
})
