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
_TAGMARK = re.compile(r"\[[a-z]+\]")     # placeholder markers the parser renders, e.g. [ph] [x]
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_HAS_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)


def _prose(text: str) -> str:
    """Text with placeholder markers removed — the real, translatable words only.
    Keeps letter-based checks from tripping on synthetic tag renders like [ph]."""
    return _TAGMARK.sub(" ", text or "")


def _f(seg, layer, cat, sev, msg, suggestion=""):
    return Finding(seg.id, layer, cat, sev, msg, seg.source, seg.target, suggestion, "rule")


def check_segment(seg):
    """All deterministic findings for one segment."""
    out = []
    src, tgt = seg.source or "", seg.target or ""
    if not tgt.strip():
        return [_f(seg, "accuracy", "empty_target", CRITICAL, "Target is empty.")]

    src_prose, tgt_prose = _prose(src), _prose(tgt)
    if src_prose.strip() and tgt_prose.strip() == src_prose.strip() and _HAS_LETTER.search(src_prose):
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

    # First-letter capitalization parity (memoQ 3030). Cased scripts only —
    # for uncased scripts .isupper() is False on both sides, so no false flag.
    # Use prose so a leading [ph] tag doesn't supply the "first letter".
    sc = next((c for c in src_prose if c.isalpha()), "")
    tc = next((c for c in tgt_prose if c.isalpha()), "")
    if sc and tc and sc.isupper() != tc.isupper():
        out.append(_f(seg, "compliance", "capitalization", MINOR,
                      "First letter capitalization differs between source and target."))

    # Bracket balance + count parity (memoQ 3086-3089). Brackets are universal;
    # quotes are locale-specific and left to the LLM layer.
    for open_ch, close_ch, name in (("(", ")", "()"), ("[", "]", "[]"), ("{", "}", "{}")):
        t_open, t_close = tgt.count(open_ch), tgt.count(close_ch)
        if t_open != t_close:
            out.append(_f(seg, "compliance", "unbalanced_bracket", MAJOR,
                          f"Unbalanced '{name}' in the target ({t_open} open, {t_close} close)."))
        elif (src.count(open_ch) != t_open) or (src.count(close_ch) != t_close):
            out.append(_f(seg, "compliance", "bracket_mismatch", MINOR,
                          f"'{name}' count differs between source and target."))

    return out


def check_inconsistency(segments):
    """Inconsistent translations across the file (memoQ 3100 + 3101)."""
    by_source: dict = {}
    by_target: dict = {}
    for s in segments:
        if s.source.strip() and s.target.strip():
            by_source.setdefault(s.source.strip().lower(), set()).add(s.target.strip())
            by_target.setdefault(s.target.strip().lower(), set()).add(s.source.strip())
    out = []
    for s in segments:
        if by_source.get(s.source.strip().lower(), set()).__len__() > 1:
            out.append(_f(s, "terminology", "inconsistency", MAJOR,
                          "Same source is translated inconsistently across segments."))
        elif by_target.get(s.target.strip().lower(), set()).__len__() > 1:
            out.append(_f(s, "terminology", "inconsistency_target", MINOR,
                          "Same target is used for different sources across segments."))
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
