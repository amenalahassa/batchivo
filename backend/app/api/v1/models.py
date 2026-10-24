"""Model catalog API endpoints (printed items with BOM)."""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.provenance_http import record_operator_origins, refuse_observed_or_409
from app.auth.dependencies import (
    MONETARY_ROLES,
    CurrentTenant,
    CurrentUser,
    RequireMember,
    TenantDB,
    role_in_tenant,
)
from app.models.user import User
from app.models.model import Model
from app.models.model_component import ModelComponent
from app.models.model_material import ModelMaterial
from app.models.printer import Printer
from app.models.spool import Spool
from app.models.tenant import Tenant
from app.models.filament_type import FilamentType
from app.schemas.model_cost_profile import (
    CostProfileFieldOrigin,
    ModelCostProfileResponse,
    ModelCostProfileUpdate,
)
from app.schemas.model import (
    BOMSpoolSuggestion,
    CostBreakdown,
    ModelComponentCreate,
    ModelComponentResponse,
    ModelCreate,
    ModelDetailResponse,
    ModelListResponse,
    ModelMaterialCreate,
    ModelMaterialResponse,
    ModelProductionDefaults,
    ModelResponse,
    ModelUpdate,
)
from app.core import clock
from app.services.cost_resolution import model_cost_breakdown
from app.services.costing import CostingService
from app.services.pricing_policy import resolve_cost_policy
from app.services.provenance import (
    ProvenanceNotEditable,
    changed_fields,
    origins_for_entity,
    record_operator_write,
    record_origin,
    refuse_overwriting_observed,
)
from app.utils.csv_handler import (
    IGNORED_COLUMNS,
    CSVImportError,
    generate_csv_export,
    parse_csv_file,
    parse_date,
    parse_print_time,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# Helper function to calculate and attach cost breakdown
async def model_with_cost(model: Model, tenant: Tenant, db: AsyncSession) -> dict:
    """Convert Model to response dict with cost breakdown.

    The policy is resolved from the database rather than read out of the
    tenant settings blob: it is the same snapshot `GET /models/{id}/cost`
    builds its structured breakdown from, so the flat total here and the
    itemised total there cannot disagree (Constitution III).
    """
    policy = await resolve_cost_policy(db, tenant)
    cost_breakdown = CostingService.calculate_model_cost(model, policy=policy)

    return {
        **model.__dict__,
        "cost_breakdown": cost_breakdown,
    }


#: Per-item overrides of a tenant rate. `labor_rate_override` replaces the
#: tenant's labour rate for this item and `overhead_percentage` its overhead
#: percentage, so both are monetary policy (FR-007a) -- the owner or admin only,
#: on every path that writes them (task T217).
POLICY_OVERRIDE_FIELDS: frozenset[str] = frozenset({"labor_rate_override", "overhead_percentage"})


async def _authorise_model_write(
    db: AsyncSession,
    tenant: Tenant,
    user: User,
    model: Optional[Model],
    changes: dict,
) -> tuple[list[str], Optional[str]]:
    """Check a write to a model's cost inputs, before anything is applied.

    Returns the registered inputs that move, and the caller's role, so the
    route can record each figure's origin once the write is made (FR-001,
    task T229). Refuses with a ``403`` a non-administrator moving a per-item
    rate or percentage (FR-007a, task T217), and with a ``409`` anyone typing
    over an observed figure (FR-004).
    """
    role = await role_in_tenant(db, user.id, tenant.id)
    fields = await refuse_observed_or_409(
        db, tenant, entity_type="model", entity=model, changes=changes
    )
    overrides = sorted(set(fields) & POLICY_OVERRIDE_FIELDS)
    if overrides and role not in MONETARY_ROLES:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Setting an item's {' and '.join(overrides)} overrides the tenant's "
                f"rate and requires the owner or admin role"
            ),
        )
    return fields, role


