"""Schema guard for the refund actuals table."""

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from app.models.refund_actual import RefundActual


def test_the_provider_refund_index_compiles_to_a_partial_unique_index() -> None:
    """The redelivery guard must build on PostgreSQL.

    Its predicate was once written with the `Text` column *type* instead of the
    `text()` SQL construct, which made `CREATE INDEX` -- and so the whole test
    schema -- fail to build on PostgreSQL while SQLite ignored it.
    """
    index = next(
        i for i in RefundActual.__table__.indexes if i.name == "uq_refund_actuals_provider_refund"
    )

    ddl = str(CreateIndex(index).compile(dialect=postgresql.dialect()))

    assert "CREATE UNIQUE INDEX uq_refund_actuals_provider_refund" in ddl
    assert "WHERE provider_refund_id IS NOT NULL" in ddl
