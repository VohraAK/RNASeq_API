import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.limiter import _get_user_or_ip, limiter
from app.models.file import File, FileType
from app.models.job import Job, JobStatus
from app.models.user import User
from app.schemas.base import SuccessResponse
from app.schemas.jobs import JobResponse, JobSubmitRequest

router = APIRouter(prefix="/jobs", tags=["jobs"])

_JOB_EXPIRE_DAYS = 14


def _job_response(job: Job) -> SuccessResponse[JobResponse]:
    return SuccessResponse(data=JobResponse(
        job_id=job.id,
        status=job.status,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error_message=job.error_message,
        expires_at=job.expires_at,
    ))


async def _get_owned_job(job_id: uuid.UUID, user: User, db: AsyncSession) -> Job:
    job = await db.scalar(select(Job).where(Job.id == job_id, Job.user_id == user.id))
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "JOB_NOT_FOUND", "message": f"Job {job_id} does not exist or is not owned by you."},
        )
    return job


@router.post("/", status_code=201)
@limiter.limit("10/hour", key_func=_get_user_or_ip)
async def submit_job(
    request: Request,
    body: JobSubmitRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SuccessResponse[JobResponse]:
    counts_file = await db.scalar(
        select(File).where(File.id == body.counts_file_id, File.user_id == current_user.id)
    )
    if counts_file is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"File {body.counts_file_id} does not exist or is not owned by you."},
        )
    if counts_file.file_type != FileType.COUNTS:
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": f"File {body.counts_file_id} is not a counts file."},
        )

    metadata_file = await db.scalar(
        select(File).where(File.id == body.metadata_file_id, File.user_id == current_user.id)
    )
    if metadata_file is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"File {body.metadata_file_id} does not exist or is not owned by you."},
        )
    if metadata_file.file_type != FileType.METADATA:
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": f"File {body.metadata_file_id} is not a metadata file."},
        )

    from sqlalchemy.dialects.postgresql import JSONB
    from sqlalchemy import cast

    active_job = await db.scalar(
        select(Job).where(
            Job.user_id == current_user.id,
            Job.counts_file_id == body.counts_file_id,
            Job.metadata_file_id == body.metadata_file_id,
            Job.design_formula == body.design_formula,
            Job.ref_levels == cast(body.ref_levels, JSONB),
            Job.contrast == cast(body.contrast, JSONB),
            Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]),
        )
    )
    if active_job is not None:
        return _job_response(active_job)

    job = Job(
        user_id=current_user.id,
        counts_file_id=body.counts_file_id,
        metadata_file_id=body.metadata_file_id,
        design_formula=body.design_formula,
        ref_levels=body.ref_levels,
        contrast=body.contrast,
        status=JobStatus.QUEUED,
        expires_at=datetime.now(UTC) + timedelta(days=_JOB_EXPIRE_DAYS),
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    from app.workers.tasks import run_analysis
    await run_analysis.defer_async(job_id=str(job.id))

    return _job_response(job)


@router.get("/{job_id}")
async def get_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SuccessResponse[JobResponse]:
    job = await _get_owned_job(job_id, current_user, db)
    return _job_response(job)


@router.delete("/{job_id}")
async def cancel_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SuccessResponse[JobResponse]:
    job = await _get_owned_job(job_id, current_user, db)

    if job.status == JobStatus.RUNNING:
        raise HTTPException(
            status_code=409,
            detail={"code": "VALIDATION_ERROR", "message": "Cannot cancel a running job."},
        )
    if job.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
        raise HTTPException(
            status_code=409,
            detail={"code": "VALIDATION_ERROR", "message": f"Job is already {job.status.value}."},
        )

    job.status = JobStatus.CANCELLED
    await db.commit()
    await db.refresh(job)
    return _job_response(job)
