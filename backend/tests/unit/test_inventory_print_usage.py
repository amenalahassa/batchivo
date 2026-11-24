"""`create_print_usage_transaction` (spec 011, T032): a USAGE entry without production run."""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory_transaction import InventoryTransaction, TransactionType
from app.models.spool import Spool
from app.services.inventory_transaction import InventoryTransactionService

pytestmark = pytest.mark.asyncio


async def test_decrements_spool_and_records_usage(
    db_session: AsyncSession, test_tenant, test_user, test_spool: Spool
):
    before = Decimal(str(test_spool.current_weight))
    job_id, send_id = uuid4(), uuid4()
    service = InventoryTransactionService(db_session, test_tenant, test_user)

    transaction = await service.create_print_usage_transaction(
        spool=test_spool,
        weight_used=Decimal("28.50"),
        print_job_id=job_id,
        print_send_id=send_id,
    )
    await db_session.commit()
    await db_session.refresh(test_spool)

    assert Decimal(str(test_spool.current_weight)) == before - Decimal("28.50")
    stored = (
        await db_session.execute(
            select(InventoryTransaction).where(InventoryTransaction.id == transaction.id)
        )
    ).scalar_one()
    assert stored.transaction_type == TransactionType.USAGE
    assert stored.production_run_id is None
    assert Decimal(str(stored.weight_change)) == Decimal("-28.50")
    assert stored.user_id == test_user.id
    assert str(job_id) in stored.description
    assert stored.transaction_metadata["print_send_id"] == str(send_id)
