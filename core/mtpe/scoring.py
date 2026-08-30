"""LQA scoring from Findings (MQM-aligned, Anova LQA sheet grades).

penalty = critical*10 + major*5 + minor*1
LQA score per 1000 words = penalty * 1000 / words   (lower is better)
"""
from collections import Counter

from core.mtpe.findings import SEVERITY_WEIGHT, CRITICAL, MAJOR, MINOR

# (upper bound inclusive, grade) on the per-1000-word score
GRADES = [(1, "Excellent"), (3, "Good"), (5, "Fair"), (9, "Poor"), (float("inf"), "Bad")]


def grade_for(score: float) -> str:
    for upper, label in GRADES:
        if score <= upper:
            return label
    return "Bad"


def score(findings, words: int) -> dict:
    penalty = sum(SEVERITY_WEIGHT.get(f.severity, 1) for f in findings)
    per_1000 = round(penalty * 1000 / words, 2) if words else 0.0
    by_severity = Counter(f.severity for f in findings)
    by_category = Counter(f.category for f in findings)
    by_layer = Counter(f.layer for f in findings)
    seg_penalty: dict = {}
    for f in findings:
        seg_penalty[f.segment_id] = seg_penalty.get(f.segment_id, 0) + SEVERITY_WEIGHT.get(f.severity, 1)
    return {
        "words": words,
        "total_findings": len(findings),
        "penalty": penalty,
        "lqa_score": per_1000,
        "grade": grade_for(per_1000),
        "critical": by_severity.get(CRITICAL, 0),
        "major": by_severity.get(MAJOR, 0),
        "minor": by_severity.get(MINOR, 0),
        "flagged_segments": len(seg_penalty),
        "by_category": dict(by_category),
        "by_layer": dict(by_layer),
        "segment_penalty": seg_penalty,
    }


if __name__ == "__main__":
    from core.mtpe.findings import Finding
    fs = [Finding("1", "accuracy", "A-MEAN", MAJOR, "x"),
          Finding("1", "compliance", "double_space", MINOR, "y"),
          Finding("2", "accuracy", "empty", CRITICAL, "z")]
    r = score(fs, words=100)
    assert r["penalty"] == 5 + 1 + 10 and r["lqa_score"] == 160.0, r
    assert r["grade"] == "Bad" and r["flagged_segments"] == 2, r
    print("scoring.py OK", {k: r[k] for k in ("penalty", "lqa_score", "grade")})
