"""GLB to STL conversion, branch by branch (spec 008 research R11, T033, T100).

GLB bytes are built by hand with ``struct`` so each test exercises exactly one
rule of ``app/services/genai/glb.py``; every refusal is an ``InputInvalid``.
"""

import json
import math
import struct
from typing import Optional

import pytest

from app.services.genai import glb
from app.services.genai.errors import InputInvalid
from app.services.genai.glb import CHUNK_BIN, CHUNK_JSON, GLB_MAGIC, build_glb, to_stl

TRIANGLE = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (0.0, 20.0, 0.0)]


def _pack(gltf: dict, bin_data: bytes = b"", *, version: int = 2) -> bytes:
    """A GLB container around a glTF JSON document and an optional BIN chunk."""
    js = json.dumps(gltf).encode()
    js += b" " * (-len(js) % 4)
    body = struct.pack("<II", len(js), CHUNK_JSON) + js
    if bin_data:
        bin_data += b"\0" * (-len(bin_data) % 4)
        body += struct.pack("<II", len(bin_data), CHUNK_BIN) + bin_data
    return GLB_MAGIC + struct.pack("<II", version, 12 + len(body)) + body


def _positions(points) -> bytes:
    return b"".join(struct.pack("<3f", *p) for p in points)


def _document(
    *,
    primitives: Optional[list] = None,
    accessors: Optional[list] = None,
    views: Optional[list] = None,
    nodes: Optional[list] = None,
    scenes: Optional[list] = None,
    **extra,
) -> dict:
    """A glTF document whose defaults describe one triangle at accessor 0, view 0."""
    doc = {
        "asset": {"version": "2.0"},
        "nodes": nodes if nodes is not None else [{"mesh": 0}],
        "meshes": [{"primitives": primitives or [{"attributes": {"POSITION": 0}}]}],
        "accessors": accessors
        or [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"}],
        "bufferViews": views or [{"buffer": 0, "byteOffset": 0, "byteLength": 36}],
        "buffers": [{"byteLength": 36}],
        **extra,
    }
    if scenes is not None:
        doc["scenes"] = scenes
        doc["scene"] = 0
    return doc


def _facets(stl: bytes) -> list[list[tuple[float, float, float]]]:
    """The three vertices of each STL facet, rounded to 4 places."""
    (count,) = struct.unpack_from("<I", stl, 80)
    out = []
    for i in range(count):
        values = struct.unpack_from("<12f", stl, 84 + i * 50)
        out.append([tuple(round(v, 4) for v in values[3 + k * 3 : 6 + k * 3]) for k in range(3)])
    return out


def _refused(content: bytes, match: str) -> None:
    with pytest.raises(InputInvalid, match=match):
        to_stl(content)


# ============================================
# Container
# ============================================


def test_not_a_glb():
    _refused(b"not a glb at all", "Not a GLB file")
    _refused(GLB_MAGIC + b"\0" * 8, "Not a GLB file")  # shorter than 20 bytes


def test_wrong_version():
    _refused(_pack(_document(), _positions(TRIANGLE), version=1), "Unsupported glTF version 1")


def test_no_json_chunk():
    data = _positions(TRIANGLE)
    body = struct.pack("<II", len(data), CHUNK_BIN) + data
    _refused(GLB_MAGIC + struct.pack("<II", 2, 12 + len(body)) + body, "no JSON chunk")


def test_malformed_json_chunk():
    js = b"{not json}  "
    body = struct.pack("<II", len(js), CHUNK_JSON) + js
    _refused(GLB_MAGIC + struct.pack("<II", 2, 12 + len(body)) + body, "Malformed GLB JSON")


@pytest.mark.parametrize("extension", ["KHR_draco_mesh_compression", "EXT_meshopt_compression"])
def test_compressed_meshes_refused(extension):
    doc = _document(extensionsUsed=[extension])
    _refused(_pack(doc, _positions(TRIANGLE)), "Compressed GLB meshes are not supported")


def test_other_extensions_are_ignored():
    doc = _document(extensionsUsed=["KHR_materials_unlit"])
    assert len(_facets(to_stl(_pack(doc, _positions(TRIANGLE))))) == 1


def test_build_glb_round_trip():
    stl = to_stl(build_glb(TRIANGLE, [0, 1, 2]))
    assert stl[:80].startswith(b"Batchivo AI draft")
    assert _facets(stl) == [TRIANGLE]


# ============================================
# Accessors
# ============================================


def test_sparse_accessor_refused():
    accessors = [
        {
            "bufferView": 0,
            "componentType": 5126,
            "count": 3,
            "type": "VEC3",
            "sparse": {"count": 1, "indices": {}, "values": {}},
        }
    ]
    _refused(_pack(_document(accessors=accessors), _positions(TRIANGLE)), "Sparse accessors")


def test_external_buffer_refused():
    views = [{"buffer": 1, "byteOffset": 0, "byteLength": 36}]
    doc = _document(views=views)
    doc["buffers"].append({"byteLength": 36, "uri": "mesh.bin"})
    _refused(_pack(doc, _positions(TRIANGLE)), "External buffers are not supported")


def test_unsupported_component_type_refused():
    accessors = [{"bufferView": 0, "componentType": 5120, "count": 3, "type": "VEC3"}]
    _refused(_pack(_document(accessors=accessors), _positions(TRIANGLE)), "component type")


def test_buffer_shorter_than_accessor_refused():
    accessors = [{"bufferView": 0, "componentType": 5126, "count": 4, "type": "VEC3"}]
    _refused(_pack(_document(accessors=accessors), _positions(TRIANGLE)), "buffer is shorter")


def test_accessor_without_buffer_view_reads_zeros():
    # A degenerate triangle at the origin is still a triangle.
    accessors = [{"componentType": 5126, "count": 3, "type": "VEC3"}]
    assert _facets(to_stl(_pack(_document(accessors=accessors), b"\0" * 4))) == [
        [(0.0, 0.0, 0.0)] * 3
    ]


def test_byte_stride_skips_interleaved_attributes():
    # POSITION then a 12-byte NORMAL per vertex: stride 24, the normals must be skipped.
    data = b"".join(struct.pack("<3f", *p) + struct.pack("<3f", 9, 9, 9) for p in TRIANGLE)
    views = [{"buffer": 0, "byteOffset": 0, "byteLength": len(data), "byteStride": 24}]
    assert _facets(to_stl(_pack(_document(views=views), data))) == [TRIANGLE]


def test_view_and_accessor_offsets_add_up():
    data = b"\xff" * 8 + b"\xee" * 4 + _positions(TRIANGLE)
    views = [{"buffer": 0, "byteOffset": 8, "byteLength": 48}]
    accessors = [
        {"bufferView": 0, "byteOffset": 4, "componentType": 5126, "count": 3, "type": "VEC3"}
    ]
    assert _facets(to_stl(_pack(_document(views=views, accessors=accessors), data))) == [TRIANGLE]


# ============================================
# Indices and primitives
# ============================================


QUAD = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0), (10.0, 10.0, 0.0), (0.0, 10.0, 0.0)]


