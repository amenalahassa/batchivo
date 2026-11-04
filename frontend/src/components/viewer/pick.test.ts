/**
 * @vitest-environment node
 *
 * A click on the part in the file's own coordinates (spec 004, T062; FR-025).
 */
import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import type { ThreeEvent } from '@react-three/fiber'

import { localPick } from './pick'

function hit(offset: [number, number, number], point: [number, number, number], normal?: [number, number, number]) {
  const group = new THREE.Group()
  group.position.set(...offset)
  const mesh = new THREE.Mesh()
  group.add(mesh)
  group.updateMatrixWorld(true)
  return {
    object: mesh,
    point: new THREE.Vector3(...point),
    face: normal ? { normal: new THREE.Vector3(...normal) } : null,
  } as unknown as ThreeEvent<MouseEvent>
}

describe('localPick', () => {
  it('takes away the placement offset so the note keeps the file coordinates', () => {
    const pick = localPick(hit([100, 50, 0], [112.345, 53, 7.5], [0, 0, 1]))
    expect(pick.position).toEqual([12.35, 3, 7.5])
    expect(pick.normal).toEqual([0, 0, 1])
    expect(pick.layer).toBeUndefined()
  })

  it('keeps the layer and faces up when there is no face', () => {
    const pick = localPick(hit([0, 0, 0], [1, 2, 0.4]), 3)
    expect(pick).toEqual({ position: [1, 2, 0.4], normal: [0, 0, 1], layer: 3 })
  })
})
