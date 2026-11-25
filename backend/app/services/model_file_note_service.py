"""Notes pinned on a model file, and how they travel from one version to the next.

A note sits at a point of the part in the file's own coordinates (research D7).
When a newer version is opened, the open notes of earlier versions show as
ghost pins; each is either resolved in the newer version or carried forward.
Carrying forward creates a new note on the newer file, linked to the original,
and leaves the original where it was with the status ``carried_forward`` --
each version's history stays exactly as it was (clarification Q2, FR-029a).

Spec 009 types notes (source, rule id, severity, measured and expected values)
and lets an open note be dismissed with a written reason; notes written without
those fields read as source ``person``, severity ``info``.
"""

import logging
import math
import uuid
from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.model_file import ModelFile
from app.models.model_file_note import ModelFileNote
from app.models.model_file_version import ModelFileVersion
from app.models.tenant import Tenant
from app.models.user import User
from app.services.model_file_version_service import VersionRuleError

logger = logging.getLogger(__name__)

#: Type fields of a note (spec 009); carried forward with it.
NOTE_TYPE_FIELDS = (
    "source",
    "rule_id",
    "severity",
    "measured_value",
    "expected_value",
    "value_unit",
)
#: Type fields that always hold a value (server defaults ``person`` / ``info``).
REQUIRED_TYPE_FIELDS = ("source", "severity")

#: How far a normal's length may stray from 1 before it is refused.
_NORMAL_TOLERANCE = 0.01


class NoteNotFound(LookupError):
    """The note (or its file) is not in this tenant's model."""


def check_normal(normal: tuple[float, float, float]) -> None:
    length = math.sqrt(sum(c * c for c in normal))
    if abs(length - 1.0) > _NORMAL_TOLERANCE:
        raise VersionRuleError("bad_normal", "The surface normal must be a unit vector", 422)


async def archive_notes_of_file(db: AsyncSession, tenant: Tenant, file_id: uuid.UUID) -> None:
    """Archive a file's notes before the file goes; the rows stay in the history (FR-030)."""
    await db.execute(
        update(ModelFileNote)
        .where(
            ModelFileNote.model_file_id == file_id,
            ModelFileNote.tenant_id == tenant.id,
            ModelFileNote.archived_at.is_(None),
        )
        .values(archived_at=datetime.now(UTC))
        .execution_options(synchronize_session=False)
    )


