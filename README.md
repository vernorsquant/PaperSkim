# PaperSkim

Condense arXiv papers into short, undergrad-readable PDFs.

Paste an arXiv link, pick a page count and models, get a compiled LaTeX PDF that
keeps the paper's story and key figures, glosses jargon, and fits the page budget.

## Stack

- Backend: Python 3.14, FastAPI, httpx, poppler (pdftotext/pdfinfo 26.08.0), tectonic
- Frontend: React 18 + Vite + Tailwind (node v26.7.0)
- Models: OpenRouter (writer + vision, ranked on a capability/cost Pareto frontier)

## Run

```bash
uv run uvicorn backend.app.main:app --port 8000   # backend
cd frontend && npm run dev                        # frontend
```

API key: enter via the settings modal (stored in `backend/paperskim.toml`, chmod 600)
or set `OPENROUTER_API_KEY`.

## Status

Work in progress — see `docs/superpowers/specs/` and `docs/superpowers/plans/`.
