"""ApiToken: a personal API token an operator gives to a script or an AI agent (spec 010).

A token belongs to one user in one tenant and acts as that user there: the
user's role applies in full and the token's scopes can only narrow it. Only a
SHA-256 hash of the secret is stored; the secret is shown once, at creation.

`status` (active, expired, revoked) is derived on read, never stored
(Constitution V). `revoked_at` is written once and never cleared.
"""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import JSON, CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.tenant import Tenant
    from app.models.user import User


class ApiToken(Base, UUIDMixin, TimestampMixin):
    """A hashed, scoped, expiring personal API token bound to one user and one tenant."""

    __tablename__ = "api_tokens"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    # `bvt_<id8>`: shown in lists so tokens can be told apart. Display only:
    # authentication always matches the full hash, never this prefix.
    token_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship("User", lazy="joined")
    tenant: Mapped["Tenant"] = relationship("Tenant")

    __table_args__ = (
        CheckConstraint(
            "char_length(trim(name)) BETWEEN 1 AND 100", name="ck_api_tokens_name_length"
        ),
        Index("ix_api_tokens_tenant_user", "tenant_id", "user_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<ApiToken(id={self.id}, prefix={self.token_prefix})>"
