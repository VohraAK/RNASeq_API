import uuid

from sqlalchemy import Float, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Result(Base):
    __tablename__ = "results"
    __table_args__ = (Index("ix_results_job_padj", "job_id", "padj"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    gene_name: Mapped[str] = mapped_column(String(255), nullable=False)
    base_mean: Mapped[float | None] = mapped_column(Float, nullable=True)
    log2_fold_change: Mapped[float | None] = mapped_column(Float, nullable=True)
    lfc_se: Mapped[float | None] = mapped_column(Float, nullable=True)
    stat: Mapped[float | None] = mapped_column(Float, nullable=True)
    pvalue: Mapped[float | None] = mapped_column(Float, nullable=True)
    padj: Mapped[float | None] = mapped_column(Float, nullable=True)

    job: Mapped["Job"] = relationship(back_populates="results")  # noqa: F821
