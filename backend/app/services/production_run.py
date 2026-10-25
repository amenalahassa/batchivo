"""Production Run service for business logic operations."""

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.production_run import ProductionRun, ProductionRunItem, ProductionRunMaterial
from app.models.inventory_transaction import InventoryTransaction, TransactionType
from app.models.spool import Spool
from app.models.filament_type import FilamentType
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.production_run import (
    ProductionRunCreate,
    ProductionRunUpdate,
    ProductionRunItemCreate,
    ProductionRunItemUpdate,
    ProductionRunMaterialCreate,
    ProductionRunMaterialUpdate,
)

logger = logging.getLogger(__name__)

# A run's money -- the per-gram figure a material is frozen at, the realised
# unit cost and the expected-against-actual summary -- lives in
# `app.services.run_costs`, which is type-checked as a money path (T265).
# Re-exported here for the callers that import it from the run service.
from app.services.run_costs import (  # noqa: E402
    COMPLETED,
    MaterialCostSummary,
    MaterialCostUnderivable,
    RealisedUnitCost,
    average_unit_cost,
    material_cost_summary,
    realised_unit_costs,
    record_actual_unit_costs,
    run_material_cost_per_gram,
)

__all__ = [
    "COMPLETED",
    "MaterialCostSummary",
    "MaterialCostUnderivable",
    "ProductionRunService",
    "RealisedUnitCost",
    "average_unit_cost",
    "realised_unit_costs",
    "run_material_cost_per_gram",
]

# OpenTelemetry tracer for production run operations
tracer = trace.get_tracer(__name__)


