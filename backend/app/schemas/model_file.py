"""Pydantic schemas for ModelFile API (3D model files)."""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.dimensions import Tenth


class ModelFileType(str, Enum):
    """Types of 3D model files."""

    SOURCE_STL = "source_stl"
    SOURCE_3MF = "source_3mf"
    SLICER_PROJECT = "slicer_project"
    GCODE = "gcode"
    PLATE_LAYOUT = "plate_layout"


class FileLocation(str, Enum):
    """Where the file is stored."""

    UPLOADED = "uploaded"
    LOCAL_REFERENCE = "local_reference"


class ModelFileBase(BaseModel):
    """Base schema for model files."""

    file_type: ModelFileType = Field(..., description="Type of file")
    part_name: Optional[str] = Field(
        None, max_length=100, description="Part name for multi-part models"
    )
    version: Optional[str] = Field(None, max_length=50, description="Version identifier")
    is_primary: bool = Field(False, description="Whether this is the primary file")
    notes: Optional[str] = Field(None, description="User notes about the file")


class ModelFileCreate(BaseModel):
    """Schema for file upload metadata (file content sent separately as multipart)."""

    file_type: ModelFileType = Field(..., description="Type of file")
    part_name: Optional[str] = Field(
        None, max_length=100, description="Part name for multi-part models"
    )
    version: Optional[str] = Field(None, max_length=50, description="Version identifier")
    is_primary: bool = Field(False, description="Whether this is the primary file")
    notes: Optional[str] = Field(None, description="User notes about the file")


class ModelFileLocalCreate(BaseModel):
    """Schema for creating a local file reference (no upload, just path link)."""

    file_type: ModelFileType = Field(..., description="Type of file")
    local_path: str = Field(..., max_length=1000, description="Local filesystem path to the file")
    part_name: Optional[str] = Field(
        None, max_length=100, description="Part name for multi-part models"
    )
    version: Optional[str] = Field(None, max_length=50, description="Version identifier")
    is_primary: bool = Field(False, description="Whether this is the primary file")
    notes: Optional[str] = Field(None, description="User notes about the file")
    version_id: Optional[UUID] = Field(None, description="Version to add the file to")
    new_version_label: Optional[str] = Field(
        None, max_length=50, description="Create a new version with this label"
    )
    new_version_note: Optional[str] = Field(
        None, max_length=2000, description="What changed in the new version"
    )


class ModelFileUpdate(BaseModel):
    """Schema for updating file metadata."""

    part_name: Optional[str] = Field(
        None, max_length=100, description="Part name for multi-part models"
    )
    version: Optional[str] = Field(None, max_length=50, description="Version identifier")
    is_primary: Optional[bool] = Field(None, description="Whether this is the primary file")
    notes: Optional[str] = Field(None, description="User notes about the file")


class MeasuredObjectOut(BaseModel):
    """One object's size in a multi-object 3MF."""

    name: str
    length_mm: Tenth
    width_mm: Tenth
    height_mm: Tenth


class FileMeasurementOut(BaseModel):
    """A file's measured bounding box (research D3, contracts: model file upload).

    Sizes are absent while ``status`` is ``pending`` and when the file could not
    be measured; ``note`` then says why.
    """

    length_mm: Optional[Tenth] = None
    width_mm: Optional[Tenth] = None
    height_mm: Optional[Tenth] = None
    objects: list[MeasuredObjectOut] = Field(default_factory=list)
    note: Optional[str] = None
    status: str = Field(..., description="done | pending | skipped | failed")
    reason: Optional[str] = Field(
        None, description="Why it was not measured: no_geometry | unreadable | too_large"
    )
    applied_to: list[str] = Field(
        default_factory=list, description="Records that took it automatically"
    )


