"""Anova MTPE engine — shared analysis core for the Post-Editor and LQA tools.

Streamlit-free on purpose: both apps (and, later, the portal) import from here.
Canonical copy lives in the `posteditor` repo; `sync_core.py` mirrors it into `lqa`.
"""
from core.mtpe.findings import Finding, SEVERITY_WEIGHT
from core.mtpe.analyze import analyze, AnalysisResult, AnalyzeOptions

__all__ = ["Finding", "SEVERITY_WEIGHT", "analyze", "AnalysisResult", "AnalyzeOptions"]
