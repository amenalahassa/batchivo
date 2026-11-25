"""Print figures read from a print file (research D4).

`parse_gcode_metadata` reads a plain G-code file's slicer comments;
`combined_figures` turns a parsed file into the figures the activation review
proposes -- all plates together, as the model form's auto-fill combines them.
"""

from decimal import Decimal

from app.schemas.model_file import ThreeMFParseResponse, ThreeMFPlateMetadata
from app.services.model_file_service import parse_3mf_metadata, parse_gcode_metadata
from app.services.model_file_version_service import combined_figures
from tests.fixtures.model_files import plain_gcode, sliced_3mf


class TestGcodeHeader:
    def test_bambu_header(self) -> None:
        parsed = parse_gcode_metadata(plain_gcode())
        assert parsed.print_time_minutes == 118
        assert parsed.plate_count is None
        assert parsed.slicer_detected == "bambu_orca"

    def test_prusaslicer_footer(self) -> None:
        body = b"G1 X1\n" * 10 + (
            b"; filament used [g] = 3.20, 1.30\n"
            b"; estimated printing time (normal mode) = 1d 2h 3m 4s\n"
        )
        parsed = parse_gcode_metadata(body)
        assert parsed.print_time_minutes == 26 * 60 + 3
        assert parsed.filament_weight_grams == 4.5

    def test_total_weight_wins_over_per_extruder(self) -> None:
        parsed = parse_gcode_metadata(
            b"; total filament weight [g] : 12.34\n; filament used [g] = 1.0\n"
        )
        assert parsed.filament_weight_grams == 12.34

    def test_nothing_known_is_nothing_guessed(self) -> None:
        parsed = parse_gcode_metadata(b"G28\nG1 X10 Y10\n")
        assert (parsed.print_time_minutes, parsed.filament_weight_grams) == (None, None)


class TestCombinedFigures:
    def test_all_plates_of_a_sliced_3mf(self) -> None:
        figures = combined_figures(parse_3mf_metadata(sliced_3mf(plates=2, objects=3)))
        assert (figures.minutes, figures.plates, figures.weight) == (224, 2, Decimal("82.0"))
        # Items are the objects the run prints, not the plates (T064).
        assert figures.items == 6
        assert [(f.type, f.color, f.grams) for f in figures.filaments] == [
            ("PLA", "#000000", Decimal("82.00"))
        ]

    def test_items_are_unknown_when_a_plate_lists_no_objects(self) -> None:
        figures = combined_figures(parse_3mf_metadata(sliced_3mf(plates=2, objects=None)))
        assert figures.items is None

    def test_skipped_objects_are_not_counted_and_filaments_are_read(self) -> None:
        import io
        import zipfile

        source = zipfile.ZipFile(io.BytesIO(sliced_3mf(plates=1, objects=3)))
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as zf:
            for name in source.namelist():
                data = source.read(name)
                if name == "Metadata/slice_info.config":
                    data = data.replace(
                        b'name="part_0" skipped="false"', b'name="part_0" skipped="true"'
                    )
                zf.writestr(name, data)
        assert parse_3mf_metadata(out.getvalue()).plates[0].object_count == 2
        plate = parse_3mf_metadata(
            sliced_3mf(plates=1, filaments=[("PETG", "#00ff00", "4.5")])
        ).plates[0]
        assert [(f.type, f.color, f.grams) for f in plate.filaments] == [("PETG", "#00FF00", 4.5)]

    def test_plates_missing_a_figure_are_skipped_not_zeroed(self) -> None:
        parsed = ThreeMFParseResponse(
            plates=[
                ThreeMFPlateMetadata(index=1, print_time_minutes=10, filament_weight_grams=None),
                ThreeMFPlateMetadata(index=2, print_time_minutes=None, filament_weight_grams=None),
            ]
        )
        figures = combined_figures(parsed)
        assert (figures.minutes, figures.plates, figures.weight) == (10, 2, None)

    def test_a_single_figure_file_without_plates(self) -> None:
        figures = combined_figures(parse_gcode_metadata(plain_gcode()))
        assert (figures.minutes, figures.plates, figures.weight) == (118, None, None)
        assert figures.items is None