@router.post("", response_model=ModelDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_model(
    model_data: ModelCreate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> ModelDetailResponse:
    """
    Create a new model (printed item).

    Requires authentication.
    Model will be associated with current tenant.
    SKU must be unique per tenant.
    """
    # Check if SKU already exists for this tenant
    existing = await db.execute(
        select(Model).where(
            Model.tenant_id == tenant.id,
            Model.sku == model_data.sku,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Model with SKU '{model_data.sku}' already exists",
        )

    fields, role = await _authorise_model_write(
        db, tenant, user, None, model_data.model_dump(exclude_unset=True)
    )

    # Create model instance
    model = Model(
        tenant_id=tenant.id,
        **model_data.model_dump(),
    )

    db.add(model)
    await db.flush()
    # The figures the body named are this person's measurement or, for a
    # per-item rate, their decision -- not assumptions (FR-001, task T229).
    await record_operator_origins(
        db, tenant, entity_type="model", entity_id=model.id, fields=fields, user=user, role=role
    )
    await db.commit()
    await db.refresh(model)

    return ModelDetailResponse(**await model_with_cost(model, tenant, db))


@router.get("", response_model=ModelListResponse)
async def list_models(
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    skip: int = Query(0, ge=0, description="Number of items to skip"),
    limit: int = Query(100, ge=1, le=1000, description="Max items to return"),
    search: Optional[str] = Query(None, description="Search by SKU or name"),
    category: Optional[str] = Query(None, description="Filter by category"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
) -> ModelListResponse:
    """
    List all models for current tenant with pagination and filtering.

    Supports:
    - Pagination (skip, limit)
    - Search (SKU, name)
    - Filter by category
    - Filter by active status

    Returns total_cost for each model (computed from materials and components).
    """
    # Build query
    query = select(Model).where(Model.tenant_id == tenant.id)

    # Apply filters
    if search:
        search_pattern = f"%{search}%"
        query = query.where(
            or_(
                Model.sku.ilike(search_pattern),
                Model.name.ilike(search_pattern),
            )
        )

    if category:
        query = query.where(Model.category == category)

    if is_active is not None:
        query = query.where(Model.is_active == is_active)

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)

    # Apply pagination and fetch with materials/components for cost calculation
    query = (
        query.options(
            selectinload(Model.materials),
            selectinload(Model.components),
        )
        .order_by(Model.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    models = result.scalars().all()

    # Resolve the operator's policy once per request, not once per row: a
    # rejected setting would otherwise log a warning for every model, and two
    # rows in one list must never be costed at two different rates.
    policy = await resolve_cost_policy(db, tenant)

    # Calculate total_cost for each model
    model_responses = []
    for m in models:
        cost_breakdown = CostingService.calculate_model_cost(m, policy=policy)
        model_dict = {
            **m.__dict__,
            "total_cost": cost_breakdown.total_cost,
            "incomplete_reasons": cost_breakdown.incomplete_reasons,
        }
        # Remove SQLAlchemy internal state
        model_dict.pop("_sa_instance_state", None)
        model_responses.append(ModelResponse.model_validate(model_dict))

    return ModelListResponse(
        models=model_responses,
        total=total or 0,
        skip=skip,
        limit=limit,
    )


@router.get("/export")
async def export_models_csv(
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
):
    """
    Export all models to CSV file.

    Returns CSV with columns matching import format.
    """
    # Fetch all models with relationships
    query = (
        select(Model)
        .where(
            Model.tenant_id == tenant.id,
            Model.is_active.is_(True),
        )
        .options(
            selectinload(Model.materials).selectinload(ModelMaterial.spool),
        )
        .order_by(Model.created_at.desc())
    )

    result = await db.execute(query)
    models = result.scalars().all()

    # Convert to dicts with cost breakdown
    model_dicts = []
    for model in models:
        model_dict = await model_with_cost(model, tenant, db)
        model_dicts.append(model_dict)

    # Generate CSV
    csv_content = generate_csv_export(model_dicts)

    # Return as downloadable file
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=models_export.csv"},
    )


# NOTE: /export (above) must be defined BEFORE /{model_id} (below) so the
# literal "export" segment isn't swallowed as a model_id path parameter.
@router.get("/{model_id}", response_model=ModelDetailResponse)
async def get_model(
    model_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
) -> ModelDetailResponse:
    """
    Get model detail with BOM, components, and cost breakdown.

    Requires authentication.
    Model must belong to current tenant.
    """
    # Fetch model with relationships
    query = (
        select(Model)
        .where(
            Model.id == model_id,
            Model.tenant_id == tenant.id,
        )
        .options(
            selectinload(Model.materials).selectinload(ModelMaterial.spool),
            selectinload(Model.components),
        )
    )

    result = await db.execute(query)
    model = result.scalar_one_or_none()

    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model not found",
        )

    return ModelDetailResponse(**await model_with_cost(model, tenant, db))


@router.get("/{model_id}/cost", response_model=CostBreakdown)
async def get_model_cost(
    model_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
    printer_id: Optional[UUID] = Query(
        None,
        description=(
            "Cost this item at the rate of the machine it is planned on "
            "(FR-011). Omitted, the policy's default machine rate applies."
        ),
    ),
) -> CostBreakdown:
    """The itemised make-cost of one printed item (task T049).

    Every line carries its amount, its risk class, where its inputs came from
    and when they were set (FR-001, FR-018). Anything the operator has not
    supplied is named in `incomplete_reasons` rather than costed at zero
    (FR-019), because a zero is indistinguishable from a real figure.
    """
    query = (
        select(Model)
        .where(Model.id == model_id, Model.tenant_id == tenant.id)
        .options(
            selectinload(Model.materials).selectinload(ModelMaterial.spool),
            selectinload(Model.components),
            selectinload(Model.printer_configs),
        )
    )
    result = await db.execute(query)
    model = result.scalar_one_or_none()

    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model not found",
        )

    printer = None
    if printer_id is not None:
        printer_result = await db.execute(
            select(Printer).where(Printer.id == printer_id, Printer.tenant_id == tenant.id)
        )
        printer = printer_result.scalar_one_or_none()
        if printer is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Printer not found",
            )

    return await model_cost_breakdown(db, tenant, model, printer=printer)


# ---------------------------------------------------------------------------
# The printed item's cost profile (task T147)
#
# Tier 1 gave `Model` these columns and the engine reads every one of them.
# Nothing could write them, so every item sat at its migration defaults --
# waste 0, yield 1.0, per-part, the labor split 0 -- which is the superseded
# model's answer, not a neutral starting point. These two routes are the write
# path FR-007b requires, and they are member-editable because a purge weight
# and a finishing time are measurements, not monetary decisions (FR-007a).
# ---------------------------------------------------------------------------

#: Figures on the profile that carry provenance. `failure_mode` is absent on
#: purpose: it is a declaration about how a yield is read, not a measurement of
#: anything, so it has no registry entry and no origin to record.
_COST_PROFILE_FIELDS: tuple[str, ...] = (
    "print_time_minutes",
    "prints_per_plate",
    "waste_grams",
    "expected_yield",
    "labor_hours_per_plate",
    "labor_hours_per_item",
    "finishing_hours_per_item",
    "packing_hours_per_item",
)


async def _cost_profile_response(
    db: AsyncSession,
    tenant: Tenant,
    model: Model,
) -> ModelCostProfileResponse:
    """One item's profile with the origin of each figure and what is missing."""
    origins = await origins_for_entity(db, tenant, "model", model.id)
    policy = await resolve_cost_policy(db, tenant)

    entries: list[CostProfileFieldOrigin] = []
    for field_name in _COST_PROFILE_FIELDS:
        origin = origins[field_name]
        entries.append(
            CostProfileFieldOrigin(
                field_name=field_name,
                source=origin.source,
                as_of=origin.as_of,
                is_stale=origin.is_stale(threshold_days=policy.staleness_threshold_days),
                # An observed figure is refreshed from its source, never typed
                # over (FR-004). The flag is served rather than inferred on the
                # client so that one rule decides it.
                editable=origin.source != "observed",
            )
        )

    # FR-019: name what the engine cannot cost rather than letting it read as
    # zero. A missing print time is the one that matters most -- it silently
    # removes the machine and overhead lines, which is how the superseded model
    # understated a nine-hour print.
    incomplete: list[str] = []
    if model.print_time_minutes is None or model.print_time_minutes <= 0:
        incomplete.append(
            "No print time recorded, so machine occupancy and overhead cannot be costed (FR-010)"
        )

    return ModelCostProfileResponse(
        model_id=model.id,
        print_time_minutes=model.print_time_minutes,
        planned_printer_id=model.planned_printer_id,
        planned_printer_name=(model.planned_printer.name if model.planned_printer else None),
        prints_per_plate=model.prints_per_plate,
        waste_grams=model.waste_grams,
        expected_yield=model.expected_yield,
        failure_mode=model.failure_mode,
        labor_hours_per_plate=model.labor_hours_per_plate,
        labor_hours_per_item=model.labor_hours_per_item,
        finishing_hours_per_item=model.finishing_hours_per_item,
        packing_hours_per_item=model.packing_hours_per_item,
        origins=entries,
        incomplete_reasons=incomplete,
    )


async def _load_model_for_tenant(db: AsyncSession, tenant: Tenant, model_id: UUID) -> Model:
    result = await db.execute(
        select(Model).where(Model.id == model_id, Model.tenant_id == tenant.id)
    )
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model not found",
        )
    return model


