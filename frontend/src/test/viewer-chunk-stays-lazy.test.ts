/**
 * @vitest-environment node
 *
 * three.js stays out of every page but the viewer (spec 004, T056; FR-024, SC-007).
 *
 * The viewer and everything that imports three, @react-three/* or the parse
 * worker live under `components/viewer/`, and the only way in from the rest of
 * the app is `React.lazy(() => import('@/components/viewer/ModelViewerDialog'))`.
 * A static import from anywhere else would pull ~600 kB into that page's
 * chunk; this test fails first. `scripts/check-viewer-chunk.mjs` checks the
 * built output the same way after `npm run build`.
 */

import { readFileSync, readdirSync } from 'node:fs'
import { join, relative, sep } from 'node:path'

import { describe, expect, it } from 'vitest'

const SRC = join(__dirname, '..')

function sourceFiles(dir: string): string[] {
  const out: string[] = []
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name)
    if (entry.isDirectory()) out.push(...sourceFiles(full))
    else if (/\.(ts|tsx)$/.test(entry.name) && !/\.(test|stories)\.tsx?$/.test(entry.name)) out.push(full)
  }
  return out
}

const rel = (file: string) => relative(SRC, file).split(sep).join('/')
const VIEWER = /^components\/viewer\//
const HEAVY = /from ['"](three(\/[^'"]*)?|@react-three\/[^'"]+)['"]/
const STATIC_VIEWER = /from ['"](@\/components\/viewer\/[^'"]+|\.\.?\/(\.\.\/)*viewer\/[^'"]+)['"]/

describe('the 3D viewer is a lazy chunk', () => {
  const files = sourceFiles(SRC).filter((f) => !rel(f).startsWith('test/'))

  it('only the viewer imports three.js', () => {
    const offenders = files
      .filter((f) => !VIEWER.test(rel(f)))
      .filter((f) => readFileSync(f, 'utf8').split('\n').some((line) => /^\s*import\b/.test(line) && HEAVY.test(line) && !/import\s+type\b/.test(line)))
      .map(rel)
    expect(offenders).toEqual([])
  })

  it('nothing outside the viewer imports it statically', () => {
    const offenders = files
      .filter((f) => !VIEWER.test(rel(f)))
      .filter((f) => readFileSync(f, 'utf8').split('\n').some((line) => /^\s*import\b(?!\s+type\b)/.test(line) && STATIC_VIEWER.test(line)))
      .map(rel)
    expect(offenders).toEqual([])
  })

  it('the files card opens it through React.lazy', () => {
    const editor = readFileSync(join(SRC, 'components/models/ModelFilesEditor.tsx'), 'utf8')
    expect(editor).toMatch(/lazy\(\(\) => import\('@\/components\/viewer\/ModelViewerDialog'\)\)/)
  })
})
