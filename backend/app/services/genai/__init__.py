"""Generative AI layer, provider-agnostic, Replicate first (spec 008).

Callers ask for a capability (``capabilities.Capability``); the catalog maps it
to a provider model; ``service.GenAIService`` validates, budgets, records and
dispatches jobs; ``runner`` submits, polls and completes them; ``adoption``
turns an output into an idea entry, a product image or a model file version.
"""

from app.services.genai import logging as _logging  # noqa: F401 - installs the redaction filter
