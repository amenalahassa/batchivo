/**
 * The viewer's 3D canvas (spec 004, T040; FR-020).
 *
 * Z is up, as in the slicer and the G-code. The planned printer's bed is drawn
 * at true size from (0, 0) to (X, Y) mm, so a part that is off the bed or too
 * large for it shows as such.
 */
import type { ReactNode } from 'react'
import { Canvas } from '@react-three/fiber'
import { Line, OrbitControls } from '@react-three/drei'

export interface Bed {
  x: number
  y: number
}

interface ViewerCanvasProps {
  bed: Bed | null
  /** Where to look: the centre of what is drawn. */
  target: [number, number, number]
  /** Largest extent of what is drawn, to place the camera. */
  extent: number
  children: ReactNode
}

function BedOutline({ bed }: { bed: Bed }) {
  const z = 0
  const grid: [number, number, number][][] = []
  for (let gx = 0; gx <= bed.x; gx += 50) grid.push([[gx, 0, z], [gx, bed.y, z]])
  for (let gy = 0; gy <= bed.y; gy += 50) grid.push([[0, gy, z], [bed.x, gy, z]])
  return (
    <group>
      {grid.map((points, i) => (
        <Line key={i} points={points} color="#94a3b8" lineWidth={0.5} transparent opacity={0.35} />
      ))}
      <Line
        points={[
          [0, 0, z],
          [bed.x, 0, z],
          [bed.x, bed.y, z],
          [0, bed.y, z],
          [0, 0, z],
        ]}
        color="#64748b"
        lineWidth={1.5}
      />
    </group>
  )
}

export function ViewerCanvas({ bed, target, extent, children }: ViewerCanvasProps) {
  const distance = Math.max(extent, bed ? Math.max(bed.x, bed.y) : 0, 20) * 1.6
  return (
    <Canvas
      camera={{
        up: [0, 0, 1],
        position: [target[0] + distance * 0.6, target[1] - distance, target[2] + distance * 0.8],
        fov: 40,
        near: 0.1,
        far: distance * 20,
      }}
      raycaster={{ params: { Line: { threshold: 0.6 }, Points: { threshold: 1 }, Mesh: {}, LOD: {}, Sprite: {} } }}
      dpr={[1, 2]}
    >
      <ambientLight intensity={0.6} />
      <directionalLight position={[1, -1, 2]} intensity={0.9} />
      <directionalLight position={[-1, 1, 1]} intensity={0.3} />
      {bed && <BedOutline bed={bed} />}
      {children}
      <OrbitControls makeDefault target={target} />
    </Canvas>
  )
}
