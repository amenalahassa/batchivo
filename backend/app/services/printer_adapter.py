"""Base protocol and dataclasses for printer adapters.

All adapter implementations must conform to the PrinterAdapter protocol.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, Protocol, runtime_checkable


@dataclass
class PrinterAdapterState:
    """Normalised state returned by any printer adapter."""

    status: str  # 'printing' | 'paused' | 'error' | 'idle' | 'offline'
    progress_percent: Optional[float] = None
    job_name: Optional[str] = None
    # { 'extruder': float, 'bed': float } — keys may be absent
    temps: dict[str, float] = field(default_factory=dict)
    eta_seconds: Optional[int] = None


@runtime_checkable
class PrinterAdapter(Protocol):
    """Protocol that every printer adapter must satisfy."""

    async def get_status(self) -> PrinterAdapterState:
        """Return the current printer state."""
        ...

    async def pause(self) -> None:
        """Pause the current print."""
        ...

    async def resume(self) -> None:
        """Resume a paused print."""
        ...

    async def cancel(self) -> None:
        """Cancel the current print."""
        ...


@dataclass(frozen=True)
class JobActuals:
    """What a finished job actually used, as the machine reports it.

    Both figures are optional and independently so, because real machines
    report one, the other or neither: filament weight comes from an AMS or a
    load cell, elapsed print time from the controller, and plenty of firmware
    exposes neither. ``None`` means "this machine did not say", which is not
    the same as zero and must never be written as one.

    ``Decimal`` rather than ``float``: these figures reach the cost engine
    (Constitution IV).
    """

    grams: Optional[Decimal] = None
    print_hours: Optional[Decimal] = None


@runtime_checkable
class ReportsJobActuals(Protocol):
    """An adapter that can say what the last job consumed.

    Deliberately separate from :class:`PrinterAdapter` rather than another
    method on it. Status, pause, resume and cancel are things every printer
    can do; reporting consumption is not, and folding it in would force every
    adapter to answer a question its hardware cannot. A caller checks with
    ``isinstance(adapter, ReportsJobActuals)`` and falls back where the answer
    is no.
    """

    async def get_job_actuals(self) -> JobActuals:
        """What the most recent job used. Fields are ``None`` when unknown."""
        ...
