"""Capability → provider model, with defaults and per-tenant overrides (research R3).

The defaults below were read from Replicate's public model pages on 2026-11-24.
Community models are pinned to an exact version (FR-002). Provider-maintained
("official") models cannot be pinned: their ``model_version`` is ``"official"``
and each job records the version the provider reports it ran (clarification
2026-11-24, answer B).

A tenant override replaces the model and version, and optionally the price. It
must accept the same inputs as the default model of its capability. For
``concept_image`` it replaces the model used without reference images only: a
concept with references always runs on ``CONCEPT_WITH_REFERENCES``, whose inputs
differ (research R3).
"""

from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Any, Optional

from app.services.genai.capabilities import INPUT_MODELS, NOT_REAL_ITEM, Capability, model_rules

OFFICIAL = "official"
PRICE_UNITS = ("per_output", "per_run", "per_second")


@dataclass(frozen=True)
class Price:
    """What one job costs at the provider, in US dollars (clarification Q1)."""

    unit: str  # per_output | per_run | per_second
    amount_usd: Decimal
    typical_seconds: int = 0
    source: str = "catalog"  # catalog | override
    assumed: bool = False  # the figure could not be confirmed on the provider's pages

    def snapshot(self) -> dict:
        """The price as written once on a job (constitution VI)."""
        return {
            "unit": self.unit,
            "amount_usd": str(self.amount_usd),
            "typical_seconds": self.typical_seconds,
            "source": self.source,
            "assumed": self.assumed,
        }


@dataclass(frozen=True)
class CapabilityConfig:
    """How one capability runs at its provider."""

    capability: Capability
    label: str
    provider: str
    model_ref: str
    model_version: str  # 64-hex for a pinned model, OFFICIAL otherwise
    output_kind: str  # image | mesh
    price: Price
    time_limit_s: int
    max_count: int = 1
    max_inputs: int = 1
    #: our field -> provider field; "images" maps the input asset URLs
    input_mapping: dict[str, str] = field(default_factory=dict)
    #: provider fields whose value is a list of image URLs (else the first URL)
    list_fields: tuple[str, ...] = ()
    default_params: dict[str, Any] = field(default_factory=dict)
    #: key of the output object holding the result (models returning an object)
    output_key: Optional[str] = None
    #: fixed prompt the operator's optional instruction is appended to
    prompt_template: Optional[str] = None
    overridden: bool = False

    @property
    def pinnable(self) -> bool:
        return self.model_version != OFFICIAL

    @property
    def shows_real_item(self) -> bool:
        return self.capability not in NOT_REAL_ITEM

    @property
    def version_spec(self) -> str:
        """The ``version`` field sent to the provider."""
        if self.pinnable:
            return f"{self.model_ref}:{self.model_version}"
        return self.model_ref


_KONTEXT = dict(
    provider="replicate",
    model_ref="black-forest-labs/flux-kontext-pro",
    model_version=OFFICIAL,
    output_kind="image",
    price=Price("per_output", Decimal("0.04"), source="catalog", assumed=True),
    time_limit_s=600,
    input_mapping={"instruction": "prompt", "images": "input_image", "seed": "seed"},
    default_params={
        "aspect_ratio": "match_input_image",
        "output_format": "png",
        "safety_tolerance": 2,
    },
)

