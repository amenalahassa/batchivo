"""Authentication dependencies for FastAPI routes."""

import logging
import uuid
from collections.abc import AsyncGenerator
from typing import Annotated, Optional

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.rls import set_rls_context
from app.database import async_session_maker, get_db, privileged_session_maker
from app.models.tenant import Tenant
from app.models.user import User, UserTenant

logger = logging.getLogger(__name__)
settings = get_settings()


async def get_current_user(
    db: Annotated[AsyncSession, Depends(get_db)],
    authorization: Annotated[Optional[str], Header()] = None,
) -> User:
    """
    Get the current authenticated user from JWT token.

    Validates JWT access token and returns the user.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.replace("Bearer ", "")

    # Decode JWT token using our security module
    from app.core.security import decode_token, verify_token_type

    # Verify it's an access token
    if not verify_token_type(token, "access"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Decode token
    token_data = decode_token(token)
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Look up user
    result = await db.execute(select(User).where(User.id == token_data.user_id))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # The user is now verified: let RLS admit their own memberships, which
    # `get_current_tenant` reads before any tenant is chosen.
    await set_rls_context(db, user_id=user.id)
    return user


async def get_current_tenant(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    x_tenant_id: Annotated[Optional[str], Header()] = None,
) -> Tenant:
    """
    Get the current tenant for the authenticated user.

    Selection Priority:
    1. X-Tenant-ID header (if provided and user has access)
    2. User's first tenant (default)

    In production, this might also check subdomain or path.
    """
    # Get user's tenants
    result = await db.execute(
        select(UserTenant)
        .where(UserTenant.user_id == user.id)
        .order_by(UserTenant.created_at.asc())
    )
    user_tenants = result.scalars().all()

    if not user_tenants:
        # User has no tenants - auto-create a default one
        # Note: In a mature SaaS, you might require explicit tenant creation/invitation
        # For now, auto-create to simplify onboarding
        tenant = Tenant(
            name=f"{user.full_name}'s Workspace",
            slug=f"user-{user.id}",
            is_active=True,
            settings={},
        )
        db.add(tenant)
        await db.flush()  # Flush to get tenant.id before using it
        # The membership and policy rows below are tenant rows: scope first.
        await set_rls_context(db, tenant_id=tenant.id)

        # Create owner relationship
        user_tenant = UserTenant(
            user_id=user.id,
            tenant_id=tenant.id,
            role="owner",
        )
        db.add(user_tenant)

        # Deferred: pricing_policy imports models that import this module.
        from app.services.pricing_policy import seed_policy_row

        await seed_policy_row(db, tenant)  # task T219

        await db.commit()
        await db.refresh(tenant)
        return tenant

    # If tenant ID specified in header, verify access
    if x_tenant_id:
        # SECURITY: Validate UUID format explicitly
        try:
            tenant_uuid = uuid.UUID(x_tenant_id)
        except ValueError:
            logger.warning(f"Invalid X-Tenant-ID format from user {user.id}: {x_tenant_id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid tenant ID format",
            )

        # SECURITY: Check if user has access to requested tenant
        user_tenant = next((ut for ut in user_tenants if ut.tenant_id == tenant_uuid), None)

        if not user_tenant:
            # SECURITY: Log unauthorized tenant access attempt
            logger.warning(f"User {user.id} attempted to access unauthorized tenant {tenant_uuid}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have access to the requested tenant",
            )

        # User has access - fetch and return the tenant
        result = await db.execute(select(Tenant).where(Tenant.id == tenant_uuid))
        tenant = result.scalar_one_or_none()

        if not tenant or not tenant.is_active:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Tenant not found or inactive",
            )

        await set_rls_context(db, tenant_id=tenant.id)
        return tenant

    # Return user's first tenant (default)
    result = await db.execute(select(Tenant).where(Tenant.id == user_tenants[0].tenant_id))
    tenant = result.scalar_one()
    # Membership is established: scope the request's session to this tenant.
    # Every dependency and handler on `get_db` in this request shares it.
    await set_rls_context(db, tenant_id=tenant.id)
    return tenant


async def require_role(
    user: Annotated[User, Depends(get_current_user)],
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
    db: Annotated[AsyncSession, Depends(get_db)],
    required_role: str = "member",
) -> bool:
    """
    Check if user has required role in current tenant.

    Role hierarchy: owner > admin > member > viewer

    Returns True if authorized, raises HTTPException if not.
    """
    # Get user's role in this tenant
    result = await db.execute(
        select(UserTenant).where(UserTenant.user_id == user.id, UserTenant.tenant_id == tenant.id)
    )
    user_tenant = result.scalar_one_or_none()

    if not user_tenant:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not have access to this tenant",
        )

    # Role hierarchy check
    role_hierarchy = {
        "viewer": 0,
        "member": 1,
        "admin": 2,
        "owner": 3,
    }

    user_level = role_hierarchy.get(user_tenant.role, 0)
    required_level = role_hierarchy.get(required_role, 0)

    if user_level < required_level:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires {required_role} role or higher",
        )

    return True


#: The roles FR-007a reserves monetary policy to: a rate, a percentage, a
#: reserve, a channel lever. Named once so every route asks the same question.
MONETARY_ROLES: frozenset[str] = frozenset({"owner", "admin"})


async def role_in_tenant(db: AsyncSession, user_id, tenant_id) -> Optional[str]:
    """The role this user holds in this tenant, as a plain string.

    What a write records as its authority (FR-001, FR-007a): a figure that
    drives a decision carries who set it and under which role. One helper,
    where three routers each used to keep their own copy.
    """
    result = await db.execute(
        select(UserTenant.role).where(
            UserTenant.user_id == user_id, UserTenant.tenant_id == tenant_id
        )
    )
    role = result.scalars().first()
    return getattr(role, "value", role)


def require_member():
    """Dependency that requires member role or higher -- refuses a viewer.

    FR-007c makes the viewer a reader: every cost and margin is visible to
    them, and no figure is theirs to change. Every route that writes a figure
    the pricing engine reads takes this (task T227); one that writes monetary
    policy takes `RequireAdmin` instead.
    """

    async def check_member(
        user: Annotated[User, Depends(get_current_user)],
        tenant: Annotated[Tenant, Depends(get_current_tenant)],
        db: Annotated[AsyncSession, Depends(get_db)],
    ) -> bool:
        return await require_role(user, tenant, db, "member")

    return check_member


def require_admin():
    """Dependency that requires admin role or higher."""

    async def check_admin(
        user: Annotated[User, Depends(get_current_user)],
        tenant: Annotated[Tenant, Depends(get_current_tenant)],
        db: Annotated[AsyncSession, Depends(get_db)],
    ) -> bool:
        return await require_role(user, tenant, db, "admin")

    return check_admin


# Type aliases for cleaner route signatures
CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentTenant = Annotated[Tenant, Depends(get_current_tenant)]
RequireAdmin = Annotated[bool, Depends(require_admin())]
RequireMember = Annotated[bool, Depends(require_member())]


async def get_platform_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """
    Require platform admin access.

    This dependency validates that the current user has platform-wide
    admin privileges. Use for endpoints that manage tenants, users
    across tenants, or platform settings.

    Raises:
        HTTPException: 403 if user is not a platform admin
    """
    if not user.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform admin access required",
        )
    return user


# Type alias for platform admin dependency
PlatformAdmin = Annotated[User, Depends(get_platform_admin)]


async def get_tenant_db(
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AsyncSession:
    """The request's database session, scoped by row-level security to its tenant.

    The tenant is the one `get_current_tenant` resolved and **validated** --
    membership checked, `X-Tenant-ID` honoured only for a tenant the user
    belongs to -- and that dependency has already scoped this same session
    (`app.core.rls`). It used to open a second session scoped from
    `request.state.tenant_id`, which `TenantContextMiddleware` copies from the
    `X-Tenant-ID` header unvalidated: under RLS, a route taking `TenantDB`
    without `CurrentTenant` would have served the header's tenant to anyone
    (bug rls-unscoped-routes). One request now has one session, so a tenant
    or user loaded by a dependency is attached to the session the handler
    writes through.

    Usage:
        @router.get("/items")
        async def get_items(db: TenantDB):
            # All queries automatically filtered by tenant_id
            result = await db.execute(select(Item))
            return result.scalars().all()
    """
    return db


TenantDB = Annotated[AsyncSession, Depends(get_tenant_db)]


async def get_platform_admin_db(
    _admin: Annotated[User, Depends(get_platform_admin)],
) -> AsyncGenerator[AsyncSession, None]:
    """
    Get a database session for platform admin WITHOUT RLS tenant scoping.

    This dependency:
    1. Validates the user is a platform admin (via get_platform_admin)
    2. Returns a database session WITHOUT setting app.current_tenant_id
    3. Allows cross-tenant queries for platform-wide operations

    Use for endpoints that need to query across all tenants, such as:
    - Listing all tenants
    - Searching users across tenants
    - Platform-wide analytics

    Note: The _admin parameter ensures platform admin access is validated
    before granting cross-tenant database access.
    """
    # Not setting a tenant is not a bypass under `app_user` -- it shows no rows.
    # The privileged connection is the one RLS really does not filter.
    async with privileged_session_maker()() as session:
        try:
            logger.debug("Platform admin DB session created (RLS bypassed)")
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# Type alias for platform admin database session (bypasses RLS)
PlatformAdminDB = Annotated[AsyncSession, Depends(get_platform_admin_db)]


async def get_shop_tenant(
    db: Annotated[AsyncSession, Depends(get_db)],
    x_shop_hostname: Annotated[str, Header(description="Shop hostname for tenant resolution")],
) -> Tenant:
    """
    Resolve tenant from shop hostname (subdomain or custom domain).

    This dependency is used for PUBLIC shop endpoints that need tenant context
    without requiring user authentication.

    Resolution priority:
    1. Custom domain match (e.g., shop.mystmereforge.co.uk)
    2. Subdomain extraction (e.g., mystmereforge.batchivo.shop)

    The shop frontend passes the hostname in the X-Shop-Hostname header.

    Raises:
        HTTPException: 404 if no tenant found for hostname
    """
    from app.api.v1.shop_resolver import (
        extract_subdomain,
        resolve_tenant_by_custom_domain,
        resolve_tenant_by_slug,
    )

    hostname = x_shop_hostname.lower().strip()
    logger.debug(f"Resolving shop tenant for hostname: {hostname}")

    # Try custom domain first
    tenant = await resolve_tenant_by_custom_domain(db, hostname)
    if tenant:
        logger.info(f"Resolved shop tenant via custom domain: {tenant.slug}")
        # Resolving is the cross-tenant step; what follows on this request's
        # session belongs to this shop alone.
        await set_rls_context(db, tenant_id=tenant.id)
        return tenant

    # Try subdomain extraction
    subdomain = extract_subdomain(hostname)
    if subdomain:
        tenant = await resolve_tenant_by_slug(db, subdomain)
        if tenant:
            logger.info(f"Resolved shop tenant via subdomain: {tenant.slug}")
            await set_rls_context(db, tenant_id=tenant.id)
            return tenant

    # No tenant found
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Shop not found for hostname: {hostname}",
    )


# Type alias for shop tenant dependency (public, no auth required)
ShopTenant = Annotated[Tenant, Depends(get_shop_tenant)]


async def get_shop_db(
    shop_tenant: Annotated[Tenant, Depends(get_shop_tenant)],
) -> AsyncGenerator[AsyncSession, None]:
    """A database session with RLS context set for a **storefront** request.

    `get_tenant_db` cannot serve the storefront: it reads
    `request.state.tenant_id`, which `TenantContextMiddleware` sets from a JWT,
    and a shopper has no JWT. So every public shop handler ran on the
    un-scoped session -- including `POST /shop/checkout/complete`, which writes
    the order and then the sale snapshot carrying `make_cost_at_sale`,
    `cost_breakdown_json`, `fees_json` and `postage_paid`. Every storefront
    sale was therefore written with no tenant scope at the database level,
    which is the one place this system does not rely on remembering to filter
    (Constitution I, FR-036).

    The tenant here comes from `get_shop_tenant`, which resolves it from the
    `X-Shop-Hostname` header, so a handler using this session requires that
    header -- the same requirement `ShopTenant` and `ShopContext` already
    impose.

    Resolving the hostname is itself a cross-tenant lookup on `tenants` and
    stays on the un-scoped session inside `get_shop_tenant`; only the work the
    handler does afterwards is scoped.
    """
    async with async_session_maker() as session:
        try:
            await set_rls_context(session, tenant_id=shop_tenant.id)

            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


#: An RLS-scoped session for a public storefront route.
ShopDB = Annotated[AsyncSession, Depends(get_shop_db)]


async def get_shop_sales_channel(
    db: Annotated[AsyncSession, Depends(get_db)],
    shop_tenant: Annotated[Tenant, Depends(get_shop_tenant)],
):
    """
    Get the shop sales channel for the resolved tenant.

    This dependency resolves the tenant's "online_shop" sales channel
    which is used for pricing lookups in public shop endpoints.

    Returns:
        Tuple of (Tenant, SalesChannel) for the shop

    Raises:
        HTTPException: 500 if tenant has no online shop channel configured
    """
    from app.models.sales_channel import SalesChannel

    # sales_channels is a tenant table: scope before reading it.
    await set_rls_context(db, tenant_id=shop_tenant.id)
    # Find the tenant's online shop sales channel
    result = await db.execute(
        select(SalesChannel).where(
            SalesChannel.tenant_id == shop_tenant.id,
            SalesChannel.platform_type == "online_shop",
            SalesChannel.is_active.is_(True),
        )
    )
    channel = result.scalar_one_or_none()

    if not channel:
        logger.error(f"Tenant {shop_tenant.slug} has no online_shop sales channel")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Shop '{shop_tenant.slug}' is not properly configured (no sales channel)",
        )

    return shop_tenant, channel


# Type alias for shop context (tenant + sales channel)
ShopContext = Annotated[tuple[Tenant, "SalesChannel"], Depends(get_shop_sales_channel)]
