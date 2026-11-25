/** /verify-email spends its single-use token once, even under StrictMode (bug e2e-register-verification). */
import { StrictMode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

import { VerifyEmail } from './VerifyEmail'

const verifyEmail = vi.fn()
const setAuthTokens = vi.fn()
const navigate = vi.fn()

vi.mock('@/lib/api/onboarding', () => ({
  verifyEmail: (token: string) => verifyEmail(token),
  resendVerification: vi.fn(),
}))
vi.mock('@/lib/auth', () => ({ setAuthTokens: (t: unknown) => setAuthTokens(t) }))
vi.mock('@/contexts/AuthContext', () => ({ useAuth: () => ({ refreshUser: vi.fn() }) }))
vi.mock('@tanstack/react-router', () => ({
  useNavigate: () => navigate,
  Link: ({ children }: { children: React.ReactNode }) => <a>{children}</a>,
}))

describe('VerifyEmail', () => {
  beforeEach(() => {
    window.history.pushState({}, '', '/verify-email?token=abc123')
    verifyEmail.mockResolvedValue({
      message: 'ok',
      tenant_id: 't',
      tenant_name: 'E2E Shop',
      tenant_slug: 'e2e-shop',
      user_id: 'u',
      access_token: 'access',
      refresh_token: 'refresh',
      token_type: 'bearer',
    })
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('verifies the token exactly once under StrictMode and stores the session', async () => {
    render(
      <StrictMode>
        <VerifyEmail />
      </StrictMode>
    )

    await waitFor(() => expect(setAuthTokens).toHaveBeenCalledTimes(1))
    expect(verifyEmail).toHaveBeenCalledTimes(1)
    expect(verifyEmail).toHaveBeenCalledWith('abc123')
    expect(setAuthTokens).toHaveBeenCalledWith(
      expect.objectContaining({ accessToken: 'access', refreshToken: 'refresh' })
    )
    expect(await screen.findByText(/E2E Shop/)).toBeInTheDocument()
  })

  it('does not call the API without a token', () => {
    window.history.pushState({}, '', '/verify-email')
    render(<VerifyEmail />)
    expect(verifyEmail).not.toHaveBeenCalled()
  })
})
