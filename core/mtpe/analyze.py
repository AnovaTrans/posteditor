"""Orchestrator: run every enabled layer over a parsed document and return one
merged view. Both tools call this; they only differ in what they do with it.

Layers:
  * rules   — deterministic per-segment + inconsistency checks
  * refcheck — TM divergence, termbase enforcement, DNT integrity
  * llm     — full MTPE proofread (errors + a proposed corrected target)  [optional]
"""
from dataclasses import dataclass, field

from core.mtpe import rules, refcheck, llm_analyze, scoring
from core.mtpe.findings import Finding


@dataclass
class AnalyzeOptions:
    target_lang: str = ""
    instructions: str = ""
    turkish: bool = False          # enable Turkish MT/terminology pattern pack
    use_llm: bool = True
    workers: int = 6


@dataclass
class SegmentView:
    segment: object
    findings: list = field(default_factory=list)
    proposed: str = ""             # LLM-improved target (empty = no change proposed)

    @property
    def penalty(self) -> int:
        return sum(f.weight for f in self.findings)

    @property
    def changed(self) -> bool:
        return bool(self.proposed) and self.proposed != self.segment.target


@dataclass
class AnalysisResult:
    doc: object
    findings: list                 # flat list[Finding], all layers
    views: list                    # list[SegmentView] for reviewable segments (in file order)

    def score(self) -> dict:
        return scoring.score(self.findings, self.doc.total_words)

    def flagged(self):
        return [v for v in self.views if v.findings]


def analyze(doc, options: AnalyzeOptions, *, llm=None, tm=None, tb=None, dnt=None,
            progress=None) -> AnalysisResult:
    segments = doc.segments

    findings: list[Finding] = []
    findings += rules.run(segments, turkish=options.turkish)
    findings += refcheck.run(segments, tm=tm, tb=tb, dnt=dnt)

    llm_map: dict = {}
    if options.use_llm and llm is not None:
        llm_map = llm_analyze.analyze(
            segments, llm, target_lang=options.target_lang,
            instructions=options.instructions, tb=tb, dnt=dnt,
            workers=options.workers, progress=progress)
        for entry in llm_map.values():
            findings += entry["findings"]

    # Merge into per-segment views (only reviewable segments carry findings).
    by_seg: dict = {}
    for f in findings:
        by_seg.setdefault(f.segment_id, []).append(f)
    views = []
    for seg in segments:
        if not seg.reviewable:
            continue
        entry = llm_map.get(seg.id, {})
        proposed = entry.get("corrected", "") or ""
        seg_findings = by_seg.get(seg.id, [])
        if seg_findings or (proposed and proposed != seg.target):
            views.append(SegmentView(seg, seg_findings, proposed))
    # order findings for stable display
    order = {"critical": 0, "major": 1, "minor": 2}
    findings.sort(key=lambda f: (str(f.segment_id), order.get(f.severity, 9)))
    return AnalysisResult(doc=doc, findings=findings, views=views)
