import asyncio
import io
import uuid

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.job import Job, JobStatus
from app.models.result import Result
from app.models.user import User
from app.schemas.base import SuccessResponse
from app.schemas.results import GeneResult

router = APIRouter(prefix="/results", tags=["results"])


async def _get_completed_job(job_id: uuid.UUID, user: User, db: AsyncSession) -> Job:
    job = await db.scalar(select(Job).where(Job.id == job_id, Job.user_id == user.id))
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "JOB_NOT_FOUND", "message": f"Job {job_id} does not exist or is not owned by you."},
        )
    if job.status != JobStatus.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail={"code": "JOB_NOT_READY", "message": f"Job is {job.status.value}, not COMPLETED."},
        )
    return job


@router.get("/{job_id}")
async def get_results(
    job_id: uuid.UUID,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=100, ge=1, le=1000),
    padj_max: float | None = Query(default=None, ge=0.0, le=1.0),
    log2fc_min: float | None = Query(default=None, ge=0.0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SuccessResponse[list[GeneResult]]:
    await _get_completed_job(job_id, current_user, db)

    filters = [Result.job_id == job_id]
    if padj_max is not None:
        filters.append(Result.padj <= padj_max)
    if log2fc_min is not None:
        filters.append(func.abs(Result.log2_fold_change) >= log2fc_min)

    total = await db.scalar(select(func.count()).select_from(Result).where(*filters))
    offset = (page - 1) * limit
    rows = await db.scalars(
        select(Result).where(*filters).order_by(Result.padj.asc()).offset(offset).limit(limit)
    )

    genes = [
        GeneResult(
            gene_name=r.gene_name,
            base_mean=r.base_mean,
            log2_fold_change=r.log2_fold_change,
            lfc_se=r.lfc_se,
            stat=r.stat,
            pvalue=r.pvalue,
            padj=r.padj,
        )
        for r in rows
    ]
    pages = max(1, -(-total // limit))  # ceiling division
    return SuccessResponse(
        data=genes,
        meta={"page": page, "limit": limit, "total": total, "pages": pages},
    )


@router.get("/{job_id}/volcano")
async def get_volcano(
    job_id: uuid.UUID,
    padj_threshold: float = Query(default=0.05, ge=0.0, le=1.0),
    lfc_threshold: float = Query(default=1.0, ge=0.0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    await _get_completed_job(job_id, current_user, db)
    rows = await db.scalars(select(Result).where(Result.job_id == job_id))
    df = _rows_to_df(list(rows))
    png = await asyncio.to_thread(_render_volcano, df, padj_threshold, lfc_threshold)
    return Response(content=png, media_type="image/png")


@router.get("/{job_id}/ma")
async def get_ma(
    job_id: uuid.UUID,
    padj_threshold: float = Query(default=0.05, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Response:
    await _get_completed_job(job_id, current_user, db)
    rows = await db.scalars(select(Result).where(Result.job_id == job_id))
    df = _rows_to_df(list(rows))
    png = await asyncio.to_thread(_render_ma, df, padj_threshold)
    return Response(content=png, media_type="image/png")


def _rows_to_df(rows: list[Result]) -> pd.DataFrame:
    return pd.DataFrame([{
        "gene_name": r.gene_name,
        "baseMean": r.base_mean,
        "log2FoldChange": r.log2_fold_change,
        "padj": r.padj,
    } for r in rows])


def _render_volcano(df: pd.DataFrame, padj_threshold: float, lfc_threshold: float) -> bytes:
    fig, ax = plt.subplots(figsize=(8, 6))
    try:
        lfc = pd.to_numeric(df.get("log2FoldChange", pd.Series(dtype=float)), errors="coerce")
        padj = pd.to_numeric(df.get("padj", pd.Series(dtype=float)), errors="coerce")
        neg_log_padj = -np.log10(padj.clip(lower=1e-300))

        sig = (padj < padj_threshold) & (lfc.abs() >= lfc_threshold)
        ax.scatter(lfc[~sig], neg_log_padj[~sig], s=4, alpha=0.5, color="grey", label="NS")
        ax.scatter(lfc[sig], neg_log_padj[sig], s=4, alpha=0.7, color="red", label="Significant")
        ax.axhline(-np.log10(padj_threshold), linestyle="--", linewidth=0.8, color="black")
        ax.axvline(lfc_threshold, linestyle="--", linewidth=0.8, color="black")
        ax.axvline(-lfc_threshold, linestyle="--", linewidth=0.8, color="black")
        ax.set_xlabel("log2 Fold Change")
        ax.set_ylabel("-log10(padj)")
        ax.set_title("Volcano Plot")
        ax.legend(markerscale=2)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        return buf.getvalue()
    finally:
        plt.close(fig)


def _render_ma(df: pd.DataFrame, padj_threshold: float) -> bytes:
    fig, ax = plt.subplots(figsize=(8, 6))
    try:
        base_mean = pd.to_numeric(df.get("baseMean", pd.Series(dtype=float)), errors="coerce")
        lfc = pd.to_numeric(df.get("log2FoldChange", pd.Series(dtype=float)), errors="coerce")
        padj = pd.to_numeric(df.get("padj", pd.Series(dtype=float)), errors="coerce")

        log_base_mean = np.log2(base_mean.clip(lower=1e-10))
        sig = padj < padj_threshold

        ax.scatter(log_base_mean[~sig], lfc[~sig], s=4, alpha=0.5, color="grey", label="NS")
        ax.scatter(log_base_mean[sig], lfc[sig], s=4, alpha=0.7, color="red", label="Significant")
        ax.axhline(0, linestyle="-", linewidth=0.8, color="black")
        ax.set_xlabel("log2 Mean Expression")
        ax.set_ylabel("log2 Fold Change")
        ax.set_title("MA Plot")
        ax.legend(markerscale=2)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        return buf.getvalue()
    finally:
        plt.close(fig)
