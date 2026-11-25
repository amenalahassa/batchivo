/**
 * @vitest-environment node
 *
 * A test file that needs no DOM must not build one (task T174).
 *
 * Building a jsdom costs more than a logic-only file's tests take to run. With
 * sixty files that budget is spent before any test starts, and under load it
 * is what pushed the component tests -- which drive Radix through `userEvent`
 * on real timers -- past their deadline. The suite then failed tests that
 * passed in isolation and passed on the next identical run: a suite whose
 * answer depended on how busy the machine was, which Constitution II does not
 * accept as passing.
 *
 * So the logic-only files declare `@vitest-environment node`. This test keeps
 * that honest in both directions:
 *
 * - a file that declares `node` must not reference a DOM global, or it will
 *   fail confusingly at some later point rather than here;
 * - a file whose tests touch no DOM at all should say so, so the saving is not
 *   quietly lost the next time one is added.
 *
 * Neither is a style rule. Both are about keeping the suite's result
 * independent of the machine it runs on.
 */

import { readFileSync, readdirSync } from 'node:fs'
import { join, relative } from 'node:path'

import { describe, expect, it } from 'vitest'

const SRC = join(__dirname, '..')

/** Every test file under `src`. */
function testFiles(dir: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) {
      out.push(...testFiles(full))
      continue
    }
    if (/\.test\.(ts|tsx)$/.test(entry.name)) out.push(full)
  }
  return out
}

/** Read once: re-reading the tree per case is the cost this file is about. */
const ALL_TESTS: ReadonlyArray<{ path: string; text: string }> = testFiles(SRC).map((path) => ({
  path: relative(SRC, path).replace(/\\/g, '/'),
  text: readFileSync(path, 'utf8'),
}))

/** This file, which cannot be scanned for DOM markers: it contains them. */
const SELF = 'test/cheap-files-stay-cheap.test.ts'

/** Files that opt out of jsdom. */
const NODE_ENV_FILES = ALL_TESTS.filter(
  ({ path, text }) => path !== SELF && /@vitest-environment\s+node/.test(text),
)

/**
 * References that mean "this file needs a document".
 *
 * `window` and `document` are the direct ones. The testing-library helpers are
 * included because they only work against a DOM, and a file that imports one
 * has a DOM dependency whether or not it names `document`.
 */
const DOM_MARKERS = [
  // Bare identifiers, not `window.`: `Object.defineProperty(window, ...)` is a
  // DOM dependency too, and requiring the dot missed it.
  /\bdocument\b/,
  /\bwindow\b/,
  /\bnavigator\b/,
  /\blocalStorage\b/,
  /\bsessionStorage\b/,
  /\brender\s*\(/,
  /\brenderHook\s*\(/,
  /\bscreen\./,
  /toBeInTheDocument\b/,
]

/**
 * A `.tsx` test renders a component, so it needs a DOM by construction. Only
 * `.ts` files are candidates for the node environment.
 */
const PLAIN_TS_TESTS = ALL_TESTS.filter(({ path }) => path.endsWith('.test.ts'))

/**
 * Files that look DOM-free but keep jsdom on purpose, with the reason.
 *
 * The test under scrutiny may touch no DOM while the *module it imports* does,
 * which is a dependency this file cannot see. Each entry is a deliberate
 * exception, not a backlog.
 */
const KEEPS_JSDOM_ON_PURPOSE: Record<string, string> = {
  'lib/api.test.ts':
    'src/lib/api.ts reads window.__RUNTIME_CONFIG__ while being imported, so the ' +
    'module under test cannot load without a DOM',
}

describe('a test file that needs no DOM does not build one', () => {
  it('finds the node-environment files', () => {
    // A guard that matched nothing would pass for ever while the saving was
    // being undone one file at a time.
    expect(NODE_ENV_FILES.length).toBeGreaterThan(0)
  })

  it.each(NODE_ENV_FILES.map(({ path }) => path))(
    '%s declares the node environment and uses no DOM global',
    (path) => {
      const { text } = NODE_ENV_FILES.find((file) => file.path === path)!
      const body = text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')

      const found = DOM_MARKERS.filter((marker) => marker.test(body)).map(String)

      expect(found, `${path} declares @vitest-environment node but references a DOM API`).toEqual(
        [],
      )
    },
  )

  it.each(PLAIN_TS_TESTS.map(({ path }) => path))(
    '%s either needs a DOM, says why it keeps one, or opts out of jsdom',
    (path) => {
      if (path === SELF) return
      const { text } = PLAIN_TS_TESTS.find((file) => file.path === path)!
      if (/@vitest-environment\s+node/.test(text)) return
      if (path in KEEPS_JSDOM_ON_PURPOSE) return

      const body = text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
      const needsDom = DOM_MARKERS.some((marker) => marker.test(body))

      expect(
        needsDom,
        `${path} touches no DOM, so it should declare "@vitest-environment node" and skip ` +
          `building a jsdom. If the module it imports needs one, add it to ` +
          `KEEPS_JSDOM_ON_PURPOSE with the reason.`,
      ).toBe(true)
    },
  )
})