@pytest.mark.parametrize("component, fmt", [(5121, "B"), (5123, "H"), (5125, "I")])
def test_indexed_primitives(component, fmt):
    indices = [0, 1, 2, 0, 2, 3]
    positions = _positions(QUAD)
    index_bytes = struct.pack(f"<{len(indices)}{fmt}", *indices)
    data = positions + index_bytes
    views = [
        {"buffer": 0, "byteOffset": 0, "byteLength": len(positions)},
        {"buffer": 0, "byteOffset": len(positions), "byteLength": len(index_bytes)},
    ]
    accessors = [
        {"bufferView": 0, "componentType": 5126, "count": 4, "type": "VEC3"},
        {"bufferView": 1, "componentType": component, "count": 6, "type": "SCALAR"},
    ]
    doc = _document(
        views=views, accessors=accessors, primitives=[{"attributes": {"POSITION": 0}, "indices": 1}]
    )
    assert _facets(to_stl(_pack(doc, data))) == [
        [QUAD[0], QUAD[1], QUAD[2]],
        [QUAD[0], QUAD[2], QUAD[3]],
    ]


def test_non_indexed_primitive_reads_vertices_in_order():
    six = TRIANGLE + [(0.0, 0.0, 5.0), (1.0, 0.0, 5.0), (0.0, 1.0, 5.0)]
    accessors = [{"bufferView": 0, "componentType": 5126, "count": 6, "type": "VEC3"}]
    views = [{"buffer": 0, "byteOffset": 0, "byteLength": 72}]
    facets = _facets(to_stl(_pack(_document(accessors=accessors, views=views), _positions(six))))
    assert facets == [TRIANGLE, six[3:]]


