/** The Packaging page renders the packaging list inside the app layout (spec 006, T011). */
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'

import { Packaging } from './Packaging'

vi.mock('@/components/layout/AppLayout', () => ({
  AppLayout: ({ children }: { children: ReactNode }) => <div data-testid="layout">{children}</div>,
}))
vi.mock('@/components/packaging/PackagingList', () => ({
  PackagingList: () => <div data-testid="packaging-list" />,
}))

describe('Packaging page', () => {
  it('shows the packaging list in the layout', () => {
    render(<Packaging />)
    expect(screen.getByTestId('layout')).toContainElement(screen.getByTestId('packaging-list'))
  })
})
