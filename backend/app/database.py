"""Database configuration and session management."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

logger = logging.getLogger(__name__)

settings = get_settings()

# Log which database connection mode is being used
if settings.rls_enabled and settings.rls_database_url:
    logger.info("Database: Using RLS-enabled connection (app_user role)")
else:
    logger.info("Database: Using standard connection (migrations/superuser)")

# Create async engine using the effective database URL
# When RLS is enabled, this uses app_user role which has RLS policies enforced
engine = create_async_engine(
    settings.effective_database_url,
    echo=settings.debug,  # Log SQL queries in debug mode
    pool_pre_ping=True,  # Verify connections before using
    pool_size=10,
    max_overflow=20,
)

# Create async session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency for getting async database sessions.

    Usage:
        @router.get("/items")
        async def get_items(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def scope_session_to_tenant(session: AsyncSession, tenant_id) -> None:
    """Engage row-level security on an already-open session (task T184).

    The RLS session dependencies -- `get_tenant_db` and `get_shop_db` -- scope
    a session before the handler runs, from a JWT or from the
    `X-Shop-Hostname` header. A webhook has neither: the Shopify ingest
    endpoint resolves its tenant from the `{tenant_slug}` path segment, which
    is a cross-tenant lookup on `tenants` that cannot itself be scoped. So the
    tenant becomes known partway through the request, after the session is
    open, and the only place left to issue the statement is there.

    `SET LOCAL` is transaction-scoped, so this applies from here until the
    transaction ends and clears itself. Call it after the tenant is resolved
    and **before the first write**, in the same transaction as those writes; a
    rollback clears it, so a handler that continues after one calls this again
    (as `filament_types.py` does).

    A no-op when `rls_enabled` is off, which is the development default --
    application-level `tenant_id` filtering is the second belt there, exactly
    as in the dependencies.
    """
    if not settings.rls_enabled:
        return
    await session.execute(
        text("SET LOCAL app.current_tenant_id = :tenant_id"),
        {"tenant_id": str(tenant_id)},
    )
    logger.debug(f"RLS context set on an open session: tenant_id={tenant_id}")


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager for database sessions (for use outside FastAPI routes).

    Usage:
        async with get_db_context() as db:
            result = await db.execute(select(User))
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize database (create tables if they don't exist)."""
    async with engine.begin() as conn:
        # In production, use Alembic migrations instead
        if settings.is_development:
            # await conn.run_sync(Base.metadata.drop_all)  # Uncomment to reset
            await conn.run_sync(Base.metadata.create_all)


async def close_db() -> None:
    """Close database connections."""
    await engine.dispose()
