"""Generate the reference meshes the measurement tests read (task T001).

Run from ``backend/``: ``python -m tests.fixtures.meshes.make_fixtures``.
The output is deterministic, so regenerating leaves the files byte for byte
unchanged (zip entries carry a fixed timestamp).

Every block is the same 40 × 30 × 20 mm box unless stated otherwise, so each
fixture's expected size follows from what it does to that box.
"""

import struct
import zipfile
from pathlib import Path
from typing import Optional

HERE = Path(__file__).parent
ZIP_DATE = (2026, 10, 25, 0, 0, 0)

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>'
    "</Types>"
)
RELS = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Target="/3D/3dmodel.model" Id="rel0" '
    'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>'
    "</Relationships>"
)
CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PROD_NS = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"


def box(lx: float, ly: float, lz: float, origin=(0.0, 0.0, 0.0)):
    """Vertices and triangles of an axis-aligned box."""
    ox, oy, oz = origin
    verts = [(ox + x, oy + y, oz + z) for z in (0.0, lz) for y in (0.0, ly) for x in (0.0, lx)]
    tris = [
        (0, 2, 1), (1, 2, 3),  # bottom
        (4, 5, 6), (5, 7, 6),  # top
        (0, 1, 4), (1, 5, 4),  # front
        (2, 6, 3), (3, 6, 7),  # back
        (0, 4, 2), (2, 4, 6),  # left
        (1, 3, 5), (3, 7, 5),  # right
    ]  # fmt: skip
    return verts, tris


def binary_stl(verts, tris, header: bytes = b"solid block (binary)") -> bytes:
    out = bytearray(header.ljust(80, b" "))
    out += struct.pack("<I", len(tris))
    for a, b, c in tris:
        out += struct.pack("<12fH", 0, 0, 0, *verts[a], *verts[b], *verts[c], 0)
    return bytes(out)


def ascii_stl(verts, tris) -> bytes:
    lines = ["solid block"]
    for a, b, c in tris:
        lines += ["  facet normal 0 0 0", "    outer loop"]
        lines += [
            f"      vertex {x:.6f} {y:.6f} {z:.6f}" for x, y, z in (verts[a], verts[b], verts[c])
        ]
        lines += ["    endloop", "  endfacet"]
    lines.append("endsolid block")
    return ("\n".join(lines) + "\n").encode()


def mesh_xml(verts, tris) -> str:
    v = "".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in verts)
    t = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in tris)
    return f"<mesh><vertices>{v}</vertices><triangles>{t}</triangles></mesh>"


def model_xml(objects: str, build: str, unit: str = "millimeter", extra_ns: str = "") -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<model unit="{unit}" xml:lang="en-US" xmlns="{CORE_NS}"{extra_ns}>'
        f"<resources>{objects}</resources><build>{build}</build></model>"
    )


def three_mf(parts: dict[str, str]) -> bytes:
    from io import BytesIO

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        entries = {"[Content_Types].xml": CONTENT_TYPES, "_rels/.rels": RELS, **parts}
        for name, text in entries.items():
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, text)
    return buf.getvalue()


def simple_3mf(verts, tris, *, transform: Optional[str] = None, unit: str = "millimeter") -> bytes:
    obj = f'<object id="1" name="Block" type="model">{mesh_xml(verts, tris)}</object>'
    attr = f' transform="{transform}"' if transform else ""
    return three_mf({"3D/3dmodel.model": model_xml(obj, f'<item objectid="1"{attr}/>', unit)})


def build_all() -> dict[str, bytes]:
    verts, tris = box(40, 30, 20)
    small_verts, small_tris = box(10, 10, 10)
    inch_verts, inch_tris = box(1, 1, 1)

    two = model_xml(
        f'<object id="1" name="Body" type="model">{mesh_xml(verts, tris)}</object>'
        f'<object id="2" name="Stand" type="model">{mesh_xml(small_verts, small_tris)}</object>',
        # The stand sits 50 mm along X, so the build is 60 × 30 × 20.
        '<item objectid="1"/><item objectid="2" transform="1 0 0 0 1 0 0 0 1 50 0 0"/>',
    )
    bambu_root = model_xml(
        '<object id="2" name="Block" type="model"><components>'
        '<component p:path="/3D/Objects/object_1.model" objectid="1"/>'
        "</components></object>",
        '<item objectid="2"/>',
        extra_ns=f' xmlns:p="{PROD_NS}"',
    )
    bambu_object = model_xml(f'<object id="1" type="model">{mesh_xml(verts, tris)}</object>', "")

    return {
        # A binary STL whose header starts with "solid", as many exporters write.
        "block_binary.stl": binary_stl(verts, tris),
        "block_ascii.stl": ascii_stl(verts, tris),
        "block.3mf": simple_3mf(verts, tris),
        # 90° about Z and 2× scale, row-vector convention of the 3MF spec:
        # x' = -2y, y' = 2x, z' = 2z → 60 × 80 × 40.
        "block_rotated_scaled.3mf": simple_3mf(verts, tris, transform="0 2 0 -2 0 0 0 0 2 0 0 0"),
        "block_inches.3mf": simple_3mf(inch_verts, inch_tris, unit="inch"),
        "two_objects.3mf": three_mf({"3D/3dmodel.model": two}),
        "bambu_objects.3mf": three_mf(
            {"3D/3dmodel.model": bambu_root, "3D/Objects/object_1.model": bambu_object}
        ),
        "not_a_mesh.stl": bytes((i * 73 + 11) % 256 for i in range(517)),
    }


def main() -> None:
    for name, data in build_all().items():
        (HERE / name).write_bytes(data)
        print(f"wrote {name} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