@router.get("/{model_id}/cost-profile", response_model=ModelCostProfileResponse)
async def get_model_cost_profile(
    model_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
) -> ModelCostProfileResponse:
    """This item's operational figures, each with where it came from.

    Readable by every role including a viewer: visibility of a cost is never
    restricted, only editing is (FR-007c).
    """
    model = await _load_model_for_tenant(db, tenant, model_id)
    return await _cost_profile_response(db, tenant, model)


@router.put("/{model_id}/cost-profile", response_model=ModelCostProfileResponse)
async def update_model_cost_profile(
    model_id: UUID,
    profile_data: ModelCostProfileUpdate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> ModelCostProfileResponse:
    """Record this item's operational figures. Any member may.

    These are measurements of a printed item -- a purge weight on the scale, a
    plate time off the slicer, minutes of finishing with a stopwatch -- so
    FR-007b puts them with the member who takes them rather than behind the
    administrator who sets a rate. A viewer is refused (FR-007c). The labor
    rate override and overhead percentage on the same table are monetary
    policy: `PUT /models/{id}` and the CSV import accept them only from the
    owner or admin (task T217).

    A field the body does not name is left alone, and each field that moves has
    its origin written as `measured`, dated today, against the user who entered
    it (FR-001). A figure the engine currently reads as observed is refused
    rather than typed over (FR-004).
    """
    model = await _load_model_for_tenant(db, tenant, model_id)

    changes = profile_data.model_dump(exclude_none=True)
    # The planned machine is the one field that may be cleared: null means
    # "no machine planned", which is a choice, not an omission (FR-011).
    if "planned_printer_id" in profile_data.model_fields_set:
        changes["planned_printer_id"] = profile_data.planned_printer_id
        if profile_data.planned_printer_id is not None:
            planned = (
                await db.execute(
                    select(Printer).where(
                        Printer.id == profile_data.planned_printer_id,
                        Printer.tenant_id == tenant.id,
                    )
                )
            ).scalar_one_or_none()
            if planned is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Printer not found"
                )
    if not changes:
        return await _cost_profile_response(db, tenant, model)

    today = clock.today()
    mode_changed = "failure_mode" in changes and changes["failure_mode"] != model.failure_mode

    for field, value in changes.items():
        setattr(model, field, value)

    for field in sorted(set(changes) & set(_COST_PROFILE_FIELDS)):
        try:
            await record_origin(
                db,
                tenant,
                entity_type="model",
                entity_id=model.id,
                field_name=field,
                source="measured",
                as_of=today,
                measured_by_user_id=user.id,
            )
        except ProvenanceNotEditable as exc:
            # 409 rather than 403: the operator has the role, and the figure is
            # the obstacle. A 403 would read as "ask an admin", which would not
            # help -- an observed figure is refreshed from its source (FR-004).
            await db.rollback()
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    # FR-015d: the same yield figure means different things under each failure
    # mode, so a mode change must not carry an observation made under the other
    # one over as if it applied. The figure stays in use -- pricing cannot stop
    # because a mode changed -- but it stops claiming to be evidence for a mode
    # it was never measured under.
    if mode_changed and "expected_yield" not in changes:
        try:
            await record_origin(
                db,
                tenant,
                entity_type="model",
                entity_id=model.id,
                field_name="expected_yield",
                source="assumed",
                as_of=today,
                measured_by_user_id=user.id,
            )
        except ProvenanceNotEditable:
            # An observed yield is its source's to revise, and refusing the
            # whole mode change over the label would be the worse outcome.
            logger.warning(
                f"Model {model.id} changed failure mode while expected_yield is "
                f"observed; the figure now applies to a mode it was not measured "
                f"under (FR-015d)"
            )

    db.add(model)
    await db.commit()
    await db.refresh(model)
    await db.refresh(model, ["planned_printer"])
    logger.info(f"Updated cost profile for model {model.id} (fields: {', '.join(sorted(changes))})")

    return await _cost_profile_response(db, tenant, model)


