import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { AssemblyRateNote } from './AssemblyRateNote'

const state = vi.hoisted(() => ({ policy: undefined as unknown, symbol: '£' }))

vi.mock('@/hooks/usePricing', () => ({
  usePricingPolicy: () => ({ policy: state.policy, isLoading: false, error: null }),
}))
vi.mock('@/hooks/useCurrency', () => ({
  useCurrency: () => ({ currency: { code: 'CAD', symbol: state.symbol } }),
}))

describe('AssemblyRateNote (T275)', () => {
  beforeEach(() => {
    state.policy = undefined
    state.symbol = '£'
  })

  it('names the configured handling rate in the books currency', () => {
    state.policy = { print_labor_rate: '25.00' }
    state.symbol = 'C$'
    render(<AssemblyRateNote />)
    expect(screen.getByTestId('assembly-rate-note')).toHaveTextContent('C$25.00/hr')
  })

  it('never states the old hardcoded rate', () => {
    state.policy = { print_labor_rate: '18.50' }
    render(<AssemblyRateNote />)
    expect(screen.getByTestId('assembly-rate-note')).not.toHaveTextContent('10/hr')
  })

  it('states no figure while the policy is unknown', () => {
    render(<AssemblyRateNote />)
    const note = screen.getByTestId('assembly-rate-note')
    expect(note).toHaveTextContent('handling labour rate')
    expect(note).not.toHaveTextContent('/hr')
  })
})
