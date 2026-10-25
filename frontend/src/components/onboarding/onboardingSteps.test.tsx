/**
 * The wizard steps send what the backend accepts (bug onboarding-wizard-steps-missing).
 *
 * Step 2 sent enum *names* ('THREED_PRINT') where the API and the module guard
 * use the values ('three_d_print'), and step 4 labelled every currency other
 * than GBP and EUR with '$'.
 */

import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Step2CraftType } from './Step2CraftType'
import { Step4FirstProduct } from './Step4FirstProduct'

describe('Step2CraftType', () => {
  it('submits the business type as the backend value', async () => {
    const onSubmit = vi.fn()
    render(<Step2CraftType onSubmit={onSubmit} onBack={() => {}} />)

    await userEvent.click(screen.getByText('Hand Knitting'))
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }))

    expect(onSubmit).toHaveBeenCalledWith({ tenant_type: 'hand_knitting' })
  })
})

describe('Step4FirstProduct', () => {
  it.each([
    ['GBP', '£'],
    ['CAD', 'CA$'],
    ['AUD', 'A$'],
  ])('labels the price in %s with %s', (currency, symbol) => {
    render(<Step4FirstProduct onSubmit={() => {}} onBack={() => {}} currency={currency} />)

    expect(screen.getByText(`Price (${symbol})`)).toBeInTheDocument()
  })
})
