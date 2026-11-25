/**
 * The scenarios page exists and runs the panel (task T132).
 *
 * SC-006 asks that an operator request a whole-catalogue shock "in a single
 * action". `ScenarioRunPanel` provides the action; until this page there was
 * nothing it could be clicked from.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'

import { Scenarios } from './Scenarios'
import { listScenarios } from '@/lib/api/pricing'

vi.mock('@/lib/api/pricing', () => ({
  listScenarios: vi.fn(),
  getScenario: vi.fn(),
  requestScenario: vi.fn(),
}))

// The layout pulls in the router, the module list and the order counts; none
// of that is what this page is for.
vi.mock('@/components/layout/AppLayout', () => ({
  AppLayout: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}))

function renderPage(node: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>)
}

describe('Scenarios page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(listScenarios).mockResolvedValue({ runs: [], total: 0 })
  })

  it('renders its heading', () => {
    renderPage(<Scenarios />)

    expect(screen.getByRole('heading', { name: 'Scenarios' })).toBeInTheDocument()
  })

  it('says that running one changes nothing (FR-044d)', () => {
    // A scenario writes no cost, price or provenance figure. An operator who
    // believes otherwise will not run the one query that would help them.
    renderPage(<Scenarios />)

    expect(
      screen.getByText(/without changing a single stored figure/i)
    ).toBeInTheDocument()
  })

  it('mounts the run panel, which fetches the run history', async () => {
    renderPage(<Scenarios />)

    await waitFor(() => {
      expect(listScenarios).toHaveBeenCalled()
    })
  })
})
