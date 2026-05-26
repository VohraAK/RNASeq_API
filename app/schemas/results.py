from pydantic import BaseModel


class GeneResult(BaseModel):
    gene_name: str
    base_mean: float | None = None
    log2_fold_change: float | None = None
    lfc_se: float | None = None
    stat: float | None = None
    pvalue: float | None = None
    padj: float | None = None
