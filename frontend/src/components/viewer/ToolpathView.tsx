/**
 * Toolpaths drawn as line segments up to a chosen layer (spec 004, T041; FR-019).
 *
 * Layers below the chosen one are drawn faint, the chosen layer bright; a
 * click on the chosen layer pins a note there, recording the layer (FR-025).
 */
import { useMemo } from 'react'
import * as THREE from 'three'

import { layerDrawRanges, type Toolpath } from '@/lib/viewer/gcode'
import { localPick, type PartPick } from './pick'

interface ToolpathViewProps {
  toolpath: Toolpath
  /** Index into `toolpath.layers` of the top layer shown. */
  layer: number
  onPick?: (pick: PartPick) => void
}

export function ToolpathView({ toolpath, layer, onPick }: ToolpathViewProps) {
  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(toolpath.positions, 3))
    return g
  }, [toolpath])

  const [below, top] = useMemo(() => {
    const ranges = layerDrawRanges(toolpath, layer)
    const faint = geometry.clone()
    faint.setDrawRange(...ranges.below)
    const bright = geometry.clone()
    bright.setDrawRange(...ranges.top)
    return [faint, bright]
  }, [geometry, toolpath, layer])

  return (
    <group>
      <lineSegments geometry={below}>
        <lineBasicMaterial color="#64748b" transparent opacity={0.55} />
      </lineSegments>
      <lineSegments
        geometry={top}
        onClick={(event) => {
          if (!onPick) return
          event.stopPropagation()
          const pick = localPick(event, layer)
          onPick({ ...pick, normal: [0, 0, 1] })
        }}
      >
        <lineBasicMaterial color="#f97316" />
      </lineSegments>
    </group>
  )
}
