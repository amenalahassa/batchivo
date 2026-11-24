"""Pydantic schemas for product ideas and their timeline (spec 007)."""

from datetime import datetime
from typing import Literal, Optional
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

IdeaStatus = Literal["inbox", "exploring", "validating", "ready", "converted", "parked", "dropped"]
WritableIdeaStatus = Literal["inbox", "exploring", "validating", "ready", "parked", "dropped"]
IdeaSource = Literal["manual", "pain_point_report", "customer", "other"]
EntryKind = Literal["note", "image", "link", "sketch", "measurement", "decision", "generation"]
TextEntryKind = Literal["note", "link", "measurement", "decision"]
ImageEntryKind = Literal["image", "sketch"]
LinkState = Literal["linked", "gone", "none"]

MAX_TEXT = 20000
MAX_TAGS = 20
MAX_TAG_LENGTH = 40
MAX_IMPORT_ITEMS = 200


def check_http_url(value: Optional[str]) -> Optional[str]:
    """Accept only absolute http(s) links (spec edge case: other schemes refused)."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Link must start with http:// or https://")
    return value


def normalise_tags(value: Optional[list[str]]) -> list[str]:
    """Trim, lowercase and de-duplicate tags, keeping their first order."""
    tags: list[str] = []
    for raw in value or []:
        tag = " ".join(str(raw).split()).lower()
        if not tag:
            continue
        if len(tag) > MAX_TAG_LENGTH:
            raise ValueError(f"A tag is at most {MAX_TAG_LENGTH} characters")
        if tag not in tags:
            tags.append(tag)
    if len(tags) > MAX_TAGS:
        raise ValueError(f"An idea has at most {MAX_TAGS} tags")
    return tags


def _strip_title(value: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ValueError("Title is required")
    return value


# ============================================
# Ideas
# ============================================


class IdeaScores(BaseModel):
    """The five pain-point criteria, 1 to 5 each; any may be missing."""

    frequency: Optional[int] = Field(None, ge=1, le=5, description="How often it happens")
    frustration: Optional[int] = Field(None, ge=1, le=5, description="How annoying it is")
    printability: Optional[int] = Field(None, ge=1, le=5, description="How printable a fix is")
    gap: Optional[int] = Field(None, ge=1, le=5, description="How poorly it is solved today")
    willingness_to_pay: Optional[int] = Field(
        None, ge=1, le=5, description="How likely people pay for a fix"
    )


class IdeaCreate(BaseModel):
    """Create an idea."""

    title: str = Field(..., min_length=1, max_length=200)
    summary: Optional[str] = Field(None, max_length=MAX_TEXT)
    status: WritableIdeaStatus = "inbox"
    source: IdeaSource = "manual"
    source_url: Optional[str] = Field(None, max_length=2048)
    tags: list[str] = Field(default_factory=list)
    scores: IdeaScores = Field(default_factory=IdeaScores)
    report_score: Optional[int] = Field(
        None, ge=0, le=25, description="Total out of 25 given by a report"
    )

    _title = field_validator("title")(_strip_title)
    _url = field_validator("source_url")(check_http_url)
    _tags = field_validator("tags", mode="before")(normalise_tags)


class IdeaUpdate(BaseModel):
    """Partial update of an idea. ``converted`` is set only by a conversion."""

    title: Optional[str] = Field(None, min_length=1, max_length=200)
    summary: Optional[str] = Field(None, max_length=MAX_TEXT)
    status: Optional[WritableIdeaStatus] = None
    source: Optional[IdeaSource] = None
    source_url: Optional[str] = Field(None, max_length=2048)
    tags: Optional[list[str]] = None
    scores: Optional[IdeaScores] = None
    archived: Optional[bool] = None
    cover_entry_id: Optional[UUID] = None

    _url = field_validator("source_url")(check_http_url)

    @field_validator("title")
    @classmethod
    def _title(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else _strip_title(value)

    @field_validator("tags", mode="before")
    @classmethod
    def _tags(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        return None if value is None else normalise_tags(value)


class UserRef(BaseModel):
    """Who wrote or created something."""

    id: UUID
    name: Optional[str] = None


class IdeaLink(BaseModel):
    """What an idea became: a model or a product, or a link that is gone."""

    id: Optional[UUID] = None
    name: Optional[str] = None
    sku: Optional[str] = None
    state: LinkState = "none"


class IdeaSummary(BaseModel):
    """An idea as shown on the board and in the list."""

    id: UUID
    title: str
    status: IdeaStatus
    source: IdeaSource
    source_url: Optional[str] = None
    tags: list[str]
    scores: IdeaScores
    report_score: Optional[int] = None
    score: Optional[int] = None
    score_source: Optional[Literal["scores", "report"]] = None
    cover_thumbnail_path: Optional[str] = None
    current_iteration: int
    archived: bool
    model: IdeaLink
    product: IdeaLink
    created_at: datetime
    updated_at: datetime


class IdeaDetail(IdeaSummary):
    """An idea with its summary, cover and creator."""

    summary: Optional[str] = None
    cover_entry_id: Optional[UUID] = None
    cover_image_path: Optional[str] = None
    created_by: Optional[UserRef] = None


class IdeaListResponse(BaseModel):
    """A page of ideas."""

    items: list[IdeaSummary]
    total: int
    skip: int
    limit: int


# ============================================
# Timeline entries
# ============================================


class IdeaEntryCreate(BaseModel):
    """A text entry: note, link, measurement or decision."""

    kind: TextEntryKind
    body: Optional[str] = Field(None, max_length=MAX_TEXT)
    link_url: Optional[str] = Field(None, max_length=2048)

    _url = field_validator("link_url")(check_http_url)


class IdeaEntryUpdate(BaseModel):
    """Edit, pin, archive or restore an entry; an image can become a sketch."""

    body: Optional[str] = Field(None, max_length=MAX_TEXT)
    link_url: Optional[str] = Field(None, max_length=2048)
    pinned: Optional[bool] = None
    archived: Optional[bool] = None
    kind: Optional[ImageEntryKind] = None

    _url = field_validator("link_url")(check_http_url)


class IdeaEntryResponse(BaseModel):
    """One timeline entry."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    idea_id: UUID
    kind: EntryKind
    iteration: int
    body: Optional[str] = None
    link_url: Optional[str] = None
    pinned: bool
    archived: bool
    image_path: Optional[str] = None
    thumbnail_path: Optional[str] = None
    content_type: Optional[str] = None
    original_filename: Optional[str] = None
    file_size: Optional[int] = None
    generation_job_id: Optional[UUID] = None
    author: Optional[UserRef] = None
    created_at: datetime
    edited_at: Optional[datetime] = None


