/**
 * @vitest-environment node
 *
 * No DOM here, so no jsdom. Building one costs more than this file's tests
 * take to run, and a budget spent before a test starts is what made the suite
 * depend on how loaded the machine was (task T174, Constitution II).
 */
/**
 * The router stub in `src/test/setup.ts` must cover what the app imports.
 *
 * The stub replaced an `importActual` passthrough, which is what made the
 * suite slow enough to time out. The passthrough's one virtue was that it
 * could not be incomplete: anything a component imported was really there.
 *
 * This is what replaces that virtue. It reads the imports out of the source
 * and fails naming any export the stub does not provide -- so a component
 * reaching for a new router API is a clear failure here rather than an
 * `undefined is not a function` inside an unrelated render.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

const SRC = join(__dirname, '..')
const MODULE = '@tanstack/react-router'

/** Every `.ts`/`.tsx` file under `src`, tests included. */
function sourceFiles(dir: string, found: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) {
      sourceFiles(path, found)
    } else if (/\.tsx?$/.test(entry)) {
      found.push(path)
    }
  }
  return found
}

/** The named imports each file takes from the router, with the file. */
function importsOfTheRouter(): Map<string, string[]> {
  const pattern = new RegExp(String.raw`import\s+(?:type\s+)?\{([^}]*)\}\s*from\s*['"]${MODULE}['"]`, 'g')
  const byName = new Map<string, string[]>()

  for (const file of sourceFiles(SRC)) {
    const text = readFileSync(file, 'utf8')
    for (const match of text.matchAll(pattern)) {
      for (const part of match[1].split(',')) {
        const name = part.trim().replace(/^type\s+/, '').split(/\s+as\s+/)[0].trim()
        if (!name) continue
        byName.set(name, [...(byName.get(name) ?? []), file])
      }
    }
  }
  return byName
}

/** The exports the stub actually defines, read through the mock itself. */
async function stubbedExports(): Promise<Set<string>> {
  const stub = await import(MODULE)
  return new Set(Object.keys(stub))
}

describe('the router stub', () => {
  it('provides every export the app imports', async () => {
    const stubbed = await stubbedExports()
    const used = importsOfTheRouter()

    const missing = [...used.keys()].filter((name) => !stubbed.has(name))
    expect(
      missing,
      `src/test/setup.ts stubs @tanstack/react-router and these imported ` +
        `exports are not in it: ${missing
          .map((name) => `${name} (${used.get(name)?.[0]})`)
          .join(', ')}. Add them to the mock.`,
    ).toEqual([])
  })

  it('is reading real imports, so an empty result cannot pass it vacuously', () => {
    const used = importsOfTheRouter()
    expect(used.size).toBeGreaterThan(5)
    expect([...used.keys()]).toContain('Link')
  })

  it('refuses to fake a router rather than building a broken one', async () => {
    // The two tests that need a genuine router unmock the module; everything
    // else would get a router that silently routes nowhere, so the stub says so.
    const stub = await import(MODULE)
    expect(() => stub.createRouter({})).toThrow(/vi\.unmock/)
  })
})
