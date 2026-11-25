/**
 * A click on the part, in the file's own coordinates (spec 004, FR-025).
 */
import * as THREE from 'three'
import type { ThreeEvent } from '@react-three/fiber'

import type { Vector3 } from '@/types/model-file-version'

export interface PartPick {
  position: Vector3
  normal: Vector3
  layer?: number | null
}

/** Turn a hit into file coordinates: the parent group only translates. */
export function localPick(event: ThreeEvent<MouseEvent>, layer?: number | null): PartPick {
  const parent = event.object.parent
  const point = parent ? parent.worldToLocal(event.point.clone()) : event.point.clone()
  const normal = event.face?.normal
    ? event.face.normal.clone().transformDirection(event.object.matrixWorld)
    : new THREE.Vector3(0, 0, 1)
  const round = (v: number) => Math.round(v * 100) / 100
  return {
    position: [round(point.x), round(point.y), round(point.z)],
    normal: [normal.x, normal.y, normal.z].map((v) => Math.round(v * 10000) / 10000) as Vector3,
    layer,
  }
}