DEFAULTS: dict[Capability, CapabilityConfig] = {
    Capability.CONCEPT_IMAGE: CapabilityConfig(
        capability=Capability.CONCEPT_IMAGE,
        label="Concept image",
        provider="replicate",
        model_ref="black-forest-labs/flux-schnell",
        model_version=OFFICIAL,
        output_kind="image",
        price=Price("per_output", Decimal("0.003")),
        time_limit_s=600,
        max_count=4,
        max_inputs=0,
        input_mapping={"prompt": "prompt", "count": "num_outputs", "seed": "seed"},
        default_params={"aspect_ratio": "1:1", "output_format": "png", "go_fast": True},
    ),
    Capability.IMAGE_EDIT: CapabilityConfig(
        capability=Capability.IMAGE_EDIT, label="Image edit", **_KONTEXT
    ),
    Capability.PRODUCT_PHOTO_ENHANCE: CapabilityConfig(
        capability=Capability.PRODUCT_PHOTO_ENHANCE,
        label="Product photo enhancement",
        prompt_template=(
            "Clean professional studio product photo: soft even lighting, neutral background, "
            "remove clutter and dust. Keep the product exactly identical in shape, colour and "
            "details."
        ),
        **_KONTEXT,
    ),
    Capability.BACKGROUND_REMOVE: CapabilityConfig(
        capability=Capability.BACKGROUND_REMOVE,
        label="Background removal",
        provider="replicate",
        model_ref="851-labs/background-remover",
        model_version="a029dff38972b5fda4ec5d75d7d1cd25aeff621d2cf4946a41055d7db66b80bc",
        output_kind="image",
        price=Price("per_second", Decimal("0.000225"), typical_seconds=3),
        time_limit_s=600,
        input_mapping={"images": "image"},
        default_params={"format": "png", "background_type": "rgba"},
    ),
    Capability.UPSCALE: CapabilityConfig(
        capability=Capability.UPSCALE,
        label="Upscale",
        provider="replicate",
        model_ref="nightmareai/real-esrgan",
        model_version="f121d640bd286e1fdc67f9799164c1d5be36ff74576ee11c803ae5b665dd46aa",
        output_kind="image",
        price=Price("per_second", Decimal("0.000225"), typical_seconds=10, assumed=True),
        time_limit_s=600,
        input_mapping={"images": "image", "factor": "scale"},
        default_params={"face_enhance": False},
    ),
    Capability.LIFESTYLE_SCENE: CapabilityConfig(
        capability=Capability.LIFESTYLE_SCENE,
        label="Lifestyle scene",
        provider="replicate",
        model_ref="bria/generate-background",
        model_version=OFFICIAL,
        output_kind="image",
        price=Price("per_output", Decimal("0.04"), assumed=True),
        time_limit_s=600,
        input_mapping={"images": "image", "scene": "bg_prompt", "seed": "seed"},
        default_params={"original_quality": True},
    ),
    Capability.IMAGE_TO_3D: CapabilityConfig(
        capability=Capability.IMAGE_TO_3D,
        label="Image to 3D",
        provider="replicate",
        model_ref="firtoz/trellis",
        model_version="e8f6c45206993f297372f5436b90350817bd9b4a0d52d2a76df50c1c8afa2b3c",
        output_kind="mesh",
        price=Price("per_second", Decimal("0.0014"), typical_seconds=30),
        time_limit_s=1800,
        max_inputs=4,
        input_mapping={"images": "images", "seed": "seed"},
        list_fields=("images",),
        default_params={
            "generate_model": True,
            "randomize_seed": False,
            "texture_size": 1024,
            "mesh_simplify": 0.95,
            "generate_color": False,
            "generate_normal": False,
        },
        output_key="model_file",
    ),
}

#: Concept images with reference images use a model that takes several images.
CONCEPT_WITH_REFERENCES = CapabilityConfig(
    capability=Capability.CONCEPT_IMAGE,
    label="Concept image",
    provider="replicate",
    model_ref="google/nano-banana",
    model_version=OFFICIAL,
    output_kind="image",
    price=Price("per_output", Decimal("0.039"), assumed=True),
    time_limit_s=600,
    max_count=1,
    max_inputs=4,
    input_mapping={"prompt": "prompt", "images": "image_input"},
    list_fields=("image_input",),
    default_params={"output_format": "png"},
)


def overrides_of(tenant_settings: Optional[dict]) -> dict:
    """The tenant's model overrides, keyed by capability value."""
    replicate = (tenant_settings or {}).get("replicate") or {}
    return dict(replicate.get("model_overrides") or {})


def _override_price(base: CapabilityConfig, override: dict) -> Price:
    """A tenant's price for its model (FR-024).

    A price charged per second needs a run time to estimate a job. The operator's
    figure comes first, then the default model's; failing both, the capability's
    time limit, the most a job can run, marked assumed: an estimate of zero would
    let spending pass the budget unchecked (SC-002).
    """
    unit = override["price_unit"]
    typical = int(override.get("typical_seconds") or 0)
    assumed = False
    if unit == "per_second" and not typical:
        typical = base.price.typical_seconds
        if not typical:
            typical, assumed = base.time_limit_s, True
    return Price(
        unit,
        Decimal(str(override["price_usd"])),
        typical_seconds=typical,
        source="override",
        assumed=assumed,
    )


