"""Pydantic schemas for ModelFile API (3D model files)."""

from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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


class ModelFileUpdate(BaseModel):
    """Schema for updating file metadata."""

    part_name: Optional[str] = Field(
        None, max_length=100, description="Part name for multi-part models"
    )
    version: Optional[str] = Field(None, max_length=50, description="Version identifier")
    is_primary: Optional[bool] = Field(None, description="Whether this is the primary file")
    notes: Optional[str] = Field(None, description="User notes about the file")


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
    version: Optional[str] = Field(None, description="Version identifier")
    is_primary: bool = Field(..., description="Whether this is the primary file")
    notes: Optional[str] = Field(None, description="User notes")
    uploaded_at: datetime = Field(..., description="When the file was uploaded")
    uploaded_by_user_id: Optional[UUID] = Field(None, description="User who uploaded")
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


class ThreeMFPlateMetadata(BaseModel):
    """Per-plate metadata for a single plate within a multi-plate 3MF file."""

    index: int = Field(..., description="1-based plate index as recorded by the slicer")
    print_time_minutes: Optional[int] = Field(
        None, description="Estimated print time in minutes for this plate"
    )
    filament_weight_grams: Optional[float] = Field(
        None, description="Filament weight in grams for this plate"
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
