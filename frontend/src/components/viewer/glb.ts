/** Parse and measure a GLB for the AI 3D draft preview (spec 008, Q4). */
import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'

interface ParsedGlb {
  scene: THREE.Object3D
  size: THREE.Vector3
  center: THREE.Vector3
}

/** Parse a GLB into a Z-up scene, and measure it. */
export async function parseGlb(buffer: ArrayBuffer): Promise<ParsedGlb> {
  const gltf = await new GLTFLoader().parseAsync(buffer, '')
  const scene = gltf.scene
  // glTF is Y-up; the viewer is Z-up like the slicer.
  scene.rotation.x = Math.PI / 2
  scene.updateMatrixWorld(true)
  const box = new THREE.Box3().setFromObject(scene)
  return {
    scene,
    size: box.getSize(new THREE.Vector3()),
    center: box.getCenter(new THREE.Vector3()),
  }
}