@router.get("/{model_id}/production-defaults", response_model=ModelProductionDefaults)
async def get_model_production_defaults(
    model_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    db: TenantDB,
) -> ModelProductionDefaults:
    """
    Get production defaults for a model (BOM materials with inventory, printer, print time).

    Used to auto-populate production run creation wizard with suggested materials and settings.

    Returns:
    - Model basic info (id, sku, name)
    - Suggested printer/machine
    - Print time and prints per plate
    - BOM materials with current spool inventory info

    Requires authentication.
    Model must belong to current tenant.
    """
    # Fetch model with BOM materials (and spool + material_type relationships)
    query = (
        select(Model)
        .where(
            Model.id == model_id,
            Model.tenant_id == tenant.id,
        )
        .options(
            selectinload(Model.materials)
            .selectinload(ModelMaterial.spool)
            .selectinload(Spool.filament_type)
            .selectinload(FilamentType.material_type)
        )
    )

    result = await db.execute(query)
    model = result.scalar_one_or_none()

    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model not found",
        )

    # Build BOM material suggestions with current spool inventory
    bom_suggestions = []
    for model_material in model.materials:
        spool = model_material.spool
        ft = spool.filament_type
        material_type = ft.material_type if ft else None

        # Create spool name: "Brand - Material - Color"
        spool_name = (
            f"{ft.brand} - {material_type.code} - {ft.color}"
            if ft and material_type
            else str(spool.spool_id)
        )

        bom_suggestion = BOMSpoolSuggestion(
            spool_id=spool.id,
            spool_name=spool_name,
            material_type_code=material_type.code if material_type else "UNKNOWN",
            color=ft.color if ft else "Unknown",
            color_hex=ft.color_hex if ft else None,
            weight_grams=model_material.weight_grams,
            cost_per_gram=model_material.cost_per_gram,
            current_weight=spool.current_weight,
            is_active=spool.is_active,
        )
        bom_suggestions.append(bom_suggestion)

    # Build production defaults response
    return ModelProductionDefaults(
        model_id=model.id,
        sku=model.sku,
        name=model.name,
        machine=model.machine,
        print_time_minutes=model.print_time_minutes,
        prints_per_plate=model.prints_per_plate,
        bom_materials=bom_suggestions,
    )


