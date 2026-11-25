"""The 3MF reader keeps each plate filament's slicer number (spec 011, T003).

The printer's start command maps filaments to AMS slots by that number, so it
must survive parsing; the other fields keep their existing meaning.
"""

from app.services.model_file_service import parse_3mf_metadata
from tests.fixtures.sliced_3mf import sliced_project

BAD_ID = """<?xml version="1.0"?>
<config><plate>
  <metadata key="index" value="1"/>
  <filament type="PLA" color="#FF0000" used_g="3.0"/>
  <filament id="x" type="PLA" color="#FF0000" used_g="2.0"/>
</plate></config>
"""


def test_filament_ids_are_read_per_plate():
    result = parse_3mf_metadata(sliced_project())

    plate_1 = next(p for p in result.plates if p.index == 1)
    assert [f.id for f in plate_1.filaments] == [1, 3]
    assert [f.type for f in plate_1.filaments] == ["PLA", "PETG"]
    assert [f.color for f in plate_1.filaments] == ["#FF0000", "#00FF00"]
    assert [f.grams for f in plate_1.filaments] == [30.10, 5.00]
    assert plate_1.print_time_minutes == 95
    assert plate_1.filament_weight_grams == 35.10

    plate_2 = next(p for p in result.plates if p.index == 2)
    assert [f.id for f in plate_2.filaments] == [2]


def test_missing_or_invalid_id_is_none():
    result = parse_3mf_metadata(sliced_project(slice_info=BAD_ID, plates=(1,)))

    assert [f.id for f in result.plates[0].filaments] == [None, None]
