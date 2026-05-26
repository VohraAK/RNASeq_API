import hashlib
import io
import uuid
from datetime import UTC, datetime, timedelta

import pandas as pd
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.dependencies import get_current_user, get_db
from app.limiter import _get_user_or_ip, limiter
from app.models.file import File, FileType
from app.models.user import User
from app.schemas.base import SuccessResponse
from app.schemas.files import FileResponse
from app.services.storage import LocalStorageBackend, get_storage

router = APIRouter(prefix="/files", tags=["files"])

_FILE_EXPIRE_DAYS = 7


def _validate_csv(data: bytes, file_type: FileType) -> None:
    try:
        df = pd.read_csv(io.BytesIO(data), index_col=0)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_FILE_FORMAT", "message": "Cannot parse file as CSV."},
        ) from exc

    if file_type == FileType.COUNTS:
        if df.columns.duplicated().any():
            raise HTTPException(
                status_code=422,
                detail={"code": "INVALID_FILE_FORMAT", "message": "Mismatched sample names: duplicate column names in counts matrix."},
            )
        if df.index.duplicated().any():
            raise HTTPException(
                status_code=422,
                detail={"code": "INVALID_FILE_FORMAT", "message": "Duplicate gene names in counts matrix."},
            )
        for col in df.columns:
            series = df[col]
            if pd.api.types.is_integer_dtype(series):
                continue
            if pd.api.types.is_float_dtype(series) and not series.isna().any():
                cast = series.astype("int64")
                if (cast == series).all():
                    continue
            raise HTTPException(
                status_code=422,
                detail={"code": "INVALID_FILE_FORMAT", "message": f"Non-integer counts in column '{col}'."},
            )
    else:
        if df.index.duplicated().any():
            raise HTTPException(
                status_code=422,
                detail={"code": "INVALID_FILE_FORMAT", "message": "Mismatched sample names: duplicate index in metadata."},
            )


def _file_response(file: File) -> SuccessResponse[FileResponse]:
    return SuccessResponse(data=FileResponse(
        file_id=file.id,
        original_filename=file.original_filename,
        file_type=file.file_type,
        size_bytes=file.size_bytes,
        expires_at=file.expires_at,
    ))


@router.post("/", status_code=201)
@limiter.limit("20/hour", key_func=_get_user_or_ip)
async def upload_file(
    request: Request,
    response: Response,
    file: UploadFile,
    file_type: FileType = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage: LocalStorageBackend = Depends(get_storage),
) -> SuccessResponse[FileResponse]:
    content = await file.read()

    if len(content) > settings.MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"code": "VALIDATION_ERROR", "message": "File exceeds 100 MB limit."},
        )

    _validate_csv(content, file_type)

    sha256 = hashlib.sha256(content).hexdigest()

    existing = await db.scalar(
        select(File).where(File.user_id == current_user.id, File.sha256_hash == sha256)
    )
    if existing is not None:
        response.status_code = 200
        return _file_response(existing)

    file_id = uuid.uuid4()
    storage_path = storage.write(current_user.id, file_id, content)

    record = File(
        id=file_id,
        user_id=current_user.id,
        original_filename=file.filename or "upload.csv",
        file_type=file_type,
        storage_path=storage_path,
        size_bytes=len(content),
        sha256_hash=sha256,
        expires_at=datetime.now(UTC) + timedelta(days=_FILE_EXPIRE_DAYS),
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return _file_response(record)


@router.get("/{file_id}")
async def get_file(
    file_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SuccessResponse[FileResponse]:
    file = await db.scalar(
        select(File).where(File.id == file_id, File.user_id == current_user.id)
    )
    if file is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"File {file_id} does not exist or is not owned by you."},
        )
    return _file_response(file)


@router.delete("/{file_id}", status_code=204)
async def delete_file(
    file_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage: LocalStorageBackend = Depends(get_storage),
) -> None:
    file = await db.scalar(
        select(File).where(File.id == file_id, File.user_id == current_user.id)
    )
    if file is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"File {file_id} does not exist or is not owned by you."},
        )
    storage.delete(file.storage_path)
    db.delete(file)
    await db.commit()
