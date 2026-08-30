"""Reference-driven checks: TM consistency, termbase enforcement, DNT integrity.

Deterministic (no model): they compare the target against the supplied TM/TB/DNT.
"""
import re
from difflib import SequenceMatcher

from core.mtpe.findings import Finding, MAJOR, MINOR

TM_MATCH_MIN = 90.0        # only judge divergence when the TM source is a near match
TM_DIVERGE_MAX = 0.75      # target vs TM-target similarity below this → flag


def _f(seg, layer, cat, sev, msg, origin, suggestion=""):
    return Finding(seg.id, layer, cat, sev, msg, seg.source, seg.target, suggestion, origin)


def tm_findings(segments, tm):
    """Flag targets that diverge from a high-scoring TM match (possible regression)."""
    if not tm or not len(tm):
        return []
    out = []
    for seg in segments:
        if not seg.reviewable:
            continue
        m = tm.best_match(seg.source)
        if not m:
            continue
        tm_target, score = m
        if score < TM_MATCH_MIN:
            continue
        sim = SequenceMatcher(None, seg.target.strip().lower(), tm_target.strip().lower()).ratio()
        if sim < TM_DIVERGE_MAX:
            sev = MAJOR if score >= 99 else MINOR
            out.append(_f(seg, "tm", "tm_divergence", sev,
                          f"TM ({score}% match) suggests a different target.", "tm", tm_target))
    return out


def tb_findings(segments, tb):
    """Flag segments whose source contains a termbase term absent from the target."""
    if not tb or not len(tb):
        return []
    out = []
    for seg in segments:
        if not seg.reviewable:
            continue
        low_tgt = seg.target.lower()
        for src_term, tgt_term in tb.hits(seg.source):
            if tgt_term.lower() not in low_tgt:
                out.append(_f(seg, "tb", "termbase", MAJOR,
                              f"Termbase: '{src_term}' should be translated as '{tgt_term}'.", "tb",
                              tgt_term))
    return out


def dnt_findings(segments, dnt):
    """Flag DNT terms that appear in the source but are altered/missing in the target."""
    if not dnt:
        return []
    out = []
    for seg in segments:
        if not seg.reviewable:
            continue
        for term in dnt:
            if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", seg.source) and \
               not re.search(rf"(?<!\w){re.escape(term)}(?!\w)", seg.target):
                out.append(_f(seg, "dnt", "dnt_violation", MAJOR,
                              f"Do-Not-Translate term is missing/altered in the target: '{term}'.", "dnt", term))
    return out


def run(segments, tm=None, tb=None, dnt=None):
    return tm_findings(segments, tm) + tb_findings(segments, tb) + dnt_findings(segments, dnt)


if __name__ == "__main__":
    from types import SimpleNamespace as S
    from core.mtpe.references import TB
    seg = S(id="1", source="Turn on the pump.", target="Pompayi ac.", reviewable=True)
    out = tb_findings([seg], TB([("pump", "pompa")]))    # present → no flag
    assert out == [], out
    seg2 = S(id="2", source="Open USTER app.", target="USTER uygulamasini ac.", reviewable=True)
    assert dnt_findings([seg2], ["USTER"]) == []          # verbatim present → ok
    seg3 = S(id="3", source="Open USTER app.", target="Uster uygulamasini ac.", reviewable=True)
    assert len(dnt_findings([seg3], ["USTER"])) == 1      # case changed → flag
    print("refcheck.py OK")
