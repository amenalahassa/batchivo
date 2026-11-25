"""GLB (binary glTF 2.0) to binary STL, pure Python (research R11).

Image-to-3D models return a GLB. Batchivo's model files, measurement and 3D
viewer read STL, so an adopted draft is converted once here and goes through
the unchanged model-file upload path. Only what a mesh needs is read: the
default scene's node tree (matrix or translation/rotation/scale), triangle
primitives, float32 VEC3 positions and optional u8/u16/u32 indices. Textures,
normals and materials are ignored; Draco-compressed meshes are refused.
"""

import json
import struct
from typing import Iterator, Optional

from app.services.genai.errors import InputInvalid

GLB_MAGIC = b"glTF"
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942
MAX_TRIANGLES = 5_000_000

_COMPONENT = {5121: ("B", 1), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
_TYPE_SIZE = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

Matrix = tuple[float, ...]  # column-major 4x4, as glTF stores it
IDENTITY: Matrix = (1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0)


def _mul(a: Matrix, b: Matrix) -> Matrix:
    """a·b for column-major 4x4 matrices."""
    out = [0.0] * 16
    for col in range(4):
        for row in range(4):
            out[col * 4 + row] = sum(a[k * 4 + row] * b[col * 4 + k] for k in range(4))
    return tuple(out)


def _trs(node: dict) -> Matrix:
    if "matrix" in node:
        return tuple(float(v) for v in node["matrix"])
    tx, ty, tz = (float(v) for v in node.get("translation", (0, 0, 0)))
    qx, qy, qz, qw = (float(v) for v in node.get("rotation", (0, 0, 0, 1)))
    sx, sy, sz = (float(v) for v in node.get("scale", (1, 1, 1)))
    r = (
        1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy + qz * qw), 2 * (qx * qz - qy * qw),
        2 * (qx * qy - qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz + qx * qw),
        2 * (qx * qz + qy * qw), 2 * (qy * qz - qx * qw), 1 - 2 * (qx * qx + qy * qy),
    )  # fmt: skip
    return (
        r[0] * sx, r[1] * sx, r[2] * sx, 0.0,
        r[3] * sy, r[4] * sy, r[5] * sy, 0.0,
        r[6] * sz, r[7] * sz, r[8] * sz, 0.0,
        tx, ty, tz, 1.0,
    )  # fmt: skip