def test_trailing_vertices_short_of_a_triangle_are_ignored():
    accessors = [{"bufferView": 0, "componentType": 5126, "count": 4, "type": "VEC3"}]
    views = [{"buffer": 0, "byteOffset": 0, "byteLength": 48}]
    data = _positions(TRIANGLE + [(5.0, 5.0, 5.0)])
    assert len(_facets(to_stl(_pack(_document(accessors=accessors, views=views), data)))) == 1


def test_index_out_of_range_refused():
    data = _positions(TRIANGLE) + struct.pack("<3I", 0, 1, 7)
    views = [
        {"buffer": 0, "byteOffset": 0, "byteLength": 36},
        {"buffer": 0, "byteOffset": 36, "byteLength": 12},
    ]
    accessors = [
        {"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3"},
        {"bufferView": 1, "componentType": 5125, "count": 3, "type": "SCALAR"},
    ]
    doc = _document(
        views=views, accessors=accessors, primitives=[{"attributes": {"POSITION": 0}, "indices": 1}]
    )
    _refused(_pack(doc, data), "index out of range")


@pytest.mark.parametrize("mode", [0, 1, 5, 6])
def test_non_triangle_modes_are_skipped(mode):
    # A points, lines, strip or fan primitive is skipped; alone, nothing is left.
    only = _document(primitives=[{"attributes": {"POSITION": 0}, "mode": mode}])
    _refused(_pack(only, _positions(TRIANGLE)), "holds no triangles")
    mixed = _document(
        primitives=[
            {"attributes": {"POSITION": 0}, "mode": mode},
            {"attributes": {"POSITION": 0}, "mode": 4},
        ]
    )
    assert _facets(to_stl(_pack(mixed, _positions(TRIANGLE)))) == [TRIANGLE]


def test_primitive_without_positions_is_skipped():
    doc = _document(primitives=[{"attributes": {"NORMAL": 0}}])
    _refused(_pack(doc, _positions(TRIANGLE)), "holds no triangles")


def test_triangle_cap(monkeypatch):
    monkeypatch.setattr(glb, "MAX_TRIANGLES", 1)
    six = TRIANGLE + [(0.0, 0.0, 5.0), (1.0, 0.0, 5.0), (0.0, 1.0, 5.0)]
    accessors = [{"bufferView": 0, "componentType": 5126, "count": 6, "type": "VEC3"}]
    views = [{"buffer": 0, "byteOffset": 0, "byteLength": 72}]
    _refused(_pack(_document(accessors=accessors, views=views), _positions(six)), "too many")
    # exactly at the cap is fine
    assert len(_facets(to_stl(_pack(_document(), _positions(TRIANGLE))))) == 1


def test_missing_references_are_malformed():
    doc = _document(nodes=[{"mesh": 3}])
    _refused(_pack(doc, _positions(TRIANGLE)), "Malformed GLB: IndexError")
    doc = _document(accessors=[{"bufferView": 0, "count": 3, "type": "VEC3"}])
    _refused(_pack(doc, _positions(TRIANGLE)), "Malformed GLB: KeyError")


# ============================================
# Node tree and transforms
# ============================================


def test_translation_applied():
    doc = _document(nodes=[{"mesh": 0, "translation": [1, 2, 3]}])
    assert _facets(to_stl(_pack(doc, _positions(TRIANGLE)))) == [
        [(1.0, 2.0, 3.0), (11.0, 2.0, 3.0), (1.0, 22.0, 3.0)]
    ]


