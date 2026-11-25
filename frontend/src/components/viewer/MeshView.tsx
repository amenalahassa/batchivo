/**
 * A mesh drawn as a solid (spec 004, T041; FR-018).
 *
 * Clicking it reports the point and surface normal in the file's own
 * coordinates, for pinning a note (FR-025).
 */
import { useMemo } from 'react'
import * as THREE from 'three'

import type { MeshData } from '@/lib/viewer/mesh'
import { localPick, type PartPick } from './pick'

interface MeshViewProps {
  mesh: MeshData
  onPick?: (pick: PartPick) => void
}

export function MeshView({ mesh, onPick }: MeshViewProps) {
  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(mesh.positions, 3))
    g.computeVertexNormals()
    g.computeBoundingSphere()
    return g
  }, [mesh])

  return (
    <mesh
      geometry={geometry}
      onClick={(event) => {
        if (!onPick) return
        event.stopPropagation()
        onPick(localPick(event))
      }}
    >
      <meshStandardMaterial color="#60a5fa" metalness={0.05} roughness={0.7} side={THREE.DoubleSide} />
    </mesh>
  )
}
