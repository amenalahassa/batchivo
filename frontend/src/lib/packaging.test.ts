/**
 * @vitest-environment node
 *
 * Which file measurement the screens offer to adopt.
 */

import { describe, expect, it } from 'vitest'

import type { ModelFile } from '@/lib/api/models'
import { fileNamesOf, latestMeasurementOffer } from './packaging'

function file(id: string, uploaded: string, measurement: ModelFile['measurement']): ModelFile {
  return {
    id,
    model_id: 'm',
    file_type: 'source_stl',
    file_location: 'uploaded',
    original_filename: `${id}.stl`,
    is_primary: false,
    uploaded_at: uploaded,
    created_at: uploaded,
    updated_at: uploaded,
    measurement,
  }
}

const done = (l: string) => ({
  length_mm: l,
  width_mm: '30.0',
  height_mm: '20.0',
  objects: [],
  note: null,
  status: 'done' as const,
  applied_to: [],
})

describe('latestMeasurementOffer', () => {
  it('offers the newest finished measurement', () => {
    const offer = latestMeasurementOffer([
      file('old', '2026-10-01T00:00:00Z', done('40.0')),
      file('new', '2026-10-20T00:00:00Z', done('41.0')),
    ])
    expect(offer).toEqual({
      fileId: 'new',
      fileName: 'new.stl',
      length_mm: '41.0',
      width_mm: '30.0',
      height_mm: '20.0',
    })
  })

  it('offers nothing pending, failed or absent', () => {
    expect(
      latestMeasurementOffer([
        file('p', '2026-10-20T00:00:00Z', { ...done('1.0'), status: 'pending', length_mm: null }),
        file('f', '2026-10-21T00:00:00Z', { ...done('1.0'), status: 'failed' }),
        file('g', '2026-10-22T00:00:00Z', null),
      ]),
    ).toBeNull()
    expect(latestMeasurementOffer(undefined)).toBeNull()
  })
})

describe('fileNamesOf', () => {
  it('maps ids to file names', () => {
    expect(fileNamesOf([file('a', '2026-10-01T00:00:00Z', null)])).toEqual({ a: 'a.stl' })
  })
})
