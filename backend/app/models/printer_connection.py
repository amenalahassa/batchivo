"""PrinterConnection model for printer integration connections (Bambu, OctoPrint, etc.)."""

import uuid
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.encryption import encrypt_value, safe_decrypt
from app.database import Base
from app.models.base import TimestampMixin, UUIDMixin

if TYPE_CHECKING:
    from app.models.printer import Printer
    from app.models.tenant import Tenant


def _encrypt(value: Optional[str]) -> Optional[str]:
    """Fernet token of ``value``; None for an empty value (nothing to protect)."""
    return encrypt_value(value) if value else None


def _decrypt(token: Optional[str]) -> Optional[str]:
    """Clear value of a stored token; None when unset or unreadable."""
    return safe_decrypt(token) if token else None


class ConnectionType(str, Enum):
    """Supported printer connection types."""

    BAMBU_LAN = "bambu_lan"  # Direct LAN MQTT connection
    BAMBU_CLOUD = "bambu_cloud"  # Cloud MQTT connection
    OCTOPRINT = "octoprint"  # OctoPrint REST API
    KLIPPER = "klipper"  # Klipper/Moonraker API (legacy alias)
    MOONRAKER = "moonraker"  # Moonraker REST API (Klipper frontend)
    MANUAL = "manual"  # Manual tracking (no auto-sync)


class PrinterConnection(Base, UUIDMixin, TimestampMixin):
    """
    PrinterConnection stores connection details for printer integrations.

    Supports multiple connection types:
    - Bambu Lab (LAN MQTT or Cloud MQTT)
    - OctoPrint (REST API)
    - Klipper/Moonraker (REST API)

    Each printer can have one active connection configuration.
    Sensitive data (access codes, tokens) is encrypted at rest (spec 009).

    Multi-tenant: Each connection belongs to a single tenant.
    """

    __tablename__ = "printer_connections"

    # Tenant isolation
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Tenant ID for multi-tenant isolation",
    )

    # Link to printer
    printer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("printers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="Associated printer ID",
    )

    # Connection type
    connection_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=ConnectionType.MANUAL.value,
        comment="Connection type (bambu_lan, bambu_cloud, octoprint, klipper, manual)",
    )

    # Bambu-specific fields
    serial_number: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="Bambu printer serial number (from printer screen)",
    )

    # Network connection details
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45),  # IPv6 max length
        nullable=True,
        comment="Printer IP address (for LAN connections)",
    )

    port: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=8883,
        server_default="8883",
        comment="Connection port (default 8883 for Bambu MQTT)",
    )

    # Authentication secrets, encrypted at rest (spec 009, research R8). The
    # columns keep their names; the ORM attributes hold the Fernet token and the
    # ``access_code`` / ``cloud_token`` properties below give the clear value.
    access_code_encrypted: Mapped[Optional[str]] = mapped_column(
        "access_code",
        Text,
        nullable=True,
        comment="LAN access code (from Bambu printer settings), Fernet-encrypted",
    )

    # Cloud connection fields
    cloud_username: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="Cloud account username/user_id (for cloud connections)",
    )

    cloud_token_encrypted: Mapped[Optional[str]] = mapped_column(
        "cloud_token",
        Text,
        nullable=True,
        comment="Cloud access token (for cloud connections), Fernet-encrypted",
    )

    # AMS Configuration
    ams_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="Number of AMS units connected (0-4)",
    )

    # Developer Mode (spec 011): declared by the operator; LAN printers in this
    # mode accept file uploads and start commands from Batchivo.
    developer_mode: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="Operator-declared Bambu Developer Mode (enables print send, disables cloud)",
    )

    # Connection status (runtime state)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="Whether connection is enabled",
    )

    is_connected: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="Current connection status (runtime)",
    )

    last_connected_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Last successful connection timestamp",
    )

    last_status_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Last status message received timestamp",
    )

    connection_error: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="Last connection error message",
    )

    # Relationships
    tenant: Mapped["Tenant"] = relationship(
        "Tenant",
        lazy="select",
    )

    printer: Mapped["Printer"] = relationship(
        "Printer",
        back_populates="connection",
        lazy="joined",
    )

    # Constraints
    __table_args__ = (
        UniqueConstraint("printer_id", name="uq_printer_connection_printer"),
        {"comment": "Printer connection configurations for integrations"},
    )

    def __repr__(self) -> str:
        return f"<PrinterConnection(printer_id={self.printer_id}, type={self.connection_type})>"

    # -- secrets (spec 009) -------------------------------------------------
    # Reading gives the clear value, or None when unset or unreadable (the
    # server key changed); `services.printer_secrets.secret_state` tells which.
    # Never log or return these values.

    @property
    def access_code(self) -> Optional[str]:
        """The clear LAN access code (Moonraker API key for Moonraker connections)."""
        return _decrypt(self.access_code_encrypted)

    @access_code.setter
    def access_code(self, value: Optional[str]) -> None:
        self.access_code_encrypted = _encrypt(value)

    @property
    def cloud_token(self) -> Optional[str]:
        """The clear cloud access token."""
        return _decrypt(self.cloud_token_encrypted)

    @cloud_token.setter
    def cloud_token(self, value: Optional[str]) -> None:
        self.cloud_token_encrypted = _encrypt(value)

    @property
    def access_code_state(self) -> str:
        """``set``, ``unset`` or ``unreadable`` (decided by ``printer_secrets``)."""
        from app.services.printer_secrets import secret_state

        return secret_state(self, "access_code")

    @property
    def cloud_token_state(self) -> str:
        """``set``, ``unset`` or ``unreadable`` (decided by ``printer_secrets``)."""
        from app.services.printer_secrets import secret_state

        return secret_state(self, "cloud_token")

    @property
    def is_bambu(self) -> bool:
        """Check if this is a Bambu Lab connection."""
        return self.connection_type in (
            ConnectionType.BAMBU_LAN.value,
            ConnectionType.BAMBU_CLOUD.value,
        )

    @property
    def can_send_prints(self) -> bool:
        """Whether Batchivo may send prints to this printer (spec 011, FR-012)."""
        return bool(self.developer_mode) and self.connection_type == ConnectionType.BAMBU_LAN.value

    @property
    def mqtt_topic_prefix(self) -> Optional[str]:
        """Get MQTT topic prefix for this connection."""
        if self.is_bambu and self.serial_number:
            return f"device/{self.serial_number}"
        return None

    @property
    def total_ams_slots(self) -> int:
        """Calculate total AMS slots (4 per unit)."""
        return self.ams_count * 4
