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

Windows: double-click `run.bat` (checks Python 3.11+, installs deps, saves your key,
starts both servers, opens the UI).

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