@router.put("/{model_id}", response_model=ModelDetailResponse)
async def update_model(
    model_id: UUID,
    model_data: ModelUpdate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> ModelDetailResponse:
    """
    Update an existing model.

    Requires the member role (FR-007c). A per-item labour rate or overhead
    percentage needs the owner or admin (FR-007a, task T217); every cost
    input that moves has its origin recorded against the person who moved it,
    and an observed one is refused rather than typed over (task T229).
    """
    # Fetch model
    query = (
        select(Model)
        .where(
            Model.id == model_id,
            Model.tenant_id == tenant.id,
        )
        .options(
            selectinload(Model.materials),
            selectinload(Model.components),
        )
    )

    result = await db.execute(query)
    model = result.scalar_one_or_none()

    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model not found",
        )

    # Check SKU uniqueness if changing
    if model_data.sku and model_data.sku != model.sku:
        existing = await db.execute(
            select(Model).where(
                Model.tenant_id == tenant.id,
                Model.sku == model_data.sku,
                Model.id != model_id,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Model with SKU '{model_data.sku}' already exists",
            )

    # Update fields
    update_data = model_data.model_dump(exclude_unset=True)
    fields, role = await _authorise_model_write(db, tenant, user, model, update_data)
    for field, value in update_data.items():
        setattr(model, field, value)

    await record_operator_origins(
        db, tenant, entity_type="model", entity_id=model.id, fields=fields, user=user, role=role
    )
    await db.commit()
    await db.refresh(model)

    return ModelDetailResponse(**await model_with_cost(model, tenant, db))


@router.delete("/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(
    model_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
):
    """
    Delete a model (soft delete by setting is_active=False).

    Requires authentication.
    Model must belong to current tenant.
    """
    # Fetch model
    query = select(Model).where(
        Model.id == model_id,
        Model.tenant_id == tenant.id,
    )

    result = await db.execute(query)
    model = result.scalar_one_or_none()

    if not model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model not found",
        )

    # Soft delete
    model.is_active = False
    await db.commit()


