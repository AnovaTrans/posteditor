"""Deterministic checks — no model, no cost. Language-agnostic: only universal
checks that hold for any target language (numbers, placeholders, tags, spacing,
repetition, length, punctuation parity, untranslated). Locale- and
language-specific judgements are left to the LLM layer, which knows the target
language.

Every rule yields Findings, so rule hits and LLM hits live in one list.
"""
import re

from core.mtpe.findings import Finding, CRITICAL, MAJOR, MINOR

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_PLACEHOLDER = re.compile(r"%[sd]|%\d+\$[sd]|\{[^{}]*\}|\$\{[^}]*\}")
_TAG = re.compile(r"<[^>]+>|\{\d+\}|\[[a-z]+\]")
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)


def _f(seg, layer, cat, sev, msg, suggestion=""):
    return Finding(seg.id, layer, cat, sev, msg, seg.source, seg.target, suggestion, "rule")


def check_segment(seg):
    """All deterministic findings for one segment."""
    out = []
    src, tgt = seg.source or "", seg.target or ""
    if not tgt.strip():
        return [_f(seg, "accuracy", "empty_target", CRITICAL, "Target is empty.")]

    if src.strip() and tgt.strip() == src.strip() and _HAS_LETTER.search(src):
        out.append(_f(seg, "accuracy", "untranslated", MAJOR, "Target is identical to the source (untranslated)."))

    if sorted(_NUMBER.findall(src)) != sorted(_NUMBER.findall(tgt)):
        out.append(_f(seg, "accuracy", "number_mismatch", MAJOR,
                      f"Numbers differ: source {_NUMBER.findall(src) or '—'} vs target {_NUMBER.findall(tgt) or '—'}."))

    if sorted(_PLACEHOLDER.findall(src)) != sorted(_PLACEHOLDER.findall(tgt)):
        out.append(_f(seg, "compliance", "placeholder_mismatch", CRITICAL, "Placeholders differ between source and target."))

    if len(_TAG.findall(src)) != len(_TAG.findall(tgt)):
        out.append(_f(seg, "compliance", "tag_mismatch", MAJOR, "Inline tag count differs between source and target."))

    if "  " in tgt:
        out.append(_f(seg, "compliance", "double_space", MINOR, "Target contains a double space.", re.sub(r" +", " ", tgt)))
    if tgt != tgt.strip():
        out.append(_f(seg, "compliance", "trailing_space", MINOR, "Target has leading or trailing whitespace.", tgt.strip()))

    words = [w.lower() for w in _WORD.findall(tgt)]
    for a, b in zip(words, words[1:]):
        if a == b and len(a) > 2:
            out.append(_f(seg, "fluency", "repeated_word", MINOR, f"Repeated word '{a}' in the target."))
            break

    s_len, t_len = len(src.strip()), len(tgt.strip())
    if s_len >= 15 and (t_len > s_len * 3 or t_len < s_len / 3):
        out.append(_f(seg, "compliance", "length_anomaly", MINOR,
                      f"Target length ({t_len}) is far from the source ({s_len})."))

    src_end = src.rstrip()[-1:] or ""
    tgt_end = tgt.rstrip()[-1:] or ""
    if src_end in (":", "?", "!") and tgt_end not in (":", "?", "!"):
        out.append(_f(seg, "compliance", "punctuation", MINOR,
                      f"Source ends with '{src_end}' but target ends with '{tgt_end}'.", tgt.rstrip() + src_end))

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
                          "Same source is translated inconsistently across segments."))
    return out


def run(segments):
    out = []
    for s in segments:
        if s.reviewable:
            out.extend(check_segment(s))
    out.extend(check_inconsistency([s for s in segments if s.reviewable]))
    return out


if __name__ == "__main__":
    from types import SimpleNamespace as S
    seg = S(id="1", source="It is 24 hours: ok?", target="42  hours ok",
            reviewable=True)
    codes = {f.category for f in check_segment(seg)}
    assert "number_mismatch" in codes and "double_space" in codes and "punctuation" in codes, codes
    print("rules.py OK", sorted(codes))
