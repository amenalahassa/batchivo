"""Measure an STL or 3MF file's bounding box (research D3, FR-007 to FR-010).

Pure Python, no geometry dependency: a binary STL is read with ``struct``, an
ASCII STL line by line, and a 3MF through ``zipfile`` and ``iterparse``,
following components into ``/3D/Objects/*.model`` as Bambu and Orca write
them, composing the 3MF transforms and applying the model's unit.

Floats live only inside the parsing; every size leaves as a ``Decimal`` to
0.1 mm. A file that cannot be read is never an error: ``measure`` returns a
``Measurement`` with no size and a note saying why, and the upload goes on
(FR-010).
"""

import logging
import struct
import sys
from array import array
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal
from io import BytesIO
from typing import Iterable, Optional
from xml.etree import ElementTree

from app.services.dims import Dims

logger = logging.getLogger(__name__)

#: Measured inside the upload request up to this size (SC-007: under 1 s).
INLINE_MEASURE_BYTES = 25 * 1024 * 1024
#: Measured by the Celery task up to this size; larger files are not measured.
MAX_MEASURE_BYTES = 200 * 1024 * 1024

MEASURABLE_EXTENSIONS = (".stl", ".3mf")

#: Millimetres per 3MF unit (3MF core spec, "unit" attribute of <model>).
UNIT_MM = {
    "micron": 0.001,
    "millimeter": 1.0,
    "centimeter": 10.0,
    "inch": 25.4,
    "foot": 304.8,
    "meter": 1000.0,
}


# An affine transform as the 3MF spec writes it: m00 m01 m02 m10 … m32,
# applied to a row vector, so x' = x·m00 + y·m10 + z·m20 + m30.
Matrix = tuple[float, ...]
IDENTITY: Matrix = (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)

Bounds = tuple[float, float, float, float, float, float]  # minx, miny, minz, maxx, maxy, maxz


@dataclass(frozen=True)
class Measurement:
    """What a file measured: the overall size, each object's, and any note.

    ``overall`` is None when the file could not be measured; ``status`` is then
    ``failed`` or ``skipped`` and ``note`` says why.
    """

    overall: Optional[Dims]
    objects: list[tuple[str, Dims]] = field(default_factory=list)
    note: Optional[str] = None
    status: str = "done"


class _Unreadable(Exception):
    """A file the parser could not make sense of; its message is the note."""


def is_measurable(filename_or_extension: str) -> bool:
    return filename_or_extension.lower().endswith(MEASURABLE_EXTENSIONS)


def measure(file_bytes: bytes, extension: str) -> Optional[Measurement]:
    """Measure a mesh file; None for a file type that has no geometry (G-code)."""
    ext = extension.lower()
    if not ext.startswith("."):
        ext = f".{ext}"
    if ext not in MEASURABLE_EXTENSIONS:
        return None
    if len(file_bytes) > MAX_MEASURE_BYTES:
        return skipped(len(file_bytes))
    try:
        if ext == ".stl":
            return _plausible(_measure_stl(file_bytes))
        return _plausible(_measure_3mf(file_bytes))
    except _Unreadable as exc:
        return Measurement(overall=None, note=str(exc), status="failed")
    except Exception as exc:  # noqa: BLE001 - a bad file must never fail an upload
        logger.warning(f"Could not measure {ext} file: {exc}")
        return Measurement(
            overall=None,
            note=f"Could not read the file's geometry ({type(exc).__name__})",
            status="failed",
        )


#: The largest length a dimension column holds (Numeric(7, 1)).
_MAX_MM = Decimal("999999.9")


def _plausible(measurement: Measurement) -> Measurement:
    """Refuse a size no item can have: a flat mesh, or one beyond any real object."""
    overall = measurement.overall
    if overall is None:
        return measurement
    sides = overall.as_tuple()
    if any(side <= 0 for side in sides):
        raise _Unreadable("The mesh is flat: it has no size along at least one axis")
    if any(side > _MAX_MM for side in sides):
        raise _Unreadable("The mesh is larger than any printable object; check its units")
    return measurement


def skipped(size: int) -> Measurement:
    """A file too large to measure (research D3)."""
    limit_mb = MAX_MEASURE_BYTES // (1024 * 1024)
    return Measurement(
        overall=None,
        note=f"Not measured: the file is {size / (1024 * 1024):.0f} MB, over the {limit_mb} MB limit",
        status="skipped",
    )


def _dims(bounds: Bounds, scale: float = 1.0) -> Dims:
    minx, miny, minz, maxx, maxy, maxz = bounds
    return Dims(
        Decimal(repr((maxx - minx) * scale)),
        Decimal(repr((maxy - miny) * scale)),
        Decimal(repr((maxz - minz) * scale)),
    ).quantize()


