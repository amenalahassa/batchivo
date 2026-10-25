import { defineConfig, devices } from '@playwright/test'

/**
 * Playwright Configuration for batchivo.com E2E Tests
 *
 * See https://playwright.dev/docs/test-configuration.
 */
export default defineConfig({
  testDir: './e2e',

  /* Run tests in files in parallel - disabled to prevent registration rate limiting */
  fullyParallel: false,

  /* Fail the build on CI if you accidentally left test.only in the source code. */
  forbidOnly: !!process.env.CI,

  /* Retry failed tests (helps with rate limiting flakiness) */
  retries: process.env.CI ? 2 : 1,

  /* Single worker to prevent registration rate limiting */
  workers: 1,

  /* Reporter to use. See https://playwright.dev/docs/test-reporters */
  reporter: 'html',

  /* Shared settings for all the projects below. See https://playwright.dev/docs/api/class-testoptions. */
  use: {
    /* Base URL to use in actions like `await page.goto('/')`. */
    /* Defaults to a local frontend (T267): an unconfigured run must never aim
       at production. Point PLAYWRIGHT_BASE_URL elsewhere deliberately. */
    baseURL: process.env.PLAYWRIGHT_BASE_URL || 'http://localhost:5173',

    /* Collect trace when retrying the failed test. See https://playwright.dev/docs/trace-viewer */
    trace: 'on-first-retry',

    /* Screenshot on failure */
    screenshot: 'only-on-failure',
  },

  /* Configure projects for major browsers */
  projects: [
    {
      name: 'chromium',
      testIgnore: /pricing\//,
      use: { ...devices['Desktop Chrome'] },
    },

    {
      name: 'firefox',
      testIgnore: /pricing\//,
      use: { ...devices['Desktop Firefox'] },
    },

    {
      name: 'webkit',
      testIgnore: /pricing\//,
      use: { ...devices['Desktop Safari'] },
    },

    /*
     * The pricing journeys (T266), against the tenant
     * `backend/scripts/seed_e2e.py` seeds. The setup project signs the owner
     * and the viewer in once each, so the suite stays inside the login rate
     * limit; every spec reuses those sessions. CI runs `--project=pricing`.
     */
    {
      name: 'pricing-setup',
      testMatch: /pricing\/auth\.setup\.ts/,
      use: { ...devices['Desktop Chrome'] },
    },
    {
      name: 'pricing',
      testMatch: /pricing\/.*\.spec\.ts/,
      dependencies: ['pricing-setup'],
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  /* Start (or reuse) the Vite dev server only for the default local address.
     CI serves a built frontend on its own port and starts nothing here. */
  webServer: (process.env.PLAYWRIGHT_BASE_URL ?? 'http://localhost:5173').startsWith(
    'http://localhost:5173',
  )
    ? {
        command: `VITE_API_URL=${process.env.PLAYWRIGHT_API_URL || 'http://localhost:8000'} npm run dev`,
        url: 'http://localhost:5173',
        reuseExistingServer: !process.env.CI,
        stdout: 'ignore',
        stderr: 'pipe',
      }
    : undefined,
})