class ModelFileNoteService:
    """Pinned notes of one tenant's model files."""

    def __init__(self, db: AsyncSession, tenant: Tenant, user: Optional[User] = None):
        self.db = db
        self.tenant = tenant
        self.user = user

    # ------------------------------------------------------------------ reads

    async def get(self, model_id: uuid.UUID, note_id: uuid.UUID) -> ModelFileNote:
        note = (
            await self.db.execute(
                select(ModelFileNote).where(
                    ModelFileNote.id == note_id,
                    ModelFileNote.model_id == model_id,
                    ModelFileNote.tenant_id == self.tenant.id,
                )
            )
        ).scalar_one_or_none()
        if note is None:
            raise NoteNotFound(f"Note {note_id} not found")
        return note

    async def _file(self, model_id: uuid.UUID, file_id: uuid.UUID) -> ModelFile:
        model_file = (
            await self.db.execute(
                select(ModelFile).where(
                    ModelFile.id == file_id,
                    ModelFile.model_id == model_id,
                    ModelFile.tenant_id == self.tenant.id,
                )
            )
        ).scalar_one_or_none()
        if model_file is None:
            raise NoteNotFound(f"File {file_id} not found")
        return model_file

    async def _version(self, model_id: uuid.UUID, version_id: uuid.UUID) -> ModelFileVersion:
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
            raise VersionRuleError("bad_version", "That version is not one of this model's", 422)
        return version

    async def list_notes(
        self,
        model_id: uuid.UUID,
        *,
        file_id: Optional[uuid.UUID] = None,
        version_id: Optional[uuid.UUID] = None,
        status: Optional[str] = None,
        include_archived: bool = False,
        ghosts_for_file_id: Optional[uuid.UUID] = None,
        source: Optional[str] = None,
        severity: Optional[str] = None,
    ) -> list[tuple[ModelFileNote, bool]]:
        """Notes of a model, each with whether it is a ghost from an earlier version.

        With ``ghosts_for_file_id`` the file's own notes come back with the open,
        unarchived notes of every earlier version of the model (FR-029).
        """
        query = select(ModelFileNote).where(
            ModelFileNote.model_id == model_id, ModelFileNote.tenant_id == self.tenant.id
        )
        if not include_archived:
            query = query.where(ModelFileNote.archived_at.is_(None))
        if status is not None:
            query = query.where(ModelFileNote.status == status)
        if version_id is not None:
            query = query.where(ModelFileNote.version_id == version_id)
        # Typed-note filters (spec 009, FR-011) apply to ghosts too.
        type_filters = []
        if source is not None:
            type_filters.append(ModelFileNote.source == source)
        if severity is not None:
            type_filters.append(ModelFileNote.severity == severity)
        query = query.where(*type_filters)

        if ghosts_for_file_id is None:
            if file_id is not None:
                query = query.where(ModelFileNote.model_file_id == file_id)
            notes = (await self.db.execute(query.order_by(ModelFileNote.created_at))).scalars()
            return [(note, False) for note in notes]

        viewed = await self._file(model_id, ghosts_for_file_id)
        viewed_version = await self._version(model_id, viewed.version_id)
        own = (
            await self.db.execute(
                query.where(ModelFileNote.model_file_id == viewed.id).order_by(ModelFileNote.number)
            )
        ).scalars()
        ghosts = (
            await self.db.execute(
                select(ModelFileNote)
                .join(ModelFileVersion, ModelFileVersion.id == ModelFileNote.version_id)
                .where(
                    ModelFileNote.model_id == model_id,
                    ModelFileNote.tenant_id == self.tenant.id,
                    ModelFileNote.status == "open",
                    ModelFileNote.archived_at.is_(None),
                    ModelFileVersion.sequence < viewed_version.sequence,
                    *type_filters,
                )
                .order_by(ModelFileVersion.sequence, ModelFileNote.number)
            )
        ).scalars()
        return [(note, False) for note in own] + [(note, True) for note in ghosts]

    # ----------------------------------------------------------------- writes

    async def create(
        self,
        model_id: uuid.UUID,
        file_id: uuid.UUID,
        *,
        position: tuple[float, float, float],
        normal: tuple[float, float, float],
        text: str,
        layer: Optional[int] = None,
        carried_from: Optional[ModelFileNote] = None,
        note_type: Optional[dict[str, Any]] = None,
    ) -> ModelFileNote:
        """Pin a note; ``note_type`` holds the spec 009 type fields (all optional)."""
        model_file = await self._file(model_id, file_id)
        check_normal(normal)
        number = (
            await self.db.execute(
                select(func.coalesce(func.max(ModelFileNote.number), 0)).where(
                    ModelFileNote.model_file_id == model_file.id,
                    ModelFileNote.tenant_id == self.tenant.id,
                )
            )
        ).scalar_one() + 1
        note = ModelFileNote(
            tenant_id=self.tenant.id,
            model_id=model_id,
            version_id=model_file.version_id,
            model_file_id=model_file.id,
            number=number,
            pos_x=position[0],
            pos_y=position[1],
            pos_z=position[2],
            normal_x=normal[0],
            normal_y=normal[1],
            normal_z=normal[2],
            layer=layer,
            text=text,
            status="open",
            carried_from_note_id=carried_from.id if carried_from else None,
            author_user_id=self.user.id if self.user else None,
            source="person",
            severity="info",
        )
        for field, value in (note_type or {}).items():
            if field in NOTE_TYPE_FIELDS and value is not None:
                setattr(note, field, value)
        self.db.add(note)
        await self.db.flush()
        return note

    async def update(
        self,
        note: ModelFileNote,
        *,
        text: Optional[str] = None,
        position: Optional[tuple[float, float, float]] = None,
        normal: Optional[tuple[float, float, float]] = None,
        status: Optional[str] = None,
        resolved_in_version_id: Optional[uuid.UUID] = None,
        dismissal_reason: Optional[str] = None,
        note_type: Optional[dict[str, Any]] = None,
    ) -> ModelFileNote:
        """Edit, move, resolve, dismiss or reopen a note. A carried-forward note is final.

        ``note_type`` holds only the type fields the caller sent (an explicit
        None clears an optional one; ``source`` and ``severity`` cannot be cleared).
        """
        if note.status == "carried_forward":
            raise VersionRuleError(
                "note_carried_forward",
                "This note was carried forward; edit the note it continues in instead",
            )
        if text is not None:
            note.text = text
        if position is not None:
            note.pos_x, note.pos_y, note.pos_z = position
        if normal is not None:
            check_normal(normal)
            note.normal_x, note.normal_y, note.normal_z = normal
        for field, value in (note_type or {}).items():
            if field not in NOTE_TYPE_FIELDS or (value is None and field in REQUIRED_TYPE_FIELDS):
                continue
            setattr(note, field, value)
        if status in ("resolved", "dismissed") and note.status == "dismissed":
            raise VersionRuleError("note_dismissed", "Reopen the dismissed note first")
        if status == "dismissed":
            # Spec 009 (clarification Q2): an ignored alert keeps its written reason.
            if note.status != "open":
                raise VersionRuleError("note_not_open", "Only an open note can be dismissed")
            if not dismissal_reason or not dismissal_reason.strip():
                raise VersionRuleError(
                    "dismissal_reason_required", "Say why the note is dismissed", 422
                )
            note.status = "dismissed"
            note.dismissal_reason = dismissal_reason
            note.dismissed_at = datetime.now(UTC)
            note.dismissed_by_user_id = self.user.id if self.user else None
        elif status == "resolved":
            if resolved_in_version_id is None:
                raise VersionRuleError(
                    "resolved_version_required", "Say which version resolved it", 422
                )
            await self._not_older(note, resolved_in_version_id)
            note.status = "resolved"
            note.resolved_in_version_id = resolved_in_version_id
        elif status == "open":
            # Reopening a dismissed note keeps its last dismissal reason, who and when.
            note.status = "open"
            note.resolved_in_version_id = None
        await self.db.flush()
        return note

    async def carry_forward(self, note: ModelFileNote, target_file_id: uuid.UUID) -> ModelFileNote:
        """Continue an open note on a newer version's file (FR-029a)."""
        if note.status != "open":
            raise VersionRuleError("note_not_open", "Only an open note can be carried forward")
        target = await self._file(note.model_id, target_file_id)
        source_version = await self._version(note.model_id, note.version_id)
        target_version = await self._version(note.model_id, target.version_id)
        if target_version.sequence <= source_version.sequence:
            raise VersionRuleError(
                "target_not_newer", "A note can only be carried to a newer version", 422
            )
        carried = await self.create(
            note.model_id,
            target.id,
            position=(note.pos_x, note.pos_y, note.pos_z),
            normal=(note.normal_x, note.normal_y, note.normal_z),
            text=note.text,
            layer=note.layer,
            carried_from=note,
            note_type={field: getattr(note, field) for field in NOTE_TYPE_FIELDS},
        )
        note.status = "carried_forward"
        note.carried_to_version_id = target_version.id
        await self.db.flush()
        logger.info(
            f"Carried note {note.id} forward to version {target_version.label} as {carried.id}"
        )
        return carried

    async def _not_older(self, note: ModelFileNote, version_id: uuid.UUID) -> None:
        own = await self._version(note.model_id, note.version_id)
        target = await self._version(note.model_id, version_id)
        if target.sequence < own.sequence:
            raise VersionRuleError(
                "resolved_in_older_version",
                "A note cannot be resolved in a version older than its own",
                422,
            )
