import logging
import uuid
from datetime import UTC, datetime

import procrastinate
from procrastinate.psycopg_connector import PsycopgConnector

import app.models  # noqa: F401 — ensures all ORM models registered before any query
from app.config import settings

logger = logging.getLogger(__name__)

_dsn = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

procrastinate_app = procrastinate.App(
    connector=PsycopgConnector(conninfo=_dsn),
    import_paths=["app.workers.tasks"],
)


@procrastinate_app.task(queue="analysis")
async def run_analysis(job_id: str) -> None:
    from app.database import AsyncSessionLocal
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, uuid.UUID(job_id))
        if job is None:
            logger.error("Job %s not found", job_id)
            return

        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        await db.commit()

        try:
            await _execute_analysis(db, job)
        except Exception as exc:
            logger.exception("Job %s failed", job_id)
            await db.rollback()
            job.status = JobStatus.FAILED
            job.error_message = _sanitize_error(exc)
            job.completed_at = datetime.now(UTC)
            await db.commit()


async def _execute_analysis(db, job) -> None:
    import asyncio

    from app.models.file import File
    from app.models.job import JobStatus
    from app.models.result import Result
    from app.services.analysis import run as run_analysis_sync
    from app.services.storage import get_storage

    storage = get_storage()

    counts_row = await db.get(File, job.counts_file_id)
    metadata_row = await db.get(File, job.metadata_file_id)

    if counts_row is None or metadata_row is None:
        job.status = JobStatus.FAILED
        job.error_message = "Input file(s) no longer exist."
        job.completed_at = datetime.now(UTC)
        await db.commit()
        return

    counts_bytes = await asyncio.to_thread(storage.read, counts_row.storage_path)
    metadata_bytes = await asyncio.to_thread(storage.read, metadata_row.storage_path)

    result = await asyncio.to_thread(
        run_analysis_sync,
        counts_bytes,
        metadata_bytes,
        job.design_formula,
        job.ref_levels,
        job.contrast,
    )

    rows = [
        Result(
            job_id=job.id,
            gene_name=g["gene_name"],
            base_mean=g.get("base_mean"),
            log2_fold_change=g.get("log2_fold_change"),
            lfc_se=g.get("lfc_se"),
            stat=g.get("stat"),
            pvalue=g.get("pvalue"),
            padj=g.get("padj"),
        )
        for g in result.genes
    ]
    db.add_all(rows)

    job.status = JobStatus.COMPLETED
    job.completed_at = datetime.now(UTC)
    await db.commit()


def _sanitize_error(exc: Exception) -> str:
    from app.services.analysis import AnalysisError
    if isinstance(exc, AnalysisError):
        return exc.message
    return "An internal error occurred during analysis."
