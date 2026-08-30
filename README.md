# Anova Post-Editor

Human-in-the-loop **MTPE** (machine-translation post-editing) for bilingual CAT
files: `.xliff` / `.xlf` / `.mxliff` / `.mqxliff` / `.sdlxliff`.

Upload a translated file (and, optionally, a **TM**, a **termbase** and a **DNT
list**). The engine flags what needs fixing across six layers — accuracy,
fluency, terminology, style, compliance and MT-hallucination — plus TM
divergence and termbase/DNT integrity. You then **accept, edit or reject** each
suggestion in the editor and export the corrected file.

The analysis lives in `core/mtpe/` — a Streamlit-free engine shared with the
**LQA** tool (that repo gets a synced copy; see `sync_core.py`).

## Run locally
```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-...   # or set it in .streamlit/secrets.toml
streamlit run app.py
```

## Deploy (Streamlit Community Cloud)
Main file `app.py`, **Python 3.13** (choose it under *Advanced settings* — the
default 3.14 has no `pyarrow` wheel and the build fails). Add
`ANTHROPIC_API_KEY` under *Secrets*.

## Tests
```bash
pip install pytest
PYTHONPATH=. pytest -q
```

## Layers
| Layer | Cost | What it checks |
|---|---|---|
| rules | free | numbers, placeholders, tags, spacing, %-position, decimal comma, punctuation, repetition, length, TR MT-isms |
| refcheck | free | TM divergence, termbase enforcement, DNT integrity |
| LLM (6-layer) | Claude | accuracy · fluency · terminology · style · compliance · hallucination + a proposed corrected target |

Phase 2 (planned): style-guide adherence, semantic reference (API embeddings),
Turkish spelling deep-dive.
