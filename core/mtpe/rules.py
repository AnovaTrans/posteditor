"""Deterministic checks — no model, no cost. Merges the portal QA rules with the
MTPE minor-sweep. Language-generic core + an optional Turkish pattern pack.

Every rule yields Findings, so rule hits and LLM hits live in one list.
"""
import re

from core.mtpe.findings import Finding, CRITICAL, MAJOR, MINOR

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_PLACEHOLDER = re.compile(r"%[sd]|%\d+\$[sd]|\{[^{}]*\}|\$\{[^}]*\}")
_TAG = re.compile(r"<[^>]+>|\{\d+\}|\[[a-z]+\]")
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)
_PCT_AFTER = re.compile(r"(?<![%])\b(\d[\d.,]*)\s*%")
_DECIMAL = re.compile(r"\b(\d+)\.(\d+)\s*(inç|mm|cm|m|kg|g|dtex|den)\b")
_PVALUE = re.compile(r"\bP0[.,]\d+\b")            # statistical p-value → not a decimal

# Turkish MT/terminology patterns: (regex, message, suggestion). Kept small and
# generic; project-specific packs (e.g. Uster textile) can extend this list.
_TR_PATTERNS = [
    (re.compile(r"lütfen\s+not\s+edin\s+ki", re.I), "MT kalıbı: 'lütfen not edin ki'", "'Dikkat:' / 'Not:'"),
    (re.compile(r"olduğundan\s+emin\s+olun", re.I), "MT kalıbı: 'olduğundan emin olun'", "'kontrol edin' / 'doğrulayın'"),
    (re.compile(r"yapılması\s+gerekmektedir", re.I), "MT kalıbı: 'yapılması gerekmektedir'", "'yapın' / 'yapılmalı'"),
    (re.compile(r"hesaba\s+katılmalıdır", re.I), "MT kalıbı: 'hesaba katılmalıdır'", "'göz önünde bulundurun'"),
    (re.compile(r"söz\s+konusu\s+\w+", re.I), "MT kalıbı: 'söz konusu [isim]'", "'bu [isim]'"),
    (re.compile(r"\s+&\s+"), "Format: '&' sembolü", "'ve' kullanın"),
]


def _f(seg, layer, cat, sev, msg, suggestion=""):
    return Finding(seg.id, layer, cat, sev, msg, seg.source, seg.target, suggestion, "rule")


def check_segment(seg, turkish: bool = False):
    """All deterministic findings for one segment."""
    out = []
    src, tgt = seg.source or "", seg.target or ""
    if not tgt.strip():
        return [_f(seg, "accuracy", "empty_target", CRITICAL, "Hedef boş.")]

    if src.strip() and tgt.strip() == src.strip() and _HAS_LETTER.search(src):
        out.append(_f(seg, "accuracy", "untranslated", MAJOR, "Hedef kaynakla birebir aynı (çevrilmemiş)."))

    if sorted(_NUMBER.findall(src)) != sorted(_NUMBER.findall(tgt)):
        out.append(_f(seg, "accuracy", "number_mismatch", MAJOR,
                      f"Sayılar farklı: kaynak {_NUMBER.findall(src) or '—'} / hedef {_NUMBER.findall(tgt) or '—'}."))

    if sorted(_PLACEHOLDER.findall(src)) != sorted(_PLACEHOLDER.findall(tgt)):
        out.append(_f(seg, "compliance", "placeholder_mismatch", CRITICAL, "Placeholder'lar kaynak/hedef arasında farklı."))

    if len(_TAG.findall(src)) != len(_TAG.findall(tgt)):
        out.append(_f(seg, "compliance", "tag_mismatch", MAJOR, "Inline tag sayısı kaynak/hedef arasında farklı."))

    if "  " in tgt:
        out.append(_f(seg, "compliance", "double_space", MINOR, "Çift boşluk.", re.sub(r" +", " ", tgt)))
    if tgt != tgt.strip():
        out.append(_f(seg, "compliance", "trailing_space", MINOR, "Baş/son boşluk.", tgt.strip()))

    words = [w.lower() for w in _WORD.findall(tgt)]
    for a, b in zip(words, words[1:]):
        if a == b and len(a) > 2:
            out.append(_f(seg, "fluency", "repeated_word", MINOR, f"Tekrarlayan kelime: '{a}'."))
            break

    s_len, t_len = len(src.strip()), len(tgt.strip())
    if s_len >= 15 and (t_len > s_len * 3 or t_len < s_len / 3):
        out.append(_f(seg, "compliance", "length_anomaly", MINOR,
                      f"Hedef uzunluğu ({t_len}) kaynaktan ({s_len}) çok uzak."))

    src_end = src.rstrip()[-1:] or ""
    tgt_end = tgt.rstrip()[-1:] or ""
    if src_end in (":", "?") and tgt_end not in (":", "?"):
        out.append(_f(seg, "compliance", "punctuation", MINOR,
                      f"Kaynak '{src_end}' ile bitiyor, hedef '{tgt_end}'.", tgt.rstrip() + src_end))

    m = _PCT_AFTER.search(tgt)
    if m and not _PVALUE.search(tgt):
        num = m.group(1).replace(".", ",")
        out.append(_f(seg, "compliance", "percent_position", MINOR,
                      f"% rakamdan sonra: '{m.group(0).strip()}'.", f"%{num}"))

    m = _DECIMAL.search(tgt)
    if m and not _PVALUE.search(tgt):
        out.append(_f(seg, "compliance", "decimal_separator", MINOR,
                      f"Ondalık ayracı nokta: '{m.group(0)}'.", m.group(0).replace(".", ",")))

    if turkish:
        for pat, msg, sug in _TR_PATTERNS:
            if pat.search(tgt):
                out.append(_f(seg, "fluency", "mt_pattern", MINOR, msg, sug))

    return out


def check_inconsistency(segments):
    """Same source translated differently across the file (deterministic)."""
    by_source: dict = {}
    for s in segments:
        if s.source.strip() and s.target.strip():
            by_source.setdefault(s.source.strip().lower(), set()).add(s.target.strip())
    out = []
    for s in segments:
        variants = by_source.get(s.source.strip().lower())
        if variants and len(variants) > 1:
            out.append(_f(s, "terminology", "inconsistency", MAJOR,
                          "Aynı kaynak dosya içinde tutarsız çevrilmiş."))
    return out


def run(segments, turkish: bool = False):
    out = []
    for s in segments:
        if s.reviewable:
            out.extend(check_segment(s, turkish))
    out.extend(check_inconsistency([s for s in segments if s.reviewable]))
    return out


if __name__ == "__main__":
    from types import SimpleNamespace as S
    seg = S(id="1", source="It is 24 hours: ok?", target="42  saat  ok",
            reviewable=True)
    codes = {f.category for f in check_segment(seg)}
    assert "number_mismatch" in codes and "double_space" in codes and "punctuation" in codes, codes
    print("rules.py OK", sorted(codes))