def test_scale_applied():
    doc = _document(nodes=[{"mesh": 0, "scale": [2, 3, 4]}])
    assert _facets(to_stl(_pack(doc, _positions(TRIANGLE)))) == [
        [(0.0, 0.0, 0.0), (20.0, 0.0, 0.0), (0.0, 60.0, 0.0)]
    ]


def test_rotation_applied():
    # 90 degrees about Z: x goes to y, y goes to -x.
    half = math.sqrt(0.5)
    doc = _document(nodes=[{"mesh": 0, "rotation": [0, 0, half, half]}])
    assert _facets(to_stl(_pack(doc, _positions(TRIANGLE)))) == [
        [(0.0, 0.0, 0.0), (0.0, 10.0, 0.0), (-20.0, 0.0, 0.0)]
    ]


def test_trs_order_is_scale_rotate_translate():
    half = math.sqrt(0.5)
    node = {"mesh": 0, "translation": [100, 0, 0], "rotation": [0, 0, half, half], "scale": [2] * 3}
    assert _facets(to_stl(_pack(_document(nodes=[node]), _positions(TRIANGLE)))) == [
        [(100.0, 0.0, 0.0), (100.0, 20.0, 0.0), (60.0, 0.0, 0.0)]
    ]


def test_matrix_wins_over_trs():
    matrix = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 5, 6, 7, 1]
    node = {"mesh": 0, "matrix": matrix, "translation": [100, 100, 100]}
    assert _facets(to_stl(_pack(_document(nodes=[node]), _positions(TRIANGLE))))[0][0] == (
        5.0,
        6.0,
        7.0,
    )


def test_parent_transform_applies_to_children():
    nodes = [{"translation": [0, 0, 10], "children": [1]}, {"mesh": 0, "translation": [1, 0, 0]}]
    doc = _document(nodes=nodes, scenes=[{"nodes": [0]}])
    assert _facets(to_stl(_pack(doc, _positions(TRIANGLE))))[0][0] == (1.0, 0.0, 10.0)


def test_without_scenes_roots_are_nodes_nobody_parents():
    # Node 1 is node 0's child: it is drawn once, through its parent, not twice.
    nodes = [{"translation": [0, 0, 10], "children": [1]}, {"mesh": 0}]
    facets = _facets(to_stl(_pack(_document(nodes=nodes), _positions(TRIANGLE))))
    assert facets == [[(0.0, 0.0, 10.0), (10.0, 0.0, 10.0), (0.0, 20.0, 10.0)]]


def test_only_the_default_scene_is_read():
    nodes = [{"mesh": 0}, {"mesh": 0, "translation": [0, 0, 50]}]
    doc = _document(nodes=nodes, scenes=[{"nodes": [0]}, {"nodes": [1]}])
    doc["scene"] = 1
    assert _facets(to_stl(_pack(doc, _positions(TRIANGLE))))[0][0] == (0.0, 0.0, 50.0)


def test_node_tree_too_deep_refused():
    depth = 70
    nodes = [{"children": [i + 1]} for i in range(depth)] + [{"mesh": 0}]
    doc = _document(nodes=nodes, scenes=[{"nodes": [0]}])
    _refused(_pack(doc, _positions(TRIANGLE)), "node tree too deep")


def test_node_tree_at_the_depth_limit_is_read():
    nodes = [{"children": [i + 1]} for i in range(64)] + [{"mesh": 0}]
    doc = _document(nodes=nodes, scenes=[{"nodes": [0]}])
    assert len(_facets(to_stl(_pack(doc, _positions(TRIANGLE))))) == 1


def test_a_cycle_is_refused_as_too_deep():
    nodes = [{"mesh": 0, "children": [1]}, {"children": [0]}]
    doc = _document(nodes=nodes, scenes=[{"nodes": [0]}])
    _refused(_pack(doc, _positions(TRIANGLE)), "node tree too deep")
