"""Design briefs: the Preflight design file of a part (spec 009, US1).

A brief starts on an idea or a model. A model converted from an idea reaches
the idea's brief through ``models.source_idea_id``; the first write or start
through the model stamps ``model_id`` on it, so idea and model always share one
brief and nothing is copied (research R1). Reads never write.

Every save that changes the intent, the risk part or the plan appends an
immutable revision (clarification Q1, research R2). The intent is validated by
``preflight_intent`` (the one authority, research R3).
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.design_brief import PREFLIGHT_STEPS, DesignBrief, DesignBriefRevision
from app.models.idea import Idea
from app.models.model import Model
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.design_brief import (
    DesignBriefResponse,
    DesignBriefRevisionResponse,
    DesignBriefStart,
    DesignBriefUpdate,
    IntentValidation,
    StepState,
)
from app.schemas.model_file_version import PersonRef
from app.services.preflight_intent import (
    IntentInvalid,
    check_size,
    parse_yaml_mapping,
    report_for,
    validate_intent,
)

logger = logging.getLogger(__name__)


class BriefNotFound(LookupError):
    """The idea, model or brief is not in this tenant."""


class DesignBriefService:
    """Reads and writes a tenant's design briefs."""

    def __init__(self, db: AsyncSession, tenant: Tenant, user: Optional[User] = None):
        self.db = db
        self.tenant = tenant
        self.user = user

    # ----------------------------------------------------------------- lookups

    async def _idea(self, idea_id: uuid.UUID) -> Idea:
        idea = await self.db.scalar(
            select(Idea).where(Idea.id == idea_id, Idea.tenant_id == self.tenant.id)
        )
        if idea is None:
            raise BriefNotFound("Idea not found")
        return idea

    async def _model(self, model_id: uuid.UUID) -> Model:
        model = await self.db.scalar(
            select(Model).where(Model.id == model_id, Model.tenant_id == self.tenant.id)
        )
        if model is None:
            raise BriefNotFound("Model not found")
        return model

    async def get(self, brief_id: uuid.UUID) -> DesignBrief:
        brief = await self.db.scalar(
            select(DesignBrief).where(
                DesignBrief.id == brief_id, DesignBrief.tenant_id == self.tenant.id
            )
        )
        if brief is None:
            raise BriefNotFound("Design brief not found")
        return brief

    async def find_for_idea(self, idea_id: uuid.UUID) -> Optional[DesignBrief]:
        await self._idea(idea_id)
        return await self.db.scalar(
            select(DesignBrief).where(
                DesignBrief.idea_id == idea_id, DesignBrief.tenant_id == self.tenant.id
            )
        )

    async def find_for_model(self, model_id: uuid.UUID) -> Optional[DesignBrief]:
        """The model's own brief, else the brief of the idea it was converted from."""
        model = await self._model(model_id)
        conditions = [DesignBrief.model_id == model.id]
        if model.source_idea_id is not None:
            conditions.append(
                (DesignBrief.idea_id == model.source_idea_id) & DesignBrief.model_id.is_(None)
            )
        found = (
            await self.db.execute(
                select(DesignBrief)
                .where(DesignBrief.tenant_id == self.tenant.id, or_(*conditions))
                # Its own brief first, should both exist.
                .order_by(DesignBrief.model_id.is_(None))
            )
        ).scalars()
        return next(iter(found), None)

    # ----------------------------------------------------------------- writes

    def _stamp(self, brief: DesignBrief) -> None:
        brief.updated_by_user_id = self.user.id if self.user else None
        brief.updated_at = datetime.now(UTC)

    async def start_on_idea(
        self, idea_id: uuid.UUID, data: DesignBriefStart
    ) -> tuple[DesignBrief, bool]:
        """The idea's brief, created if needed; returns (brief, created)."""
        existing = await self.find_for_idea(idea_id)
        if existing is not None:
            return existing, False
        brief = self._new(idea_id=idea_id)
        await self._apply_intent(brief, data, created_revisions=[])
        await self.db.flush()
        logger.info(f"Started design brief {brief.id} on idea {idea_id}")
        return brief, True

    async def start_on_model(
        self, model_id: uuid.UUID, data: DesignBriefStart
    ) -> tuple[DesignBrief, bool]:
        """The model's brief (its own or its source idea's, then stamped), created if needed."""
        existing = await self.find_for_model(model_id)
        if existing is not None:
            if existing.model_id is None:
                existing.model_id = model_id
                self._stamp(existing)
                await self.db.flush()
            return existing, False
        brief = self._new(model_id=model_id)
        await self._apply_intent(brief, data, created_revisions=[])
        await self.db.flush()
        logger.info(f"Started design brief {brief.id} on model {model_id}")
        return brief, True

    def _new(self, **owner: uuid.UUID) -> DesignBrief:
        user_id = self.user.id if self.user else None
        brief = DesignBrief(
            tenant_id=self.tenant.id,
            step_status={},
            created_by_user_id=user_id,
            updated_by_user_id=user_id,
            **owner,
        )
        self.db.add(brief)
        return brief

    def _revision(self, brief: DesignBrief, part: str, content: dict, version=None) -> None:
        self.db.add(
            DesignBriefRevision(
                tenant_id=self.tenant.id,
                brief_id=brief.id,
                part=part,
                content=content,
                schema_version=version,
                author_user_id=self.user.id if self.user else None,
            )
        )

    async def _apply_intent(
        self, brief: DesignBrief, data: DesignBriefStart, created_revisions: list[str]
    ) -> None:
        if data.intent is None and data.intent_yaml is None:
            return
        document = (
            parse_yaml_mapping(data.intent_yaml, "intent_yaml")
            if data.intent_yaml is not None
            else data.intent
        )
        try:
            validate_intent(document)
        except IntentInvalid as exc:
            # contracts/api.md: locations start at the field the intent came in.
            field_name = "intent_yaml" if data.intent_yaml is not None else "intent"
            raise IntentInvalid(
                [
                    (loc if loc[0] == field_name else (field_name, *loc), msg)
                    for loc, msg in exc.errors
                ]
            ) from None
        if brief.intent == document:
            return
        await self.db.flush()  # the brief needs its id for the revision
        brief.intent = document
        brief.intent_schema_version = document.get("schema_version")
        self._revision(brief, "intent", document, brief.intent_schema_version)
        created_revisions.append("intent")

    async def update(self, brief: DesignBrief, data: DesignBriefUpdate) -> list[str]:
        """Apply any subset of parts; returns the parts that got a new revision."""
        created: list[str] = []
        await self._apply_intent(brief, data, created)

        if "risk" in data.model_fields_set and data.risk is not None:
            risk = data.risk
            if risk.triage is not None:
                check_size(risk.triage, "risk.triage")
            content = {
                "risk_class": risk.risk_class,
                "risk_md": risk.risk_md,
                "triage": risk.triage,
            }
            current = {
                "risk_class": brief.risk_class,
                "risk_md": brief.risk_md,
                "triage": brief.triage,
            }
            if content != current:
                brief.risk_class, brief.risk_md, brief.triage = (
                    risk.risk_class,
                    risk.risk_md,
                    risk.triage,
                )
                self._revision(brief, "risk", content)
                created.append("risk")

        if "plan_md" in data.model_fields_set and data.plan_md != brief.plan_md:
            brief.plan_md = data.plan_md
            self._revision(brief, "plan", {"plan_md": data.plan_md})
            created.append("plan")

        if data.params is not None or data.params_yaml is not None:
            params = (
                parse_yaml_mapping(data.params_yaml, "params_yaml")
                if data.params_yaml is not None
                else data.params
            )
            check_size(params, "params")
            brief.params = params
            brief.params_updated_at = datetime.now(UTC)

        if data.steps:
            now = datetime.now(UTC).isoformat()
            states = dict(brief.step_status or {})
            for step, step_status in data.steps.items():
                states[step] = {
                    "status": step_status,
                    "updated_at": now,
                    "updated_by": str(self.user.id) if self.user else None,
                }
            brief.step_status = states  # a new dict, so the JSON column is flushed

        self._stamp(brief)
        await self.db.flush()
        return created

    async def delete(self, brief: DesignBrief) -> None:
        await self.db.delete(brief)
        await self.db.flush()
        logger.info(f"Deleted design brief {brief.id}")

    async def list_revisions(
        self, brief: DesignBrief, part: Optional[str], skip: int, limit: int
    ) -> list[DesignBriefRevisionResponse]:
        query = select(DesignBriefRevision).where(
            DesignBriefRevision.brief_id == brief.id,
            DesignBriefRevision.tenant_id == self.tenant.id,
        )
        if part is not None:
            query = query.where(DesignBriefRevision.part == part)
        rows = (
            await self.db.execute(
                query.order_by(DesignBriefRevision.created_at.desc(), DesignBriefRevision.id.desc())
                .offset(skip)
                .limit(limit)
            )
        ).scalars()
        rows = list(rows)
        people = await self._people({row.author_user_id for row in rows})
        return [
            DesignBriefRevisionResponse(
                id=row.id,
                part=row.part,
                content=row.content,
                schema_version=row.schema_version,
                author=people.get(str(row.author_user_id)),
                created_at=row.created_at,
            )
            for row in rows
        ]

    # ----------------------------------------------------------------- output

    async def _people(self, ids: set[Any]) -> dict[str, PersonRef]:
        """PersonRef of each user id (UUID or its string), keyed by the id as a string."""
        wanted = {uuid.UUID(str(user_id)) for user_id in ids if user_id}
        if not wanted:
            return {}
        users = (await self.db.execute(select(User).where(User.id.in_(wanted)))).scalars()
        return {
            str(user.id): PersonRef(id=user.id, name=user.full_name or user.email) for user in users
        }

    async def to_response(self, brief: DesignBrief) -> DesignBriefResponse:
        ids: set[Any] = {brief.created_by_user_id, brief.updated_by_user_id}
        for state in (brief.step_status or {}).values():
            ids.add(state.get("updated_by"))
        people = await self._people(ids)

        steps = []
        stored = brief.step_status or {}
        for step in PREFLIGHT_STEPS:
            state = stored.get(step) or {}
            steps.append(
                StepState(
                    step=step,
                    status=state.get("status", "not_started"),
                    updated_at=state.get("updated_at"),
                    updated_by=people.get(str(state.get("updated_by"))),
                )
            )

        counts = dict.fromkeys(("intent", "risk", "plan"), 0)
        for part, count in (
            await self.db.execute(
                select(DesignBriefRevision.part, func.count())
                .where(
                    DesignBriefRevision.brief_id == brief.id,
                    DesignBriefRevision.tenant_id == self.tenant.id,
                )
                .group_by(DesignBriefRevision.part)
            )
        ).all():
            counts[part] = count

        idea_title = model_name = None
        if brief.idea_id is not None:
            idea_title = await self.db.scalar(
                select(Idea.title).where(Idea.id == brief.idea_id, Idea.tenant_id == self.tenant.id)
            )
        if brief.model_id is not None:
            model_name = await self.db.scalar(
                select(Model.name).where(
                    Model.id == brief.model_id, Model.tenant_id == self.tenant.id
                )
            )

        return DesignBriefResponse(
            id=brief.id,
            idea_id=brief.idea_id,
            model_id=brief.model_id,
            idea_title=idea_title,
            model_name=model_name,
            intent=brief.intent,
            intent_schema_version=brief.intent_schema_version,
            risk_class=brief.risk_class,
            risk_md=brief.risk_md,
            triage=brief.triage,
            plan_md=brief.plan_md,
            params=brief.params,
            params_updated_at=brief.params_updated_at,
            steps=steps,
            validation=IntentValidation(**report_for(brief.intent).as_dict()),
            revision_counts=counts,
            created_by=people.get(str(brief.created_by_user_id)),
            updated_by=people.get(str(brief.updated_by_user_id)),
            created_at=brief.created_at,
            updated_at=brief.updated_at,
        )