def _apply(m: Matrix, p: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = p
    return (
        m[0] * x + m[4] * y + m[8] * z + m[12],
        m[1] * x + m[5] * y + m[9] * z + m[13],
        m[2] * x + m[6] * y + m[10] * z + m[14],
    )


class _Glb:
    def __init__(self, content: bytes) -> None:
        if len(content) < 20 or content[:4] != GLB_MAGIC:
            raise InputInvalid("Not a GLB file")
        version, length = struct.unpack_from("<II", content, 4)
        if version != 2:
            raise InputInvalid(f"Unsupported glTF version {version}")
        offset = 12
        self.json: Optional[dict] = None
        self.bin = b""
        end = min(length, len(content))
        while offset + 8 <= end:
            chunk_len, chunk_type = struct.unpack_from("<II", content, offset)
            data = content[offset + 8 : offset + 8 + chunk_len]
            if chunk_type == CHUNK_JSON:
                try:
                    self.json = json.loads(data.decode("utf-8"))
                except (UnicodeDecodeError, ValueError) as exc:
                    raise InputInvalid("Malformed GLB JSON chunk") from exc
            elif chunk_type == CHUNK_BIN and not self.bin:
                self.bin = data
            offset += 8 + chunk_len
        if self.json is None:
            raise InputInvalid("GLB has no JSON chunk")
        used = set(self.json.get("extensionsUsed") or [])
        if "KHR_draco_mesh_compression" in used or "EXT_meshopt_compression" in used:
            raise InputInvalid("Compressed GLB meshes are not supported")

    def accessor(self, index: int) -> list[tuple]:
        acc = self.json["accessors"][index]
        if acc.get("sparse"):
            raise InputInvalid("Sparse accessors are not supported")
        fmt, size = _COMPONENT.get(acc["componentType"], (None, 0))
        if fmt is None:
            raise InputInvalid("Unsupported accessor component type")
        n_comp = _TYPE_SIZE[acc["type"]]
        count = int(acc["count"])
        if "bufferView" not in acc:
            return [(0,) * n_comp] * count
        view = self.json["bufferViews"][acc["bufferView"]]
        if view.get("buffer", 0) != 0:
            raise InputInvalid("External buffers are not supported")
        base = int(view.get("byteOffset", 0)) + int(acc.get("byteOffset", 0))
        stride = int(view.get("byteStride") or size * n_comp)
        need = base + stride * (count - 1) + size * n_comp if count else base
        if need > len(self.bin):
            raise InputInvalid("GLB buffer is shorter than its accessors")
        item = struct.Struct("<" + fmt * n_comp)
        return [item.unpack_from(self.bin, base + i * stride) for i in range(count)]

    def triangles(self) -> Iterator[tuple[tuple, tuple, tuple]]:
        scenes = self.json.get("scenes") or []
        nodes = self.json.get("nodes") or []
        meshes = self.json.get("meshes") or []
        if scenes:
            roots = scenes[int(self.json.get("scene", 0))].get("nodes", [])
        else:
            children = {c for n in nodes for c in n.get("children", [])}
            roots = [i for i in range(len(nodes)) if i not in children]
        stack: list[tuple[int, Matrix, int]] = [(r, IDENTITY, 0) for r in roots]
        while stack:
            idx, parent, depth = stack.pop()
            if depth > 64:
                raise InputInvalid("GLB node tree too deep")
            node = nodes[idx]
            world = _mul(parent, _trs(node))
            if "mesh" in node:
                for prim in meshes[node["mesh"]].get("primitives", []):
                    yield from self._primitive(prim, world)
            for child in node.get("children", []):
                stack.append((child, world, depth + 1))

    def _primitive(self, prim: dict, world: Matrix) -> Iterator[tuple[tuple, tuple, tuple]]:
        if prim.get("mode", 4) != 4:
            return
        attrs = prim.get("attributes", {})
        if "POSITION" not in attrs:
            return
        positions = [_apply(world, p) for p in self.accessor(attrs["POSITION"])]
        if "indices" in prim:
            idx = [i[0] for i in self.accessor(prim["indices"])]
        else:
            idx = list(range(len(positions)))
        for i in range(0, len(idx) - 2, 3):
            a, b, c = idx[i], idx[i + 1], idx[i + 2]
            if max(a, b, c) >= len(positions):
                raise InputInvalid("GLB index out of range")
            yield positions[a], positions[b], positions[c]


def _normal(a: tuple, b: tuple, c: tuple) -> tuple[float, float, float]:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    length = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
    return nx / length, ny / length, nz / length


def to_stl(content: bytes) -> bytes:
    """Convert a GLB to a binary STL; ``InputInvalid`` if it cannot be read."""
    glb = _Glb(content)
    facets: list[bytes] = []
    record = struct.Struct("<12fH")
    try:
        for a, b, c in glb.triangles():
            if len(facets) >= MAX_TRIANGLES:
                raise InputInvalid("The mesh has too many triangles")
            facets.append(record.pack(*_normal(a, b, c), *a, *b, *c, 0))
    except (KeyError, IndexError, TypeError, struct.error) as exc:
        raise InputInvalid(f"Malformed GLB: {type(exc).__name__}") from exc
    if not facets:
        raise InputInvalid("The GLB holds no triangles")
    header = b"Batchivo AI draft (converted from GLB)".ljust(80, b" ")
    return header + struct.pack("<I", len(facets)) + b"".join(facets)


def build_glb(positions: list[tuple[float, float, float]], indices: Optional[list[int]] = None,
              *, matrix: Optional[list[float]] = None) -> bytes:  # fmt: skip
    """A minimal GLB holding one triangle mesh (used by tests and the e2e fake provider)."""
    bin_parts = b"".join(struct.pack("<3f", *p) for p in positions)
    pos_len = len(bin_parts)
    accessors = [
        {
            "bufferView": 0,
            "componentType": 5126,
            "count": len(positions),
            "type": "VEC3",
            "min": [min(p[i] for p in positions) for i in range(3)],
            "max": [max(p[i] for p in positions) for i in range(3)],
        }
    ]
    views = [{"buffer": 0, "byteOffset": 0, "byteLength": pos_len}]
    primitive: dict = {"attributes": {"POSITION": 0}, "mode": 4}
    if indices is not None:
        idx_bytes = b"".join(struct.pack("<I", i) for i in indices)
        views.append({"buffer": 0, "byteOffset": pos_len, "byteLength": len(idx_bytes)})
        accessors.append(
            {"bufferView": 1, "componentType": 5125, "count": len(indices), "type": "SCALAR"}
        )
        primitive["indices"] = 1
        bin_parts += idx_bytes
    node: dict = {"mesh": 0}
    if matrix is not None:
        node["matrix"] = matrix
    gltf = {
        "asset": {"version": "2.0"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [node],
        "meshes": [{"primitives": [primitive]}],
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(bin_parts)}],
    }
    js = json.dumps(gltf).encode()
    js += b" " * (-len(js) % 4)
    bin_parts += b"\0" * (-len(bin_parts) % 4)
    body = (
        struct.pack("<II", len(js), CHUNK_JSON) + js + struct.pack("<II", len(bin_parts), CHUNK_BIN)
        + bin_parts
    )  # fmt: skip
    return GLB_MAGIC + struct.pack("<II", 2, 12 + len(body)) + body


__all__ = ["MAX_TRIANGLES", "build_glb", "to_stl"]
