"""Model files for the versions, viewer and notes tests (spec 004, T002).

Built in code rather than checked in as binaries so each one says what it is:
a sliced Bambu plate is a zip with plate G-code and a 3D part whose build is
empty, which is exactly why measuring it fails with "no geometry".
"""

import io
import zipfile
from pathlib import Path

MESHES = Path(__file__).resolve().parent / "meshes"

#: The header lines Bambu Studio and OrcaSlicer write; the viewer reads the same ones.
GCODE_HEADER = """; HEADER_BLOCK_START
; BambuStudio 02.00.00.00
; model printing time: 1h 52m 0s; total estimated time: 1h 58m 0s
; total layer number: 3
; HEADER_BLOCK_END
; CONFIG_BLOCK_START
; printer_model = Bambu Lab A1
; filament_type = PLA
; nozzle_diameter = 0.4
; CONFIG_BLOCK_END
"""

GCODE_BODY = """G90
M83
G1 Z0.2 F600
;LAYER_CHANGE
G1 X10 Y10 F3000
G1 X30 Y10 E1.0
G1 X30 Y30 E1.0
;LAYER_CHANGE
G1 Z0.4
G1 X10 Y30 E1.0
G1 X10 Y10 E1.0
;LAYER_CHANGE
G1 Z0.6
G1 X20 Y20 E0.5
"""

EMPTY_BUILD_MODEL = """<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
  <resources/>
  <build/>
</model>
"""

SLICE_INFO_PLATE = """  <plate>
    <metadata key="index" value="{index}"/>
    <metadata key="prediction" value="{seconds}"/>
    <metadata key="weight" value="{weight}"/>
{objects}{filaments}  </plate>
"""


def plain_gcode() -> bytes:
    return (GCODE_HEADER + GCODE_BODY).encode()


def sliced_3mf(
    plates: int = 2,
    seconds: int = 6720,
    weight: str = "41.00",
    objects: int | None = 1,
    filaments: list[tuple[str, str, str]] | None = None,
) -> bytes:
    """A Bambu ``.gcode.3mf``: plate G-code and slice info, no mesh in the build.

    Each plate prints ``objects`` objects (``None``: the plate lists none) and
    uses ``filaments`` as (type, colour, grams); by default one black PLA of
    ``weight`` grams.
    """
    uses = filaments if filaments is not None else [("PLA", "#000000FF", weight)]
    object_lines = "".join(
        f'    <object identify_id="{100 + n}" name="part_{n}" skipped="false"/>\n'
        for n in range(objects or 0)
    )
    filament_lines = "".join(
        f'    <filament id="{n + 1}" type="{t}" color="{c}" used_m="1.0" used_g="{g}"/>\n'
        for n, (t, c, g) in enumerate(uses)
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("3D/3dmodel.model", EMPTY_BUILD_MODEL)
        plate_elements = "".join(
            SLICE_INFO_PLATE.format(
                index=i,
                seconds=seconds,
                weight=weight,
                objects=object_lines,
                filaments=filament_lines,
            )
            for i in range(1, plates + 1)
        )
        info = f'<?xml version="1.0" encoding="UTF-8"?>\n<config>\n{plate_elements}</config>\n'
        zf.writestr("Metadata/slice_info.config", info)
        for i in range(1, plates + 1):
            zf.writestr(f"Metadata/plate_{i}.gcode", GCODE_HEADER + GCODE_BODY)
    return buffer.getvalue()


def block_stl() -> bytes:
    """A 40 x 30 x 20 mm block (the existing mesh fixture)."""
    return (MESHES / "block_binary.stl").read_bytes()


def block_3mf() -> bytes:
    """A project 3MF with a mesh in its build."""
    return (MESHES / "block.3mf").read_bytes()
