/**
 * Tests for Settings page
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Settings } from './Settings'
import * as settingsApi from '@/lib/api/settings'
import * as ordersApi from '@/lib/api/orders'
import { listEstimateRevisions, pricingApi } from '@/lib/api/pricing'
import { feeRulesApi } from '@/lib/api/feeRules'

import type { TenantRole } from '@/lib/auth'
import type { PricingPolicy } from '@/types/pricing'

// Mock the APIs
vi.mock('@/lib/api/settings', () => ({
  getTenant: vi.fn(),
  updateTenant: vi.fn(),
  getSquareSettings: vi.fn(),
  updateSquareSettings: vi.fn(),
  testSquareConnection: vi.fn(),
  listTenantMembers: vi.fn(),
  inviteTenantMember: vi.fn(),
  updateMemberRole: vi.fn(),
  removeTenantMember: vi.fn(),
}))

vi.mock('@/lib/api/orders', () => ({
  getOrderCounts: vi.fn(),
}))

// The pricing tab mounts MarginDivergencePanel, which reads this client. An
// unmocked call reaches real axios and fails as a network error, which looks
// like a broken tab rather than a missing mock.
vi.mock('@/lib/api/feeRules', () => ({
  feeRulesApi: { getMarginDivergence: vi.fn() },
}))

vi.mock('@/lib/api/pricing', () => ({
  pricingApi: {
    getPricingPolicy: vi.fn(),
    updatePricingPolicy: vi.fn(),
  },
  listEstimateRevisions: vi.fn(),
  acceptEstimateRevision: vi.fn(),
  rejectEstimateRevision: vi.fn(),
}))

// The role the mocked `useAuth` reports. Settings reads it to decide whether
// the pricing tab's controls are editable (FR-007a).
let currentRole: TenantRole | null = 'admin'

// Mock AuthContext
vi.mock('@/contexts/AuthContext', () => ({
  useAuth: () => ({
    user: { email: 'test@example.com', role: currentRole },
    logout: vi.fn(),
  }),
  // `useCurrency` reads this one, deliberately optionally, so a leaf showing a
  // cost does not throw in a tree without an AuthProvider.
  useOptionalAuth: () => ({
    user: { email: 'test@example.com', role: currentRole },
    logout: vi.fn(),
  }),
}))

const mockPolicy: PricingPolicy = {
  print_labor_rate: '25.0000',
  finishing_labor_rate: '25.0000',
  default_machine_rate_per_hour: '0.2324',
  overhead_method: 'per_machine_hour',
  overhead_monthly_pool: '180.0000',
  expected_monthly_machine_hours: '600.0000',
  overhead_rate_per_machine_hour: '0.30',
  overhead_percentage: '0',
  electricity_rate_per_kwh: '0.1300',
  margin_basis: 'customer_total',
  default_target_margin_pct: '35',
  rounding_rule: null,
  sales_tax_recoverable: false,
  staleness_threshold_days: 180,
  margin_alert_threshold_pct: '5',
  min_outcomes_before_auto_update: 5,
  estimate_divergence_threshold_pct: '25',
  origin: 'policy_row',
  effective_from: '2026-03-01',
  effective_to: null,
  set_by_role: 'admin',
}

const mockTenant = {
  id: 'tenant-123',
  name: 'Test Organization',
  slug: 'test-org',
  description: 'A test organization',
  is_active: true,
  created_at: '2024-01-01T00:00:00Z',
  updated_at: '2024-01-01T00:00:00Z',
}

const mockSquareSettings = {
  enabled: false,
  environment: 'sandbox' as const,
  is_configured: false,
  access_token_masked: null,
  app_id: null,
  location_id_masked: null,
  updated_at: null,
}

const mockMembers = {
  members: [
    {
      id: 'user-1',
      email: 'test@example.com',
      full_name: 'Test User',
      role: 'owner' as const,
      is_active: true,
      joined_at: '2024-01-01T00:00:00Z',
    },
  ],
  total: 1,
}

function renderWithQueryClient(component: React.ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      {component}
    </QueryClientProvider>
  )
}

describe('Settings Page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    currentRole = 'admin'
    vi.mocked(pricingApi.getPricingPolicy).mockResolvedValue(mockPolicy)
    vi.mocked(listEstimateRevisions).mockResolvedValue({ revisions: [], total: 0 })
    vi.mocked(feeRulesApi.getMarginDivergence).mockResolvedValue({
      divergences: [],
      total: 0,
      alerting: 0,
      threshold_points: '5.0000',
    })
    vi.mocked(settingsApi.getTenant).mockResolvedValue(mockTenant)
    vi.mocked(settingsApi.getSquareSettings).mockResolvedValue(mockSquareSettings)
    vi.mocked(settingsApi.listTenantMembers).mockResolvedValue(mockMembers)
    vi.mocked(ordersApi.getOrderCounts).mockResolvedValue({
      pending: 0,
      processing: 0,
      shipped: 0,
      delivered: 0,
      refunded: 0,
      total: 0,
      cancelled: 0,
    })
  })

  it('renders page title and description', async () => {
    renderWithQueryClient(<Settings />)

    // Use heading role for the main title
    expect(screen.getByRole('heading', { name: 'Settings' })).toBeInTheDocument()
    expect(
      screen.getByText('Manage your organization settings and integrations')
    ).toBeInTheDocument()
  })

  it('renders all three tabs', async () => {
    renderWithQueryClient(<Settings />)

    expect(screen.getByRole('tab', { name: /general/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /payments/i })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /team/i })).toBeInTheDocument()
  })

  it('offers a Pricing tab, which is where the labor rate is set', async () => {
    // US1 opens with "the operator sets an hourly labor rate in settings".
    // Without this tab the whole feature's premise has no way in.
    renderWithQueryClient(<Settings />)

    expect(screen.getByRole('tab', { name: /pricing/i })).toBeInTheDocument()
  })

  it('switches to the Pricing tab and shows the policy screen', async () => {
    const user = userEvent.setup({ delay: null })

    renderWithQueryClient(<Settings />)

    await user.click(screen.getByRole('tab', { name: /pricing/i }))

    await waitFor(() => {
      expect(pricingApi.getPricingPolicy).toHaveBeenCalled()
    })
    expect(await screen.findByLabelText(/print handling rate/i)).toBeInTheDocument()
  })

  it('shows a viewer the Pricing tab with its controls disabled, not hidden', async () => {
    // FR-007c: visibility is never restricted by role, only editing. The edge
    // case asks for "unavailable rather than hidden", so that the figures on
    // screen stay explainable to whoever is reading them.
    currentRole = 'viewer'
    const user = userEvent.setup({ delay: null })

    renderWithQueryClient(<Settings />)

    await user.click(screen.getByRole('tab', { name: /pricing/i }))

    const rate = await screen.findByLabelText(/print handling rate/i)
    expect(rate).toBeInTheDocument()
    expect(rate).toBeDisabled()
  })

  it('lets an admin edit the pricing policy', async () => {
    currentRole = 'admin'
    const user = userEvent.setup({ delay: null })

    renderWithQueryClient(<Settings />)

    await user.click(screen.getByRole('tab', { name: /pricing/i }))

    expect(await screen.findByLabelText(/print handling rate/i)).toBeEnabled()
  })

  it('lists held estimate proposals beside the thresholds that produce them', async () => {
    // FR-042c: a divergent observation waits for the operator to accept or
    // reject it. With nowhere to review one, pricing silently keeps using the
    // old estimate for ever (FR-042e).
    const user = userEvent.setup({ delay: null })

    renderWithQueryClient(<Settings />)

    await user.click(screen.getByRole('tab', { name: /pricing/i }))

    await waitFor(() => {
      expect(listEstimateRevisions).toHaveBeenCalledWith(
        expect.objectContaining({ state: 'pending' })
      )
    })
  })

  it('shows General tab content by default', async () => {
    renderWithQueryClient(<Settings />)

    await waitFor(() => {
      expect(screen.getByText('Organization Details')).toBeInTheDocument()
    })
  })

  it('switches to Payments tab when clicked', async () => {
    const user = userEvent.setup({ delay: null })

    renderWithQueryClient(<Settings />)

    await user.click(screen.getByRole('tab', { name: /payments/i }))

    await waitFor(() => {
      expect(screen.getByText('Square Payments')).toBeInTheDocument()
    })
  })

  it('switches to Team tab when clicked', async () => {
    const user = userEvent.setup({ delay: null })

    renderWithQueryClient(<Settings />)

    await user.click(screen.getByRole('tab', { name: /team/i }))

    await waitFor(() => {
      expect(screen.getByText('Team Members')).toBeInTheDocument()
    })
  })

  it('loads data for General tab on mount', async () => {
    renderWithQueryClient(<Settings />)

    await waitFor(() => {
      expect(settingsApi.getTenant).toHaveBeenCalled()
    })
  })

  it('loads Square settings when Payments tab is shown', async () => {
    const user = userEvent.setup({ delay: null })

    renderWithQueryClient(<Settings />)

    await user.click(screen.getByRole('tab', { name: /payments/i }))

    await waitFor(() => {
      expect(settingsApi.getSquareSettings).toHaveBeenCalled()
    })
  })

  it('loads team members when Team tab is shown', async () => {
    const user = userEvent.setup({ delay: null })

    renderWithQueryClient(<Settings />)

    await user.click(screen.getByRole('tab', { name: /team/i }))

    await waitFor(() => {
      expect(settingsApi.listTenantMembers).toHaveBeenCalled()
    })
  })
})