# ==================== BOM (Model Materials) Management ====================


@router.post(
    "/{model_id}/materials",
    response_model=ModelMaterialResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_model_material(
    model_id: UUID,
    material_data: ModelMaterialCreate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> ModelMaterialResponse:
    """
    Add a material to model's Bill of Materials (BOM).

    Requires authentication.
    Model and spool must belong to current tenant.
    """
    # Verify model exists and belongs to tenant
    model = await db.get(Model, model_id)
    if not model or model.tenant_id != tenant.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model not found",
        )

    # Verify spool exists and belongs to tenant
    spool = await db.get(Spool, material_data.spool_id)
    if not spool or spool.tenant_id != tenant.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Spool not found",
        )

    # Create material entry
    material = ModelMaterial(
        model_id=model_id,
        **material_data.model_dump(),
    )

    db.add(material)
    await db.flush()
    # The weight and the cost per gram are what this person entered (T229).
    await record_operator_origins(
        db,
        tenant,
        entity_type="model_material",
        entity_id=material.id,
        fields=await refuse_observed_or_409(
            db,
            tenant,
            entity_type="model_material",
            entity=None,
            changes=material_data.model_dump(),
        ),
        user=user,
    )
    await db.commit()
    await db.refresh(material)

    return ModelMaterialResponse.model_validate(material)


@router.delete("/{model_id}/materials/{material_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_model_material(
    model_id: UUID,
    material_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
):
    """
    Remove a material from model's BOM.

    Requires authentication.
    Model must belong to current tenant.
    """
    # Fetch material with model
    query = (
        select(ModelMaterial)
        .join(Model)
        .where(
            ModelMaterial.id == material_id,
            ModelMaterial.model_id == model_id,
            Model.tenant_id == tenant.id,
        )
    )

    result = await db.execute(query)
    material = result.scalar_one_or_none()

    if not material:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Material not found",
        )

    await db.delete(material)
    await db.commit()


# ==================== Component Management ====================


@router.post(
    "/{model_id}/components",
    response_model=ModelComponentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_model_component(
    model_id: UUID,
    component_data: ModelComponentCreate,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
) -> ModelComponentResponse:
    """
    Add a component to model.

    Requires authentication.
    Model must belong to current tenant.
    """
    # Verify model exists and belongs to tenant
    model = await db.get(Model, model_id)
    if not model or model.tenant_id != tenant.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model not found",
        )

    # Create component entry
    component = ModelComponent(
        model_id=model_id,
        **component_data.model_dump(),
    )

    db.add(component)
    await db.flush()
    # The quantity and the unit cost are what this person entered (T229).
    await record_operator_origins(
        db,
        tenant,
        entity_type="model_component",
        entity_id=component.id,
        fields=await refuse_observed_or_409(
            db,
            tenant,
            entity_type="model_component",
            entity=None,
            changes=component_data.model_dump(),
        ),
        user=user,
    )
    await db.commit()
    await db.refresh(component)

    return ModelComponentResponse.model_validate(component)


@router.delete("/{model_id}/components/{component_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_model_component(
    model_id: UUID,
    component_id: UUID,
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
):
    """
    Remove a component from model.

    Requires authentication.
    Model must belong to current tenant.
    """
    # Fetch component with model
    query = (
        select(ModelComponent)
        .join(Model)
        .where(
            ModelComponent.id == component_id,
            ModelComponent.model_id == model_id,
            Model.tenant_id == tenant.id,
        )
    )

    result = await db.execute(query)
    component = result.scalar_one_or_none()

    if not component:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Component not found",
        )

    await db.delete(component)
    await db.commit()


# ==================== CSV Import/Export ====================