class IdeaEntryList(BaseModel):
    """An idea's timeline."""

    items: list[IdeaEntryResponse]
    current_iteration: int


class RefusedFile(BaseModel):
    """A file an upload did not save, and why."""

    filename: Optional[str] = None
    reason: str


class ImageUploadResult(BaseModel):
    """Images saved as entries, and files refused."""

    created: list[IdeaEntryResponse]
    refused: list[RefusedFile]


class IterationCreate(BaseModel):
    """Start the next iteration, optionally with a note."""

    note: Optional[str] = Field(None, max_length=MAX_TEXT)


# ============================================
# Conversion
# ============================================


class ConvertRequest(BaseModel):
    """Turn an idea into a model, or a product with its model."""

    target: Literal["model", "product"]
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    model_sku: Optional[str] = Field(None, min_length=1, max_length=50)
    product_sku: Optional[str] = Field(None, min_length=1, max_length=100)
    include_images: bool = True


class ConvertResponse(BaseModel):
    """What a conversion created."""

    idea: IdeaDetail
    model_id: UUID
    product_id: Optional[UUID] = None
    copied_images: int
    warnings: list[str]


# ============================================
# Import
# ============================================


class ImportItem(BaseModel):
    """One problem of a pain-point report, as agents and the screen send it."""

    title: str = Field(..., min_length=1, max_length=200)
    summary: Optional[str] = Field(None, max_length=MAX_TEXT)
    scores: Optional[IdeaScores] = None
    report_score: Optional[int] = Field(None, ge=0, le=25)
    tags: list[str] = Field(default_factory=list)
    source_url: Optional[str] = Field(None, max_length=2048)


class ImportRequest(BaseModel):
    """Create ideas in bulk. Items are validated one by one by the service."""

    items: list[dict] = Field(..., min_length=1, max_length=MAX_IMPORT_ITEMS)
    dry_run: bool = False


class ImportCreated(BaseModel):
    id: Optional[UUID] = None
    title: str


class ImportSkipped(BaseModel):
    title: str
    source_url: Optional[str] = None
    existing_idea_id: Optional[UUID] = None


class ImportRefused(BaseModel):
    index: int
    title: Optional[str] = None
    reason: str


class ImportResult(BaseModel):
    """What an import created, skipped and refused."""

    created: list[ImportCreated]
    skipped: list[ImportSkipped]
    refused: list[ImportRefused]


class ParseReportRequest(BaseModel):
    """The markdown text of a pain-point report."""

    text: str = Field(..., min_length=1, max_length=500000)


class ParseReportResponse(BaseModel):
    """Problems found in a report, ready for import."""

    items: list[ImportItem]
    warnings: list[str]