class ProductionRunService:
    """Service for managing production runs."""

    def __init__(self, db: AsyncSession, tenant: Tenant, user: Optional[User] = None):
        """
        Initialize the production run service.

        Args:
            db: AsyncSession instance for database operations
            tenant: Current tenant for isolation
            user: Current user performing actions (optional, for audit trail)
        """
        self.db = db
        self.tenant = tenant
        self.user = user

    def record_actual_unit_costs(
        self,
        production_run: ProductionRun,
        *,
        total_material_cost: Decimal,
        successful_weight: Decimal,
    ) -> None:
        """Write what each finished unit actually cost; see :func:`run_costs.record_actual_unit_costs`."""
        record_actual_unit_costs(
            production_run,
            total_material_cost=total_material_cost,
            successful_weight=successful_weight,
        )

    @staticmethod
    def material_cost_summary(production_run: ProductionRun) -> MaterialCostSummary:
        """A run's filament expected against actual; see :func:`run_costs.material_cost_summary`."""
        return material_cost_summary(production_run)

    async def create_production_run(
        self,
        data: ProductionRunCreate,
        items: Optional[list[ProductionRunItemCreate]] = None,
        materials: Optional[list[ProductionRunMaterialCreate]] = None,
    ) -> ProductionRun:
        """
        Create a new production run with optional items and materials.

        Args:
            data: ProductionRunCreate schema with base run data
            items: Optional list of production run items
            materials: Optional list of production run materials

        Returns:
            Created ProductionRun instance with relationships loaded
        """
        # Generate run number if not provided
        if not data.run_number:
            data.run_number = await self.generate_run_number()

        # Create production run instance
        production_run = ProductionRun(
            tenant_id=self.tenant.id,
            **data.model_dump(exclude={"run_number"}),
            run_number=data.run_number,
        )

        self.db.add(production_run)
        await self.db.flush()  # Flush to get production_run.id

        # Add items if provided
        if items:
            for item_data in items:
                item = ProductionRunItem(
                    production_run_id=production_run.id,
                    **item_data.model_dump(),
                )
                self.db.add(item)

        # Add materials if provided
        if materials:
            # Every spool in one query; each material without a typed figure
            # is frozen at its spool's landed cost.
            spool_ids = [m.spool_id for m in materials if m.cost_per_gram is None]
            spools_by_id: dict[UUID, Spool] = {}
            if spool_ids:
                spools_result = await self.db.execute(
                    select(Spool).where(Spool.id.in_(spool_ids), Spool.tenant_id == self.tenant.id)
                )
                spools_by_id = {s.id: s for s in spools_result.scalars().all()}

            for material_data in materials:
                if material_data.cost_per_gram is None:
                    spool = spools_by_id.get(material_data.spool_id)
                    if spool is None:
                        raise MaterialCostUnderivable(
                            f"spool {material_data.spool_id} was not found, so no cost "
                            "per gram can be derived"
                        )
                    material_data.cost_per_gram = run_material_cost_per_gram(spool, None)

                material = ProductionRunMaterial(
                    production_run_id=production_run.id,
                    **material_data.model_dump(),
                )
                self.db.add(material)

        await self.db.commit()
        await self.db.refresh(production_run)

        # Load relationships
        await self._load_relationships(production_run)

        return production_run

    async def get_production_run(self, run_id: UUID) -> Optional[ProductionRun]:
        """
        Get a production run by ID with all relationships loaded.

        Args:
            run_id: UUID of the production run

        Returns:
            ProductionRun instance or None if not found
        """
        result = await self.db.execute(
            select(ProductionRun)
            .where(ProductionRun.id == run_id)
            .where(ProductionRun.tenant_id == self.tenant.id)
            .options(
                selectinload(ProductionRun.items).selectinload(ProductionRunItem.model),
                selectinload(ProductionRun.materials)
                .selectinload(ProductionRunMaterial.spool)
                .selectinload(Spool.filament_type)
                .selectinload(FilamentType.material_type),
            )
        )
        return result.scalar_one_or_none()

    async def get_production_run_by_number(self, run_number: str) -> Optional[ProductionRun]:
        """
        Get a production run by run number.

        Args:
            run_number: Run number (e.g., "TENANT-20251113-001")

        Returns:
            ProductionRun instance or None if not found
        """
        result = await self.db.execute(
            select(ProductionRun)
            .where(ProductionRun.run_number == run_number)
            .where(ProductionRun.tenant_id == self.tenant.id)
            .options(
                selectinload(ProductionRun.items).selectinload(ProductionRunItem.model),
                selectinload(ProductionRun.materials)
                .selectinload(ProductionRunMaterial.spool)
                .selectinload(Spool.filament_type)
                .selectinload(FilamentType.material_type),
            )
        )
        return result.scalar_one_or_none()

    async def list_production_runs(
        self,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        started_after: Optional[datetime] = None,
        started_before: Optional[datetime] = None,
        search: Optional[str] = None,
    ) -> tuple[list[ProductionRun], int]:
        """
        List production runs with pagination and filtering.

        Args:
            page: Page number (1-indexed)
            page_size: Number of items per page
            status: Filter by status
            started_after: Filter runs started after this datetime
            started_before: Filter runs started before this datetime
            search: Search by run_number, printer_name, or notes

        Returns:
            Tuple of (list of ProductionRun instances, total count)
        """
        # Base query with tenant isolation
        query = select(ProductionRun).where(ProductionRun.tenant_id == self.tenant.id)

        # Apply filters
        if status:
            query = query.where(ProductionRun.status == status)

        if started_after:
            query = query.where(ProductionRun.started_at >= started_after)

        if started_before:
            query = query.where(ProductionRun.started_at <= started_before)

        if search:
            search_filter = or_(
                ProductionRun.run_number.ilike(f"%{search}%"),
                ProductionRun.printer_name.ilike(f"%{search}%"),
                ProductionRun.notes.ilike(f"%{search}%"),
            )
            query = query.where(search_filter)

        # Get total count
        count_query = select(func.count()).select_from(query.subquery())
        count_result = await self.db.execute(count_query)
        total = count_result.scalar_one()

        # Apply pagination and ordering
        query = (
            query.order_by(ProductionRun.started_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .options(
                selectinload(ProductionRun.items).selectinload(ProductionRunItem.model),
                selectinload(ProductionRun.materials)
                .selectinload(ProductionRunMaterial.spool)
                .selectinload(Spool.filament_type)
                .selectinload(FilamentType.material_type),
            )
        )

        result = await self.db.execute(query)
        runs = result.scalars().all()

        return list(runs), total

    async def update_production_run(
        self,
        run_id: UUID,
        data: ProductionRunUpdate,
    ) -> Optional[ProductionRun]:
        """
        Update a production run.

        Args:
            run_id: UUID of the production run
            data: ProductionRunUpdate schema with fields to update

        Returns:
            Updated ProductionRun instance or None if not found
        """
        # Get existing run
        production_run = await self.get_production_run(run_id)
        if not production_run:
            return None

        # Update fields (only non-None values)
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(production_run, field, value)

        await self.db.commit()
        await self.db.refresh(production_run)

        # Reload relationships
        await self._load_relationships(production_run)

        return production_run

    async def delete_production_run(self, run_id: UUID) -> bool:
        """
        Delete a production run (hard delete).

        Args:
            run_id: UUID of the production run

        Returns:
            True if deleted, False if not found
        """
        production_run = await self.get_production_run(run_id)
        if not production_run:
            return False

        await self.db.delete(production_run)
        await self.db.commit()

        return True

    async def add_item_to_run(
        self,
        run_id: UUID,
        item_data: ProductionRunItemCreate,
    ) -> Optional[ProductionRunItem]:
        """
        Add an item to an existing production run.

        Args:
            run_id: UUID of the production run
            item_data: ProductionRunItemCreate schema

        Returns:
            Created ProductionRunItem or None if run not found
        """
        production_run = await self.get_production_run(run_id)
        if not production_run:
            return None

        item = ProductionRunItem(
            production_run_id=run_id,
            **item_data.model_dump(),
        )

        self.db.add(item)
        await self.db.commit()
        await self.db.refresh(item)

        return item

    async def update_item(
        self,
        item_id: UUID,
        item_data: ProductionRunItemUpdate,
    ) -> Optional[ProductionRunItem]:
        """
        Update a production run item.

        Args:
            item_id: UUID of the item
            item_data: ProductionRunItemUpdate schema

        Returns:
            Updated ProductionRunItem or None if not found
        """
        result = await self.db.execute(
            select(ProductionRunItem)
            .join(ProductionRun)
            .where(ProductionRunItem.id == item_id)
            .where(ProductionRun.tenant_id == self.tenant.id)
        )
        item = result.scalar_one_or_none()
        if not item:
            return None

        # Update fields
        update_data = item_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(item, field, value)

        await self.db.commit()
        await self.db.refresh(item)

        return item

    async def add_material_to_run(
        self,
        run_id: UUID,
        material_data: ProductionRunMaterialCreate,
    ) -> Optional[ProductionRunMaterial]:
        """
        Add a material to an existing production run.

        Args:
            run_id: UUID of the production run
            material_data: ProductionRunMaterialCreate schema

        Returns:
            Created ProductionRunMaterial or None if run not found
        """
        production_run = await self.get_production_run(run_id)
        if not production_run:
            return None

        if material_data.cost_per_gram is None:
            spool_result = await self.db.execute(
                select(Spool).where(
                    Spool.id == material_data.spool_id, Spool.tenant_id == self.tenant.id
                )
            )
            spool = spool_result.scalar_one()
            material_data.cost_per_gram = run_material_cost_per_gram(spool, None)

        material = ProductionRunMaterial(
            production_run_id=run_id,
            **material_data.model_dump(),
        )

        self.db.add(material)
        await self.db.commit()
        await self.db.refresh(material)

        return material

    async def update_material(
        self,
        material_id: UUID,
        material_data: ProductionRunMaterialUpdate,
    ) -> Optional[ProductionRunMaterial]:
        """
        Update a production run material.

        Args:
            material_id: UUID of the material
            material_data: ProductionRunMaterialUpdate schema

        Returns:
            Updated ProductionRunMaterial or None if not found
        """
        result = await self.db.execute(
            select(ProductionRunMaterial)
            .join(ProductionRun)
            .where(ProductionRunMaterial.id == material_id)
            .where(ProductionRun.tenant_id == self.tenant.id)
        )
        material = result.scalar_one_or_none()
        if not material:
            return None

        # Update fields
        update_data = material_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(material, field, value)

        await self.db.commit()
        await self.db.refresh(material)

        return material

    async def generate_run_number(self) -> str:
        """
        Generate a unique run number for the current tenant.

        Format: {tenant_short}-YYYYMMDD-NNN
        Example: ACME-20251113-001

        Returns:
            Generated run number string
        """
        # Get tenant short code (first 4 chars of slug, uppercase)
        tenant_short = self.tenant.slug[:4].upper()

        # Get current date
        date_str = datetime.now().strftime("%Y%m%d")

        # Find the highest sequence number for today
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)

        result = await self.db.execute(
            select(func.count(ProductionRun.id))
            .where(ProductionRun.tenant_id == self.tenant.id)
            .where(ProductionRun.started_at >= today_start)
            .where(ProductionRun.started_at < today_end)
        )
        count = result.scalar_one()

        # Increment sequence
        sequence = count + 1

        # Format: TENANT-YYYYMMDD-001
        run_number = f"{tenant_short}-{date_str}-{sequence:03d}"

        return run_number

    async def complete_production_run(
        self,
        run_id: UUID,
    ) -> Optional[ProductionRun]:
        """
        Complete a production run and deduct materials from spool inventory.

        The one implementation of completion (task T218). `POST
        /production-runs/{id}/complete` is a thin call into this; it used to
        carry its own ~150-line copy -- validation, deduction, cost -- while
        this method, the one the suite tested, had no caller. Where the two
        disagreed this keeps, deliberately:

        * the route's refusals: a run already completed, and a material with
          no actual usage recorded, are both errors rather than a silent
          deduction of nothing;
        * this method's audit trail: an `InventoryTransaction` per material
          and an atomic `UPDATE` of the spool, which the route skipped;
        * this method's telemetry dispatch, which
          the route never reached -- so a run completed from the console
          never asked the printer what it used;
        * the route's exact cost: `record_actual_unit_costs`, rounded once to
          each column's scale, instead of a second copy of that arithmetic.

        The material cost is `ProductionRunMaterial.total_cost` summed -- the
        one place the weight-times-rate multiplication lives.

        Args:
            run_id: UUID of the production run

        Returns:
            Completed ProductionRun instance or None if not found

        Raises:
            ValueError: If the run is already completed, a material has no
                recorded usage, or a spool holds too little filament
        """
        with tracer.start_as_current_span("complete_production_run") as span:
            span.set_attribute("production_run.id", str(run_id))
            span.set_attribute("tenant.id", str(self.tenant.id))

            # Get production run with materials loaded
            production_run = await self.get_production_run(run_id)
            if not production_run:
                span.set_attribute("production_run.found", False)
                return None

            span.set_attribute("production_run.found", True)
            span.set_attribute("production_run.run_number", production_run.run_number)
            span.set_attribute("production_run.materials_count", len(production_run.materials))

            if production_run.status == "completed":
                raise ValueError("Production run is already completed")

            # Every material needs a recorded usage -- a weighing or a manual
            # figure. Deducting nothing for a material nobody weighed would
            # report a run that consumed no filament (FR-019).
            for material in production_run.materials:
                has_weighing = (
                    material.spool_weight_before_grams is not None
                    and material.spool_weight_after_grams is not None
                )
                if not has_weighing and material.actual_model_weight_grams is None:
                    raise ValueError(
                        f"Material {material.id} does not have actual usage recorded. "
                        f"Please weigh spools or enter manual usage."
                    )

            try:
                # Batch-fetch all spools for this run's materials in one query
                spool_ids = [m.spool_id for m in production_run.materials]
                if spool_ids:
                    spools_result = await self.db.execute(
                        select(Spool).where(Spool.id.in_(spool_ids))
                    )
                    spools_by_id = {s.id: s for s in spools_result.scalars().all()}
                else:
                    spools_by_id = {}

                # Validate sufficient spool weight for all materials
                for material in production_run.materials:
                    actual_weight = material.actual_total_weight
                    spool = spools_by_id[material.spool_id]

                    if Decimal(str(spool.current_weight)) < actual_weight:
                        error_msg = (
                            f"Insufficient inventory (weight) in spool {spool.spool_id}: "
                            f"Required {actual_weight}g, Available {spool.current_weight}g"
                        )
                        span.set_status(Status(StatusCode.ERROR, error_msg))
                        span.set_attribute("error.type", "insufficient_weight")
                        raise ValueError(error_msg)

                # Deduct materials from spools and create inventory transactions
                # Count materials before commit/refresh to avoid lazy loading issues
                materials_count = len(production_run.materials)
                total_material_cost = Decimal("0")

                for material in production_run.materials:
                    actual_weight = material.actual_total_weight  # Keep as Decimal
                    spool = spools_by_id[material.spool_id]
                    weight_before = Decimal(str(spool.current_weight))

                    # Calculate variance percentage
                    estimated = material.estimated_total_weight
                    variance_percentage = None
                    if estimated > 0:
                        variance_percentage = ((actual_weight - estimated) / estimated) * Decimal(
                            "100"
                        )

                    # The material's own cost, from the one multiplication
                    # that exists for it (task T218).
                    if material.cost_per_gram:
                        total_material_cost += material.total_cost

                    # Update spool weight atomically
                    await self.db.execute(
                        update(Spool)
                        .where(Spool.id == material.spool_id)
                        .values(current_weight=Spool.current_weight - actual_weight)
                    )

                    # Create inventory transaction record
                    transaction = InventoryTransaction(
                        tenant_id=self.tenant.id,
                        spool_id=material.spool_id,
                        transaction_type=TransactionType.USAGE,
                        weight_before=weight_before,
                        weight_change=-actual_weight,
                        weight_after=weight_before - actual_weight,
                        production_run_id=production_run.id,
                        production_run_material_id=material.id,
                        user_id=self.user.id if self.user else None,
                        description=f"Production run {production_run.run_number}: Used {actual_weight}g from spool {spool.spool_id}",
                        transaction_at=datetime.now(),
                        transaction_metadata={
                            "run_number": production_run.run_number,
                            "estimated_weight": float(estimated),
                            "actual_weight": float(actual_weight),
                            "variance_percentage": float(variance_percentage)
                            if variance_percentage
                            else None,
                        },
                    )
                    self.db.add(transaction)

                # What each finished unit actually cost, with the run's waste
                # spread across the units that survived (FR-040).
                await self._record_run_actuals(production_run, total_material_cost)

                # Update production run status
                production_run.status = "completed"
                if not production_run.completed_at:
                    production_run.completed_at = datetime.now(timezone.utc)

                # Calculate duration if not set
                if not production_run.duration_hours and production_run.completed_at:
                    # Ensure both timestamps are timezone-aware for comparison
                    completed = production_run.completed_at
                    started = production_run.started_at
                    if started.tzinfo is None:
                        started = started.replace(tzinfo=timezone.utc)
                    if completed.tzinfo is None:
                        completed = completed.replace(tzinfo=timezone.utc)
                    duration = completed - started
                    production_run.duration_hours = Decimal(
                        str(duration.total_seconds() / 3600)
                    ).quantize(Decimal("0.01"))

                await self.db.flush()  # Flush changes before commit
                await self.db.commit()
                await self.db.refresh(production_run)

                # Record metrics
                try:
                    from app.observability.metrics import record_production_run_completed

                    duration_seconds = (
                        (production_run.completed_at - production_run.started_at).total_seconds()
                        if production_run.completed_at and production_run.started_at
                        else 0
                    )
                    record_production_run_completed(
                        tenant_id=str(self.tenant.id),
                        duration_seconds=duration_seconds,
                        material_cost=float(total_material_cost),
                    )
                except Exception as metrics_error:
                    logger.warning(f"Failed to record metrics: {metrics_error}")

                # Ask the machine what the job actually used (FR-040, FR-042).
                #
                # Dispatched here because this is the moment worth asking: the
                # printer still holds the finished job's figures and a nightly
                # sweep would ask after it had moved on. Before this call the
                # task had no caller anywhere, so `actual_grams` and
                # `actual_print_hours` were never observed from a machine and
                # no cost line could acquire an observed origin from one
                # (task T159).
                #
                # Never fatal. The run is already committed; an unreachable
                # broker or an offline printer costs the observation, not the
                # record of the run, which is why this is a warning and not a
                # rollback.
                try:
                    from app.tasks.telemetry import ingest_run_actuals_task

                    ingest_run_actuals_task.apply_async(args=[str(production_run.id)])
                except Exception as dispatch_error:
                    logger.warning(
                        f"Could not queue telemetry ingestion for run "
                        f"{production_run.run_number}: {dispatch_error}"
                    )

                logger.info(
                    f"Completed production run {production_run.run_number} with "
                    f"{materials_count} material transactions"
                )

                span.set_status(Status(StatusCode.OK))
                span.set_attribute("production_run.status", "completed")
                span.set_attribute("production_run.material_cost", float(total_material_cost))

                # Reload relationships
                await self._load_relationships(production_run)

                return production_run

            except ValueError:
                # Rollback any pending changes on validation errors
                await self.db.rollback()
                raise
            except Exception as e:
                # Rollback to prevent partial inventory updates
                await self.db.rollback()
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                logger.error(f"Failed to complete production run {run_id}, rolled back: {e}")
                raise

    async def revert_completion(
        self,
        run_id: UUID,
    ) -> Optional[ProductionRun]:
        """
        Revert a completed production run back to in_progress status.

        This method:
        1. Finds original usage transactions for the run
        2. Returns materials to spool inventory
        3. Creates reversal transaction records for audit trail
        4. Updates run status back to 'in_progress'

        Args:
            run_id: UUID of the production run

        Returns:
            Reverted ProductionRun instance or None if not found

        Raises:
            ValueError: If run is not in completed status
        """
        with tracer.start_as_current_span("revert_completion") as span:
            span.set_attribute("production_run.id", str(run_id))
            span.set_attribute("tenant.id", str(self.tenant.id))

            # Get production run with materials loaded
            production_run = await self.get_production_run(run_id)
            if not production_run:
                span.set_attribute("production_run.found", False)
                return None

            span.set_attribute("production_run.found", True)
            span.set_attribute("production_run.run_number", production_run.run_number)

            try:
                if production_run.status != "completed":
                    error_msg = "Can only revert completed production runs"
                    span.set_status(Status(StatusCode.ERROR, error_msg))
                    span.set_attribute("error.type", "invalid_status")
                    raise ValueError(error_msg)

                # Get original usage transactions for this run
                original_transactions_result = await self.db.execute(
                    select(InventoryTransaction)
                    .where(InventoryTransaction.production_run_id == run_id)
                    .where(InventoryTransaction.transaction_type == TransactionType.USAGE)
                    .where(InventoryTransaction.is_reversal is False)
                )
                original_transactions = {
                    tx.production_run_material_id: tx
                    for tx in original_transactions_result.scalars().all()
                }

                # Return materials to spools and create reversal transactions
                # Count materials before commit/refresh to avoid lazy loading issues
                materials_count = len(production_run.materials)
                span.set_attribute("production_run.materials_count", materials_count)

                # Batch-fetch all spools for this run's materials in one query
                spool_ids = [m.spool_id for m in production_run.materials]
                if spool_ids:
                    spools_result = await self.db.execute(
                        select(Spool).where(Spool.id.in_(spool_ids))
                    )
                    spools_by_id = {s.id: s for s in spools_result.scalars().all()}
                else:
                    spools_by_id = {}

                for material in production_run.materials:
                    actual_weight = material.actual_total_weight  # Keep as Decimal
                    spool = spools_by_id[material.spool_id]
                    weight_before = Decimal(str(spool.current_weight))

                    # Update spool weight atomically
                    await self.db.execute(
                        update(Spool)
                        .where(Spool.id == material.spool_id)
                        .values(current_weight=Spool.current_weight + actual_weight)
                    )

                    # Get original transaction ID for this material (if exists)
                    original_tx = original_transactions.get(material.id)
                    reversal_of_id = original_tx.id if original_tx else None

                    # Create reversal transaction record
                    transaction = InventoryTransaction(
                        tenant_id=self.tenant.id,
                        spool_id=material.spool_id,
                        transaction_type=TransactionType.RETURN,
                        weight_before=weight_before,
                        weight_change=actual_weight,
                        weight_after=weight_before + actual_weight,
                        production_run_id=production_run.id,
                        production_run_material_id=material.id,
                        user_id=self.user.id if self.user else None,
                        description=f"Revert production run {production_run.run_number}: Returned {actual_weight}g to spool {spool.spool_id}",
                        transaction_at=datetime.now(),
                        reversal_of_id=reversal_of_id,
                        is_reversal=True,
                        transaction_metadata={
                            "run_number": production_run.run_number,
                            "reason": "Production run completion reverted",
                        },
                    )
                    self.db.add(transaction)

                # Update production run status
                production_run.status = "in_progress"

                await self.db.flush()  # Flush changes before commit
                await self.db.commit()
                await self.db.refresh(production_run)

                logger.info(
                    f"Reverted production run {production_run.run_number} with "
                    f"{materials_count} material reversals"
                )

                span.set_status(Status(StatusCode.OK))
                span.set_attribute("production_run.status", "in_progress")

                # Reload relationships
                await self._load_relationships(production_run)

                return production_run

            except ValueError:
                # Rollback any pending changes on validation errors
                await self.db.rollback()
                raise
            except Exception as e:
                # Rollback to prevent partial inventory updates
                await self.db.rollback()
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                logger.error(f"Failed to revert production run {run_id}, rolled back: {e}")
                raise

    async def calculate_run_variance(
        self,
        run_id: UUID,
    ) -> Optional[dict]:
        """
        Calculate comprehensive variance metrics for a production run.

        Returns variance data including:
        - Material weight variance (total and per-material)
        - Time variance
        - Success rate statistics

        Args:
            run_id: UUID of the production run

        Returns:
            Dictionary with variance metrics or None if run not found
        """
        production_run = await self.get_production_run(run_id)
        if not production_run:
            return None

        # Material weight variance
        total_estimated_weight = Decimal("0")
        total_actual_weight = Decimal("0")
        material_variances = []

        for material in production_run.materials:
            estimated = material.estimated_total_weight
            actual = material.actual_total_weight

            total_estimated_weight += estimated
            total_actual_weight += actual

            material_variances.append(
                {
                    "spool_id": str(material.spool_id),
                    "estimated_grams": float(estimated),
                    "actual_grams": float(actual),
                    "variance_grams": float(material.variance_grams),
                    "variance_percentage": float(material.variance_percentage),
                }
            )

        # Overall weight variance
        weight_variance_grams = total_actual_weight - total_estimated_weight
        weight_variance_percentage = (
            (weight_variance_grams / total_estimated_weight * Decimal("100"))
            if total_estimated_weight > 0
            else Decimal("0")
        )

        # Time variance
        time_variance_hours = None
        time_variance_percentage = None
        if production_run.duration_hours and production_run.estimated_print_time_hours:
            time_variance_hours = Decimal(str(production_run.duration_hours)) - Decimal(
                str(production_run.estimated_print_time_hours)
            )
            time_variance_percentage = (
                time_variance_hours / Decimal(str(production_run.estimated_print_time_hours))
            ) * Decimal("100")

        # Success rate statistics
        total_quantity = 0
        total_successful = 0
        total_failed = 0

        for item in production_run.items:
            total_quantity += item.quantity
            total_successful += item.successful_quantity or 0
            total_failed += item.failed_quantity or 0

        success_rate = (
            (Decimal(str(total_successful)) / Decimal(str(total_quantity)) * Decimal("100"))
            if total_quantity > 0
            else Decimal("0")
        )

        return {
            "run_id": str(run_id),
            "run_number": production_run.run_number,
            "status": production_run.status,
            "weight_variance": {
                "total_estimated_grams": float(total_estimated_weight),
                "total_actual_grams": float(total_actual_weight),
                "variance_grams": float(weight_variance_grams),
                "variance_percentage": float(weight_variance_percentage),
                "materials": material_variances,
            },
            "time_variance": {
                "estimated_hours": float(production_run.estimated_print_time_hours)
                if production_run.estimated_print_time_hours
                else None,
                "actual_hours": float(production_run.duration_hours)
                if production_run.duration_hours
                else None,
                "variance_hours": float(time_variance_hours) if time_variance_hours else None,
                "variance_percentage": float(time_variance_percentage)
                if time_variance_percentage
                else None,
            },
            "success_rate": {
                "total_quantity": total_quantity,
                "successful_quantity": total_successful,
                "failed_quantity": total_failed,
                "success_rate_percentage": float(success_rate),
            },
        }

    async def calculate_aggregate_variance(
        self,
        started_after: Optional[datetime] = None,
        started_before: Optional[datetime] = None,
        status: str = "completed",
    ) -> dict:
        """
        Calculate aggregate variance metrics across multiple production runs.

        Useful for reporting and trend analysis.

        Args:
            started_after: Filter runs started after this datetime
            started_before: Filter runs started before this datetime
            status: Filter by run status (default: completed)

        Returns:
            Dictionary with aggregate variance metrics
        """
        # Get runs matching criteria
        runs, total = await self.list_production_runs(
            page=1,
            page_size=1000,  # Large page size for aggregate calculation
            status=status,
            started_after=started_after,
            started_before=started_before,
        )

        if not runs:
            return {
                "runs_analyzed": 0,
                "aggregate_weight_variance": None,
                "aggregate_time_variance": None,
                "aggregate_success_rate": None,
            }

        # Aggregate calculations
        total_estimated_weight = Decimal("0")
        total_actual_weight = Decimal("0")
        total_estimated_time = Decimal("0")
        total_actual_time = Decimal("0")
        total_quantity = 0
        total_successful = 0
        total_failed = 0
        runs_with_time_data = 0

        for run in runs:
            # Weight aggregates
            for material in run.materials:
                total_estimated_weight += material.estimated_total_weight
                total_actual_weight += material.actual_total_weight

            # Time aggregates
            if run.duration_hours and run.estimated_print_time_hours:
                total_estimated_time += Decimal(str(run.estimated_print_time_hours))
                total_actual_time += Decimal(str(run.duration_hours))
                runs_with_time_data += 1

            # Success rate aggregates
            for item in run.items:
                total_quantity += item.quantity
                total_successful += item.successful_quantity or 0
                total_failed += item.failed_quantity or 0

        # Calculate aggregate variances
        weight_variance_grams = total_actual_weight - total_estimated_weight
        weight_variance_percentage = (
            (weight_variance_grams / total_estimated_weight * Decimal("100"))
            if total_estimated_weight > 0
            else Decimal("0")
        )

        time_variance_hours = (
            total_actual_time - total_estimated_time if runs_with_time_data > 0 else None
        )
        time_variance_percentage = (
            (time_variance_hours / total_estimated_time * Decimal("100"))
            if runs_with_time_data > 0 and total_estimated_time > 0
            else None
        )

        success_rate = (
            (Decimal(str(total_successful)) / Decimal(str(total_quantity)) * Decimal("100"))
            if total_quantity > 0
            else Decimal("0")
        )

        return {
            "runs_analyzed": len(runs),
            "aggregate_weight_variance": {
                "total_estimated_grams": float(total_estimated_weight),
                "total_actual_grams": float(total_actual_weight),
                "variance_grams": float(weight_variance_grams),
                "variance_percentage": float(weight_variance_percentage),
            },
            "aggregate_time_variance": {
                "total_estimated_hours": float(total_estimated_time)
                if runs_with_time_data > 0
                else None,
                "total_actual_hours": float(total_actual_time) if runs_with_time_data > 0 else None,
                "variance_hours": float(time_variance_hours) if time_variance_hours else None,
                "variance_percentage": float(time_variance_percentage)
                if time_variance_percentage
                else None,
                "runs_with_data": runs_with_time_data,
            },
            "aggregate_success_rate": {
                "total_quantity": total_quantity,
                "successful_quantity": total_successful,
                "failed_quantity": total_failed,
                "success_rate_percentage": float(success_rate),
            },
        }

    async def cancel_production_run(
        self,
        run_id: UUID,
        cancel_mode: str = "full_reversal",
        partial_usage: Optional[dict[UUID, Decimal]] = None,
    ) -> Optional[ProductionRun]:
        """
        Cancel a production run with options for handling materials.

        Cancel modes:
        - "full_reversal": Restore all spool weights to original (as if run never happened)
        - "record_partial": Record actual filament used up to cancellation point

        Args:
            run_id: UUID of the production run
            cancel_mode: Either "full_reversal" or "record_partial"
            partial_usage: Dict mapping spool_id to actual grams used (for record_partial mode)

        Returns:
            Cancelled ProductionRun instance or None if not found

        Raises:
            ValueError: If run is not in in_progress status or invalid cancel_mode
        """
        with tracer.start_as_current_span("cancel_production_run") as span:
            span.set_attribute("production_run.id", str(run_id))
            span.set_attribute("tenant.id", str(self.tenant.id))
            span.set_attribute("cancel_mode", cancel_mode)

            # Get production run with materials loaded
            production_run = await self.get_production_run(run_id)
            if not production_run:
                span.set_attribute("production_run.found", False)
                return None

            span.set_attribute("production_run.found", True)
            span.set_attribute("production_run.run_number", production_run.run_number)

            try:
                if production_run.status != "in_progress":
                    error_msg = "Can only cancel in-progress production runs"
                    span.set_status(Status(StatusCode.ERROR, error_msg))
                    span.set_attribute("error.type", "invalid_status")
                    raise ValueError(error_msg)

                if cancel_mode not in ("full_reversal", "record_partial"):
                    error_msg = f"Invalid cancel_mode: {cancel_mode}"
                    span.set_status(Status(StatusCode.ERROR, error_msg))
                    span.set_attribute("error.type", "invalid_cancel_mode")
                    raise ValueError(error_msg)

                if cancel_mode == "record_partial":
                    # Record the partial usage and deduct from spools
                    if not partial_usage:
                        partial_usage = {}

                    # Pre-fetch all spools that have partial usage in one query
                    active_spool_ids = [
                        m.spool_id
                        for m in production_run.materials
                        if partial_usage.get(m.spool_id, Decimal("0")) > 0
                    ]
                    if active_spool_ids:
                        sp_result = await self.db.execute(
                            select(Spool).where(Spool.id.in_(active_spool_ids))
                        )
                        spools_by_id = {s.id: s for s in sp_result.scalars().all()}
                    else:
                        spools_by_id = {}

                    for material in production_run.materials:
                        # Use provided partial usage or fall back to 0
                        actual_used = partial_usage.get(material.spool_id, Decimal("0"))

                        if actual_used > 0:
                            spool = spools_by_id[material.spool_id]
                            weight_before = Decimal(str(spool.current_weight))

                            # Validate sufficient weight
                            if weight_before < actual_used:
                                error_msg = (
                                    f"Insufficient inventory (weight) in spool {spool.spool_id}: "
                                    f"Requested {actual_used}g, Available {weight_before}g"
                                )
                                span.set_status(Status(StatusCode.ERROR, error_msg))
                                span.set_attribute("error.type", "insufficient_weight")
                                raise ValueError(error_msg)

                            # Update spool weight
                            await self.db.execute(
                                update(Spool)
                                .where(Spool.id == material.spool_id)
                                .values(current_weight=Spool.current_weight - actual_used)
                            )

                            # Create usage transaction
                            transaction = InventoryTransaction(
                                tenant_id=self.tenant.id,
                                spool_id=material.spool_id,
                                transaction_type=TransactionType.USAGE,
                                weight_before=weight_before,
                                weight_change=-actual_used,
                                weight_after=weight_before - actual_used,
                                production_run_id=production_run.id,
                                production_run_material_id=material.id,
                                user_id=self.user.id if self.user else None,
                                description=f"Cancelled run {production_run.run_number}: Partial usage {actual_used}g from spool {spool.spool_id}",
                                transaction_at=datetime.now(),
                                transaction_metadata={
                                    "run_number": production_run.run_number,
                                    "cancel_mode": "record_partial",
                                    "actual_used": float(actual_used),
                                },
                            )
                            self.db.add(transaction)

                # Update production run status to cancelled
                production_run.status = "cancelled"
                production_run.completed_at = datetime.now(timezone.utc)

                # Calculate duration
                duration = production_run.completed_at - production_run.started_at
                production_run.duration_hours = Decimal(
                    str(duration.total_seconds() / 3600)
                ).quantize(Decimal("0.01"))

                await self.db.flush()
                await self.db.commit()
                await self.db.refresh(production_run)

                logger.info(
                    f"Cancelled production run {production_run.run_number} with mode: {cancel_mode}"
                )

                span.set_status(Status(StatusCode.OK))
                span.set_attribute("production_run.status", "cancelled")

                await self._load_relationships(production_run)
                return production_run

            except ValueError:
                # Rollback any pending changes on validation errors
                await self.db.rollback()
                raise
            except Exception as e:
                # Rollback to prevent partial state changes
                await self.db.rollback()
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                logger.error(f"Failed to cancel production run {run_id}, rolled back: {e}")
                raise

    async def fail_production_run(
        self,
        run_id: UUID,
        waste_grams: dict[UUID, Decimal],
        failure_reason: str,
        notes: Optional[str] = None,
    ) -> Optional[ProductionRun]:
        """
        Mark a production run as failed and record waste materials.

        This method:
        1. Records waste materials as WASTE transaction type
        2. Deducts waste from spool inventory
        3. Updates run status to 'failed' with failure reason

        Args:
            run_id: UUID of the production run
            waste_grams: Dict mapping spool_id to grams of wasted filament
            failure_reason: Reason for failure (e.g., "spaghetti", "layer_shift", "clog")
            notes: Optional additional notes about the failure

        Returns:
            Failed ProductionRun instance or None if not found

        Raises:
            ValueError: If run is not in in_progress status
        """
        with tracer.start_as_current_span("fail_production_run") as span:
            span.set_attribute("production_run.id", str(run_id))
            span.set_attribute("tenant.id", str(self.tenant.id))
            span.set_attribute("failure_reason", failure_reason)

            # Get production run with materials loaded
            production_run = await self.get_production_run(run_id)
            if not production_run:
                span.set_attribute("production_run.found", False)
                return None

            span.set_attribute("production_run.found", True)
            span.set_attribute("production_run.run_number", production_run.run_number)

            try:
                if production_run.status != "in_progress":
                    error_msg = "Can only fail in-progress production runs"
                    span.set_status(Status(StatusCode.ERROR, error_msg))
                    span.set_attribute("error.type", "invalid_status")
                    raise ValueError(error_msg)

                total_waste = Decimal("0")

                # Pre-fetch all spools that have waste in one query
                waste_spool_ids = [
                    m.spool_id
                    for m in production_run.materials
                    if waste_grams.get(m.spool_id, Decimal("0")) > 0
                ]
                if waste_spool_ids:
                    waste_sp_result = await self.db.execute(
                        select(Spool).where(Spool.id.in_(waste_spool_ids))
                    )
                    waste_spools_by_id = {s.id: s for s in waste_sp_result.scalars().all()}
                else:
                    waste_spools_by_id = {}

                # Process waste for each material
                for material in production_run.materials:
                    waste_amount = waste_grams.get(material.spool_id, Decimal("0"))

                    if waste_amount > 0:
                        total_waste += waste_amount

                        spool = waste_spools_by_id[material.spool_id]
                        weight_before = Decimal(str(spool.current_weight))

                        # Validate sufficient weight
                        if weight_before < waste_amount:
                            error_msg = (
                                f"Insufficient inventory (weight) in spool {spool.spool_id}: "
                                f"Waste amount {waste_amount}g exceeds available {weight_before}g"
                            )
                            span.set_status(Status(StatusCode.ERROR, error_msg))
                            span.set_attribute("error.type", "insufficient_weight")
                            raise ValueError(error_msg)

                        # Update spool weight
                        await self.db.execute(
                            update(Spool)
                            .where(Spool.id == material.spool_id)
                            .values(current_weight=Spool.current_weight - waste_amount)
                        )

                        # Create WASTE transaction
                        transaction = InventoryTransaction(
                            tenant_id=self.tenant.id,
                            spool_id=material.spool_id,
                            transaction_type=TransactionType.WASTE,
                            weight_before=weight_before,
                            weight_change=-waste_amount,
                            weight_after=weight_before - waste_amount,
                            production_run_id=production_run.id,
                            production_run_material_id=material.id,
                            user_id=self.user.id if self.user else None,
                            description=f"Failed run {production_run.run_number}: {failure_reason} - Waste {waste_amount}g from spool {spool.spool_id}",
                            transaction_at=datetime.now(),
                            transaction_metadata={
                                "run_number": production_run.run_number,
                                "failure_reason": failure_reason,
                                "waste_grams": float(waste_amount),
                                "notes": notes,
                            },
                        )
                        self.db.add(transaction)

                # Update production run
                production_run.status = "failed"
                production_run.completed_at = datetime.now(timezone.utc)
                production_run.waste_filament_grams = total_waste
                production_run.waste_reason = failure_reason
                if notes:
                    production_run.notes = (
                        production_run.notes or ""
                    ) + f"\n\nFailure notes: {notes}"

                # Calculate duration
                duration = production_run.completed_at - production_run.started_at
                production_run.duration_hours = Decimal(
                    str(duration.total_seconds() / 3600)
                ).quantize(Decimal("0.01"))

                await self.db.flush()
                await self.db.commit()
                await self.db.refresh(production_run)

                logger.info(
                    f"Failed production run {production_run.run_number}: {failure_reason} "
                    f"with {total_waste}g total waste"
                )

                span.set_status(Status(StatusCode.OK))
                span.set_attribute("production_run.status", "failed")
                span.set_attribute("production_run.total_waste_grams", float(total_waste))

                await self._load_relationships(production_run)
                return production_run

            except ValueError:
                # Rollback any pending changes on validation errors
                await self.db.rollback()
                raise
            except Exception as e:
                # Rollback to prevent partial inventory updates (waste transactions)
                await self.db.rollback()
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                logger.error(f"Failed to fail production run {run_id}, rolled back: {e}")
                raise

    async def backfill_run_actuals(self, production_run: ProductionRun) -> bool:
        """Record a completed run's unit actuals where it carries none (task T237).

        For ``scripts/backfill_cost_analysis.py``, which had its own copy of
        the weight-times-rate arithmetic. The material cost is each
        material's own ``total_cost``, and the unit costs are
        :meth:`record_actual_unit_costs`'s. Once recorded, the run counts in
        its models' realised averages by its units like any other, since those
        are derived on read (T255). Returns whether anything was recorded.
        """
        total_material_cost = sum(
            (
                material.total_cost
                for material in production_run.materials
                if material.cost_per_gram
            ),
            Decimal("0"),
        )
        if total_material_cost == Decimal("0"):
            return False
        await self._record_run_actuals(production_run, total_material_cost)
        return production_run.cost_per_gram_actual is not None

    async def _record_run_actuals(
        self,
        production_run: ProductionRun,
        total_material_cost: Decimal,
    ) -> None:
        """Weigh the successful output and record its unit costs.

        The successful weight is each successful unit's BOM weight. The unit
        costs themselves are `record_actual_unit_costs`'s -- the exact,
        once-rounded figures -- so this method decides only which units count.
        A model's realised average is derived from those records on read
        (:func:`realised_unit_costs`), never stored (T255).
        """
        successful_weight = Decimal("0")
        if production_run.is_multi_plate and production_run.plates:
            units = [
                (plate, plate.successful_prints)
                for plate in production_run.plates
                if plate.successful_prints > 0
            ]
        else:
            units = [
                (item, item.successful_quantity)
                for item in (production_run.items or [])
                if item.successful_quantity > 0
            ]

        for unit, quantity in units:
            unit.model_weight_grams = await self._get_model_weight(unit.model_id)
            successful_weight += Decimal(str(quantity)) * unit.model_weight_grams

        self.record_actual_unit_costs(
            production_run,
            total_material_cost=total_material_cost,
            successful_weight=successful_weight,
        )

        if successful_weight <= Decimal("0"):
            logger.warning(
                f"No successful items for run {production_run.run_number}, skipping cost analysis"
            )
            return

        logger.info(
            f"Recorded run actuals for {production_run.run_number}: "
            f"cost_per_gram={production_run.cost_per_gram_actual}, "
            f"successful_weight={successful_weight}g"
        )

    async def _get_model_weight(self, model_id: UUID) -> Decimal:
        """
        Get total material weight for a model from its BOM.

        Args:
            model_id: UUID of the model

        Returns:
            Total weight in grams from all BOM materials
        """
        from app.models.model_material import ModelMaterial

        result = await self.db.execute(
            select(func.sum(ModelMaterial.weight_grams)).where(ModelMaterial.model_id == model_id)
        )
        total_weight = result.scalar()
        return Decimal(str(total_weight)) if total_weight else Decimal("0")

    async def _load_relationships(self, production_run: ProductionRun) -> None:
        """
        Load all relationships for a production run.

        Args:
            production_run: ProductionRun instance to load relationships for
        """
        # Refresh with relationships
        result = await self.db.execute(
            select(ProductionRun)
            .where(ProductionRun.id == production_run.id)
            .options(
                selectinload(ProductionRun.items).selectinload(ProductionRunItem.model),
                selectinload(ProductionRun.materials)
                .selectinload(ProductionRunMaterial.spool)
                .selectinload(Spool.filament_type)
                .selectinload(FilamentType.material_type),
            )
        )
        loaded_run = result.scalar_one()

        # Copy loaded relationships back to original instance
        production_run.items = loaded_run.items
        production_run.materials = loaded_run.materials
