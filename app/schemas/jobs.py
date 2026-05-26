import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.job import JobStatus

_FORMULA_RE = re.compile(r"^[~+\-*:()\^.\s\w]+$")


class JobSubmitRequest(BaseModel):
    counts_file_id: uuid.UUID
    metadata_file_id: uuid.UUID
    design_formula: str = Field(max_length=200)
    ref_levels: dict[str, str]
    contrast: list[str] = Field(min_length=3, max_length=3)

    @field_validator("design_formula")
    @classmethod
    def validate_formula(cls, v: str) -> str:
        if not _FORMULA_RE.match(v):
            raise ValueError("Invalid design formula syntax.")
        return v


class JobResponse(BaseModel):
    job_id: uuid.UUID
    status: JobStatus
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    expires_at: datetime
