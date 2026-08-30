"""LLM layer: full MTPE proofread of each translated segment.

Per segment the model returns an improved target (`corrected`) AND a list of the
errors it fixed, tagged by MQM category + LQA severity. The Post-Editor applies
`corrected`; LQA scores the errors. Segments are batched to cut request count and
run through a bounded thread pool.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed

from core.mtpe.findings import Finding, CRITICAL, MAJOR, MINOR

BATCH = 12
DEFAULT_WORKERS = 6
MAX_TOKENS = 4000

_CAT2LAYER = {
    "accuracy": "accuracy", "fluency": "fluency", "terminology": "terminology",
    "style": "style", "compliance": "compliance",
}
_SEV = {"critical": CRITICAL, "major": MAJOR, "minor": MINOR}

SYSTEM = """You are a professional translation post-editor working to ISO 18587 \
full post-editing quality. You are given source segments and their machine/human \
translations in the target language. For EACH segment:
1. Judge accuracy (meaning, omissions, additions, numbers, untranslated text, \
hallucination), fluency (grammar, word order, naturalness, MT-isms), terminology \
(domain terms, internal consistency), style (register/tone) and compliance \
(tags, punctuation, capitalisation, spacing).
2. Produce an improved target ONLY if a change is warranted; otherwise repeat the \
target unchanged. Change nothing needlessly. Preserve numbers, placeholders and \
inline tags exactly. Honour any [TERM: source -> target] and [DNT: term] entries.
3. List each real error you found, with an MQM category and an LQA severity.

Categories: accuracy | fluency | terminology | style | compliance.
Severity: critical (meaning-inverting, safety/legal, wrong translation) | \
major (seriously hurts readability, banned terminology, big grammar error) | \
minor (spelling, punctuation, small fluency/style).

Return ONLY JSON, no prose:
{"segments":[{"id":"<id>","corrected":"<improved target>","errors":[{"category":"fluency","code":"L-MT","severity":"minor","message":"<short reason in the target language>"}]}]}
If a segment has no error, return its "errors" as [] and "corrected" equal to the target."""


def _user_block(batch, target_lang, instructions, tb, dnt):
    lines = [f"Target language: {target_lang or 'unknown'}"]
    if instructions:
        lines.append(f"Project instructions: {instructions}")
    lines.append("\nSegments:")
    for seg in batch:
        lines.append(f"\n[id {seg.id}]")
        lines.append(f"Source: {seg.source}")
        lines.append(f"Translation: {seg.target}")
        if tb:
            for s, t in tb.hits(seg.source):
                lines.append(f"[TERM: {s} -> {t}]")
        if dnt:
            for term in dnt:
                if term in seg.source:
                    lines.append(f"[DNT: {term}]")
    lines.append('\nReturn the JSON described in the system message.')
    return "\n".join(lines)


def analyze(segments, llm, *, target_lang="", instructions="", tb=None, dnt=None,
            workers=DEFAULT_WORKERS, progress=None):
    """Return {seg_id: {"corrected": str, "findings": [Finding]}} for reviewable segments."""
    review = [s for s in segments if s.reviewable]
    by_id = {s.id: s for s in review}
    batches = [review[i:i + BATCH] for i in range(0, len(review), BATCH)]
    result: dict = {}
    total = len(batches)
    done = 0
    if progress:
        progress(0, total)

    def call(batch):
        user = _user_block(batch, target_lang, instructions, tb, dnt)
        data = llm.complete_json(SYSTEM, user, max_tokens=MAX_TOKENS)
        return data.get("segments", [])

    def absorb(rows):
        for row in rows:
            sid = str(row.get("id", ""))
            seg = by_id.get(sid)
            if seg is None:
                continue
            corrected = (row.get("corrected") or "").strip()
            findings = []
            for err in row.get("errors", []) or []:
                cat = (err.get("category") or "fluency").lower()
                findings.append(Finding(
                    segment_id=sid, layer=_CAT2LAYER.get(cat, "fluency"),
                    category=err.get("code") or cat,
                    severity=_SEV.get((err.get("severity") or "minor").lower(), MINOR),
                    message=err.get("message") or "", source=seg.source, target=seg.target,
                    suggestion=corrected if corrected and corrected != seg.target else "",
                    origin="llm"))
            result[sid] = {"corrected": corrected, "findings": findings}

    if not batches:
        return result
    with ThreadPoolExecutor(max_workers=max(1, min(workers, total))) as pool:
        futures = {pool.submit(call, b): b for b in batches}
        for fut in as_completed(futures):
            try:
                absorb(fut.result())
            except Exception as exc:                       # one batch must not sink the run
                print(f"[llm_analyze] batch failed: {exc}")
            done += 1
            if progress:
                progress(done, total)
    return result
