import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.file import FileType


class FileResponse(BaseModel):
    file_id: uuid.UUID
    original_filename: str
    file_type: FileType
    size_bytes: int
    expires_at: datetime

    model_config = {"from_attributes": True}
