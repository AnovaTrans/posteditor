"""LLM spelling + grammar pass for the target language (memoQ 3161/3162).

Multilingual by design: one model handles any target language, so no per-language
dictionary is bundled (which would be locale-specific and heavy on Streamlit Cloud).
Deliberately conservative — it flags only genuine spelling/grammar errors, never
restyles, and it leaves termbase/DNT terms alone to avoid false positives on proper
nouns and technical terms. Corrections are suggestions; nothing is auto-applied.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.mtpe.findings import Finding, MAJOR, MINOR

BATCH = 15
DEFAULT_WORKERS = 6
MAX_TOKENS = 3000

SYSTEM = """You are a strict proofreader checking spelling and grammar in the \
TARGET language of already-translated segments. For each segment, report ONLY:
- spelling mistakes (typos, wrong letters, misspelled words), and
- grammar mistakes (agreement, inflection, wrong verb form, word that is clearly wrong).
Do NOT restyle, rephrase, or change wording that is already correct. Do NOT flag \
proper nouns, brand/product names, technical terms, or any term listed under \
[KEEP: ...] — treat those as correct. If you are not sure something is a real \
error, do NOT flag it (favour precision over recall).
Return ONLY JSON, messages in English:
{"segments":[{"id":"<id>","errors":[{"type":"spelling","wrong":"<the wrong text>","correction":"<fix>","message":"<short reason in English>"}]}]}
A segment with no error returns "errors": []."""


def check(segments, llm, *, protected_terms=None, workers=DEFAULT_WORKERS, progress=None):
    """Return a flat list[Finding] of spelling/grammar issues for reviewable segments."""
    review = [s for s in segments if s.reviewable]
    by_id = {s.id: s for s in review}
    keep = sorted({t for t in (protected_terms or []) if t})[:200]
    batches = [review[i:i + BATCH] for i in range(0, len(review), BATCH)]
    findings: list[Finding] = []
    total = len(batches)
    done = 0
    if progress:
        progress(0, total)

    def user_block(batch):
        lines = []
        if keep:
            lines.append("[KEEP: " + " | ".join(keep) + "]")
        lines.append("Segments:")
        for seg in batch:
            lines.append(f"[id {seg.id}] {seg.target}")
        lines.append('\nReturn the JSON described in the system message.')
        return "\n".join(lines)

    def absorb(rows):
        for row in rows:
            sid = str(row.get("id", ""))
            seg = by_id.get(sid)
            if seg is None:
                continue
            for err in row.get("errors", []) or []:
                etype = (err.get("type") or "spelling").lower()
                findings.append(Finding(
                    segment_id=sid, layer="fluency",
                    category="spelling" if "spell" in etype else "grammar",
                    severity=MINOR if "spell" in etype else MAJOR,
                    message=err.get("message") or f"{etype}: '{err.get('wrong','')}'",
                    source=seg.source, target=seg.target,
                    suggestion=err.get("correction") or "", origin="llm"))

    if not batches:
        return findings
    with ThreadPoolExecutor(max_workers=max(1, min(workers, total))) as pool:
        futures = [pool.submit(lambda b: llm.complete_json(SYSTEM, user_block(b), max_tokens=MAX_TOKENS).get("segments", []), b)
                   for b in batches]
        for fut in as_completed(futures):
            try:
                absorb(fut.result())
            except Exception as exc:
                print(f"[spellcheck] batch failed: {exc}")
            done += 1
            if progress:
                progress(done, total)
    return findings
