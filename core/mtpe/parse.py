"""Editable XLIFF document — parse, expose segments, write corrected targets back.

Supports XLIFF 1.2/2.0, memoQ (.mxliff/.mqxliff) and SDL Trados (.sdlxliff).

CRITICAL (memoQ): a trans-unit carries the real <target> as a *direct* child and
often a second <target> buried inside <mq:insertedmatch> — the old TM record.
We only ever read/write the direct child. Iterating direct children (never a
recursive search) is what keeps the TM reference untouched.

Uses lxml so namespaces/prefixes survive a round-trip; write-back sets the target
element's text.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from lxml import etree


def _local(tag) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _text(el) -> str:
    """Readable text of an element: inline tags become [ph]/<tag> placeholders."""
    if el is None:
        return ""
    parts = [el.text or ""]
    for child in el:
        ln = _local(child.tag).lower()
        if ln in ("ph", "x"):
            parts.append(f"[{child.get('ctype') or child.get('type') or 'ph'}]")
        elif ln in ("bpt", "ept", "it", "g", "mrk"):
            parts.append(_text(child))          # keep nested text (mrk especially)
        else:
            parts.append(child.text or "")
        parts.append(child.tail or "")
    return "".join(parts).strip()


def _has_tags(el) -> bool:
    return el is not None and any(
        _local(c.tag).lower() in {"ph", "bpt", "ept", "it", "g", "x"} for c in el)


def _direct(el, name):
    """First DIRECT child with the given local name (never recurses)."""
    if el is None:
        return None
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


@dataclass
class Segment:
    id: str
    source: str
    target: str
    status: str            # translated | untranslated | final
    locked: bool
    has_tags: bool
    source_words: int
    _target_el: object = field(default=None, repr=False)

    @property
    def reviewable(self) -> bool:
        return not self.locked and self.status != "final" and bool(self.target.strip())


class XliffDoc:
    def __init__(self, data: bytes, filename: str = ""):
        self.filename = filename
        # recover=True: real-world CAT files are occasionally slightly malformed
        self._tree = etree.fromstring(data, etree.XMLParser(recover=True, huge_tree=True))
        if self._tree is None:
            raise ValueError("Could not parse the file as XLIFF — it may be empty or not a bilingual XML file.")
        self.fmt = self._detect()
        self.source_lang, self.target_lang = self._langs()
        self.segments: list[Segment] = []
        self._parse()

    # ---- detection -------------------------------------------------------
    def _detect(self) -> str:
        name = (self.filename or "").lower()
        if name.endswith((".mxliff", ".mqxliff")):
            return "mxliff"
        if name.endswith(".sdlxliff"):
            return "sdlxliff"
        nsmap = {v for v in (self._tree.nsmap or {}).values()}
        if any("memoq" in u for u in nsmap):
            return "mxliff"
        if any("sdl.com" in u for u in nsmap):
            return "sdlxliff"
        if any("xliff:document:2" in u for u in nsmap):
            return "xliff2"
        return "xliff1"

    def _langs(self):
        root = self._tree
        s = root.get("srcLang") or root.get("source-language")
        t = root.get("trgLang") or root.get("target-language")
        if not s or not t:
            for el in root.iter():
                if _local(el.tag) == "file":
                    s = s or el.get("source-language") or el.get("srcLang")
                    t = t or el.get("target-language") or el.get("trgLang")
                    break
        return (s or "").strip(), (t or "").strip()

    # ---- parsing ---------------------------------------------------------
    def _parse(self):
        if self.fmt == "xliff2":
            self._parse_xliff2()
        elif self.fmt == "sdlxliff":
            self._parse_sdl()
        else:
            self._parse_units()          # xliff1 + mxliff share the trans-unit shape

    def _parse_units(self):
        n = 0
        for tu in self._tree.iter():
            if _local(tu.tag) != "trans-unit":
                continue
            n += 1
            src = _direct(tu, "source")
            tgt = _direct(tu, "target")          # DIRECT child only → real target
            locked = (tu.get("translate", "yes").lower() == "no")
            source_text, target_text = _text(src), _text(tgt)
            status = "translated" if target_text else "untranslated"
            state = (tgt.get("state") if tgt is not None else "") or ""
            if state in ("final", "signed-off", "confirmed"):
                status = "final"
            self.segments.append(Segment(
                id=tu.get("id") or str(n), source=source_text, target=target_text,
                status=status, locked=locked, has_tags=_has_tags(src),
                source_words=len(source_text.split()), _target_el=tgt))

    def _parse_xliff2(self):
        n = 0
        for seg in self._tree.iter():
            if _local(seg.tag) != "segment":
                continue
            n += 1
            src = _direct(seg, "source")
            tgt = _direct(seg, "target")
            source_text, target_text = _text(src), _text(tgt)
            state = seg.get("state", "")
            status = "final" if state == "final" else ("translated" if target_text else "untranslated")
            self.segments.append(Segment(
                id=seg.get("id") or str(n), source=source_text, target=target_text,
                status=status, locked=(state == "final"), has_tags=_has_tags(src),
                source_words=len(source_text.split()), _target_el=tgt))

    def _parse_sdl(self):
        sdl = "http://sdl.com/FileTypes/SdlXliff/1.0"
        conf = {}
        for el in self._tree.iter():
            if _local(el.tag) == "seg-def" or el.tag == f"{{{sdl}}}seg-def":
                if el.get("id"):
                    conf[el.get("id")] = (el.get("conf", ""), el.get("locked", "false").lower() == "true")
        n = 0
        for tu in self._tree.iter():
            if _local(tu.tag) != "trans-unit":
                continue
            src = _direct(tu, "source")
            tgt = _direct(tu, "target")
            if src is None:
                continue
            src_mrks = [c for c in src.iter() if _local(c.tag) == "mrk" and c.get("mtype") == "seg"]
            tgt_mrks = [c for c in (tgt.iter() if tgt is not None else []) if _local(c.tag) == "mrk" and c.get("mtype") == "seg"]
            if not src_mrks:                     # whole trans-unit as one segment
                self._add_sdl(tu.get("id") or str(n), _text(src), _text(tgt), tgt, conf)
                n += 1
                continue
            tgt_by_mid = {m.get("mid"): m for m in tgt_mrks}
            for sm in src_mrks:
                mid = sm.get("mid") or str(n)
                tm = tgt_by_mid.get(mid)
                self._add_sdl(mid, _text(sm), _text(tm), tm, conf)
                n += 1

    def _add_sdl(self, sid, source_text, target_text, tgt_el, conf):
        c, locked = conf.get(sid, ("", False))
        status = "final" if c in ("Translated", "ApprovedSignOff", "ApprovedTranslation") else (
            "translated" if target_text else "untranslated")
        self.segments.append(Segment(
            id=sid, source=source_text, target=target_text, status=status,
            locked=locked, has_tags=False, source_words=len(source_text.split()),
            _target_el=tgt_el))

    # ---- write-back ------------------------------------------------------
    def set_target(self, seg: Segment, text: str) -> bool:
        """Replace a segment's target text. Returns False if it could not be applied.

        ponytail: collapses inline tags in the target (clears children) — fine for
        prose MTPE; upgrade to a tag-preserving merge if tagged targets need editing.
        """
        el = seg._target_el
        if el is None:
            return False
        for child in list(el):
            el.remove(child)
        el.text = text
        seg.target = text
        return True

    def to_bytes(self) -> bytes:
        return etree.tostring(self._tree, xml_declaration=True, encoding="UTF-8")

    # ---- stats -----------------------------------------------------------
    @property
    def total_words(self) -> int:
        return sum(s.source_words for s in self.segments)

    def stats(self) -> dict:
        return {
            "file_name": self.filename, "format": self.fmt,
            "source_lang": self.source_lang, "target_lang": self.target_lang,
            "total": len(self.segments),
            "translated": sum(1 for s in self.segments if s.target),
            "locked": sum(1 for s in self.segments if s.locked),
            "final": sum(1 for s in self.segments if s.status == "final"),
            "reviewable": sum(1 for s in self.segments if s.reviewable),
            "words": self.total_words,
        }


def load(data: bytes, filename: str = "") -> XliffDoc:
    return XliffDoc(data, filename)


if __name__ == "__main__":            # tiny self-check
    sample = b"""<?xml version="1.0"?>
<xliff version="1.2"><file source-language="en" target-language="tr"><body>
<trans-unit id="1"><source>Click OK.</source><target>Tamam'a tikla.</target></trans-unit>
<trans-unit id="2"><source>There are 24 hours.</source>
  <target>42 saat vardir.</target>
  <mq:insertedmatch xmlns:mq="http://www.memoq.com/2015/xliff/mq"><target>ESKI TM</target></mq:insertedmatch>
</trans-unit></body></file></xliff>"""
    d = load(sample, "t.xliff")
    assert len(d.segments) == 2, d.stats()
    # the TM reference target must NOT be picked up
    assert d.segments[1].target == "42 saat vardir.", d.segments[1].target
    assert d.set_target(d.segments[1], "24 saat vardir.")
    assert b"24 saat" in d.to_bytes() and b"ESKI TM" in d.to_bytes()  # real changed, TM intact
    print("parse.py OK", d.stats())