def _union(a: Optional[Bounds], b: Bounds) -> Bounds:
    if a is None:
        return b
    return (
        min(a[0], b[0]), min(a[1], b[1]), min(a[2], b[2]),
        max(a[3], b[3]), max(a[4], b[4]), max(a[5], b[5]),
    )  # fmt: skip


# ============================================
# STL
# ============================================


def _measure_stl(data: bytes) -> Measurement:
    if len(data) >= 84:
        (count,) = struct.unpack_from("<I", data, 80)
        expected = 84 + 50 * count
        # A binary file often starts with "solid" too, so the length decides (D3).
        if count and len(data) == expected:
            return Measurement(overall=_dims(_binary_stl_bounds(data, count)))
        if data[:5].lower() != b"solid" and count and len(data) > expected:
            # Some exporters pad the end; the triangles are still all there.
            return Measurement(overall=_dims(_binary_stl_bounds(data, count)))
    if data[:5].lower() == b"solid":
        return Measurement(overall=_dims(_ascii_stl_bounds(data)))
    raise _Unreadable("Not an STL file: neither a binary nor an ASCII mesh")


def _binary_stl_bounds(data: bytes, count: int) -> Bounds:
    """Min and max of every vertex coordinate, without a Python loop per triangle.

    Each 50-byte record holds a normal, three vertices and an attribute. For
    every coordinate, four strided byte slices gather its float's bytes from
    all records at once, and ``array`` reads them back as floats (SC-007).
    """
    end = 84 + 50 * count
    lo: list[float] = []
    hi: list[float] = []
    for axis in range(3):
        axis_lo, axis_hi = float("inf"), float("-inf")
        for vertex in range(3):
            offset = 84 + 12 + vertex * 12 + axis * 4
            packed = bytearray(4 * count)
            for byte in range(4):
                packed[byte::4] = data[offset + byte : end : 50]
            floats = array("f", packed)
            if sys.byteorder != "little":
                floats.byteswap()
            axis_lo = min(axis_lo, min(floats))
            axis_hi = max(axis_hi, max(floats))
        lo.append(axis_lo)
        hi.append(axis_hi)
    return (lo[0], lo[1], lo[2], hi[0], hi[1], hi[2])


def _ascii_stl_bounds(data: bytes) -> Bounds:
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    seen = False
    for raw in data.splitlines():
        line = raw.strip()
        if not line.startswith(b"vertex"):
            continue
        parts = line.split()
        if len(parts) != 4:
            raise _Unreadable("Malformed ASCII STL: a vertex line without three numbers")
        for axis in range(3):
            v = float(parts[axis + 1])
            if v < lo[axis]:
                lo[axis] = v
            if v > hi[axis]:
                hi[axis] = v
        seen = True
    if not seen:
        raise _Unreadable("The STL file has no vertices")
    return (lo[0], lo[1], lo[2], hi[0], hi[1], hi[2])


# ============================================
# 3MF
# ============================================

_CORE = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
_PROD = "{http://schemas.microsoft.com/3dmanufacturing/production/2015/06}"


def _matrix(text: Optional[str]) -> Matrix:
    if not text:
        return IDENTITY
    values = tuple(float(v) for v in text.split())
    if len(values) != 12:
        raise _Unreadable("Malformed 3MF transform")
    return values


def _compose(inner: Matrix, outer: Matrix) -> Matrix:
    """The transform that applies ``inner`` first, then ``outer``."""
    a, b = inner, outer
    out = []
    for row in range(4):
        r = a[row * 3 : row * 3 + 3]
        for col in range(3):
            v = r[0] * b[col] + r[1] * b[3 + col] + r[2] * b[6 + col]
            if row == 3:
                v += b[9 + col]
            out.append(v)
    return tuple(out)


def _apply_bounds(vertices: list[tuple[float, float, float]], m: Matrix) -> Optional[Bounds]:
    if not vertices:
        return None
    if m == IDENTITY:
        xs = [v[0] for v in vertices]
        ys = [v[1] for v in vertices]
        zs = [v[2] for v in vertices]
    else:
        xs, ys, zs = [], [], []
        for x, y, z in vertices:
            xs.append(x * m[0] + y * m[3] + z * m[6] + m[9])
            ys.append(x * m[1] + y * m[4] + z * m[7] + m[10])
            zs.append(x * m[2] + y * m[5] + z * m[8] + m[11])
    return (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))


@dataclass
class _Object:
    name: Optional[str]
    vertices: list[tuple[float, float, float]] = field(default_factory=list)
    # (path or None for this part, object id, transform)
    components: list[tuple[Optional[str], str, Matrix]] = field(default_factory=list)


@dataclass
class _Part:
    unit: float
    objects: dict[str, _Object]
    build: list[tuple[str, Matrix, Optional[str]]]


