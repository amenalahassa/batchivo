import { afterEach, vi } from 'vitest'

/**
 * Whether this file is running with a DOM.
 *
 * A test file that touches no DOM declares `@vitest-environment node` and gets
 * no jsdom, because building one costs more than such a file's tests take to
 * run -- that budget, spent before a test starts, is what made the suite's
 * result depend on how loaded the machine was (task T174, Constitution II).
 *
 * So everything below that needs a `window` is guarded. A DOM stub applied to
 * a missing DOM is not a safer default: it throws at setup and reports as ten
 * failed files with no tests, which is what this guard replaces.
 */
const HAS_DOM = typeof window !== 'undefined'

if (HAS_DOM) {
  // Matchers and unmounting are only meaningful against a DOM. Imported
  // dynamically so a node-environment file does not pay for them either.
  await import('@testing-library/jest-dom/vitest')
  const { cleanup } = await import('@testing-library/react')
  afterEach(() => {
    cleanup()
  })
}

/**
 * `@tanstack/react-router`, stubbed rather than wrapped.
 *
 * Components reach for `Link`, `useNavigate`, `useParams` and friends, and a
 * test that renders one must not have to stand up a router to do it. This mock
 * used to satisfy that by spreading `await vi.importActual(...)` over four
 * overrides -- which pulled the router's whole module graph into **every** test
 * file, including the ones that only check a pure function.
 *
 * That was the single largest cost in the suite: one logic-only file took 61s,
 * of which 58s was this import, and across the suite it accounted for ~340s of
 * setup and about as much again of environment time. Under that load the
 * component tests that drive Radix through `userEvent` ran out of the default
 * 5000ms budget, so a full run failed tests that passed in isolation -- a suite
 * whose result depended on how busy the machine was (Constitution II).
 *
 * So nothing real is imported here. Every export the application actually uses
 * is listed below, which is checked by
 * `src/test/router-mock-covers-the-app.test.ts`: if a component starts using a
 * new one, that test names it rather than leaving `undefined` to surface as a
 * confusing render error.
 *
 * The router-construction API is the exception. Two tests build a genuine
 * memory router on purpose, and there is no stubbing that; they call
 * `vi.unmock('@tanstack/react-router')` and pay the import themselves.
 */
vi.mock('@tanstack/react-router', async () => {
  const React = await import('react')

  const notStubbed = (name: string) => () => {
    throw new Error(
      `${name} is the real router's, not stubbed: a test that builds a router ` +
        `must call vi.unmock('@tanstack/react-router') first.`,
    )
  }

  return {
    // Navigation, rendered as the plain anchor a test can read and click.
    Link: React.forwardRef(
      (
        props: {
          children?: React.ReactNode
          to?: string | object
          [key: string]: unknown
        },
        ref: React.Ref<HTMLAnchorElement>,
      ) => {
        const { children, to, ...rest } = props
        // `params` and `search` belong to the router, not to an anchor:
        // forwarding them to a DOM element makes React warn about unknown
        // attributes on every rendered Link.
        delete rest.params
        delete rest.search
        return React.createElement(
          'a',
          { href: typeof to === 'string' ? to : '#', ref, ...rest },
          children,
        )
      },
    ),
    Navigate: () => null,
    Outlet: ({ children }: { children?: React.ReactNode }) =>
      React.createElement(React.Fragment, null, children),

    // The hooks, answering as they would on a route with nothing in it. A test
    // that needs a particular param or search value mocks the hook itself.
    useNavigate: () => vi.fn(),
    useParams: () => ({}),
    useSearch: () => ({}),
    useLocation: () => ({ pathname: '/settings', search: '', hash: '', href: '/settings' }),
    useRouter: () => ({
      navigate: vi.fn(),
      state: {
        location: { pathname: '/settings' },
        matches: [],
        isLoading: false,
      },
    }),
    useRouterState: () => ({
      location: { pathname: '/settings' },
      matches: [],
      isLoading: false,
    }),

    // Building a router is not something a stub can fake into working.
    RouterProvider: notStubbed('RouterProvider'),
    createRouter: notStubbed('createRouter'),
    createMemoryHistory: notStubbed('createMemoryHistory'),
    createRootRoute: notStubbed('createRootRoute'),
    createRoute: notStubbed('createRoute'),
    Router: notStubbed('Router'),
    Route: notStubbed('Route'),
    RootRoute: notStubbed('RootRoute'),
  }
})

if (HAS_DOM) {
// Mock window.matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation(query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

// Mock IntersectionObserver
global.IntersectionObserver = class IntersectionObserver {
  readonly root = null
  readonly rootMargin = "0px"
  readonly thresholds = [0]
  takeRecords = vi.fn(() => [])
  observe = vi.fn()
  unobserve = vi.fn()
  disconnect = vi.fn()
}

// Mock ResizeObserver
global.ResizeObserver = class ResizeObserver {
  readonly root = null
  readonly rootMargin = "0px"
  readonly thresholds = [0]
  takeRecords = vi.fn(() => [])
  observe = vi.fn()
  unobserve = vi.fn()
  disconnect = vi.fn()
}

// Mock scrollTo and scrollIntoView
window.scrollTo = vi.fn()
Element.prototype.scrollIntoView = vi.fn()

// Mock pointer capture APIs (needed for Radix UI)
Element.prototype.hasPointerCapture = vi.fn().mockReturnValue(false)
Element.prototype.setPointerCapture = vi.fn()
Element.prototype.releasePointerCapture = vi.fn()

} // end HAS_DOM

// `crypto.randomUUID` is used by UI components and is not a DOM API, so it is
// stubbed in both environments.
Object.defineProperty(globalThis, 'crypto', {
  value: {
    randomUUID: () => Math.random().toString(36).substring(2),
  },
})
