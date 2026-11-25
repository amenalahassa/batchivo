/** The fourteen Preflight steps (spec 009, US1). */
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { StepStrip } from './StepStrip'
import { aBrief } from './preflightTestData'

describe('StepStrip', () => {
  it('lists every step with its status', () => {
    const steps = aBrief().steps.map((s) => (s.step === 'risk' ? { ...s, status: 'done' as const } : s))
    render(<StepStrip steps={steps} canWrite={false} onChange={vi.fn()} />)
    expect(screen.getAllByRole('listitem')).toHaveLength(14)
    const risk = screen.getByText('Risk').closest('li') as HTMLElement
    expect(risk).toHaveTextContent('Done')
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
  })

  it('lets a member change a step', async () => {
    const onChange = vi.fn()
    render(<StepStrip steps={aBrief().steps} canWrite onChange={onChange} />)
    await userEvent.selectOptions(screen.getByLabelText('Plan status'), 'in_progress')
    expect(onChange).toHaveBeenCalledWith('plan', 'in_progress')
  })
})
