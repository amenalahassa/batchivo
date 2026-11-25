"""Capabilities and their input rules (spec 008 FR-001, data-model "Validation rules").

Callers ask for a capability, never a model. Each capability has its own input
model; unknown fields are refused so that nothing a caller sends reaches the
provider unvalidated. ``count`` is bounded again by the resolved model's
``max_count`` (catalog), since some models return one image per run.
"""

import uuid
from enum import Enum
from typing import Any, Literal, Optional, Union, get_args, get_origin

import annotated_types
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from pydantic_core import PydanticUndefined

from app.services.genai.errors import InputInvalid

MAX_SEED = 2**31 - 1


class Capability(str, Enum):
    """What a screen or an agent can ask the generative layer for."""

    CONCEPT_IMAGE = "concept_image"
    IMAGE_EDIT = "image_edit"
    PRODUCT_PHOTO_ENHANCE = "product_photo_enhance"
    BACKGROUND_REMOVE = "background_remove"
    UPSCALE = "upscale"
    LIFESTYLE_SCENE = "lifestyle_scene"
    IMAGE_TO_3D = "image_to_3d"


class AssetRef(BaseModel):
    """A tenant-owned image used as an input; resolved by the service (FR-032)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["asset", "idea_entry", "product_image", "model_image"]
    id: uuid.UUID


class _Inputs(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    seed: Optional[int] = Field(None, ge=0, le=MAX_SEED)

    def text(self) -> Optional[str]:
        """The operator's words for this job, shown in idea entries and job details."""
        return None


class ConceptImageInputs(_Inputs):
    prompt: str = Field(..., min_length=1, max_length=2000)
    style: Optional[str] = Field(None, max_length=200)
    count: int = Field(1, ge=1, le=4)
    input_assets: list[AssetRef] = Field(default_factory=list, max_length=4)

    def text(self) -> Optional[str]:
        return self.prompt


class ImageEditInputs(_Inputs):
    instruction: str = Field(..., min_length=1, max_length=2000)
    input_assets: list[AssetRef] = Field(..., min_length=1, max_length=1)

    def text(self) -> Optional[str]:
        return self.instruction


class ProductPhotoEnhanceInputs(_Inputs):
    instruction: Optional[str] = Field(None, max_length=500)
    input_assets: list[AssetRef] = Field(..., min_length=1, max_length=1)

    def text(self) -> Optional[str]:
        return self.instruction


class BackgroundRemoveInputs(_Inputs):
    input_assets: list[AssetRef] = Field(..., min_length=1, max_length=1)


class UpscaleInputs(_Inputs):
    factor: Literal[2, 4] = 2
    input_assets: list[AssetRef] = Field(..., min_length=1, max_length=1)


class LifestyleSceneInputs(_Inputs):
    scene: str = Field(..., min_length=1, max_length=2000)
    count: int = Field(1, ge=1, le=4)
    input_assets: list[AssetRef] = Field(..., min_length=1, max_length=1)

    def text(self) -> Optional[str]:
        return self.scene


class ImageTo3DInputs(_Inputs):
    input_assets: list[AssetRef] = Field(..., min_length=1, max_length=4)


CapabilityInputs = Union[
    ConceptImageInputs,
    ImageEditInputs,
    ProductPhotoEnhanceInputs,
    BackgroundRemoveInputs,
    UpscaleInputs,
    LifestyleSceneInputs,
    ImageTo3DInputs,
]

INPUT_MODELS: dict[Capability, type[_Inputs]] = {
    Capability.CONCEPT_IMAGE: ConceptImageInputs,
    Capability.IMAGE_EDIT: ImageEditInputs,
    Capability.PRODUCT_PHOTO_ENHANCE: ProductPhotoEnhanceInputs,
    Capability.BACKGROUND_REMOVE: BackgroundRemoveInputs,
    Capability.UPSCALE: UpscaleInputs,
    Capability.LIFESTYLE_SCENE: LifestyleSceneInputs,
    Capability.IMAGE_TO_3D: ImageTo3DInputs,
}

#: Capabilities whose output does not show the real item (FR-030): adopting one as a
#: product image needs the operator to confirm the "listings must show the real item"
#: warning.
NOT_REAL_ITEM = frozenset({Capability.CONCEPT_IMAGE, Capability.IMAGE_TO_3D})


def _field_rule(name: str, info: Any) -> dict[str, Any]:
    """One field's rule, read from its type and constraints (one source with validation)."""
    rule: dict[str, Any] = {"required": info.is_required()}
    annotation = info.annotation
    if get_origin(annotation) is Union:  # Optional[X]
        annotation = next(a for a in get_args(annotation) if a is not type(None))
    origin = get_origin(annotation)
    is_list = origin is list
    is_text = annotation is str
    if origin is Literal:
        rule["values"] = list(get_args(annotation))
    for meta in info.metadata:
        if isinstance(meta, annotated_types.MinLen):
            rule["min" if is_list else "min_length"] = meta.min_length
        elif isinstance(meta, annotated_types.MaxLen):
            rule["max" if is_list else "max_length"] = meta.max_length
        elif isinstance(meta, annotated_types.Ge):
            rule["min"] = meta.ge
        elif isinstance(meta, annotated_types.Le):
            rule["max"] = meta.le
    if is_list and not info.is_required():
        rule.setdefault("min", 0)
    if is_text and rule.get("min_length") == 1 and rule["required"]:
        rule.pop("min_length")  # "required" already says it may not be empty
    if not info.is_required() and info.default not in (None, PydanticUndefined):
        if not isinstance(info.default, (list, dict)):
            rule["default"] = info.default
    return rule


def model_rules(model: type[BaseModel]) -> dict[str, dict[str, Any]]:
    """The input rules of an input model, keyed by field name (``inputs{}`` of the API)."""
    return {name: _field_rule(name, info) for name, info in model.model_fields.items()}


def parse_capability(value: str) -> Capability:
    """The capability named by ``value``; ``InputInvalid`` for an unknown one."""
    try:
        return Capability(value)
    except ValueError as exc:
        raise InputInvalid(f"Unknown capability: {value}") from exc


def output_count(inputs: _Inputs) -> int:
    """How many outputs the caller asked for (1 where the capability has no count)."""
    return int(getattr(inputs, "count", 1) or 1)


def validate_inputs(capability: Capability, raw: dict, max_count: int = 4) -> _Inputs:
    """Validate a caller's inputs for a capability; ``InputInvalid`` with a readable reason."""
    model = INPUT_MODELS[capability]
    try:
        inputs = model.model_validate(raw or {})
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first.get("loc", ())) or "inputs"
        raise InputInvalid(f"{where}: {first.get('msg', 'invalid value')}") from exc
    if output_count(inputs) > max_count:
        raise InputInvalid(
            f"count: this model returns at most {max_count} image"
            f"{'s' if max_count > 1 else ''} per job"
        )
    return inputs


__all__ = [
    "AssetRef",
    "Capability",
    "CapabilityInputs",
    "INPUT_MODELS",
    "MAX_SEED",
    "NOT_REAL_ITEM",
    "model_rules",
    "output_count",
    "parse_capability",
    "validate_inputs",
]
