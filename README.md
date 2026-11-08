# PaperSkim

Condense papers into short, undergrad-readable PDFs.

Paste a paper link, pick a page count and models, get a compiled LaTeX PDF that
keeps the paper's story and key figures, glosses jargon, and fits the page budget.

## Supported inputs

- **arXiv** — URLs (`arxiv.org/abs/…`, `/pdf/…`), bare IDs (`2401.12345`), `arXiv:` prefix.
  arXiv papers use the LaTeX source, so real figures are kept.
- **DOI** — bare (`10.1101/2024.01.01.575000`) or resolver URLs (`doi.org/10.…`).
  Resolved to an open-access PDF via OpenAlex; also covers **bioRxiv** and **medRxiv**
  article URLs. If the DOI traces back to arXiv, the LaTeX path is used automatically.
- **Semantic Scholar** — paper page URLs (`semanticscholar.org/paper/…`).
- **OpenReview** — `openreview.net/forum?id=…` / `/pdf?id=…`.
- **ACL Anthology** — `aclanthology.org/2024.acl-long.123` (with or without `.pdf`).
- **Direct PDF URLs** — any `https://…` link that serves a PDF.
- **Local PDF upload** — drag and drop onto the form.
- **Search** — the 🔍 Search button queries arXiv + Semantic Scholar and lets you
  submit a result directly.

Non-arXiv sources go through a text-only PDF fallback pipeline (`pdftotext`), so
figures are limited compared to the arXiv LaTeX path.

## Stack

- Backend: Python 3.11+, FastAPI, httpx, poppler (`pdftotext`/`pdfinfo`), tectonic
- Frontend: React 18 + Vite + Tailwind
- Models: OpenRouter (writer + vision, ranked on a capability/cost Pareto frontier),
  per-job cost tracked and shown

## Run

Windows: double-click **`setup.bat`** once — it installs every dependency
(Python 3.12, uv, backend packages, tectonic, poppler, Node.js LTS, frontend
packages) via winget with pip fallbacks, then prompts for your OpenRouter key.
Afterwards, double-click `run.bat` to start both servers and open the UI.
(If a tool was installed mid-run, open a new terminal window and re-run
`setup.bat` to let it verify everything.)

macOS / Linux:

```bash
uv run uvicorn backend.app.main:app --port 8000   # backend
cd frontend && npm run dev                        # frontend
```

Requirements: `tectonic` (LaTeX), poppler (`pdftotext`, `pdfinfo`) on PATH.

```bash
# Arch:  sudo pacman -S tectonic poppler
# macOS: brew install tectonic poppler
```

API key: enter via the settings modal — it is verified live against OpenRouter before
being saved (stored in `backend/paperskim.toml`, chmod 600, never committed), or set
`OPENROUTER_API_KEY`.

## Queue

- **Two jobs run in parallel** by default so batches finish in roughly half the
  time. Change it in `backend/paperskim.toml`:

  ```toml
  [queue]
  workers = 3   # default 2
  ```

- **Stop queue** — the ■ button above the job list (or `POST /api/queue/stop`)
  cancels every queued job that has not started yet; running jobs finish.
  Cancelled jobs show as failed with "cancelled — the queue was stopped".

## Quality loop

Each job is not a one-shot draft. After the first compilable draft:

1. **Review** — a rubric reviewer compares the draft against the original text:
   faithfulness, coverage (anything important *missing* from the original is
   listed and must be restored), jargon glosses, figure captions.
2. **Fact-check** — after the reviewer passes, a second pass re-verifies every
   number and claim against the original before the job may ship.
3. **Revise** — reviewer critiques, missing-coverage items, or fact-check
   errors are all fed back to the writer; up to 4 rounds
   (`max_rounds` in `write_and_refine`). The last compilable revision is always
   what gets delivered, with notes in the job warnings if output is best-effort.

## Troubleshooting

- **"API key expired"** — OpenRouter keys can expire; create a new one at
  [openrouter.ai/keys](https://openrouter.ai/keys) and save it in Settings.
- **Dropdowns empty** — the backend is probably not running (check the backend
  window) or `npm run dev` cannot reach `localhost:8000`.
- **401/402 errors on jobs** — expired/invalid key, or out of credits; the job error
  says which.
- **Missing tools banner** — install tectonic + poppler (commands above); PDF
  compilation cannot run without them.

## Status

Work in progress — see `docs/superpowers/specs/` and `.hermes/plans/`.
