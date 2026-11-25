"""Customer authentication dependencies for shop API routes.

Customers have separate auth from admin Users.
Customer tokens include customer_id and tenant_id.
"""

import logging
import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt.exceptions import PyJWTError
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.rls import set_rls_context
from app.database import async_session_maker, get_db
from app.models.customer import Customer
from app.models.tenant import Tenant

logger = logging.getLogger(__name__)

settings = get_settings()

# JWT Configuration
ALGORITHM = "HS256"
CUSTOMER_ACCESS_TOKEN_EXPIRE_MINUTES = 60  # 1 hour
CUSTOMER_REFRESH_TOKEN_EXPIRE_DAYS = 30  # 30 days for customer convenience


class CustomerTokenData(BaseModel):
    """Data encoded in customer JWT tokens."""

    customer_id: uuid.UUID
    tenant_id: uuid.UUID
    email: str


def create_customer_access_token(
    customer_id: uuid.UUID,
    tenant_id: uuid.UUID,
    email: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a JWT access token for a customer."""
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=CUSTOMER_ACCESS_TOKEN_EXPIRE_MINUTES
        )

    to_encode = {
        "customer_id": str(customer_id),
        "tenant_id": str(tenant_id),
        "email": email,
        "exp": expire,
        "type": "customer_access",
    }
    return jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)


def create_customer_refresh_token(
    customer_id: uuid.UUID,
    tenant_id: uuid.UUID,
    email: str,
) -> str:
    """Create a JWT refresh token for a customer."""
    expire = datetime.now(timezone.utc) + timedelta(days=CUSTOMER_REFRESH_TOKEN_EXPIRE_DAYS)

    to_encode = {
        "customer_id": str(customer_id),
        "tenant_id": str(tenant_id),
        "email": email,
        "exp": expire,
        "type": "customer_refresh",
    }
    return jwt.encode(to_encode, settings.secret_key, algorithm=ALGORITHM)


def decode_customer_token(token: str) -> Optional[CustomerTokenData]:
    """Decode and validate a customer JWT token."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        customer_id = payload.get("customer_id")
        tenant_id = payload.get("tenant_id")
        email = payload.get("email")

        if not customer_id or not tenant_id or not email:
            return None

        return CustomerTokenData(
            customer_id=uuid.UUID(customer_id),
            tenant_id=uuid.UUID(tenant_id),
            email=email,
        )
    except (PyJWTError, ValueError):
        return None


def verify_customer_token_type(token: str, expected_type: str) -> bool:
    """Verify that a token is of the expected type."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        token_type = payload.get("type")
        return token_type == expected_type
    except PyJWTError:
        return False


async def get_current_customer(
    db: Annotated[AsyncSession, Depends(get_db)],
    authorization: Annotated[Optional[str], Header()] = None,
) -> Customer:
    """
    Get the current authenticated customer from JWT token.

    Use this dependency in customer-facing endpoints.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = authorization.replace("Bearer ", "")

    # Verify it's a customer access token
    if not verify_customer_token_type(token, "customer_access"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Decode token
    token_data = decode_customer_token(token)
    if not token_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # The token's signature is verified, so its tenant can scope the lookup:
    # customers is a tenant table under RLS.
    await set_rls_context(db, tenant_id=token_data.tenant_id)

    # Look up customer
    result = await db.execute(
        select(Customer).where(
            Customer.id == token_data.customer_id,
            Customer.tenant_id == token_data.tenant_id,
        )
    )
    customer = result.scalar_one_or_none()

    if not customer or not customer.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Customer not found or inactive",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return customer


async def get_current_customer_tenant(
    customer: Annotated[Customer, Depends(get_current_customer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Tenant:
    """Get the tenant for the current customer."""
    result = await db.execute(select(Tenant).where(Tenant.id == customer.tenant_id))
    tenant = result.scalar_one_or_none()

    if not tenant or not tenant.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Shop not found or inactive",
        )

    return tenant


async def get_optional_customer(
    db: Annotated[AsyncSession, Depends(get_db)],
    authorization: Annotated[Optional[str], Header()] = None,
) -> Optional[Customer]:
    """
    Get the current customer if authenticated, or None if not.

    Use for endpoints that work differently for logged-in customers.
    """
    if not authorization or not authorization.startswith("Bearer "):
        return None

    token = authorization.replace("Bearer ", "")

    if not verify_customer_token_type(token, "customer_access"):
        return None

    token_data = decode_customer_token(token)
    if not token_data:
        return None

    await set_rls_context(db, tenant_id=token_data.tenant_id)
    result = await db.execute(
        select(Customer).where(
            Customer.id == token_data.customer_id,
            Customer.tenant_id == token_data.tenant_id,
            Customer.is_active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def get_customer_db(
    customer: Annotated[Customer, Depends(get_current_customer)],
) -> AsyncGenerator[AsyncSession, None]:
    """A database session with RLS context set for a **customer** request.

    Neither existing session dependency fits the customer account surface.
    `get_tenant_db` reads `request.state.tenant_id`, which
    `TenantContextMiddleware` sets from a *staff* JWT, and a shopper has none.
    `get_shop_db` resolves its tenant from the `X-Shop-Hostname` header, which
    is supplied by the client and unauthenticated, and making it required here
    would turn fourteen working endpoints into 422s for any storefront that
    does not send it.

    The customer's own access token already carries `tenant_id`, and
    `get_current_customer` has verified the signature and loaded the matching
    row before this runs. So the tenant used to scope the session is the one
    the token was issued for -- stronger provenance than a header, and no new
    requirement on the caller.

    Until this existed, all fourteen handlers ran on the un-scoped session,
    four of them serving a customer their own order money with an
    application-level `Order.tenant_id == customer.tenant_id` filter and a
    lowercase email match as the only belt (Constitution I).
    """
    async with async_session_maker() as session:
        try:
            await set_rls_context(session, tenant_id=customer.tenant_id)

            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# Type aliases for cleaner route signatures
CurrentCustomer = Annotated[Customer, Depends(get_current_customer)]
CurrentCustomerTenant = Annotated[Tenant, Depends(get_current_customer_tenant)]
OptionalCustomer = Annotated[Optional[Customer], Depends(get_optional_customer)]

#: An RLS-scoped session for an authenticated customer route.
CustomerDB = Annotated[AsyncSession, Depends(get_customer_db)]