def _parse_part(stream) -> _Part:
    """One model part: its objects (mesh vertices or components) and build items."""
    unit = 1.0
    objects: dict[str, _Object] = {}
    build: list[tuple[str, Matrix, Optional[str]]] = []
    current: Optional[_Object] = None
    for event, elem in ElementTree.iterparse(stream, events=("start", "end")):
        tag = elem.tag
        if event == "start":
            if tag == f"{_CORE}model":
                name = elem.get("unit", "millimeter")
                if name not in UNIT_MM:
                    raise _Unreadable(f"Unknown 3MF unit '{name}'")
                unit = UNIT_MM[name]
            elif tag == f"{_CORE}object":
                current = _Object(name=elem.get("name"))
                objects[elem.get("id", "")] = current
            continue
        # end events: the attributes are complete, and the element can go.
        if tag == f"{_CORE}vertex" and current is not None:
            current.vertices.append(
                (float(elem.get("x", 0)), float(elem.get("y", 0)), float(elem.get("z", 0)))
            )
        elif tag == f"{_CORE}component" and current is not None:
            current.components.append(
                (elem.get(f"{_PROD}path"), elem.get("objectid", ""), _matrix(elem.get("transform")))
            )
        elif tag == f"{_CORE}object":
            current = None
        elif tag == f"{_CORE}item":
            build.append(
                (elem.get("objectid", ""), _matrix(elem.get("transform")), elem.get(f"{_PROD}path"))
            )
        if tag in (f"{_CORE}vertex", f"{_CORE}triangle", f"{_CORE}item", f"{_CORE}component"):
            elem.clear()
    return _Part(unit=unit, objects=objects, build=build)


def _root_model_path(zf: zipfile.ZipFile) -> str:
    names = {n.lower(): n for n in zf.namelist()}
    if "3d/3dmodel.model" in names:
        return names["3d/3dmodel.model"]
    for lower, name in names.items():
        if lower.startswith("3d/") and lower.endswith(".model") and "/objects/" not in lower:
            return name
    raise _Unreadable("Not a 3MF file: no 3D model part in the package")


def _measure_3mf(data: bytes) -> Measurement:
    try:
        zf = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile:
        raise _Unreadable("Not a 3MF file: the package is not a zip archive") from None
    with zf:
        names = {n.lower().lstrip("/"): n for n in zf.namelist()}
        parts: dict[str, _Part] = {}

        def part(path: str) -> _Part:
            key = path.lower().lstrip("/")
            if key not in parts:
                if key not in names:
                    raise _Unreadable(f"The 3MF refers to a missing part {path}")
                with zf.open(names[key]) as stream:
                    parts[key] = _parse_part(stream)
            return parts[key]

        root_path = _root_model_path(zf)
        root = part(root_path)

        def bounds_of(path: str, object_id: str, m: Matrix, depth: int = 0) -> Optional[Bounds]:
            if depth > 16:
                raise _Unreadable("The 3MF components nest too deeply")
            p = part(path)
            obj = p.objects.get(object_id)
            if obj is None:
                raise _Unreadable(f"The 3MF build names an object ({object_id}) it does not define")
            # A part's own unit scales its vertices before any transform.
            scale = p.unit / root.unit
            m_scaled = _compose((scale, 0, 0, 0, scale, 0, 0, 0, scale, 0, 0, 0), m)
            total = _apply_bounds(obj.vertices, m_scaled)
            for comp_path, comp_id, comp_m in obj.components:
                b = bounds_of(comp_path or path, comp_id, _compose(comp_m, m), depth + 1)
                if b is not None:
                    total = _union(total, b)
            return total

        overall: Optional[Bounds] = None
        objects: list[tuple[str, Dims]] = []
        for index, (object_id, m, item_path) in enumerate(root.build, start=1):
            b = bounds_of(item_path or root_path, object_id, m)
            if b is None:
                continue
            obj = part(item_path or root_path).objects[object_id]
            objects.append((obj.name or f"Object {index}", _dims(b, root.unit)))
            overall = _union(overall, b)

    if overall is None:
        raise _Unreadable("The 3MF build has no geometry")
    note = None
    if len(objects) > 1:
        note = (
            f"{len(objects)} objects; the overall size is the build plate as laid out, "
            "which may not be the assembled size"
        )
    return Measurement(overall=_dims(overall, root.unit), objects=objects, note=note)


def objects_json(objects: Iterable[tuple[str, Dims]]) -> list[dict]:
    """Per-object sizes as stored on ``model_files.measured_objects``."""
    return [
        {
            "name": name,
            "length_mm": str(d.length),
            "width_mm": str(d.width),
            "height_mm": str(d.height),
        }
        for name, d in objects
    ]
