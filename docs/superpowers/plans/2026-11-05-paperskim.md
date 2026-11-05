# PaperSkim Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Local web app that condenses arXiv papers into short, undergrad-readable PDFs via an OpenRouter-powered write→review→revise loop with real figures and a page budget.

**Architecture:** FastAPI backend runs a 7-stage pipeline per job (fetch → extract → vision → draft → review → revise → done) through a single-worker queue; React/Vite/Tailwind frontend submits jobs and polls progress. SQLite persists job state; tectonic compiles LaTeX.

**Tech Stack:** Python 3.14, FastAPI, httpx, poppler-utils (pdftotext/pdfinfo), tectonic, SQLite (stdlib), React 18 + Vite + Tailwind, uv.

**Spec:** `docs/superpowers/specs/2026-11-05-paperskim-design.md`

## Global Constraints

- Python 3.14 (`uv venv --python 3.14`); package manager is `uv` (no pip module on this box).
- LaTeX compile via `tectonic` binary only; PDF text/page-count via poppler CLI (`pdftotext`, `pdfinfo`).
- Vision batches: ≤5 images per OpenRouter call; ≤12 figures selected per paper.
- Page budget tolerance: ±1 page; max 1 auto page-adjust re-prompt; max 3 review→revise rounds.
- Model API errors: 2 retries, then job fails with error surfaced.
- API key stored in `backend/paperskim.toml` (chmod 600, gitignored) or `OPENROUTER_API_KEY` env; never committed.
- All external calls: export.arxiv.org downloads + openrouter.ai only.
- Frontend polls every 2s; dark theme; one job processes at a time.
- PDF-fallback (no LaTeX source): text-only, figures omitted, warning badge (deliberate v1 simplification of the spec's page-region figure extraction).

## Review Focus

1. arXiv URL/ID variants — `arxiv.org/abs/2401.12345v2`, `arXiv:2401.12345`, bare `2401.12345`, old-style `cs/0301012` must all normalize; garbage input must raise ValueError, not crash a job. (Pinned in Task 2 tests.)
2. Tarballs with nested subdirs and multiple `.tex` files — main file detection + recursive `\input` flattening must not miss sections or duplicate them. (Pinned in Task 3 tests.)
3. Overlong paper text blowing up prompts — extracted text is truncated to a character budget before any LLM call; test pins the truncation. (Pinned in Task 8.)
4. Compile-failure loops — exactly one error-log repair pass, then a clean failure; no infinite retry. (Pinned in Task 7 test.)
5. Missing API key at submit time — POST /api/jobs returns 400 with a clear message, job is not created. (Pinned in Task 10 test.)

---

### Task 1: Scaffold + settings module

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `README.md`, `AGENTS.md`, `backend/app/__init__.py`, `backend/app/settings.py`
- Test: `tests/test_settings.py`

**Interfaces:**
- Produces: `Settings` dataclass with fields `api_key: str`, `data_dir: Path` (default `backend/data`), `config_path: Path` (default `backend/paperskim.toml`); functions `load_settings() -> Settings` (env var overrides config file), `save_api_key(key: str) -> None` (writes config, chmod 600), `masked_key(s: Settings) -> str` (returns `abcd****wxyz` or `""`).

- [ ] **Step 1: Env setup** — `uv venv --python 3.14`; `uv add fastapi uvicorn httpx pytest pytest-asyncio`; `uv add --dev respx`; check `tectonic --version`, else `pacman -S --noconfirm tectonic`; check `pdftotext -v` and `node --version`, install via pacman if missing. Record versions in README.
- [ ] **Step 2: Write failing test** — `test_load_env_override` (monkeypatch env, config file absent → key from env), `test_save_and_load` (save key → file exists, mode ≤0o600, reload returns key), `test_masked` (short/empty key → empty or masked, never full key).
- [ ] **Step 3: Run test, verify FAIL** — `uv run pytest tests/test_settings.py -v`; expect ModuleNotFoundError.
- [ ] **Step 4: Implement settings.py** — stdlib `tomllib` for read; write with manual TOML string; `Path.chmod(0o600)` after write.
- [ ] **Step 5: Run test, verify PASS.** Commit: `feat: scaffold + settings`.

### Task 2: arXiv fetch

**Files:**
- Create: `backend/pipeline/__init__.py`, `backend/pipeline/fetch.py`
- Test: `tests/test_fetch.py`

**Interfaces:**
- Produces: `normalize_arxiv_id(s: str) -> str` (raises `ValueError` on garbage); `@dataclass SourceBundle: kind: str  # "latex"|"pdf", path: Path, warnings: list[str]`; `fetch_source(arxiv_id: str, dest_dir: Path, client: httpx.Client | None = None) -> SourceBundle` (downloads `https://export.arxiv.org/e-print/{id}`; if response is `application/pdf` or tar extraction fails → retry as PDF `https://export.arxiv.org/pdf/{id}`, warning appended).

- [ ] **Step 1: Write failing tests** — `test_normalize_abs_url` (`https://arxiv.org/abs/2401.12345v2` → `2401.12345v2`), `test_normalize_prefix_form` (`arXiv:2401.12345` → `2401.12345`), `test_normalize_old_style` (`cs/0301012` → `cs/0301012`), `test_normalize_rejects_garbage` (`"hello world"` → ValueError), `test_fetch_prefers_latex` (respx: mock e-print endpoint returning tar.gz bytes from `tests/fixtures/mini.tar.gz` → kind=="latex"), `test_fetch_falls_back_to_pdf` (e-print returns PDF bytes → kind=="pdf", warnings non-empty).
- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement** — regex-based normalization; content-type sniffing for fallback; fixture `tests/fixtures/mini.tar.gz` created in Task 3's conftest (create it in this task with a 2-file tar via `tarfile` in the test helper so Task 2 is self-contained).
- [ ] **Step 4: Run, verify PASS.** Commit: `feat: arxiv fetch`.

### Task 3: Extract (LaTeX source → text + figures)

**Files:**
- Create: `backend/pipeline/extract.py`
- Test: `tests/test_extract.py` (+ `tests/conftest.py` fixture builder for a realistic mini tarball: `main.tex` with `\input{sections/intro}`, one `\includegraphics{fig1.png}` inside `figure` env with caption, `sections/intro.tex`, nested `sections/deep/notes.tex` included from intro)

**Interfaces:**
- Produces: `@dataclass Figure: path: Path, caption: str | None`; `@dataclass Paper: arxiv_id: str, title: str, full_text: str, sections: list[tuple[str, str]], figures: list[Figure], warnings: list[str]`; `extract_paper(bundle: SourceBundle, arxiv_id: str, workdir: Path) -> Paper`.
- Behavior: flatten `\input{...}`/`\include{...}` recursively (guard against include cycles); strip `%` comments (not `\%`); title = first `\title{...}`; figures = `\includegraphics[...]{path}` occurrences, resolved relative to tarball root, with the caption of the enclosing `figure` environment; PDF bundle → `pdftotext` into `full_text`, no figures.

- [ ] **Step 1: Write failing tests** — `test_title_extracted`, `test_input_flattened` (full_text contains intro body and nested notes body), `test_cycle_guard` (a.tex inputs b.tex inputs a.tex → terminates), `test_comments_stripped` (`% hidden` absent, `100\% sure` present), `test_figures_with_captions` (fig1.png found, caption matched), `test_pdf_fallback_text_only` (poppler `pdftotext` on a fixture PDF → full_text non-empty, figures empty, warning present).
- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, verify PASS.** Commit: `feat: extraction`.

### Task 4: OpenRouter client

**Files:**
- Create: `backend/pipeline/llm.py`
- Test: `tests/test_llm.py`

**Interfaces:**
- Consumes: nothing (standalone).
- Produces: `class OpenRouterClient: __init__(api_key: str, base_url: str = "https://openrouter.ai/api/v1")`; `.chat(model: str, messages: list[dict], max_tokens: int = 16000, temperature: float = 0.4, retries: int = 2) -> str` (POST `/chat/completions`, returns `choices[0].message.content`; retries on `httpx.TransportError`/5xx with 2s backoff, raises `LLMError` after retries); `.vision(model: str, prompt: str, images: list[Path]) -> str` (same endpoint, images inlined as `data:image/png;base64,...` content parts).

- [ ] **Step 1: Write failing tests** (respx) — `test_chat_returns_content`, `test_chat_retries_on_500` (500,500,200 → success, exactly 3 calls), `test_chat_raises_after_retries` (always 500 → LLMError), `test_vision_encodes_images` (request body contains data-URL parts, one per image).
- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, verify PASS.** Commit: `feat: openrouter client`.

### Task 5: Model ranking (Pareto frontier)

**Files:**
- Create: `backend/pipeline/pareto.py`
- Test: `tests/test_pareto.py`

**Interfaces:**
- Consumes: `httpx` directly.
- Produces: `@dataclass ModelInfo: id: str, name: str, pricing: dict, vision: bool`; `@dataclass RankedModel: id: str, name: str, vision: bool, tier: int, prompt_cost: float`; `fetch_models(api_key: str, client: httpx.Client | None = None) -> list[ModelInfo]` (GET `/models`, module-level 1h cache `{fetched_at, data}`); `rank_models(models: list[ModelInfo]) -> list[RankedModel]` (sort by tier desc then prompt_cost asc; keep only non-dominated models on the tier-vs-cost frontier); `vision_capable(m: ModelInfo) -> bool` (model metadata `architecture.input_modalities` contains `"image"`).
- Tier map: module constant `TIER_MAP: dict[str, int]` — curated strong-model tier list (prefix match on model id; unknown models tier 1). Frontend shows top 10 by this ranking; `rank_models` returns all, API truncates.

- [ ] **Step 1: Write failing tests** — `test_fetch_parses_and_caches` (respx: 2 calls, endpoint hit once), `test_vision_filter` (fixture model with image modality → True), `test_rank_prefers_frontier` (fixture models: tier3 cheap, tier3 pricey, tier2 cheap → ranked = [tier3 cheap, tier2 cheap], pricey tier3 dominated and dropped).
- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement** (stdlib `functools`; dominance check pairwise).
- [ ] **Step 4: Run, verify PASS.** Commit: `feat: model ranking`.

### Task 6: Vision stage

**Files:**
- Create: `backend/pipeline/vision.py`
- Test: `tests/test_vision.py`

**Interfaces:**
- Consumes: `Paper.figures` (Task 3), `OpenRouterClient.vision` (Task 4).
- Produces: `@dataclass Caption: summary: str, axes: str, takeaway: str, jargon: list[str], to_dict() -> dict`; `select_figures(figures: list[Figure], cap: int = 12) -> list[Figure]` (prefer figures with captions; cap); `describe_figures(client, model: str, figures: list[Figure], batch_size: int = 5) -> dict[str, Caption]` keyed by `str(figure.path)`; batches figure lists ≤5 per call; parses model JSON (tolerant: strip code fences, `json.loads`, on failure skip batch with warning list returned alongside).

- [ ] **Step 1: Write failing tests** (fake client object, no HTTP) — `test_select_prefers_captions_and_caps` (14 figures, 12 returned, captioned first), `test_batches_of_five` (11 figures → 3 calls with sizes 5/5/1), `test_parses_captions` (fake returns JSON → dict with 5 entries), `test_bad_json_skips_batch` (one bad batch → entries from good batch only, warning recorded).
- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, verify PASS.** Commit: `feat: vision stage`.

### Task 7: Compiler

**Files:**
- Create: `backend/pipeline/compiler.py`
- Test: `tests/test_compiler.py`

**Interfaces:**
- Produces: `@dataclass CompileResult: ok: bool, pdf_path: Path | None, log: str, pages: int`; `compile_tex(tex_path: Path, outdir: Path, allow_repair: bool = True, repair_fn=None) -> CompileResult` (runs `tectonic -X compile {tex} --outdir {outdir}` via `subprocess.run` (timeout 180s); on failure and `allow_repair`, calls `repair_fn(log) -> str` (new tex) once — `repair_fn` injected by caller (Task 8); recompiles; `pages` via `pdfinfo`).

- [ ] **Step 1: Write failing tests** — fixture `tests/fixtures/ok.tex` (minimal article), `tests/fixtures/broken.tex` (`\usepackage{notarealpackage123}`). `test_compile_ok` (skipped if `shutil.which("tectonic") is None`): ok.tex → ok=True, pages==1. `test_repair_called_once`: repair_fn records calls, returns fixed tex (fixture writes working tex on first repair) → ok=True, exactly 1 repair call. `test_repair_exhausted`: repair_fn returns broken tex again → ok=False, exactly 1 repair call (no loop).
- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, verify PASS.** Commit: `feat: tectonic compiler`.

### Task 8: Writer + reviewer + refine loop

**Files:**
- Create: `backend/pipeline/writer.py`, `backend/pipeline/reviewer.py`
- Test: `tests/test_writer.py`, `tests/test_reviewer.py`

**Interfaces:**
- Consumes: `Paper`, `dict[str, Caption]` (Tasks 3, 6), `OpenRouterClient.chat` (Task 4), `compile_tex`, `page_count` (Task 7).
- Produces writer.py: `PROMPT_BUDGET_CHARS = 90000` (module const); `truncate(text: str, budget: int = PROMPT_BUDGET_CHARS) -> str`; `build_draft_messages(paper: Paper, captions: dict[str, Caption], target_pages: int, adjust: str | None = None) -> list[dict]` (system prompt: undergrad audience, gloss rare jargon at first use, self-contained article preamble, embed figures via `\includegraphics` paths copied into a `figures/` dir next to the tex, page target, adjust instruction when given); `draft_once(client, model, paper, captions, target_pages, adjust=None) -> str` (returns raw LaTeX, strips markdown fences); `copy_figure_assets(paper: Paper, outdir: Path) -> dict[str, str]` (copies selected figure files to `outdir/figures/`, returns tex-path map).
- Produces reviewer.py: `@dataclass ReviewVerdict: passed: bool, critique: list[str]`; `review(client, model, paper: Paper, draft_tex: str) -> ReviewVerdict` (rubric prompt: faithfulness/coverage/jargon/caption-accuracy; output JSON `{"passed": bool, "critique": [...]}`, tolerant parse, unparsable → passed=False with generic critique).
- Produces writer.py loop: `@dataclass IterationResult: tex_path: Path, pdf_path: Path | None, pages: int, rounds: int, passed: bool`; `write_and_refine(client, writer_model, reviewer_model, paper, captions, target_pages, workdir: Path, max_rounds: int = 3, compile_fn=compile_tex) -> IterationResult` — flow: copy assets → draft → compile → page miss (target±1) → 1 adjust re-prompt → recompile (even if still off, continue) → review→revise loop (revise = `draft_once` with critique appended as adjust) max 3 rounds or pass → return best tex.

- [ ] **Step 1: Write failing tests** (fake client + fake compile_fn; no real tectonic) — `test_truncate_budget` (120k chars in → ≤90k out), `test_draft_strips_fences` (fake returns ```` ```latex ... ``` ```` → raw tex out), `test_page_adjust_called_once` (fake compile returns pages 8 then 8 then 4 with target 4 → draft called exactly twice), `test_refine_stops_on_pass` (review passes round 1 → rounds==1), `test_refine_caps_at_three` (review always fails → rounds==3, result still returned), `test_review_parses_verdict` (JSON with critique list), `test_review_unparsable_is_fail`.
- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, verify PASS.** Commit: `feat: writer/reviewer loop`.

### Task 9: Job store + queue + runner

**Files:**
- Create: `backend/app/db.py`, `backend/app/queue.py`, `backend/pipeline/runner.py`
- Test: `tests/test_db.py`, `tests/test_runner.py`

**Interfaces:**
- Produces db.py: `init_db(db_path: Path) -> sqlite3.Connection`; `create_job(conn, arxiv_input: str, arxiv_id: str, target_pages: int, writer_model: str, vision_model: str) -> int`; `update_job(conn, job_id: int, **fields)` (allowed: status, stage, warning, error, pdf_path, tex_path, captions_path, rounds); `get_job(conn, job_id) -> dict | None`; `list_jobs(conn) -> list[dict]`. Job status enum: `queued|running|done|failed`; stage string among `fetch|extract|vision|draft|review|revise|done`.
- Produces runner.py: `run_job(job_id: int, settings: Settings, conn: sqlite3.Connection, client: OpenRouterClient | None = None) -> None` — executes all stages in order, `update_job` at each stage transition, collects warnings, on exception sets `status=failed` + `error`.
- Produces queue.py: `class JobQueue: __init__(settings, db_path)`, `.submit(job_id) -> int` (position), `.start()` (ThreadPoolExecutor(max_workers=1) consumes; idempotent), `._worker(job_id)` calls `run_job` with its own connection.

- [ ] **Step 1: Write failing tests** — db: `test_create_and_get_roundtrip`, `test_update_unknown_field_raises`, `test_list_orders_newest_first`. runner (monkeypatched pipeline stage funcs returning fakes): `test_run_job_happy_path` (status ends done, stage transitions recorded in order fetch→…→done), `test_run_job_failure_sets_error` (fetch raises → status failed, error contains message). queue: `test_submit_runs_job` (fake run_job records call; wait for executor drain ≤5s).
- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, verify PASS.** Commit: `feat: job store + queue + runner`.

### Task 10: FastAPI routes

**Files:**
- Create: `backend/app/main.py`, `backend/app/schemas.py`, `backend/app/routes/__init__.py`, `backend/app/routes/jobs.py`, `backend/app/routes/models.py`, `backend/app/routes/settings.py`
- Modify: `backend/app/settings.py` if needed for app-level singleton
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: db, queue, pareto, settings (Tasks 1, 5, 9).
- Produces endpoints:
  - `POST /api/jobs` body `{input: str, target_pages: int, writer_model: str, vision_model: str}` → 400 if target_pages not in 1..30 or models empty or API key missing; else creates job + submits, returns `{id, position}`.
  - `GET /api/jobs` → list (newest first); `GET /api/jobs/{id}` → detail incl. warnings/error; `GET /api/jobs/{id}/pdf` → FileResponse (404 until done); `GET /api/jobs/{id}/latex` → FileResponse.
  - `GET /api/models?kind=writer|vision` → `{models: [RankedModel...][:10], advanced: [all]}` (writer: all models ranked; vision: vision-capable only; on OpenRouter failure → 502 with message).
  - `GET /api/settings` → `{has_key: bool, masked: str}`; `PUT /api/settings` body `{api_key: str}` → saves via `save_api_key`.
- App state: module-level `AppState` (conn, queue, settings) created in `create_app(db_path, data_dir)` factory; tests use `create_app(tmp_path...)` with TestClient.

- [ ] **Step 1: Write failing tests** — `test_submit_rejects_missing_key` (no key anywhere → 400, job count 0), `test_submit_rejects_bad_pages` (0 and 31 → 400), `test_submit_ok_enqueues` (key set → 200, id ≥1), `test_get_models_writer_vs_vision` (respx-mocked /models: vision list ⊆ writer list), `test_models_502_on_openrouter_failure`, `test_settings_mask_roundtrip` (PUT then GET: has_key true, masked != full key), `test_pdf_404_before_done` then `test_pdf_served_after_done` (insert fake pdf file + status done in db).
- [ ] **Step 2: Run, verify FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, verify PASS.** Commit: `feat: API routes`.

### Task 11: Frontend

**Files:**
- Create: `frontend/` (Vite React: `package.json`, `vite.config.js`, `index.html`, `src/main.jsx`, `src/App.jsx`, `src/api.js`, `src/components/JobForm.jsx`, `src/components/ModelDropdown.jsx`, `src/components/JobList.jsx`, `src/components/JobDetail.jsx`, `src/components/SettingsModal.jsx`), `frontend/tailwind` via `@tailwindcss/vite` plugin
- Test: none (verified by build + manual E2E)

**Interfaces:**
- Consumes: all Task 10 endpoints via `src/api.js` (fetch wrappers: `submitJob`, `listJobs`, `getJob`, `getModels(kind)`, `saveKey(key)`, `getSettings`).

- [ ] **Step 1: Scaffold** — `npm create vite@latest frontend -- --template react`; `npm i -D tailwindcss @tailwindcss/vite`; wire plugin + `@import "tailwindcss"` in `src/index.css`.
- [ ] **Step 2: Implement components** — App: settings modal (opens if `has_key` false), JobForm (arXiv input, page-count stepper 1–30 default 4, two ModelDropdowns fed by `getModels`, Condense button → submitJob), JobList (2s polling, stage badge, position in queue, warning/error badges), JobDetail (iframe PDF preview via `/api/jobs/{id}/pdf`, download links PDF + LaTeX, figure captions list). Dark theme (slate-950 base, indigo accents).
- [ ] **Step 3: Verify build** — `npm run build` exits 0; `uv run uvicorn backend.app.main:app` + `curl localhost:8000/api/models` returns JSON (with key set).
- [ ] **Step 4: Commit:** `feat: frontend`.

### Task 12: E2E on a real paper + review + push

**Files:**
- Modify: whatever E2E exposes; `README.md` (run instructions: `uv run uvicorn backend.app.main:app --port 8000`, `cd frontend && npm run dev`, OPENROUTER_API_KEY or settings modal)

**Interfaces:**
- Consumes: everything.

- [ ] **Step 1: E2E** — pick a short real arXiv paper (e.g. `arxiv.org/abs/1706.03762`), run a job at target 3 pages through the running app; verify: job reaches done, PDF compiles, page count within ±1, figures present with captions, no invented-claims flags from a manual read of the review log.
- [ ] **Step 2: Full test suite** — `uv run pytest -v` all green; `npm run build` clean.
- [ ] **Step 3: Claude Code review pass** — run `claude -p` review of the full diff per user's standing "Claude Code review before deploy" rule; fix findings.
- [ ] **Step 4: Push** — verify gh auth (`gh auth status`), `git remote add origin https://github.com/vernorsquant/PaperSkim.git` (or ssh), push `main`. Confirm remote commit visible via `gh repo view vernorsquant/PaperSkim`.
- [ ] **Step 5: Report** — summary + remind user to rotate the OpenRouter key if it was pasted in chat.
