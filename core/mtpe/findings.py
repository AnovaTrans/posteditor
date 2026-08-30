"""The one currency both tools trade in: a Finding.

Every analysis layer (rules, TM, TB/DNT, LLM) emits Findings. The Post-Editor
renders them for human accept/reject; LQA scores them. Same objects, two uses.
"""
from dataclasses import dataclass, field, asdict

CRITICAL, MAJOR, MINOR = "critical", "major", "minor"
SEVERITY_WEIGHT = {CRITICAL: 10, MAJOR: 5, MINOR: 1}

# Layers a finding can come from (drives grouping in the UI).
LAYERS = ("accuracy", "fluency", "terminology", "style", "compliance", "tm", "tb", "dnt")


@dataclass
class Finding:
    segment_id: str
    layer: str                 # one of LAYERS
    category: str              # short code, e.g. "A-MEAN", "number_mismatch", "termbase"
    severity: str              # critical | major | minor
    message: str               # what is wrong (human readable)
    source: str = ""
    target: str = ""
    suggestion: str = ""       # proposed fix for THIS finding (may be empty)
    origin: str = "rule"       # "rule" | "tm" | "tb" | "dnt" | "llm"

    @property
    def weight(self) -> int:
        return SEVERITY_WEIGHT.get(self.severity, 1)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["weight"] = self.weight
        return d
