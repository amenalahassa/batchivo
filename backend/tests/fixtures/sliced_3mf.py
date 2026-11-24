"""In-memory Bambu Studio sliced projects (``.gcode.3mf``) for the print send tests (spec 011).

Built rather than checked in so each test can see exactly what the file
declares: two plates; plate 1 uses filament 1 (PLA, red, 30.10 g) and
filament 3 (PETG, green, 5.00 g), predicted 5700 s and 35.10 g.
"""

import zipfile
from io import BytesIO

SLICE_INFO = """<?xml version="1.0" encoding="UTF-8"?>
<config>
  <header><header_item key="X-BBL-Client-Type" value="slicer"/></header>
  <plate>
    <metadata key="index" value="1"/>
    <metadata key="prediction" value="5700"/>
    <metadata key="weight" value="35.10"/>
    <object identify_id="1" name="dragon" skipped="false"/>
    <filament id="1" tray_info_idx="GFA00" type="PLA" color="#FF0000" used_m="10" used_g="30.10"/>
    <filament id="3" tray_info_idx="GFG00" type="PETG" color="#00FF00FF" used_m="2" used_g="5.00"/>
  </plate>
  <plate>
    <metadata key="index" value="2"/>
    <metadata key="prediction" value="600"/>
    <metadata key="weight" value="4.00"/>
    <filament id="2" type="PLA" color="#000000" used_m="1" used_g="4.00"/>
  </plate>
</config>
"""


def sliced_project(*, slice_info: str = SLICE_INFO, plates: tuple[int, ...] = (1, 2)) -> bytes:
    """A sliced Bambu project with plate G-code for each plate in ``plates``."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("3D/3dmodel.model", "<model/>")
        zf.writestr("Metadata/slice_info.config", slice_info)
        for plate in plates:
            zf.writestr(f"Metadata/plate_{plate}.gcode", f"; plate {plate}\nG28\n")
    return buffer.getvalue()


def unsliced_project() -> bytes:
    """A 3MF project with metadata but no plate G-code (not sliced)."""
    return sliced_project(plates=())
