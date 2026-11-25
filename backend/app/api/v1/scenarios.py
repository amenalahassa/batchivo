"""Catalogue-wide scenario endpoints (task T114, FR-044a - FR-044e).

``POST /scenarios`` acknowledges and returns. It persists the question, hands
it to a worker and answers ``202`` with a handle -- it does not calculate
anything, because a sweep takes as long as the catalogue takes and no ceiling
is placed on catalogue size (FR-044e).

## Why a broker failure is a failed run and not a 500

A request that answered ``202`` while nothing was queued would leave a row
sitting at ``queued`` for ever, and an operator refreshing a job that will
never start. So an unreachable broker marks the run ``failed`` with the
reason, which is still a ``202``: the request was accepted and recorded, and
the outcome is on the row where FR-044b requires it to be visible.

## Why any authenticated role may request one

A scenario writes no cost, price or provenance figure (FR-044d) -- it is a
read of the catalogue with arithmetic on top, like the margin endpoint, which
every role may read (FR-007c). Requiring admin to *ask a question* would mean
the people closest to the printers cannot find out which products stop paying.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.auth.dependencies import CurrentTenant, CurrentUser, TenantDB, RequireMember
from app.schemas.scenario import (
    ScenarioRunListResponse,
    ScenarioRunRequest,
    ScenarioRunResponse,
)
from app.services.scenario_service import (
    Shock,
    ShockIsEmpty,
    list_runs,
    load_run,
    request_run,
)
from app.tasks.scenario import dispatch_run

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "/scenarios",
    response_model=ScenarioRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_scenario(
    payload: ScenarioRunRequest,
    tenant: CurrentTenant,
    user: CurrentUser,
    _member: RequireMember,
    db: TenantDB,
) -> ScenarioRunResponse:
    """Accept a shock and hand it to a worker (FR-044a).

    The response is the handle, and its ``state`` is ``queued`` with no result:
    an operator reading it knows the question was recorded and that nothing has
    been computed yet.
    """
    try:
        shock = Shock(
            material_cost_pct=payload.shock.material_cost_pct,
            labor_rate_pct=payload.shock.labor_rate_pct,
            fee_rate_pct=payload.shock.fee_rate_pct,
            electricity_rate_pct=payload.shock.electricity_rate_pct,
        )
        run = await request_run(
            db,
            tenant,
            shock=shock,
            margin_floor_pct=payload.margin_floor_pct,
            sales_channel_id=payload.sales_channel_id,
            user=user,
        )
    except (ShockIsEmpty, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    await db.commit()
    await db.refresh(run)

    try:
        dispatch_run(run.id, tenant.id)
    except Exception as exc:  # noqa: BLE001 - recorded on the run, never hidden
        # FR-044b: a job must not appear to hang. The request succeeded and the
        # row exists; what failed is the queueing, and that belongs on the run
        # where an operator can see it.
        logger.error(f"Scenario run {run.id} could not be queued: {exc}")
        run.state = "failed"
        run.error_text = f"the scenario could not be queued: {exc}"
        db.add(run)
        await db.commit()
        await db.refresh(run)

    return ScenarioRunResponse.of(run)


@router.get("/scenarios", response_model=ScenarioRunListResponse)
async def list_scenarios(
    tenant: CurrentTenant,
    user: CurrentUser,
    db: TenantDB,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> ScenarioRunListResponse:
    """This tenant's scenario history, newest first."""
    runs, total = await list_runs(db, tenant, limit=limit, offset=offset)
    return ScenarioRunListResponse(runs=[ScenarioRunResponse.of(run) for run in runs], total=total)


@router.get("/scenarios/{run_id}", response_model=ScenarioRunResponse)
async def get_scenario(
    run_id: UUID,
    tenant: CurrentTenant,
    user: CurrentUser,
    db: TenantDB,
) -> ScenarioRunResponse:
    """One run's state and, once it has finished, its result.

    Another tenant's run is a ``404`` rather than a ``403``: confirming the row
    exists would leak that they ran a scenario, and the list of products a
    scenario names is a catalogue with margins attached.
    """
    run = await load_run(db, tenant, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No scenario run {run_id} in this tenant",
        )
    return ScenarioRunResponse.of(run)
