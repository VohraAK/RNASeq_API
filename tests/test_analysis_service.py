"""
Tests for app.services.analysis.

DESeqEngine is only available inside the Docker container at /deseq_src/backend.
All tests here inject a mock via sys.modules so they run without Docker.
"""
import sys
from contextlib import contextmanager
from unittest.mock import MagicMock

import pandas as pd
import pytest

from app.services.analysis import AnalysisError, AnalysisResult, run

_RUN_ARGS = (
    b"gene1,s1,s2\n100,10,20\n",
    b"sample,condition\ns1,ctrl\ns2,trt\n",
    "~ condition",
    {"condition": "ctrl"},
    ["condition", "trt", "ctrl"],
)


def _sample_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "baseMean": [150.0, 80.0, 30.0],
            "log2FoldChange": [2.5, -1.8, 0.2],
            "lfcSE": [0.4, 0.3, 0.5],
            "stat": [6.25, -6.0, 0.4],
            "pvalue": [4e-10, 2e-9, 0.69],
            "padj": [8e-9, 4e-8, 0.90],
        },
        index=["GENE_A", "GENE_B", "GENE_C"],
    )


def _mock_deseq_module(engine_instance) -> MagicMock:
    mod = MagicMock()
    mod.DESeqEngine = MagicMock(return_value=engine_instance)
    return mod


# --- normal path ---

def test_run_returns_analysis_result():
    engine = MagicMock()
    engine.get_results.return_value = _sample_df()
    with patch_deseq(engine):
        result = run(*_RUN_ARGS)
    assert isinstance(result, AnalysisResult)


def test_run_genes_count_matches_dataframe():
    engine = MagicMock()
    df = _sample_df()
    engine.get_results.return_value = df
    with patch_deseq(engine):
        result = run(*_RUN_ARGS)
    assert len(result.genes) == len(df)


def test_run_gene_names_from_index():
    engine = MagicMock()
    engine.get_results.return_value = _sample_df()
    with patch_deseq(engine):
        result = run(*_RUN_ARGS)
    names = [g["gene_name"] for g in result.genes]
    assert names == ["GENE_A", "GENE_B", "GENE_C"]


def test_run_produces_nonempty_volcano_png():
    engine = MagicMock()
    engine.get_results.return_value = _sample_df()
    with patch_deseq(engine):
        result = run(*_RUN_ARGS)
    assert result.volcano_png[:4] == b"\x89PNG"  # PNG magic bytes


def test_run_produces_nonempty_ma_png():
    engine = MagicMock()
    engine.get_results.return_value = _sample_df()
    with patch_deseq(engine):
        result = run(*_RUN_ARGS)
    assert result.ma_png[:4] == b"\x89PNG"


def test_run_numeric_fields_extracted():
    engine = MagicMock()
    engine.get_results.return_value = _sample_df()
    with patch_deseq(engine):
        result = run(*_RUN_ARGS)
    g = result.genes[0]
    assert g["base_mean"] == pytest.approx(150.0)
    assert g["log2_fold_change"] == pytest.approx(2.5)
    assert g["padj"] == pytest.approx(8e-9)


# --- fresh instance per call ---

def test_fresh_engine_instance_per_call():
    mock_cls = MagicMock()
    mock_cls.return_value.get_results.return_value = _sample_df()
    mod = MagicMock()
    mod.DESeqEngine = mock_cls
    with _patch_module(mod):
        run(*_RUN_ARGS)
        run(*_RUN_ARGS)
    assert mock_cls.call_count == 2


# --- error mapping ---

def test_load_data_exception_maps_to_invalid_file_format():
    engine = MagicMock()
    engine.load_data.side_effect = Exception("malformed csv")
    with patch_deseq(engine):
        with pytest.raises(AnalysisError) as exc_info:
            run(*_RUN_ARGS)
    assert exc_info.value.code == "INVALID_FILE_FORMAT"


def test_analyse_value_error_maps_to_validation_error():
    engine = MagicMock()
    engine.analyse.side_effect = ValueError("unknown factor")
    with patch_deseq(engine):
        with pytest.raises(AnalysisError) as exc_info:
            run(*_RUN_ARGS)
    assert exc_info.value.code == "VALIDATION_ERROR"


def test_analyse_generic_exception_maps_to_analysis_failed():
    engine = MagicMock()
    engine.analyse.side_effect = RuntimeError("deseq2 diverged")
    with patch_deseq(engine):
        with pytest.raises(AnalysisError) as exc_info:
            run(*_RUN_ARGS)
    assert exc_info.value.code == "ANALYSIS_FAILED"


def test_get_results_exception_maps_to_analysis_failed():
    engine = MagicMock()
    engine.get_results.side_effect = Exception("contrast error")
    with patch_deseq(engine):
        with pytest.raises(AnalysisError) as exc_info:
            run(*_RUN_ARGS)
    assert exc_info.value.code == "ANALYSIS_FAILED"


def test_analysis_error_carries_message():
    engine = MagicMock()
    engine.load_data.side_effect = Exception("bad bytes")
    with patch_deseq(engine):
        with pytest.raises(AnalysisError) as exc_info:
            run(*_RUN_ARGS)
    assert exc_info.value.message  # non-empty


# --- null/NaN handling ---

def test_nan_values_become_none():
    engine = MagicMock()
    df = pd.DataFrame(
        {"baseMean": [float("nan")], "log2FoldChange": [float("nan")],
         "lfcSE": [float("nan")], "stat": [float("nan")],
         "pvalue": [float("nan")], "padj": [float("nan")]},
        index=["GENE_NAN"],
    )
    engine.get_results.return_value = df
    with patch_deseq(engine):
        result = run(*_RUN_ARGS)
    g = result.genes[0]
    assert g["base_mean"] is None
    assert g["padj"] is None


# --- helpers ---

@contextmanager
def patch_deseq(engine_instance):
    mod = _mock_deseq_module(engine_instance)
    with _patch_module(mod):
        yield


@contextmanager
def _patch_module(mod):
    original = sys.modules.get("DESeqEngine")
    sys.modules["DESeqEngine"] = mod
    try:
        yield
    finally:
        if original is None:
            sys.modules.pop("DESeqEngine", None)
        else:
            sys.modules["DESeqEngine"] = original
