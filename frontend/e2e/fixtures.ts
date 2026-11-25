/**
 * Signed-in test fixtures.
 *
 * `test` from this module opens every page already signed in as the owner of a
 * 3D-print tenant, without walking the signup pages. The account is made
 * through the same endpoints the signup page calls (register, the e2e-only
 * verification-token hook, verify-email, setup step 2), then handed to the
 * browser context as its storage state.
 *
 * The real browser signup stays covered by `tests/auth/*`, which still use
 * `registerAndLogin` from helpers.ts.
 *
 * `account` option:
 * - 'fresh' (default): a new tenant for every test, like the old per-test
 *   signup. Use it whenever a test reads an empty state, counts rows, or
 *   reuses names fixed once per file.
 * - 'shared': one tenant per worker and spec file, made on first use and
 *   reused by that file's later tests in the same worker. Only for files whose
 *   tests read nothing another test of the file writes.
 *
 *   test.use({ account: 'shared' })
 */

import { test as base, expect, type APIRequestContext } from '@playwright/test'

import { API_URL } from './config'
import { isBackendAvailable, rememberAccount, uniqueSuffix, type E2EAccount } from './helpers'

export { expect }

export type AccountMode = 'fresh' | 'shared'

const PASSWORD = 'TestPassword123!'
const TOKEN_STORAGE_KEY = 'batchivo_auth_tokens'
const REMEMBER_ME_KEY = 'batchivo_remember_me'
/** Access tokens live 24 h; keep the stored expiry well ahead of any run so the app never refreshes. */
const SESSION_LIFETIME_MS = 20 * 60 * 60 * 1000

async function ok(response: Awaited<ReturnType<APIRequestContext['get']>>, what: string) {
  if (!response.ok()) {
    throw new Error(`${what} answered HTTP ${response.status()}: ${await response.text()}`)
  }
  return response
}

/**
 * Register and verify a new tenant owner through the API, and pick 3D printing
 * as the business type (setup step 2), as the signup + wizard would.
 */
export async function createAccountViaApi(request: APIRequestContext): Promise<E2EAccount> {
  const suffix = uniqueSuffix()
  const email = `test-${suffix}@example.com`

  const register = await request.post(`${API_URL}/api/v1/onboarding/register`, {
    data: {
      email,
      password: PASSWORD,
      full_name: email.split('@')[0],
      business_name: `E2E Shop ${suffix}`,
    },
  })
  await ok(register, 'POST /onboarding/register')

  const hook = await request.get(`${API_URL}/api/v1/onboarding/test/verification-token`, {
    params: { email },
  })
  if (hook.status() === 404) {
    throw new Error(
      'No verification token from the e2e hook. Start the local backend with ' +
        'E2E_TEST_HOOKS_ENABLED=true (see e2e/README.md).'
    )
  }
  const { token } = (await (await ok(hook, 'Verification token hook')).json()) as { token: string }

  const verify = await request.post(`${API_URL}/api/v1/onboarding/verify-email`, { data: { token } })
  const session = (await (await ok(verify, 'POST /onboarding/verify-email')).json()) as {
    access_token: string
    refresh_token: string
    token_type: string
  }

  const craft = await request.put(`${API_URL}/api/v1/onboarding/wizard/step/2`, {
    headers: { Authorization: `Bearer ${session.access_token}` },
    data: { tenant_type: 'three_d_print' },
  })
  await ok(craft, 'Setting the business type')

  return {
    email,
    password: PASSWORD,
    accessToken: session.access_token,
    refreshToken: session.refresh_token,
    tokenType: session.token_type || 'bearer',
  }
}

type TestFixtures = {
  /** Which tenant the test signs in to (see the module comment). */
  account: AccountMode
  /** The signed-in owner the page starts with. */
  e2eAccount: E2EAccount
}

type WorkerFixtures = {
  sharedAccounts: Map<string, Promise<E2EAccount>>
}

export const test = base.extend<TestFixtures, WorkerFixtures>({
  account: ['fresh', { option: true }],

  sharedAccounts: [
    // eslint-disable-next-line no-empty-pattern
    async ({}, provide) => {
      await provide(new Map())
    },
    { scope: 'worker' },
  ],

  e2eAccount: async ({ account, sharedAccounts, playwright }, provide, testInfo) => {
    // Same behaviour as the specs' own guard: no backend → skip, not fail.
    testInfo.skip(!(await isBackendAvailable()), 'Backend API not available')

    const create = async () => {
      const request = await playwright.request.newContext()
      try {
        return await createAccountViaApi(request)
      } finally {
        await request.dispose()
      }
    }

    let made: Promise<E2EAccount>
    if (account === 'shared') {
      const key = testInfo.file
      if (!sharedAccounts.has(key)) {
        const pending = create()
        // A failed signup must not poison the file's later tests.
        pending.catch(() => sharedAccounts.delete(key))
        sharedAccounts.set(key, pending)
      }
      made = sharedAccounts.get(key)!
    } else {
      made = create()
    }
    await provide(await made)
  },

  storageState: async ({ e2eAccount, baseURL }, provide) => {
    const tokens = {
      accessToken: e2eAccount.accessToken,
      refreshToken: e2eAccount.refreshToken,
      tokenType: e2eAccount.tokenType,
      expiresAt: Date.now() + SESSION_LIFETIME_MS,
    }
    await provide({
      cookies: [],
      origins: [
        {
          origin: new URL(baseURL!).origin,
          localStorage: [
            { name: TOKEN_STORAGE_KEY, value: JSON.stringify(tokens) },
            { name: REMEMBER_ME_KEY, value: '1' },
          ],
        },
      ],
    })
  },

  context: async ({ context, e2eAccount }, provide) => {
    // Lets apiAs() find the session before the page has opened the app.
    rememberAccount(context, e2eAccount)
    await provide(context)
  },
})