class ModelFileResponse(BaseModel):
    """Schema for file response."""

    id: UUID
    model_id: UUID
    file_type: str = Field(..., description="Type of file")
    file_location: str = Field(
        "uploaded", description="Where file is stored: 'uploaded' or 'local_reference'"
    )
    file_url: Optional[str] = Field(
        None, description="URL to download the file (for uploaded files)"
    )
    local_path: Optional[str] = Field(
        None, description="Local filesystem path (for local_reference files)"
    )
    local_path_exists: Optional[bool] = Field(
        None, description="Whether the local file path exists (only for local_reference)"
    )
    original_filename: str = Field(..., description="Original filename")
    file_size: Optional[int] = Field(None, description="File size in bytes")
    content_type: Optional[str] = Field(None, description="MIME content type")
    part_name: Optional[str] = Field(None, description="Part name for multi-part models")
    version: Optional[str] = Field(
        None, description="Label of the file's version (informational; grouping follows version_id)"
    )
    version_id: Optional[UUID] = Field(None, description="Version this file belongs to")
    is_sliced: bool = Field(False, description="True for a sliced plate (G-code or .gcode.3mf)")
    is_primary: bool = Field(..., description="Whether this is the primary file")
    notes: Optional[str] = Field(None, description="User notes")
    uploaded_at: datetime = Field(..., description="When the file was uploaded")
    uploaded_by_user_id: Optional[UUID] = Field(None, description="User who uploaded")
    measurement: Optional[FileMeasurementOut] = Field(
        None, description="Measured bounding box; null for G-code"
    )
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ModelFileListResponse(BaseModel):
    """Response for listing model files."""

    files: list[ModelFileResponse] = Field(..., description="List of files")
    total: int = Field(..., description="Total number of files")


class ModelFileUploadResponse(BaseModel):
    """Response after successful file upload."""

    file: ModelFileResponse = Field(..., description="Uploaded file details")
    measurement: Optional[FileMeasurementOut] = Field(
        None, description="The file's measurement; null for G-code"
    )
    version_created: bool = Field(
        False, description="A new version was made for this file; offer to make it active"
    )
    message: str = Field("File uploaded successfully", description="Success message")


class LocalPathValidationRequest(BaseModel):
    """Request to validate a local file path."""

    path: str = Field(..., description="Local filesystem path to validate")


class LocalPathValidationResponse(BaseModel):
    """Response for local path validation."""

    path: str = Field(..., description="The path that was validated")
    exists: bool = Field(..., description="Whether the path exists")
    is_file: bool = Field(False, description="Whether the path is a file (not directory)")
    file_size: Optional[int] = Field(None, description="File size in bytes if exists")
    filename: Optional[str] = Field(None, description="Extracted filename from path")


class ThreeMFFilamentUse(BaseModel):
    """One filament a plate uses, as the slicer reports it (spec 004, T063)."""

    id: Optional[int] = Field(
        None, description="Slicer filament number (1-based) as in slice_info.config"
    )
    type: Optional[str] = Field(None, description="Material, e.g. PLA")
    color: Optional[str] = Field(None, description="Colour as #RRGGBB")
    grams: Optional[float] = Field(None, description="Grams of this filament on the plate")


class ThreeMFPlateMetadata(BaseModel):
    """Per-plate metadata for a single plate within a multi-plate 3MF file."""

    index: int = Field(..., description="1-based plate index as recorded by the slicer")
    print_time_minutes: Optional[int] = Field(
        None, description="Estimated print time in minutes for this plate"
    )
    filament_weight_grams: Optional[float] = Field(
        None, description="Filament weight in grams for this plate"
    )
    object_count: Optional[int] = Field(
        None,
        description="Objects printed on the plate (skipped ones excluded); null when not listed",
    )
    filaments: list[ThreeMFFilamentUse] = Field(
        default_factory=list, description="Filaments the plate uses, with grams of each"
    )


class ThreeMFParseResponse(BaseModel):
    """Response for parsing embedded slicer metadata out of a 3MF file.

    Transient/informational only - parsing never creates or modifies a
    Model, ModelFile, or ModelMaterial record.
    """

    print_time_minutes: Optional[int] = Field(
        None, description="Estimated print time in minutes, from the selected plate"
    )
    filament_weight_grams: Optional[float] = Field(
        None, description="Total filament weight in grams, from the selected plate"
    )
    plate_count: Optional[int] = Field(None, description="Total number of plates found in the file")
    source_plate_index: Optional[int] = Field(
        None,
        description="1-based index of the plate print_time_minutes/filament_weight_grams were taken from",
    )
    slicer_detected: Optional[str] = Field(
        None, description="'bambu_orca', 'prusaslicer', or None if unrecognized"
    )
    thumbnail_available: bool = Field(
        False, description="Whether a thumbnail was also found in this file"
    )
    plates: list[ThreeMFPlateMetadata] = Field(
        default_factory=list,
        description=(
            "Per-plate breakdown when the slicer format exposes one (Bambu/Orca only; "
            "empty for PrusaSlicer or single-plate files). Lets the caller combine "
            "multiple plates instead of only using the first."
        ),
    )
    measurement: Optional[FileMeasurementOut] = Field(
        None, description="The file's measured bounding box, not stored"
    )
