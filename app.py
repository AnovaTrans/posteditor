"""Anova Post-Editor — human-in-the-loop MTPE.

Upload a translated bilingual file (+ optional TM / termbase / DNT list), let the
engine find what needs fixing, then accept / edit / reject each suggestion in the
editor and export the corrected file. Language-agnostic: works for any target language.
"""
import os

import streamlit as st

from core.mtpe import parse, references
from core.mtpe.analyze import analyze, AnalyzeOptions
from core.mtpe.llm import LLMClient, CURRENT_MODELS, MissingKey

st.set_page_config(page_title="Anova Post-Editor", page_icon="✍️", layout="wide")
SEV_ICON = {"critical": "🟥", "major": "🟧", "minor": "🟨"}


def _api_key():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"]
    try:
        return st.secrets.get("ANTHROPIC_API_KEY", "")
    except Exception:            # no secrets.toml present (local dev)
        return ""


def _reset():
    for k in ("result", "src_name", "applied_bytes", "llm_cost"):
        st.session_state.pop(k, None)


st.title("✍️ Anova Post-Editor")
st.caption("Human-in-the-loop machine-translation post-editing (MTPE) — XLIFF / MXLIFF / MQXLIFF / SDLXLIFF")

with st.sidebar:
    st.header("Settings")
    key = _api_key()
    if not key:
        key = st.text_input("Claude API key", type="password")
    model = st.selectbox("Model", CURRENT_MODELS, index=0)
    target_lang = st.text_input("Target language (blank = from file)", "")
    instructions = st.text_area("Project instructions (optional)", "", height=80)
    use_llm = st.checkbox("LLM analysis (6 layers)", value=True,
                          help="If off, only the free rule + TM/TB/DNT checks run")
    workers = st.slider("Parallel requests", 1, 12, 6)

st.subheader("1) Files")
c1, c2 = st.columns(2)
with c1:
    up = st.file_uploader("Translated file", type=["xliff", "xlf", "mxliff", "mqxliff", "sdlxliff"])
with c2:
    tm_up = st.file_uploader("TM (.tmx) — optional", type=["tmx"])
    tb_up = st.file_uploader("Termbase (.csv/.tbx) — optional", type=["csv", "tbx"])
    dnt_up = st.file_uploader("DNT list (.txt/.csv) — optional", type=["txt", "csv"])

if up and st.button("2) Analyze", type="primary"):
    if use_llm and not key:
        st.error("The LLM analysis needs a Claude API key (or turn the LLM analysis off).")
        st.stop()
    _reset()
    try:
        doc = parse.load(up.getvalue(), up.name)
    except Exception as e:
        st.error(f"Could not read the file: {e}")
        st.stop()
    tm = references.load_tm(tm_up.getvalue()) if tm_up else None
    tb = references.load_tb(tb_up.getvalue(), tb_up.name) if tb_up else None
    dnt = references.load_dnt(dnt_up.getvalue()) if dnt_up else None

    llm = None
    if use_llm:
        try:
            llm = LLMClient(key, model)
        except MissingKey as e:
            st.error(str(e)); st.stop()

    opts = AnalyzeOptions(target_lang=target_lang, instructions=instructions,
                          use_llm=use_llm, workers=workers)
    bar = st.progress(0.0, "Analyzing…")
    def prog(done, total):
        bar.progress(done / total if total else 1.0, f"LLM {done}/{total} batches")
    with st.spinner("Reviewing segments…"):
        result = analyze(doc, opts, llm=llm, tm=tm, tb=tb, dnt=dnt, progress=prog)
    bar.empty()
    st.session_state["result"] = result
    st.session_state["src_name"] = up.name
    if llm:
        st.session_state["llm_cost"] = llm.cost_usd

result = st.session_state.get("result")
if result:
    stats = result.doc.stats()
    sc = result.score()
    st.subheader("Summary")
    m = st.columns(6)
    m[0].metric("Segments", stats["total"])
    m[1].metric("Reviewed", stats["reviewable"])
    m[2].metric("Flagged", sc["flagged_segments"])
    m[3].metric("LQA score", sc["lqa_score"])
    m[4].metric("Grade", sc["grade"])
    m[5].metric("C/Ma/Mi", f"{sc['critical']}/{sc['major']}/{sc['minor']}")
    if st.session_state.get("llm_cost"):
        st.caption(f"LLM cost ≈ ${st.session_state['llm_cost']}")

    views = result.flagged()
    st.subheader(f"3) Editor — {len(views)} segments")
    if not views:
        st.success("No suggestions — the file looks clean. ✅")
    else:
        fc1, fc2 = st.columns([3, 1])
        only_sev = fc1.multiselect("Severity filter", ["critical", "major", "minor"],
                                   default=["critical", "major", "minor"])
        if fc2.button("Accept all suggestions"):
            for v in views:
                if v.changed:
                    st.session_state[f"accept_{v.segment.id}"] = True

        for v in views:
            seg = v.segment
            if only_sev and v.findings and not any(f.severity in only_sev for f in v.findings):
                continue
            worst = min((f.severity for f in v.findings), key=lambda s: ["critical", "major", "minor"].index(s)) \
                if v.findings else "minor"
            head = f"{SEV_ICON.get(worst,'⬜')} Segment {seg.id} · {len(v.findings)} finding(s) · penalty {v.penalty}"
            with st.expander(head, expanded=False):
                st.markdown(f"**Source:** {seg.source}")
                st.markdown(f"**Current translation:** {seg.target}")
                for f in v.findings:
                    tip = f"{SEV_ICON.get(f.severity,'')} `{f.layer}/{f.category}` — {f.message}"
                    if f.suggestion and f.origin != "llm":
                        tip += f"  → _{f.suggestion}_"
                    st.markdown(tip)
                default = v.proposed if v.changed else seg.target
                st.text_area("Corrected target", value=default, key=f"edit_{seg.id}", height=80)
                st.checkbox("✅ Apply this segment", key=f"accept_{seg.id}", value=v.changed)

        st.subheader("4) Apply & download")
        if st.button("Apply accepted", type="primary"):
            applied = 0
            id2seg = {s.id: s for s in result.doc.segments}
            for v in views:
                sid = v.segment.id
                if st.session_state.get(f"accept_{sid}"):
                    text = st.session_state.get(f"edit_{sid}", "").strip()
                    if text and result.doc.set_target(id2seg[sid], text):
                        applied += 1
            st.session_state["applied_bytes"] = result.doc.to_bytes()
            st.success(f"Applied {applied} segment(s).")

        if st.session_state.get("applied_bytes"):
            name = st.session_state["src_name"].rsplit(".", 1)
            out_name = f"{name[0]}_postedited.{name[1] if len(name) > 1 else 'xliff'}"
            st.download_button("⬇️ Download corrected file", st.session_state["applied_bytes"],
                               file_name=out_name, mime="application/xliff+xml", width="stretch")
