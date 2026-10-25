"""Database configuration and session management."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings
from app.core.rls import set_rls_context

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


@lru_cache(maxsize=1)
def privileged_session_maker() -> async_sessionmaker[AsyncSession]:
    """Sessions on the migration role, which row-level security does not apply to.

    Under `app_user` a session with no tenant set sees no rows at all -- it is
    not a bypass. Work that is cross-tenant by nature (the platform admin)
    needs a connection RLS really does not filter, and this is the only one.
    It has two users, pinned by a test: `get_platform_admin_db`, behind
    `get_platform_admin`, and the power-reading task, which must find which
    tenant a printer belongs to before it can scope anything. With RLS off both URLs are the same
    connection and this is the ordinary session factory.
    """
    if settings.effective_database_url == settings.database_url:
        return async_session_maker
    privileged = create_async_engine(
        settings.database_url, pool_pre_ping=True, pool_size=2, max_overflow=3
    )
    return async_sessionmaker(
        privileged,
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

    The scope holds for the rest of the session's life, across commits and
    rollbacks (`app.core.rls`). Call it after the tenant is resolved and
    **before the first write**.

    A no-op when `rls_enabled` is off, which is the development default --
    application-level `tenant_id` filtering is the second belt there, exactly
    as in the dependencies.
    """
    await set_rls_context(session, tenant_id=tenant_id)


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
