# paperskim — Design Spec

Date: 2026-11-05
Status: Approved design, pending implementation plan.

## Purpose

Condense arXiv papers into short, undergrad-readable PDFs. The user pastes an arXiv
link or ID, picks a target page count and models, and paperskim produces a compiled
LaTeX PDF that preserves the paper's story and key figures, explains rare jargon,
and fits the requested page budget. Purpose: skim many papers in a field without
reading 20 pages each.

## Success criteria

- Input: arXiv ID or URL; output: compiled PDF at the target page count (±1).
- Key figures from the paper appear in the output, each paired with a
  vision-derived description.
- Language is understandable by an undergrad; rare jargon is glossed on first use.
- A reviewer agent verifies faithfulness (no invented claims); up to 3
  review→revise rounds.
- Everything runs locally; the only external calls are arXiv downloads and
  OpenRouter API calls.

## Architecture

- **Backend:** Python 3.14, FastAPI + uvicorn, SQLite for job state, uv for deps.
- **Frontend:** React 18 + Vite + Tailwind (dark theme).
- **LaTeX:** tectonic (single binary, Arch repos).
- **Layout:**
  ```
  paperskim/
    backend/
      app/            # FastAPI app, routes, settings
      pipeline/       # fetch, extract, vision, draft, review, revise, compile
      db.py           # SQLite job store
    frontend/         # Vite React app
    docs/superpowers/specs/
    AGENTS.md, README.md, .gitignore
  ```

## Pipeline stages (per job)

1. **fetch** — normalize the input to an arXiv ID, download the e-print source
   tarball from export.arxiv.org. If no LaTeX source is available, fall back to
   PDF-only extraction and flag a warning on the job.
2. **extract** — untar, detect the main `.tex` (contains `\documentclass`),
   flatten `\input`/`\include` recursively, strip comments, inventory
   `\includegraphics` assets, build a section map. PDF fallback: PyMuPDF text
   extraction plus page-region figure extraction.
3. **vision** — select up to 12 key figures (heuristics: referenced from body
   text, position, size), batch ≤5 per vision-model call. Each call returns
   structured JSON per figure: content summary, axes/panels, key takeaway,
   jargon terms appearing in it. Captions are stored with the figure assets.
4. **draft** — writer model generates a self-contained LaTeX document from the
   extracted text + figure captions: undergrad audience, jargon glossed at first
   use, target page count N. Compile with tectonic. If the compiled page count
   misses N±1, re-prompt once with a shorten/expand instruction (max 1
   auto-adjust).
5. **review** — reviewer model receives the original text and the draft LaTeX
   and returns PASS or a structured critique against the rubric:
   faithfulness (no invented claims or numbers), coverage of the main
   contributions, jargon handling, figure-caption accuracy.
6. **revise** — writer applies the critique; review→revise repeats, max 3 rounds
   or until PASS.
7. **done** — final PDF, compile log, and figure captions are stored as job
   artifacts, served by the backend for preview and download.

Compile failure at any stage gets one repair pass that feeds tectonic's error log
back to the writer. Model API errors retry twice, then fail the job with the
error surfaced in the UI.

## Model selection

- Backend queries OpenRouter `GET /api/v1/models`, caches for 1 hour.
- Vision-capable filter uses the model's modality metadata.
- Both dropdowns (writer, vision) are ranked on a capability-vs-price Pareto
  frontier: a curated capability tier list crossed with live pricing, top ~10
  shown; an advanced toggle reveals all models.
- Writer and vision models are chosen independently per job.
- API key lives in `backend/paperskim.toml` (chmod 600, gitignored) or the
  `OPENROUTER_API_KEY` env var; entered via the settings modal.

## Frontend

Single page: arXiv input, page-count stepper, writer/vision model dropdowns,
Condense button. Job list below with live stage progress (2s polling). Result
view: in-browser PDF preview (iframe) plus download links for PDF and LaTeX
source. Settings modal for the API key. Dark theme, Tailwind.

## Concurrency

One paper processes at a time (LLM-bound); jobs queue with position shown in
the UI. A `ThreadPoolExecutor(max_workers=1)` consumes the queue.

## Error handling

- fetch failure → job fails with the reason (bad ID, network).
- No LaTeX source → PDF fallback path, warning badge on the job.
- tectonic failure → one error-log repair pass, then fail.
- Vision call failure → job continues text-only, figures omitted, warning badge.

## Testing

- Pytest unit tests for ID normalization, tarball extraction, comment stripping,
  figure selection, and vision batching (fixture mini-tarball in `tests/fixtures/`).
- Pipeline integration tests with a mocked OpenRouter client.
- End-to-end: one real arXiv paper through fetch→PDF at the end of implementation.
