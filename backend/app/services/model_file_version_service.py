"""Versions of a model's files: which revision is printed, and which file in it feeds the cost.

A version groups the files of one revision of a design (spec 004, research D1).
One version per model is active; within a version one sliced file is the print
file. Making a version active -- or choosing another print file in the active
one -- never writes a figure on its own: the operator is shown each print-time,
plate-count, weight and dimension figure that would change, and only the ones
they pick are written, through the same writers the cost profile uses
(FR-012, research D4). Past orders, quotes and runs are never touched (FR-014).
"""

import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.model import Model
from app.models.model_file import ModelFile
from app.models.model_file_note import ModelFileNote
from app.models.model_file_version import ModelFileVersion
from app.models.model_material import ModelMaterial
from app.models.model_printer_config import ModelPrinterConfig
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.model_file_version import ActivationPreview, ActivationRow

if TYPE_CHECKING:
    from app.models.filament_type import FilamentType
    from app.schemas.model_file import ThreeMFParseResponse

logger = logging.getLogger(__name__)


class VersionNotFound(LookupError):
    """The version does not exist in this tenant, or belongs to another model."""


class VersionRuleError(ValueError):
    """A request that breaks a version rule; ``code`` is what the API reports."""

    def __init__(self, code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class ModelFileVersionService:
    """Versions of one tenant's model files."""

    def __init__(self, db: AsyncSession, tenant: Tenant, user: Optional[User] = None):
        self.db = db
        self.tenant = tenant
        self.user = user

    # ------------------------------------------------------------------ reads

    async def get(self, model_id: uuid.UUID, version_id: uuid.UUID) -> ModelFileVersion:
        version = (
            await self.db.execute(
                select(ModelFileVersion).where(
                    ModelFileVersion.id == version_id,
                    ModelFileVersion.model_id == model_id,
                    ModelFileVersion.tenant_id == self.tenant.id,
                )
            )
        ).scalar_one_or_none()
        if version is None:
            raise VersionNotFound(f"Version {version_id} not found")
        return version

    async def active_version(self, model_id: uuid.UUID) -> Optional[ModelFileVersion]:
        return (
            await self.db.execute(
                select(ModelFileVersion).where(
                    ModelFileVersion.model_id == model_id,
                    ModelFileVersion.tenant_id == self.tenant.id,
                    ModelFileVersion.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()

    async def list_versions(self, model_id: uuid.UUID) -> list[ModelFileVersion]:
        """Every version of a model, newest first (FR-010)."""
        return list(
            (
                await self.db.execute(
                    select(ModelFileVersion)
                    .where(
                        ModelFileVersion.model_id == model_id,
                        ModelFileVersion.tenant_id == self.tenant.id,
                    )
                    .order_by(ModelFileVersion.sequence.desc())
                )
            )
            .scalars()
            .all()
        )

    async def files_of(self, version_id: uuid.UUID) -> list[ModelFile]:
        return list(
            (
                await self.db.execute(
                    select(ModelFile)
                    .where(
                        ModelFile.version_id == version_id,
                        ModelFile.tenant_id == self.tenant.id,
                    )
                    .order_by(ModelFile.uploaded_at.desc())
                )
            )
            .scalars()
            .all()
        )

    async def open_note_counts(self, model_id: uuid.UUID) -> dict[uuid.UUID, int]:
        rows = await self.db.execute(
            select(ModelFileNote.version_id, func.count())
            .where(
                ModelFileNote.model_id == model_id,
                ModelFileNote.tenant_id == self.tenant.id,
                ModelFileNote.status == "open",
                ModelFileNote.archived_at.is_(None),
            )
            .group_by(ModelFileNote.version_id)
        )
        return {version_id: count for version_id, count in rows.all()}

    # ----------------------------------------------------------------- writes

    async def create_version(
        self,
        model: Model,
        label: Optional[str] = None,
        note: Optional[str] = None,
    ) -> ModelFileVersion:
        """Add the next version. Inactive, unless the model has none yet (FR-009, Q3)."""
        last = (
            await self.db.execute(
                select(func.max(ModelFileVersion.sequence)).where(
                    ModelFileVersion.model_id == model.id,
                    ModelFileVersion.tenant_id == self.tenant.id,
                )
            )
        ).scalar_one_or_none()
        sequence = (last or 0) + 1
        version = ModelFileVersion(
            tenant_id=self.tenant.id,
            model_id=model.id,
            sequence=sequence,
            label=(label or "").strip() or str(sequence),
            note=note,
            is_active=last is None,
            created_by_user_id=self.user.id if self.user else None,
        )
        self.db.add(version)
        await self.db.flush()
        logger.info(
            f"Created version {version.label} of model {model.id} "
            f"({'active' if version.is_active else 'inactive'})"
        )
        return version

    async def version_for_upload(
        self,
        model: Model,
        *,
        version_id: Optional[uuid.UUID] = None,
        new_version_label: Optional[str] = None,
        new_version_note: Optional[str] = None,
        legacy_version: Optional[str] = None,
    ) -> tuple[ModelFileVersion, bool]:
        """The version a new file goes into, and whether it was created for it.

        In order: an explicit version; a new version asked for by label or note;
        an older client's free-text ``version`` matched to a label (or a new
        version with that label); otherwise the active version, creating
        version 1 when the model has none.
        """
        if version_id is not None:
            return await self.get(model.id, version_id), False
        if new_version_label or new_version_note:
            return await self.create_version(model, new_version_label, new_version_note), True
        if legacy_version and legacy_version.strip():
            label = legacy_version.strip()[:50]
            existing = (
                await self.db.execute(
                    select(ModelFileVersion).where(
                        ModelFileVersion.model_id == model.id,
                        ModelFileVersion.tenant_id == self.tenant.id,
                        ModelFileVersion.label == label,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                return existing, False
            return await self.create_version(model, label), True
        active = await self.active_version(model.id)
        if active is not None:
            return active, False
        return await self.create_version(model), True

    async def attach_file(self, version: ModelFileVersion, model_file: ModelFile) -> None:
        """Put a new file in a version; the version's first sliced file becomes its print file."""
        model_file.version_id = version.id
        model_file.version = version.label
        await self.db.flush()
        if model_file.is_sliced and version.print_file_id is None:
            version.print_file_id = model_file.id
            await self.db.flush()

    async def update_version(
        self,
        version: ModelFileVersion,
        *,
        label: Optional[str] = None,
        note: Optional[str] = None,
        note_given: bool = False,
    ) -> ModelFileVersion:
        """Rename a version or edit its note; the files' legacy ``version`` text follows the label."""
        if label is not None:
            version.label = label.strip()
            await self.db.execute(
                update(ModelFile)
                .where(ModelFile.version_id == version.id, ModelFile.tenant_id == self.tenant.id)
                .values(version=version.label)
            )
        if note_given:
            version.note = note
        await self.db.flush()
        return version

    # ---------------------------------------------------------- deleting files

    async def before_file_delete(self, version: ModelFileVersion, model_file: ModelFile) -> None:
        """Refuse a delete that would break a version rule; archive the file's notes (D9).

        The active version must keep a file (FR-015) and keep its print file
        while it has another sliced file to choose from, because swapping the
        print file of the active version is a reviewed change (FR-012a).
        """
        others = [f for f in await self.files_of(version.id) if f.id != model_file.id]
        if version.is_active and not others:
            logger.warning(f"Refused deleting the last file of the active version {version.id}")
            raise VersionRuleError(
                "last_file_of_active_version",
                "This is the last file of the active version. Make another version active first.",
            )
        other_sliced = [f for f in others if f.is_sliced]
        if version.print_file_id == model_file.id:
            if version.is_active and other_sliced:
                logger.warning(
                    f"Refused deleting the print file of the active version {version.id}"
                )
                raise VersionRuleError(
                    "active_print_file",
                    "This is the print file of the active version. Mark another print file first.",
                )
            version.print_file_id = other_sliced[0].id if other_sliced else None

        from app.services.model_file_note_service import archive_notes_of_file

        await archive_notes_of_file(self.db, self.tenant, model_file.id)
        await self.db.flush()

    async def after_file_delete(self, version: ModelFileVersion) -> None:
        """An inactive version left with no file goes too -- unless notes still hang off it.

        A version holding archived notes stays, empty, so the notes keep their
        place in the model's history (FR-030).
        """
        if version.is_active or await self.files_of(version.id):
            return
        has_notes = (
            await self.db.execute(
                select(func.count())
                .select_from(ModelFileNote)
                .where(ModelFileNote.version_id == version.id)
            )
        ).scalar_one()
        if not has_notes:
            await self.db.delete(version)
            await self.db.flush()

    # ---------------------------------------------------------- print file

    async def set_print_file(self, version: ModelFileVersion, file_id: uuid.UUID) -> None:
        """Mark the print file of an inactive version (FR-011a).

        On the active version the choice moves cost figures, so it goes through
        the activation review instead (FR-012a).
        """
        if version.is_active:
            raise VersionRuleError(
                "review_required",
                "Changing the print file of the active version changes its figures; "
                "review them with the activation preview first",
            )
        await self._check_print_file(version, file_id)
        version.print_file_id = file_id
        await self.db.flush()

    async def _check_print_file(self, version: ModelFileVersion, file_id: uuid.UUID) -> ModelFile:
        model_file = (
            await self.db.execute(
                select(ModelFile).where(
                    ModelFile.id == file_id,
                    ModelFile.version_id == version.id,
                    ModelFile.tenant_id == self.tenant.id,
                )
            )
        ).scalar_one_or_none()
        if model_file is None:
            raise VersionRuleError(
                "print_file_not_in_version", "The print file must be a file of this version", 422
            )
        if not model_file.is_sliced:
            raise VersionRuleError(
                "print_file_not_sliced", "The print file must be a sliced plate", 422
            )
        return model_file

    # ----------------------------------------------------- activation review

    async def activation_preview(
        self,
        model: Model,
        version: ModelFileVersion,
        print_file_id: Optional[uuid.UUID] = None,
    ) -> ActivationPreview:
        """Every cost-profile and dimension figure that would change (FR-012, research D4)."""
        from app.services.model_file_service import (
            ModelFileService,
            ModelFileStorageError,
            parse_3mf_metadata,
            parse_gcode_metadata,
        )

        notices: list[str] = []
        rows: list[ActivationRow] = []

        print_file: Optional[ModelFile] = None
        chosen_id = print_file_id or version.print_file_id
        if chosen_id is not None:
            print_file = await self._check_print_file(version, chosen_id)

        figures: Optional[PrintFigures] = None
        if print_file is None:
            notices.append("This version has no sliced file, so no print figures are proposed")
        else:
            try:
                content, _, _ = await ModelFileService(
                    self.db, self.tenant, self.user
                ).get_file_content(print_file.id)
            except ModelFileStorageError as exc:
                notices.append(f"The print file could not be read: {exc}")
            else:
                if print_file.original_filename.lower().endswith(".3mf"):
                    figures = combined_figures(parse_3mf_metadata(content))
                else:
                    figures = combined_figures(parse_gcode_metadata(content))

        config = await self._planned_config(model)
        if figures is not None:
            rows.extend(await self._print_rows(model, config, figures))

        dimension_file = await self._dimension_file(version)
        if dimension_file is None:
            notices.append("The version has no measurable file, so its dimensions are not known")
        else:
            row = _dimension_row(model, dimension_file)
            if row is not None:
                rows.append(row)

        return ActivationPreview(
            version_id=version.id,
            print_file_id=print_file.id if print_file else None,
            dimension_file_id=dimension_file.id if dimension_file else None,
            dimension_file_name=dimension_file.original_filename if dimension_file else None,
            rows=rows,
            notices=notices,
        )

    async def activate(
        self,
        model: Model,
        version: ModelFileVersion,
        apply: list[str],
        print_file_id: Optional[uuid.UUID] = None,
    ) -> ModelFileVersion:
        """Make a version active and write only the figures the operator picked (FR-012).

        Values are re-read here rather than taken from the preview the operator
        saw, so a concurrent edit is never overwritten with a stale "current".
        Nothing is committed if any chosen figure cannot be written.
        """
        from app.services.provenance import ProvenanceNotEditable

        unknown = set(apply) - set(APPLICABLE_FIELDS)
        if unknown:
            raise VersionRuleError(
                "unknown_field", f"Not a figure a version can apply: {sorted(unknown)}", 422
            )
        preview = await self.activation_preview(model, version, print_file_id)
        by_field = {row.field: row for row in preview.rows}
        for field in apply:
            row = by_field.get(field)
            if row is not None and not row.selectable:
                raise VersionRuleError(
                    "not_selectable", f"{field} cannot be applied: {row.reason}", 422
                )

        if print_file_id is not None:
            version.print_file_id = print_file_id
        if not version.is_active:
            await self.db.execute(
                update(ModelFileVersion)
                .where(
                    ModelFileVersion.model_id == model.id,
                    ModelFileVersion.tenant_id == self.tenant.id,
                    ModelFileVersion.is_active.is_(True),
                )
                .values(is_active=False)
                .execution_options(synchronize_session="fetch")
            )
            await self.db.flush()
            version.is_active = True
            await self.db.flush()

        config = await self._planned_config(model)
        try:
            for field in apply:
                row = by_field.get(field)
                if row is None:  # already equal: nothing to write
                    continue
                await self._write_row(model, config, row)
        except ProvenanceNotEditable as exc:
            await self.db.rollback()
            raise VersionRuleError("observed_figure", str(exc)) from exc

        await self.db.commit()
        await self.db.refresh(version)
        logger.info(
            f"Activated version {version.label} of model {model.id}; applied {sorted(apply)}"
        )
        return version

    async def _write_row(
        self, model: Model, config: Optional[ModelPrinterConfig], row: ActivationRow
    ) -> None:
        """Write one chosen figure through the writer the cost profile uses, provenance included."""
        from app.schemas.dimensions import DimensionsIn
        from app.services.item_dimensions import set_dimensions
        from app.services.provenance import record_operator_write

        if row.field == "dimensions":
            await set_dimensions(
                self.db, self.tenant, model, DimensionsIn(adopt_file_id=row.source_file_id)
            )
            return
        entity: object
        if row.target == "model_printer_config" and config is not None:
            entity, entity_type = config, "model_printer_config"
            column = "material_weight_grams" if row.field == "weight_grams" else row.field
        elif row.target == "model_material" and isinstance(row.proposed, dict):
            materials = {str(m.id): m for m in await self._materials(model)}
            for material_id, grams in row.proposed["lines"].items():
                material = materials[material_id]
                await record_operator_write(
                    self.db,
                    self.tenant,
                    entity_type="model_material",
                    entity_id=material.id,
                    fields=["weight_grams"],
                    user_id=self.user.id if self.user else None,
                )
                material.weight_grams = Decimal(grams)
            await self.db.flush()
            return
        elif row.target == "model_material":
            entity, entity_type, column = (
                (await self._materials(model))[0],
                "model_material",
                "weight_grams",
            )
        else:
            entity, entity_type, column = model, "model", row.field
        await record_operator_write(
            self.db,
            self.tenant,
            entity_type=entity_type,
            entity_id=entity.id,
            fields=[column],
            user_id=self.user.id if self.user else None,
        )
        value = Decimal(row.proposed) if column in DECIMAL_COLUMNS else int(row.proposed)
        setattr(entity, column, value)
        await self.db.flush()

    async def _planned_config(self, model: Model) -> Optional[ModelPrinterConfig]:
        """The per-printer row the cost engine reads first, when the planned printer has one."""
        if model.planned_printer_id is None:
            return None
        return (
            await self.db.execute(
                select(ModelPrinterConfig).where(
                    ModelPrinterConfig.model_id == model.id,
                    ModelPrinterConfig.printer_id == model.planned_printer_id,
                )
            )
        ).scalar_one_or_none()

    async def _materials(self, model: Model) -> list[ModelMaterial]:
        return list(
            (
                await self.db.execute(
                    # Model materials carry no tenant_id of their own; the model
                    # they belong to has already been resolved in this tenant.
                    select(ModelMaterial)
                    .where(ModelMaterial.model_id == model.id)
                    .order_by(ModelMaterial.created_at)
                )
            )
            .scalars()
            .all()
        )

    async def _print_rows(
        self, model: Model, config: Optional[ModelPrinterConfig], figures: "PrintFigures"
    ) -> list[ActivationRow]:
        target = "model_printer_config" if config is not None else "model"
        owner = config if config is not None else model
        rows: list[ActivationRow] = []
        for field, proposed in (
            ("print_time_minutes", figures.minutes),
            # Items per run, not plates per file (T064).
            ("prints_per_plate", figures.items),
        ):
            current = getattr(owner, field, None)
            if proposed is None:
                reason = ITEMS_UNKNOWN if field == "prints_per_plate" else "not in the file"
                rows.append(_missing(field, target, current, reason))
            elif proposed != current:
                rows.append(
                    ActivationRow(
                        field=field, target=target, current=_text(current), proposed=str(proposed)
                    )
                )
        rows.extend(await self._weight_rows(model, config, figures))
        return rows

    async def _weight_rows(
        self, model: Model, config: Optional[ModelPrinterConfig], figures: "PrintFigures"
    ) -> list[ActivationRow]:
        """The weight row, aimed where the cost engine reads weight (costing.py)."""
        if config is not None and config.material_weight_grams is not None:
            # The per-printer row holds the weight of ONE item.
            current = Decimal(str(config.material_weight_grams))
            if figures.weight is None:
                return [_missing("weight_grams", "model_printer_config", current)]
            if figures.items is None:
                return [_missing("weight_grams", "model_printer_config", current, ITEMS_UNKNOWN)]
            per_item = figures.weight / Decimal(figures.items)
            proposed = per_item.quantize(Decimal("0.01"))
            if proposed == current:
                return []
            return [
                ActivationRow(
                    field="weight_grams",
                    target="model_printer_config",
                    current=str(current),
                    proposed=str(proposed),
                )
            ]

        # A model material holds the weight of a whole plate (the engine divides
        # it by parts per plate).
        materials = await self._materials(model)
        if figures.weight is None:
            if len(materials) > 1:
                # Each line's grams as it stands, by name, like the per-line row.
                lines = await self._labelled_lines(materials)
                return [
                    ActivationRow(
                        field="weight_grams",
                        target="model_material",
                        current={label: str(m.weight_grams) for m, _, _, label in lines},
                        proposed=None,
                        selectable=False,
                        reason="not in the file",
                    )
                ]
            current = materials[0].weight_grams if materials else None
            return [_missing("weight_grams", "model_material", current)]
        proposed = figures.weight.quantize(Decimal("0.01"))
        if len(materials) > 1:
            return await self._per_line_weight_rows(materials, figures)
        if not materials:
            return [
                ActivationRow(
                    field="weight_grams",
                    target="model_material",
                    current=None,
                    proposed=str(proposed),
                    selectable=False,
                    reason="no material yet",
                )
            ]
        current = Decimal(str(materials[0].weight_grams))
        if proposed == current:
            return []
        return [
            ActivationRow(
                field="weight_grams",
                target="model_material",
                current=str(current),
                proposed=str(proposed),
            )
        ]

    async def _per_line_weight_rows(
        self, materials: list[ModelMaterial], figures: "PrintFigures"
    ) -> list[ActivationRow]:
        """Each bill-of-materials line its own grams, matched on material and colour (T065).

        Selectable only when lines and filaments match one to one; otherwise the
        row says what did not match, and nothing is guessed.
        """
        lines = await self._labelled_lines(materials)
        uses = list(figures.filaments)
        current = {label: str(m.weight_grams) for m, _, _, label in lines}
        unmatched: list[str] = []
        proposed: dict[str, str] = {}
        labelled: dict[str, str] = {}
        claimed: set[int] = set()
        for material, code, color, label in lines:
            hits = [
                i
                for i, use in enumerate(uses)
                if code is not None
                and (use.type or "").upper() == code
                and (color is None or use.color == color)
            ]
            if len(hits) != 1 or hits[0] in claimed:
                unmatched.append(label)
                continue
            claimed.add(hits[0])
            proposed[str(material.id)] = str(uses[hits[0]].grams)
            labelled[label] = str(uses[hits[0]].grams)
        spare = [
            " ".join(p for p in (u.type, u.color) if p)
            for i, u in enumerate(uses)
            if i not in claimed
        ]
        if unmatched or spare or not uses:
            parts = []
            if not uses:
                parts.append("the file does not give grams per filament")
            else:
                if unmatched:
                    parts.append(f"no single filament in the file for {', '.join(unmatched)}")
                if spare:
                    parts.append(f"no material line for {', '.join(spare)}")
            return [
                ActivationRow(
                    field="weight_grams",
                    target="model_material",
                    current=current,
                    proposed=None,
                    selectable=False,
                    reason="; ".join(parts),
                )
            ]
        if all(Decimal(proposed[str(m.id)]) == Decimal(str(m.weight_grams)) for m, *_ in lines):
            return []
        return [
            ActivationRow(
                field="weight_grams",
                target="model_material",
                current=current,
                # Keyed by line id for the write, and by name for the screen.
                proposed={"lines": proposed, "labels": labelled},
            )
        ]

    async def _labelled_lines(
        self, materials: list[ModelMaterial]
    ) -> list[tuple[ModelMaterial, Optional[str], Optional[str], str]]:
        """Each line with its material code, colour (#RRGGBB) and a name ("PLA Red")."""
        lines = []
        for material in materials:
            filament_type = await self._filament_type_of(material)
            code = filament_type.material_type.code.upper() if filament_type else None
            color = ((filament_type.color_hex or "").upper()[:7] or None) if filament_type else None
            label = " ".join(p for p in (code, filament_type.color if filament_type else None) if p)
            lines.append((material, code, color, label or str(material.id)))
        return lines

    async def _filament_type_of(self, material: ModelMaterial) -> Optional["FilamentType"]:
        from app.models.filament_type import FilamentType
        from app.models.spool import Spool

        return (
            await self.db.execute(
                select(FilamentType)
                .join(Spool, Spool.filament_type_id == FilamentType.id)
                .where(Spool.id == material.spool_id, Spool.tenant_id == self.tenant.id)
                .options(selectinload(FilamentType.material_type))
            )
        ).scalar_one_or_none()

    async def _dimension_file(self, version: ModelFileVersion) -> Optional[ModelFile]:
        """The version's newest file with a measurement (FR-013)."""
        return (
            await self.db.execute(
                select(ModelFile)
                .where(
                    ModelFile.version_id == version.id,
                    ModelFile.tenant_id == self.tenant.id,
                    ModelFile.measurement_status == "done",
                    ModelFile.measured_length_mm.is_not(None),
                )
                .order_by(ModelFile.uploaded_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()


# --------------------------------------------------------------------------
# Figures and rows
# --------------------------------------------------------------------------

#: The figures activation can write (contracts/api.md).
APPLICABLE_FIELDS = ("print_time_minutes", "prints_per_plate", "weight_grams", "dimensions")
DECIMAL_COLUMNS = {"weight_grams", "material_weight_grams"}


@dataclass(frozen=True)
class FilamentGrams:
    """Grams of one filament over the whole run."""

    type: Optional[str]
    color: Optional[str]
    grams: Decimal


@dataclass(frozen=True)
class PrintFigures:
    """What a print file says about one print run: all its plates together.

    ``items`` is what the run produces -- the objects on its plates -- never
    the number of plates: two plates may make one item (a body and its base)
    or eight (four copies each). Unknown when a plate does not list its objects.
    """

    minutes: Optional[int]
    plates: Optional[int]
    items: Optional[int]
    weight: Optional[Decimal]
    filaments: tuple[FilamentGrams, ...] = ()


def combined_figures(parsed: "ThreeMFParseResponse") -> PrintFigures:
    """One print run of every plate of a print file (spec 004, T064).

    Print time and weight are the sums of the plates; items are the sum of
    the objects the plates print; filaments are summed by type and colour.
    The cost engine reads these as one "plate": time and weight for the run,
    divided by items per run.
    """
    if parsed.plates:
        minutes = [p.print_time_minutes for p in parsed.plates if p.print_time_minutes]
        weights = [p.filament_weight_grams for p in parsed.plates if p.filament_weight_grams]
        counts = [p.object_count for p in parsed.plates]
        by_filament: dict[tuple[Optional[str], Optional[str]], Decimal] = {}
        for plate in parsed.plates:
            for use in plate.filaments:
                key = (use.type, use.color)
                by_filament[key] = by_filament.get(key, Decimal("0")) + Decimal(str(use.grams))
        return PrintFigures(
            minutes=sum(minutes) if minutes else None,
            plates=len(parsed.plates),
            items=sum(c for c in counts if c) if all(counts) else None,
            weight=Decimal(str(round(sum(weights), 2))) if weights else None,
            filaments=tuple(
                FilamentGrams(type=t, color=c, grams=g.quantize(Decimal("0.01")))
                for (t, c), g in by_filament.items()
            ),
        )
    return PrintFigures(
        minutes=parsed.print_time_minutes,
        plates=parsed.plate_count,
        items=None,
        weight=(
            Decimal(str(parsed.filament_weight_grams))
            if parsed.filament_weight_grams is not None
            else None
        ),
    )


ITEMS_UNKNOWN = "the file doesn't say how many items this run makes"


def _text(value: object) -> Optional[str]:
    return None if value is None else str(value)


def _missing(
    field: str, target: str, current: object, reason: str = "not in the file"
) -> ActivationRow:
    return ActivationRow(
        field=field,
        target=target,
        current=_text(current),
        proposed=None,
        selectable=False,
        reason=reason,
    )


def _dimension_row(model: Model, model_file: ModelFile) -> Optional[ActivationRow]:
    from app.services.dims import Dims

    proposed = Dims.from_row(model_file, prefix="measured_")
    current = Dims.from_row(model)
    if proposed is None:
        return None
    if current is not None and current.quantize().as_tuple() == proposed.quantize().as_tuple():
        return None
    return ActivationRow(
        field="dimensions",
        target="dimensions",
        current=_dims_text(current, model.dimensions_source),
        proposed=_dims_text(proposed, None),
        source_file_id=model_file.id,
    )


def _dims_text(dims: object, source: Optional[str]) -> Optional[dict]:
    if dims is None:
        return None
    length, width, height = dims.quantize().as_tuple()  # type: ignore[attr-defined]
    out = {"length_mm": str(length), "width_mm": str(width), "height_mm": str(height)}
    if source is not None:
        out["source"] = source
    return out
