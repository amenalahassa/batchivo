import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tsconfigPaths from 'vite-tsconfig-paths'
import path from 'path'

export default defineConfig({
  plugins: [react(), tsconfigPaths()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
    include: ['src/**/*.{test,spec}.{js,jsx,ts,tsx}'],
    /*
     * The component tests drive Radix through `userEvent`, which waits on real
     * timers for the open/focus transitions. The default 5000ms is enough for
     * a file run on its own and not enough for the same file run alongside
     * every other one, which made a full run fail tests that passed in
     * isolation -- a suite whose answer depended on how loaded the machine
     * was. An explicit budget that holds under load is worth more than a tight
     * one that does not (Constitution II), and `test:ci` runs with `--coverage`
     * on top, which is slower again.
     */
    testTimeout: 20000,
    hookTimeout: 20000,
    /*
     * The budget above was raised to stop the timeouts; task T174 cut what was
     * consuming it, which is the part that actually makes the result
     * independent of the machine:
     *
     * - **No jsdom where there is no DOM.** The logic-only test files declare
     *   `@vitest-environment node`. Building a jsdom cost more than such a
     *   file's tests take to run, and across sixty files that was spent before
     *   any test started. `src/test/cheap-files-stay-cheap.test.ts` keeps it
     *   that way, and `src/test/setup.ts` guards its DOM stubs accordingly.
     * - **No real-timer delay between synthetic events.** Every
     *   `userEvent.setup()` passes `{ delay: null }`. By default `userEvent`
     *   waits a macrotask between keystrokes, so typing five characters meant
     *   five trips through a loaded event loop, each with a React render --
     *   which is how a form test that passed alone ran out of budget in a full
     *   run.
     *
     * Together these took the full run from ~63s to ~48s, with setup, import
     * and environment each cut by about a third. The budget stays generous on
     * purpose: it is headroom for a slow machine, not a substitute for the
     * work above (Constitution II).
     */
    /*
     * Each worker builds its own jsdom. Sixteen of them on a 16GB machine
     * spend more time competing for memory than running tests, and the
     * contention is what turned slow setup into timeouts. Half the cores keeps
     * every worker responsive; the suite is bounded by setup, not by
     * parallelism.
     */
    maxWorkers: '50%',
    minWorkers: 1,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'lcov'],
      exclude: [
        'node_modules/',
        'src/test/',
        '**/*.d.ts',
        '**/*.config.*',
        'src/main.tsx',
        'src/vite-env.d.ts',
      ],
      thresholds: {
        statements: 30,
        branches: 30,
        functions: 30,
        lines: 30,
      }
    }
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
})