@router.post("/import", status_code=status.HTTP_200_OK)
async def import_models_csv(
    user: CurrentUser,
    tenant: CurrentTenant,
    _member: RequireMember,
    db: TenantDB,
    file: UploadFile = File(...),
):
    """
    Import models from CSV file.

    Supports user's spreadsheet format with columns:
    - ID, Name, SKU, Category, Description
    - Designer, Source, Machine
    - Print Time (13h38m format or minutes)
    - Date Printed Last (DD/MM/YYYY)
    - Units (stock count)
    - Filament1-4, Weight1-4 (multi-material BOM)

    Creates new models or updates existing ones based on SKU.
    Returns summary of import results.

    The cost inputs are written as exact decimals into the columns the engine
    reads (task T225): the sheet's "labor hours" is handling per item, so it
    goes to `labor_hours_per_item` -- the deprecated single `labor_hours` is
    read only when the per-item and per-plate figures are both zero, so
    writing it onto a model with a cost profile changed nothing and said
    nothing. Every figure that moves has its origin recorded as `measured`
    against the importing user (FR-001), an observed one is refused, and an
    overhead percentage is refused from anyone but the owner or admin
    (FR-007a, task T217) -- each refusal skips that row and says why.
    Columns the import reads past (a labour rate, a cost, a sell price) are
    reported as ignored.
    """
    # Validate file type
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be a CSV file",
        )

    # Read file content
    try:
        content = await file.read()
        csv_content = content.decode("utf-8")
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read CSV file: {str(e)}",
        )

    # Parse CSV
    try:
        rows = parse_csv_file(csv_content)
    except CSVImportError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    # Import models
    created_count = 0
    updated_count = 0
    skipped_count = 0
    errors = []
    ignored: list[str] = []
    role = await role_in_tenant(db, user.id, tenant.id)

    for row in rows:
        for column in row.ignored_columns:
            ignored.append(
                f"SKU '{row.sku}': '{column}' was not imported -- {IGNORED_COLUMNS[column]}"
            )
        try:
            # Check if model exists by SKU
            existing = await db.execute(
                select(Model).where(
                    Model.tenant_id == tenant.id,
                    Model.sku == row.sku,
                )
            )
            model = existing.scalar_one_or_none()

            # Parse special fields
            print_time_minutes = parse_print_time(row.print_time) if row.print_time else None
            last_printed_date = parse_date(row.last_printed_date) if row.last_printed_date else None

            # The cost inputs this row carries. A blank cell leaves the figure
            # alone rather than zeroing it.
            cost_inputs = {
                key: value
                for key, value in (
                    ("print_time_minutes", print_time_minutes),
                    ("labor_hours_per_item", row.labor_hours),
                    ("overhead_percentage", row.overhead_percentage),
                )
                if value is not None
            }
            fields = changed_fields("model", model, cost_inputs)
            if "overhead_percentage" in fields and role not in MONETARY_ROLES:
                raise ValueError(
                    "an overhead percentage overrides the tenant's and requires the "
                    "owner or admin role; the row was not imported"
                )
            if model is not None:
                await refuse_overwriting_observed(
                    db, tenant, entity_type="model", entity_id=model.id, fields=fields
                )

            if model:
                # Update existing model
                model.name = row.name
                model.category = row.category
                model.description = row.description
                model.designer = row.designer
                model.source = row.source
                model.machine = row.machine
                model.last_printed_date = last_printed_date
                model.units_in_stock = row.units_in_stock or 0
                for key, value in cost_inputs.items():
                    setattr(model, key, value)

                updated_count += 1
            else:
                # Create new model
                model = Model(
                    tenant_id=tenant.id,
                    sku=row.sku,
                    name=row.name,
                    category=row.category,
                    description=row.description,
                    designer=row.designer,
                    source=row.source,
                    machine=row.machine,
                    last_printed_date=last_printed_date,
                    units_in_stock=row.units_in_stock or 0,
                    **cost_inputs,
                )
                db.add(model)
                await db.flush()
                created_count += 1

            await record_operator_write(
                db,
                tenant,
                entity_type="model",
                entity_id=model.id,
                fields=fields,
                user_id=user.id,
                role=role,
            )

        except Exception as e:
            errors.append(f"SKU '{row.sku}': {str(e)}")
            skipped_count += 1
            continue

    # Commit all changes
    try:
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save models: {str(e)}",
        )

    return {
        "success": True,
        "created": created_count,
        "updated": updated_count,
        "skipped": skipped_count,
        "total_rows": len(rows),
        "errors": errors if errors else None,
        "ignored": ignored if ignored else None,
    }
