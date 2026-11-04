"""Why a file could not be measured, and whether it is a sliced plate (research D3, D11, T010)."""

import io
import zipfile

from app.services import mesh_bounds
from tests.fixtures.model_files import block_3mf, block_stl, plain_gcode, sliced_3mf


class TestReasons:
    def test_a_sliced_plate_has_no_geometry(self) -> None:
        measurement = mesh_bounds.measure(sliced_3mf(), ".3mf")
        assert measurement.status == "failed"
        assert measurement.reason == mesh_bounds.REASON_NO_GEOMETRY

    def test_a_mesh_measures_with_no_reason(self) -> None:
        measurement = mesh_bounds.measure(block_stl(), ".stl")
        assert measurement.status == "done"
        assert measurement.reason is None

    def test_garbage_is_unreadable(self) -> None:
        measurement = mesh_bounds.measure(b"not a mesh at all", ".stl")
        assert measurement.status == "failed"
        assert measurement.reason == mesh_bounds.REASON_UNREADABLE

    def test_too_large_is_skipped_with_its_reason(self) -> None:
        measurement = mesh_bounds.skipped(mesh_bounds.MAX_MEASURE_BYTES + 1)
        assert measurement.status == "skipped"
        assert measurement.reason == mesh_bounds.REASON_TOO_LARGE


class TestIsSliced:
    def test_gcode_names(self) -> None:
        assert mesh_bounds.is_sliced("plate.gcode")
        assert mesh_bounds.is_sliced("Plate.GCODE.3MF")

    def test_a_renamed_sliced_3mf_is_recognised_by_its_contents(self) -> None:
        assert mesh_bounds.is_sliced("lub_emptyer.3mf", sliced_3mf())

    def test_a_project_3mf_is_not_sliced(self) -> None:
        assert not mesh_bounds.is_sliced("block.3mf", block_3mf())

    def test_an_stl_is_not_sliced(self) -> None:
        assert not mesh_bounds.is_sliced("block.stl", block_stl())

    def test_a_broken_zip_is_not_sliced(self) -> None:
        assert not mesh_bounds.is_sliced("broken.3mf", b"PK\x03\x04 truncated")

    def test_without_contents_the_name_decides(self) -> None:
        assert not mesh_bounds.is_sliced("lub_emptyer.3mf")
        assert mesh_bounds.is_sliced("x.gcode", plain_gcode())

    def test_other_metadata_gcode_is_not_a_plate(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zf:
            zf.writestr("Metadata/custom.gcode", "G1 X0")
        assert not mesh_bounds.is_sliced("x.3mf", buffer.getvalue())
