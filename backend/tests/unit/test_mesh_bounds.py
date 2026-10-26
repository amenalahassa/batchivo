"""Bounding boxes of STL and 3MF files (T033, research D3, SC-003, SC-007)."""

import struct
import time
from decimal import Decimal
from pathlib import Path


from app.services import mesh_bounds
from app.services.dims import Dims
from app.services.mesh_bounds import measure

MESHES = Path(__file__).parent.parent / "fixtures" / "meshes"


def _read(name: str) -> bytes:
    return (MESHES / name).read_bytes()


def _d(length, width, height) -> Dims:
    return Dims(Decimal(str(length)), Decimal(str(width)), Decimal(str(height)))


BLOCK = _d("40.0", "30.0", "20.0")


# ============================================
# STL
# ============================================


class TestStl:
    def test_binary_block(self):
        m = measure(_read("block_binary.stl"), ".stl")
        assert m.status == "done"
        assert m.overall == BLOCK

    def test_binary_with_solid_header_is_read_as_binary(self):
        data = _read("block_binary.stl")
        assert data.startswith(b"solid")
        assert measure(data, "stl").overall == BLOCK

    def test_ascii_block(self):
        m = measure(_read("block_ascii.stl"), ".stl")
        assert m.overall == BLOCK
        assert m.objects == []

    def test_sizes_are_decimals_to_a_tenth(self):
        m = measure(_read("block_binary.stl"), ".stl")
        assert str(m.overall.length) == "40.0"

    def test_random_bytes_fail_with_a_note(self):
        m = measure(_read("not_a_mesh.stl"), ".stl")
        assert m.overall is None
        assert m.status == "failed"
        assert m.note


# ============================================
# 3MF
# ============================================


class TestThreeMF:
    def test_block(self):
        assert measure(_read("block.3mf"), ".3mf").overall == BLOCK

    def test_rotated_and_scaled_transform(self):
        assert measure(_read("block_rotated_scaled.3mf"), ".3mf").overall == _d(
            "60.0", "80.0", "40.0"
        )

    def test_inch_unit_converts_to_mm(self):
        assert measure(_read("block_inches.3mf"), ".3mf").overall == _d("25.4", "25.4", "25.4")

    def test_two_objects_listed_with_the_build_size(self):
        m = measure(_read("two_objects.3mf"), ".3mf")
        assert m.overall == _d("60.0", "30.0", "20.0")
        assert [name for name, _ in m.objects] == ["Body", "Stand"]
        assert m.objects[0][1] == BLOCK
        assert m.objects[1][1] == _d("10.0", "10.0", "10.0")
        assert "assembled" in m.note

    def test_bambu_component_file(self):
        m = measure(_read("bambu_objects.3mf"), ".3mf")
        assert m.overall == BLOCK
        assert m.note is None

    def test_not_a_zip_fails_with_a_note(self):
        m = measure(_read("not_a_mesh.stl"), ".3mf")
        assert m.status == "failed"
        assert "zip" in m.note


# ============================================
# Limits and other types
# ============================================


class TestLimits:
    def test_gcode_has_no_measurement(self):
        assert measure(b"G1 X0 Y0\n", ".gcode") is None

    def test_a_flat_mesh_is_not_a_size(self):
        tri = struct.pack("<12fH", 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0)
        m = measure(b"\0" * 80 + struct.pack("<I", 1) + tri, ".stl")
        assert m.status == "failed"
        assert "flat" in m.note

    def test_over_the_limit_is_skipped(self, monkeypatch):
        monkeypatch.setattr(mesh_bounds, "MAX_MEASURE_BYTES", 100)
        m = measure(_read("block_binary.stl"), ".stl")
        assert m.status == "skipped"
        assert m.overall is None
        assert "limit" in m.note

    def test_25mb_binary_stl_measures_in_under_a_second(self):
        count = (mesh_bounds.INLINE_MEASURE_BYTES - 84) // 50
        tri = struct.pack("<12fH", 0, 0, 0, 0, 0, 0, 10, 0, 0, 0, 5, 3, 0)
        data = b"\0" * 80 + struct.pack("<I", count) + tri * count
        start = time.perf_counter()
        m = measure(data, ".stl")
        elapsed = time.perf_counter() - start
        assert m.overall == _d("10.0", "5.0", "3.0")
        assert elapsed < 1.0, f"took {elapsed:.2f}s"
