"""Engine tests — no network, no API key (LLM layer off)."""
from core.mtpe import parse, references
from core.mtpe.analyze import analyze, AnalyzeOptions

MQXLIFF = b"""<?xml version="1.0" encoding="utf-8"?>
<xliff version="1.2" xmlns:mq="http://www.memoq.com/2015/xliff/mq">
<file source-language="en" target-language="tr"><body>
<trans-unit id="1"><source>There are 24 hours.</source><target>42 saat vardir.</target>
  <mq:insertedmatch><target>ESKI TM HEDEFI</target></mq:insertedmatch></trans-unit>
<trans-unit id="2"><source>Turn on the pump.</source><target>Pompayi  ac</target></trans-unit>
<trans-unit id="3"><source>Open USTER app.</source><target>Uster uygulamasini ac.</target></trans-unit>
</body></file></xliff>"""


def _load():
    return parse.load(MQXLIFF, "job.mqxliff")


def test_real_target_not_tm_reference():
    doc = _load()
    assert doc.fmt == "mxliff"
    assert doc.segments[0].target == "42 saat vardir."     # not "ESKI TM HEDEFI"


def test_rules_flag_number_and_spacing():
    doc = _load()
    res = analyze(doc, AnalyzeOptions(use_llm=False))
    cats = {f.category for f in res.findings}
    assert "number_mismatch" in cats          # 24 vs 42
    assert "double_space" in cats             # "Pompayi  ac"


def test_dnt_and_tb_and_score():
    doc = _load()
    tb = references.TB([("pump", "pompa")])
    dnt = ["USTER"]
    res = analyze(doc, AnalyzeOptions(use_llm=False), tb=tb, dnt=dnt)
    cats = {f.category for f in res.findings}
    assert "dnt_violation" in cats            # Uster != USTER
    sc = res.score()
    assert sc["penalty"] > 0 and sc["grade"] in ("Excellent", "Good", "Fair", "Poor", "Bad")


def test_apply_preserves_tm_reference():
    doc = _load()
    doc.set_target(doc.segments[0], "24 saat vardir.")
    out = doc.to_bytes()
    assert b"24 saat" in out and b"ESKI TM HEDEFI" in out   # real changed, TM untouched
