"""Versions API and the activation review (T022, T025; FR-009 to FR-013, research D4).

Making a version active writes nothing on its own: the preview lists each
figure that would change, aimed at the row the cost engine reads, and only the
figures the operator picks are written -- as ``measured`` -- through the same
writers the cost profile uses.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models.model_material import ModelMaterial
from app.models.pricing_input_provenance import PricingInputProvenance
from app.models.user import UserRole
from tests.fixtures.model_files import block_stl, plain_gcode, sliced_3mf
from tests.integration.test_model_files_api_versions import upload, versions

API = "/api/v1/models"

#: sliced_3mf(): two plates of 112 minutes and 41.00 g each.
TWO_PLATES_MINUTES = "224"
TWO_PLATES_WEIGHT = "82.00"


async def _two_versions(client, model_id) -> tuple[dict, dict]:
    """Version 1 (active): an STL. Version 2 (inactive): a two-plate sliced 3MF."""
    v1 = await upload(client, model_id, "v1.stl", block_stl(), "source_stl")
    v2 = await upload(
        client,
        model_id,
        "v2.gcode.3mf",
        sliced_3mf(),
        "source_3mf",
        new_version_label="thicker",
        new_version_note="thicker walls",
    )
    return v1, v2


async def _preview(client, model_id, version_id, **params) -> dict:
    response = await client.get(
        f"{API}/{model_id}/file-versions/{version_id}/activation-preview", params=params
    )
    assert response.status_code == 200, response.text
    return response.json()


def _rows(preview: dict) -> dict[str, dict]:
    return {row["field"]: row for row in preview["rows"]}


class TestVersions:
    async def test_new_versions_are_listed_newest_first_and_inactive(self, client, test_model):
        _, v2 = await _two_versions(client, test_model.id)
        assert v2["version_created"] is True
        listed = await versions(client, test_model.id)
        assert [(v["label"], v["note"], v["is_active"]) for v in listed] == [
            ("thicker", "thicker walls", False),
            ("1", None, True),
        ]
        assert listed[0]["print_file_id"] == v2["file"]["id"]
        assert listed[0]["created_by"]["name"]

    async def test_create_rename_and_note(self, client, test_model):
        await upload(client, test_model.id, "v1.stl", block_stl(), "source_stl")
        created = await client.post(f"{API}/{test_model.id}/file-versions", json={})
        assert created.status_code == 201
        assert (created.json()["label"], created.json()["is_active"]) == ("2", False)
        renamed = await client.patch(
            f"{API}/{test_model.id}/file-versions/{created.json()['id']}",
            json={"label": "lighter", "note": "hollowed"},
        )
        assert (renamed.json()["label"], renamed.json()["note"]) == ("lighter", "hollowed")

    async def test_a_rename_carries_to_the_files_legacy_version_text(self, client, test_model):
        v1 = await upload(client, test_model.id, "v1.stl", block_stl(), "source_stl")
        await client.patch(
            f"{API}/{test_model.id}/file-versions/{v1['file']['version_id']}",
            json={"label": "1a"},
        )
        listed = (await client.get(f"{API}/{test_model.id}/files")).json()["files"]
        assert [f["version"] for f in listed] == ["1a"]

    async def test_first_version_of_a_model_is_active(self, client, test_model):
        created = await client.post(f"{API}/{test_model.id}/file-versions", json={"label": "a"})
        assert created.json()["is_active"] is True

    async def test_label_too_long_is_422(self, client, test_model):
        response = await client.post(
            f"{API}/{test_model.id}/file-versions", json={"label": "x" * 51}
        )
        assert response.status_code == 422

    async def test_print_file_of_an_inactive_version_must_be_its_sliced_file(
        self, client, test_model
    ):
        v1, v2 = await _two_versions(client, test_model.id)
        version_id = v2["file"]["version_id"]
        not_sliced = await upload(
            client, test_model.id, "v2.stl", block_stl(), "source_stl", version_id=version_id
        )
        bad = await client.patch(
            f"{API}/{test_model.id}/file-versions/{version_id}",
            json={"print_file_id": not_sliced["file"]["id"]},
        )
        assert bad.status_code == 422
        assert bad.json()["detail"]["code"] == "print_file_not_sliced"
        foreign = await client.patch(
            f"{API}/{test_model.id}/file-versions/{version_id}",
            json={"print_file_id": v1["file"]["id"]},
        )
        assert foreign.json()["detail"]["code"] == "print_file_not_in_version"

    async def test_print_file_of_the_active_version_needs_the_review(self, client, test_model):
        first = await upload(client, test_model.id, "a.gcode", plain_gcode(), "gcode")
        second = await upload(client, test_model.id, "b.gcode", plain_gcode(), "gcode")
        response = await client.patch(
            f"{API}/{test_model.id}/file-versions/{first['file']['version_id']}",
            json={"print_file_id": second["file"]["id"]},
        )
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "review_required"


class TestActivationPreview:
    async def test_rows_only_for_figures_that_change(self, client, test_model):
        _, v2 = await _two_versions(client, test_model.id)
        rows = _rows(await _preview(client, test_model.id, v2["file"]["version_id"]))
        assert rows["print_time_minutes"]["current"] == "60"
        assert rows["print_time_minutes"]["proposed"] == TWO_PLATES_MINUTES
        assert rows["print_time_minutes"]["target"] == "model"
        assert rows["prints_per_plate"]["proposed"] == "2"
        # No material yet: the weight is shown but cannot be applied.
        assert rows["weight_grams"]["selectable"] is False
        assert rows["weight_grams"]["reason"] == "no material yet"

    async def test_no_measurable_file_is_a_notice(self, client, test_model):
        _, v2 = await _two_versions(client, test_model.id)
        preview = await _preview(client, test_model.id, v2["file"]["version_id"])
        assert "dimensions" not in _rows(preview)
        assert any("no measurable file" in n for n in preview["notices"])

    async def test_dimensions_come_from_the_versions_newest_measured_file(self, client, test_model):
        _, v2 = await _two_versions(client, test_model.id)
        version_id = v2["file"]["version_id"]
        stl = await upload(
            client, test_model.id, "v2.stl", block_stl(), "source_stl", version_id=version_id
        )
        # The model already took version 1's block, so equal dims give no row...
        preview = await _preview(client, test_model.id, version_id)
        assert preview["dimension_file_id"] == stl["file"]["id"]
        assert preview["dimension_file_name"] == "v2.stl"
        assert "dimensions" not in _rows(preview)

    async def test_planned_printer_config_is_the_target(
        self, client, test_model, test_printer, test_model_printer_config, db_session
    ):
        test_model.planned_printer_id = test_printer.id
        await db_session.commit()
        _, v2 = await _two_versions(client, test_model.id)
        rows = _rows(await _preview(client, test_model.id, v2["file"]["version_id"]))
        assert rows["print_time_minutes"]["target"] == "model_printer_config"
        assert rows["print_time_minutes"]["current"] == "45"
        # The per-printer weight is per item: 82.00 g over 2 plates.
        assert rows["weight_grams"]["target"] == "model_printer_config"
        assert rows["weight_grams"]["proposed"] == "41.00"

    async def test_plain_gcode_reads_its_header_and_says_what_is_missing(self, client, test_model):
        await upload(client, test_model.id, "v1.stl", block_stl(), "source_stl")
        g = await upload(
            client, test_model.id, "v2.gcode", plain_gcode(), "gcode", new_version_label="2"
        )
        rows = _rows(await _preview(client, test_model.id, g["file"]["version_id"]))
        assert rows["print_time_minutes"]["proposed"] == "118"
        assert rows["prints_per_plate"]["selectable"] is False
        assert rows["prints_per_plate"]["reason"] == (
            "the file doesn't say how many items this run makes"
        )

    async def test_unknown_version_is_404(self, client, test_model):
        response = await client.get(
            f"{API}/{test_model.id}/file-versions/{uuid4()}/activation-preview"
        )
        assert response.status_code == 404


class TestActivate:
    async def test_only_the_chosen_figures_are_written_as_measured(
        self, client, test_model, db_session
    ):
        _, v2 = await _two_versions(client, test_model.id)
        version_id = v2["file"]["version_id"]
        response = await client.post(
            f"{API}/{test_model.id}/file-versions/{version_id}/activate",
            json={"apply": ["print_time_minutes"]},
        )
        assert response.status_code == 200, response.text
        assert response.json()["is_active"] is True
        await db_session.refresh(test_model)
        assert test_model.print_time_minutes == int(TWO_PLATES_MINUTES)
        assert test_model.prints_per_plate in (None, 1)
        origin = (
            await db_session.execute(
                select(PricingInputProvenance).where(
                    PricingInputProvenance.entity_id == test_model.id,
                    PricingInputProvenance.field_name == "print_time_minutes",
                )
            )
        ).scalar_one()
        assert origin.source == "measured"
        labels = [(v["label"], v["is_active"]) for v in await versions(client, test_model.id)]
        assert labels == [("thicker", True), ("1", False)]

    async def test_material_weight_is_written_to_the_single_material(
        self, client, test_model, test_spool, db_session
    ):
        db_session.add(
            ModelMaterial(
                model_id=test_model.id, spool_id=test_spool.id, weight_grams=Decimal("30")
            )
        )
        await db_session.commit()
        _, v2 = await _two_versions(client, test_model.id)
        response = await client.post(
            f"{API}/{test_model.id}/file-versions/{v2['file']['version_id']}/activate",
            json={"apply": ["weight_grams"]},
        )
        assert response.status_code == 200, response.text
        material = (
            await db_session.execute(
                select(ModelMaterial).where(ModelMaterial.model_id == test_model.id)
            )
        ).scalar_one()
        await db_session.refresh(material)
        assert material.weight_grams == Decimal(TWO_PLATES_WEIGHT)

    async def test_a_non_selectable_figure_is_422_and_nothing_moves(
        self, client, test_model, db_session
    ):
        _, v2 = await _two_versions(client, test_model.id)
        response = await client.post(
            f"{API}/{test_model.id}/file-versions/{v2['file']['version_id']}/activate",
            json={"apply": ["weight_grams", "print_time_minutes"]},
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "not_selectable"
        listed = await versions(client, test_model.id)
        assert [v["is_active"] for v in listed] == [False, True]

    async def test_unknown_field_is_422(self, client, test_model):
        _, v2 = await _two_versions(client, test_model.id)
        response = await client.post(
            f"{API}/{test_model.id}/file-versions/{v2['file']['version_id']}/activate",
            json={"apply": ["labor_rate"]},
        )
        assert response.status_code == 422

    async def test_switching_the_active_print_file_goes_through_activate(
        self, client, test_model, db_session
    ):
        await upload(client, test_model.id, "a.gcode.3mf", sliced_3mf(plates=1), "source_3mf")
        b = await upload(
            client, test_model.id, "b.gcode.3mf", sliced_3mf(plates=1, seconds=600), "source_3mf"
        )
        version_id = b["file"]["version_id"]
        preview = await _preview(client, test_model.id, version_id, print_file_id=b["file"]["id"])
        assert _rows(preview)["print_time_minutes"]["proposed"] == "10"
        response = await client.post(
            f"{API}/{test_model.id}/file-versions/{version_id}/activate",
            json={"apply": ["print_time_minutes"], "print_file_id": b["file"]["id"]},
        )
        assert response.json()["print_file_id"] == b["file"]["id"]
        await db_session.refresh(test_model)
        assert test_model.print_time_minutes == 10

    async def test_reactivating_an_older_version(self, client, test_model):
        v1, v2 = await _two_versions(client, test_model.id)
        for version_id in (v2["file"]["version_id"], v1["file"]["version_id"]):
            response = await client.post(
                f"{API}/{test_model.id}/file-versions/{version_id}/activate", json={"apply": []}
            )
            assert response.status_code == 200
        assert [v["is_active"] for v in await versions(client, test_model.id)] == [False, True]


class TestAccess:
    async def test_unauthenticated_is_401(self, unauthenticated_client, test_model):
        response = await unauthenticated_client.get(f"{API}/{test_model.id}/file-versions")
        assert response.status_code == 401

    async def test_another_tenants_model_is_404(self, client):
        response = await client.get(f"{API}/{uuid4()}/file-versions")
        assert response.status_code == 404

    @pytest.mark.parametrize(
        "method,path,body",
        [
            ("POST", "/file-versions", {}),
            ("PATCH", "/file-versions/{v}", {"label": "x"}),
            ("POST", "/file-versions/{v}/activate", {"apply": []}),
        ],
    )
    async def test_a_viewer_may_read_but_not_write(
        self, as_role, test_model, db_session, method, path, body
    ):
        async with as_role(UserRole.MEMBER) as member:
            v = (await upload(member, test_model.id, "a.stl", block_stl(), "source_stl"))["file"][
                "version_id"
            ]
        async with as_role(UserRole.VIEWER) as viewer:
            assert (await viewer.get(f"{API}/{test_model.id}/file-versions")).status_code == 200
            response = await viewer.request(
                method, f"{API}/{test_model.id}{path.format(v=v)}", json=body
            )
        assert response.status_code == 403


# ============================================
# Items per run and weight per filament (T064, T065)
# ============================================


async def _sliced_version(client, model_id, content: bytes) -> str:
    await upload(client, model_id, "v1.stl", block_stl(), "source_stl")
    v2 = await upload(client, model_id, "v2.gcode.3mf", content, "gcode", new_version_label="2")
    return v2["file"]["version_id"]


async def _material(db_session, tenant, model, color: str, color_hex: str, grams: str):
    from app.models.filament_type import FilamentType
    from app.models.material import MaterialType
    from app.models.spool import Spool

    pla = (
        await db_session.execute(select(MaterialType).where(MaterialType.code == "PLA"))
    ).scalar_one()
    filament = FilamentType(
        id=uuid4(),
        tenant_id=tenant.id,
        material_type_id=pla.id,
        brand="Test",
        color=color,
        color_hex=color_hex,
        diameter=1.75,
        has_sample=False,
        translucent=False,
        glow=False,
    )
    spool = Spool(
        id=uuid4(),
        tenant_id=tenant.id,
        filament_type_id=filament.id,
        spool_id=f"SP-{color}",
        initial_weight=1000,
        current_weight=1000,
        is_active=True,
        is_labeled=False,
    )
    line = ModelMaterial(model_id=model.id, spool_id=spool.id, weight_grams=Decimal(grams))
    db_session.add_all([filament, spool])
    await db_session.flush()
    db_session.add(line)
    await db_session.commit()
    return line


class TestItemsPerRun:
    async def test_items_are_the_objects_on_the_plates_not_the_plate_count(
        self, client, test_model
    ):
        version_id = await _sliced_version(client, test_model.id, sliced_3mf(plates=2, objects=4))
        rows = _rows(await _preview(client, test_model.id, version_id))
        assert rows["prints_per_plate"]["proposed"] == "8"

    async def test_unknown_items_are_not_guessed(self, client, test_model):
        version_id = await _sliced_version(
            client, test_model.id, sliced_3mf(plates=2, objects=None)
        )
        rows = _rows(await _preview(client, test_model.id, version_id))
        assert rows["prints_per_plate"]["selectable"] is False
        assert rows["prints_per_plate"]["reason"] == (
            "the file doesn't say how many items this run makes"
        )

    async def test_per_printer_item_weight_divides_by_items(
        self, client, test_model, test_printer, test_model_printer_config, db_session
    ):
        test_model.planned_printer_id = test_printer.id
        test_model_printer_config.material_weight_grams = 5
        await db_session.commit()
        version_id = await _sliced_version(
            client, test_model.id, sliced_3mf(plates=2, objects=4, weight="40.00")
        )
        rows = _rows(await _preview(client, test_model.id, version_id))
        # 80 g over 8 items, not over 2 plates.
        assert rows["weight_grams"]["proposed"] == "10.00"
        assert rows["weight_grams"]["target"] == "model_printer_config"


class TestWeightPerFilament:
    TWO_COLOURS = [("PLA", "#FF0000FF", "30.00"), ("PLA", "#000000FF", "12.00")]

    async def test_each_line_gets_its_own_filament(
        self, client, test_model, test_tenant, db_session
    ):
        red = await _material(db_session, test_tenant, test_model, "Red", "#ff0000", "1")
        black = await _material(db_session, test_tenant, test_model, "Black", "#000000", "1")
        version_id = await _sliced_version(
            client, test_model.id, sliced_3mf(plates=2, filaments=self.TWO_COLOURS)
        )
        row = _rows(await _preview(client, test_model.id, version_id))["weight_grams"]
        assert row["selectable"] is True
        assert row["proposed"]["labels"] == {"PLA Red": "60.00", "PLA Black": "24.00"}

        response = await client.post(
            f"{API}/{test_model.id}/file-versions/{version_id}/activate",
            json={"apply": ["weight_grams"]},
        )
        assert response.status_code == 200, response.text
        for line, grams in ((red, "60.00"), (black, "24.00")):
            await db_session.refresh(line)
            assert line.weight_grams == Decimal(grams)
            origin = (
                await db_session.execute(
                    select(PricingInputProvenance).where(
                        PricingInputProvenance.entity_id == line.id,
                        PricingInputProvenance.field_name == "weight_grams",
                    )
                )
            ).scalar_one()
            assert origin.source == "measured"

    async def test_a_file_without_weight_shows_each_lines_current_grams(
        self, client, test_model, test_tenant, db_session
    ):
        # Regression (walkthrough): the row read "not set -> not set" over 60 g / 24 g.
        await _material(db_session, test_tenant, test_model, "Red", "#ff0000", "60")
        await _material(db_session, test_tenant, test_model, "Black", "#000000", "24")
        await upload(client, test_model.id, "v1.stl", block_stl(), "source_stl")
        v2 = await upload(
            client, test_model.id, "v2.gcode", plain_gcode(), "gcode", new_version_label="2"
        )
        preview = await _preview(client, test_model.id, v2["file"]["version_id"])
        row = _rows(preview)["weight_grams"]
        assert row["selectable"] is False
        assert row["reason"] == "not in the file"
        assert row["current"] == {"PLA Red": "60.00", "PLA Black": "24.00"}

    async def test_a_filament_with_no_line_is_named_and_nothing_applies(
        self, client, test_model, test_tenant, db_session
    ):
        await _material(db_session, test_tenant, test_model, "Red", "#ff0000", "1")
        await _material(db_session, test_tenant, test_model, "White", "#ffffff", "1")
        version_id = await _sliced_version(
            client, test_model.id, sliced_3mf(plates=1, filaments=self.TWO_COLOURS)
        )
        row = _rows(await _preview(client, test_model.id, version_id))["weight_grams"]
        assert row["selectable"] is False
        assert "PLA White" in row["reason"]
        assert "PLA #000000" in row["reason"]
        response = await client.post(
            f"{API}/{test_model.id}/file-versions/{version_id}/activate",
            json={"apply": ["weight_grams"]},
        )
        assert response.status_code == 422
