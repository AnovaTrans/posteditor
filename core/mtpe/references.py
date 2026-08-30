"""Load the reference material a reviewer would consult: a TM (.tmx), a termbase
(.csv/.tbx) and a Do-Not-Translate list (.txt/.csv).

All parsing is defensive — real client files are messy and a bad reference must
never sink the run.
"""
import csv
import io
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from lxml import etree


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) and "}" in tag else (tag or "")


def _to_text(data: bytes) -> str:
    """Decode bytes, honouring the UTF-16 BOM memoQ loves to emit for TMX."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    # NUL-heavy content is UTF-16 without a BOM
    if data[:4096].count(0) > len(data[:4096]) // 4:
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="replace")


# --------------------------------------------------------------------------- TM
@dataclass
class TM:
    pairs: list = field(default_factory=list)      # [(source, target)]

    def __len__(self):
        return len(self.pairs)

    def best_match(self, source: str):
        """Return (tm_target, score 0-100) for the closest TM source, or None."""
        if not self.pairs or not source.strip():
            return None
        s = source.strip().lower()
        best_t, best_r = None, 0.0
        for src, tgt in self.pairs:
            r = SequenceMatcher(None, s, src.strip().lower()).ratio()
            if r > best_r:
                best_t, best_r = tgt, r
                if r == 1.0:
                    break
        return (best_t, round(best_r * 100, 1)) if best_t is not None else None


def load_tm(data: bytes) -> TM:
    text = _to_text(data)
    try:
        root = etree.fromstring(text.encode("utf-8"), etree.XMLParser(recover=True, huge_tree=True))
    except Exception:
        return TM()
    if root is None:                       # recover=True can yield None on bad input
        return TM()
    pairs = []
    for tu in root.iter():
        if _local(tu.tag) != "tu":
            continue
        segs = []
        for tuv in tu:
            if _local(tuv.tag) != "tuv":
                continue
            lang = (tuv.get("{http://www.w3.org/XML/1998/namespace}lang")
                    or tuv.get("lang") or "")
            seg = next((c for c in tuv.iter() if _local(c.tag) == "seg"), None)
            segs.append((lang, "".join(seg.itertext()).strip() if seg is not None else ""))
        if len(segs) >= 2 and segs[0][1] and segs[1][1]:
            pairs.append((segs[0][1], segs[1][1]))
    return TM(pairs)


# --------------------------------------------------------------------------- TB
@dataclass
class TB:
    pairs: list = field(default_factory=list)      # [(source_term, target_term)]

    def __len__(self):
        return len(self.pairs)

    def hits(self, segment_source: str):
        """Termbase entries whose source term occurs in the segment (whole word)."""
        low = segment_source.lower()
        out = []
        for s, t in self.pairs:
            if s and re.search(rf"(?<!\w){re.escape(s.lower())}(?!\w)", low):
                out.append((s, t))
                if len(out) >= 30:
                    break
        return out


def load_tb(data: bytes, filename: str = "") -> TB:
    if filename.lower().endswith(".tbx"):
        return _load_tbx(data)
    return _load_tb_csv(data)


def _load_tb_csv(data: bytes) -> TB:
    text = _to_text(data)
    sample = text[:2000]
    delim = ";" if sample.count(";") > sample.count(",") else ","
    if "\t" in sample and sample.count("\t") > sample.count(delim):
        delim = "\t"
    pairs = []
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = list(reader)
    start = 0
    if rows and any(h.lower() in ("source", "target", "en", "tr", "term") for h in rows[0][:2]):
        start = 1
    for row in rows[start:]:
        if len(row) >= 2 and row[0].strip() and row[1].strip():
            pairs.append((row[0].strip(), row[1].strip()))
    return TB(pairs)


def _load_tbx(data: bytes) -> TB:
    try:
        root = etree.fromstring(_to_text(data).encode("utf-8"),
                                etree.XMLParser(recover=True, huge_tree=True))
    except Exception:
        return TB()
    if root is None:
        return TB()
    pairs = []
    for entry in root.iter():
        if _local(entry.tag) not in ("termEntry", "conceptEntry"):
            continue
        terms = []
        for lang_set in entry:
            if _local(lang_set.tag) not in ("langSet", "langSec"):
                continue
            term = next((c for c in lang_set.iter() if _local(c.tag) == "term"), None)
            if term is not None:
                terms.append("".join(term.itertext()).strip())
        if len(terms) >= 2 and terms[0] and terms[1]:
            pairs.append((terms[0], terms[1]))
    return TB(pairs)


# -------------------------------------------------------------------------- DNT
def load_dnt(data: bytes) -> list:
    """Do-Not-Translate terms: one per line, or first column of a CSV."""
    text = _to_text(data)
    out = []
    for line in text.splitlines():
        term = line.split(",")[0].split(";")[0].strip().strip('"')
        if term and term.lower() not in ("term", "dnt", "do not translate"):
            out.append(term)
    return out


if __name__ == "__main__":
    tm = load_tm("""<?xml version="1.0"?><tmx><body>
      <tu><tuv xml:lang="en"><seg>car</seg></tuv><tuv xml:lang="tr"><seg>araba</seg></tuv></tu>
      </body></tmx>""".encode())
    assert len(tm) == 1 and tm.best_match("car")[1] == 100.0, tm.pairs
    tb = load_tb(b"source,target\ndriver,sofor\n", "t.csv")
    assert tb.hits("the driver") == [("driver", "sofor")], tb.pairs
    assert load_dnt(b"USTER STATISTICS\nAFIS\n") == ["USTER STATISTICS", "AFIS"]
    print("references.py OK")
