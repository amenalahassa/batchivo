/**
 * @vitest-environment node
 *
 * Test files share their worker, and each one still starts clean (bug `vitest-slow`).
 *
 * `vitest.config.ts` runs with `isolate: false`, so a worker builds its jsdom
 * and loads `node_modules` once instead of once per file. That took the full
 * run from ~186s to ~42s. It only holds if `src/test/setup.ts` gives every file
 * back what a fresh worker used to give it:
 *
 * - `vi.resetModules()` runs before the file's own imports, or application
 *   modules stay bound to the previous file's `vi.mock` factories (20 of 130
 *   tests failed that way on a sample)
 * - every global a test file replaces outright (`Object.defineProperty(window,
 *   'localStorage', ...)`, `global.fetch = ...`) is on the list that setup
 *   restores after the file, or the replacement leaks into the next file in the
 *   same worker and makes the result depend on file order.
 *
 * This test names the global when a new test starts replacing one that is not
 * on the list.
 */

import { readFileSync, readdirSync } from 'node:fs'
import { join, relative } from 'node:path'

import { describe, expect, it } from 'vitest'

const SRC = join(__dirname, '..')
const SETUP = readFileSync(join(__dirname, 'setup.ts'), 'utf8')
const CONFIG = readFileSync(join(SRC, '..', 'vitest.config.ts'), 'utf8')

function testFiles(dir: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) out.push(...testFiles(full))
    else if (/\.test\.(ts|tsx)$/.test(entry.name)) out.push(full)
  }
  return out
}

/** Code only: the comments in this suite quote the patterns they describe. */
function code(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
}

/** The names `setup.ts` saves and restores around every file. */
const RESTORED: ReadonlySet<string> = new Set(
  [
    ...(
      code(SETUP).match(/const SHARED_GLOBALS = \[([\s\S]*?)\]/)?.[1] ?? ''
    ).matchAll(/'(\w+)'/g),
  ].map((match) => match[1]),
)

/**
 * Globals a test file replaces outright. Assigning to a property of one (as in
 * `URL.createObjectURL = ...`) changes no global binding and is not counted
 * `vi.stubGlobal` is undone by `vi.unstubAllGlobals()` in setup.
 */
const REPLACEMENT = [
  /Object\.defineProperty\(\s*(?:w\w*|global\w*),\s*'(\w+)'/g,
  /\bglobal(?:This)?\.(\w+)\s*=(?!=)/g,
]

const REPLACED: ReadonlyArray<{ path: string; name: string }> = testFiles(SRC)
  .map((path) => ({
    path: relative(SRC, path).replace(/\\/g, '/'),
    text: code(readFileSync(path, 'utf8')),
  }))
  .flatMap(({ path, text }) =>
    REPLACEMENT.flatMap((pattern) =>
      [...text.matchAll(pattern)].map((match) => ({ path, name: match[1] })),
    ),
  )

describe('test files share a worker and still start clean', () => {
  it('runs without per-file isolation', () => {
    expect(code(CONFIG)).toMatch(/isolate:\s*false/)
  })

  it('re-evaluates application modules before each file imports them', () => {
    const body = code(SETUP)
    const reset = body.indexOf('vi.resetModules()')
    expect(reset, 'setup.ts must call vi.resetModules()').toBeGreaterThan(-1)
    // Before the file's mocks and imports run: nothing above it but imports.
    expect(
      body
        .slice(0, reset)
        .replace(/^import .*$/gm, '')
        .trim(),
    ).toBe('')
  })

  it('finds the globals that test files replace', () => {
    // A pattern that matched nothing would pass for ever.
    expect(REPLACED.length).toBeGreaterThan(0)
  })

  it.each(REPLACED.map(({ path, name }) => [path, name]))(
    '%s replaces %s, which setup restores after the file',
    (path, name) => {
      expect(
        RESTORED.has(name),
        `${path} replaces the global '${name}'. Add it to SHARED_GLOBALS in ` +
          `src/test/setup.ts so it does not leak into the next file in the worker.`,
      ).toBe(true)
    },
  )
})
