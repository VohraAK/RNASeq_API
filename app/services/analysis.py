import io
import os
import tempfile
from dataclasses import dataclass, field

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

matplotlib.use("Agg")


class AnalysisError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class AnalysisResult:
    genes: list[dict] = field(default_factory=list)
    volcano_png: bytes = b""
    ma_png: bytes = b""


def run(
    counts_bytes: bytes,
    metadata_bytes: bytes,
    design_formula: str,
    ref_levels: dict,
    contrast: list[str],
) -> AnalysisResult:
    from DESeqEngine import DESeqEngine  # mounted at /deseq_src/backend

    counts_path = metadata_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as cf:
            cf.write(counts_bytes)
            counts_path = cf.name
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as mf:
            mf.write(metadata_bytes)
            metadata_path = mf.name

        engine = DESeqEngine()

        try:
            engine.load_data(counts_path, metadata_path)
        except Exception as exc:
            raise AnalysisError("INVALID_FILE_FORMAT", "Failed to load input data.") from exc

        try:
            engine.analyse(design_formula, ref_levels)
        except ValueError as exc:
            raise AnalysisError("VALIDATION_ERROR", "Invalid design formula or reference levels.") from exc
        except Exception as exc:
            raise AnalysisError("ANALYSIS_FAILED", "DESeq2 model fitting failed.") from exc

        try:
            results_df = engine.get_results(contrast)
        except Exception as exc:
            raise AnalysisError("ANALYSIS_FAILED", "Failed to extract results.") from exc

        genes = _extract_genes(results_df)
        volcano_png = _render_volcano(results_df)
        ma_png = _render_ma(results_df)

        return AnalysisResult(genes=genes, volcano_png=volcano_png, ma_png=ma_png)
    finally:
        for p in (counts_path, metadata_path):
            if p and os.path.exists(p):
                os.unlink(p)


def _to_float(val) -> float | None:
    try:
        f = float(val)
        return None if np.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _extract_genes(df: pd.DataFrame) -> list[dict]:
    genes = []
    for gene_name, row in df.iterrows():
        genes.append({
            "gene_name": str(gene_name),
            "base_mean": _to_float(row.get("baseMean")),
            "log2_fold_change": _to_float(row.get("log2FoldChange")),
            "lfc_se": _to_float(row.get("lfcSE")),
            "stat": _to_float(row.get("stat")),
            "pvalue": _to_float(row.get("pvalue")),
            "padj": _to_float(row.get("padj")),
        })
    return genes


def _render_volcano(df: pd.DataFrame, padj_threshold: float = 0.05, lfc_threshold: float = 1.0) -> bytes:
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


def _render_ma(df: pd.DataFrame, padj_threshold: float = 0.05) -> bytes:
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
