#!/usr/bin/env node
/**
 * After `npm run build`: three.js must not be in the entry chunk (spec 004,
 * T056; SC-007). The entry is the script `dist/index.html` loads, plus the
 * chunks it preloads; three's renderer class name marks where it landed.
 *
 * Usage: node scripts/check-viewer-chunk.mjs [distDir]
 */
import { readFileSync, readdirSync } from 'node:fs'
import { join } from 'node:path'

const dist = process.argv[2] ?? 'dist'
const html = readFileSync(join(dist, 'index.html'), 'utf8')
const eager = [...html.matchAll(/(?:src|href)="\/?(assets\/[^"]+\.js)"/g)].map((m) => m[1])
const MARK = 'WebGLRenderer'

const bad = eager.filter((file) => readFileSync(join(dist, file), 'utf8').includes(MARK))
const holders = readdirSync(join(dist, 'assets'))
  .filter((f) => f.endsWith('.js'))
  .filter((f) => readFileSync(join(dist, 'assets', f), 'utf8').includes(MARK))

if (bad.length > 0) {
  console.error(`three.js is in the entry: ${bad.join(', ')}`)
  process.exit(1)
}
if (holders.length === 0) {
  console.error('three.js was not found in any chunk: is the viewer still built?')
  process.exit(1)
}
console.log(`three.js is lazy: ${holders.join(', ')} (entry: ${eager.join(', ')})`)