def resolve(
    capability: Capability,
    tenant_settings: Optional[dict] = None,
    *,
    has_references: bool = False,
) -> CapabilityConfig:
    """The config a job of this capability uses for this tenant (override first)."""
    if capability is Capability.CONCEPT_IMAGE and has_references:
        # The override names a model taking the no-reference inputs; references keep
        # the official with-references model (research R3, FR-003).
        return CONCEPT_WITH_REFERENCES
    base = DEFAULTS[capability]
    override = overrides_of(tenant_settings).get(capability.value)
    if not override:
        return base
    price = base.price
    if override.get("price_unit") and override.get("price_usd") not in (None, ""):
        price = _override_price(base, override)
    return replace(
        base,
        model_ref=override["model_ref"],
        model_version=override.get("model_version") or OFFICIAL,
        price=price,
        overridden=True,
    )


def build_provider_input(
    config: CapabilityConfig, inputs: Any, image_urls: list[str], seed: int
) -> dict:
    """The provider's ``input`` object for a validated request."""
    values: dict[str, Any] = {
        "prompt": getattr(inputs, "prompt", None),
        "instruction": getattr(inputs, "instruction", None),
        "scene": getattr(inputs, "scene", None),
        "count": getattr(inputs, "count", None),
        "factor": getattr(inputs, "factor", None),
        "seed": seed,
    }
    style = getattr(inputs, "style", None)
    if style and values["prompt"]:
        values["prompt"] = f"{values['prompt']}. Style: {style}"
    if config.prompt_template:
        extra = (values.get("instruction") or "").strip()
        values["instruction"] = config.prompt_template + (f" {extra}" if extra else "")
    payload: dict[str, Any] = dict(config.default_params)
    for ours, theirs in config.input_mapping.items():
        if ours == "images":
            if not image_urls:
                continue
            payload[theirs] = list(image_urls) if theirs in config.list_fields else image_urls[0]
        elif values.get(ours) is not None:
            payload[theirs] = values[ours]
    return payload


def extract_output_urls(config: CapabilityConfig, output: Any) -> list[str]:
    """Normalise a provider output (string, list or object) to a list of URLs."""
    if output is None:
        return []
    if isinstance(output, dict):
        if config.output_key:
            output = output.get(config.output_key)
        else:
            output = [v for v in output.values() if isinstance(v, str)]
    if isinstance(output, str):
        return [output]
    if isinstance(output, list):
        return [u for u in output if isinstance(u, str) and u]
    return []


def selectable_inputs(config: CapabilityConfig) -> int:
    """How many input images the operator may pick for this capability.

    A concept image is resolved without references (its price and model are the
    no-reference default), but the operator may add references, which switch the
    job to ``CONCEPT_WITH_REFERENCES``: its limit is the one to offer.
    """
    if config.capability is Capability.CONCEPT_IMAGE:
        return max(config.max_inputs, CONCEPT_WITH_REFERENCES.max_inputs)
    return config.max_inputs


def input_rules(config: CapabilityConfig) -> dict[str, dict[str, Any]]:
    """The input rules of a capability as resolved, for screens and agents (FR-005).

    Derived from the capability's input model (the validation the service applies),
    narrowed by the resolved model's own limits, so the rules are written once.
    """
    rules = model_rules(INPUT_MODELS[config.capability])
    count = rules.get("count")
    if count is not None:
        count["max"] = min(count.get("max", config.max_count), config.max_count)
        if config.capability is Capability.CONCEPT_IMAGE:
            count["max_with_inputs"] = CONCEPT_WITH_REFERENCES.max_count
    assets = rules.get("input_assets")
    if assets is not None:
        assets["max"] = min(assets.get("max", selectable_inputs(config)), selectable_inputs(config))
    return rules


def capability_list(tenant_settings: Optional[dict] = None) -> list[CapabilityConfig]:
    """Every capability as it resolves for this tenant, in the enum's order."""
    return [resolve(c, tenant_settings) for c in Capability]


__all__ = [
    "CONCEPT_WITH_REFERENCES",
    "DEFAULTS",
    "OFFICIAL",
    "PRICE_UNITS",
    "CapabilityConfig",
    "Price",
    "build_provider_input",
    "capability_list",
    "extract_output_urls",
    "input_rules",
    "overrides_of",
    "resolve",
    "selectable_inputs",
]
