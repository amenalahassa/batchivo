"""Ideas module: capture, brainstorm and convert product ideas (spec 007)."""

from fastapi import APIRouter

from app.modules.base import BaseModule
from app.schemas.tenant_settings import TenantType


class IdeasModule(BaseModule):
    """
    Product ideas module.

    Provides functionality for:
    - Capturing and scoring product ideas
    - A brainstorming timeline of notes, images and decisions per iteration
    - Converting an idea into a model or a product
    - Importing ideas from the pain-point report
    """

    name = "ideas"
    display_name = "Ideas"
    icon = "lightbulb"
    description = "Capture, brainstorm and convert product ideas"

    # On by default for 3D-print shops; other types can enable it.
    tenant_types = [TenantType.THREE_D_PRINT, TenantType.GENERIC]

    def register_routes(self, router: APIRouter) -> None:
        """Register idea routes."""
        from app.api.v1 import ideas

        for route in ideas.router.routes:
            router.routes.append(route)
