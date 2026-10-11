# Hindi PDF Translator

A small app that runs on an ordinary office laptop with **8–12 GB RAM and no graphics card**. Upload a Hindi PDF (for example, documents from Beltron) and get an English translation back as a Word file, a side-by-side review screen, or text.

- **Primary model: Gemma 4,** E2B on 8 GB laptops and E4B on 12 GB laptops. It runs through llama.cpp's `llama-server`, with models downloaded from Hugging Face (no Ollama).
- **IndicTrans2** produces a quick draft within minutes and is the first fallback.
- **Users choose the model:** Auto (recommended), Fast, Balanced or Best quality. Only tested models are offered.
- **Free and local only:** no paid APIs, and documents never leave the laptop.
- **Fallbacks at every stage:** every sentence is checked, and a failed sentence falls back to the next engine.
- An **offline model pack** lets IT install models on many laptops without internet.

The full design is in **[PLAN.md](PLAN.md)**.

## Status: Phase 1 (MVP)

| Area | Done | Next (PLAN.md §14) |
|---|---|---|
| Reading PDFs | Page classification (Unicode, legacy font, scan, English). A quality check that catches garbled text layers. Native extraction. Tesseract OCR. | Kruti Dev conversion, PaddleOCR as a second OCR engine with number cross-check, tables, Gemma 4 re-reading of hard pages |
| Translation | IndicTrans2 quick draft. Gemma 4 final via `llama-server`, with JSON output and protected numbers. Per-sentence checks and selection. Memory guard. Circuit breaker. Translation memory. | Back-translation quality score, Qwen3.5 third opinion, ensemble for amber sentences |
| App | Upload with model choice, translation page (stage tracker, time remaining, live preview, "While you wait"), side-by-side review with keyboard editing, Word and text downloads, glossary, settings, model downloads | Tech-news panel, team sync, layout-preserving PDF, Windows installer |

## Quick start (developer mode, no models needed)

Developer mode uses a stand-in engine that **transliterates** instead of translating. It lets you try the whole app and UI on any machine.

```bash
# 1. Backend (Python 3.11+)
cd backend
python -m venv .venv
.venv/bin/pip install -e ".[dev]"            # Windows: .venv\Scripts\pip

# 2. Web UI (Node 20+)
cd ../frontend
npm install
npm run build

# 3. Run (opens http://127.0.0.1:8080)
cd ..
PDFT_PROFILE=dev backend/.venv/bin/python run.py   # Windows: set PDFT_PROFILE=dev & backend\.venv\Scripts\python run.py
```

OCR for scanned pages needs **Tesseract with Hindi**:
- Ubuntu: `apt install tesseract-ocr tesseract-ocr-hin`
- Windows: the UB Mannheim installer, with Hindi selected

## Running with the real models

1. **IndicTrans2 (quick draft):** `backend/.venv/bin/pip install -e "backend[indictrans2]"`
2. **llama-server (Gemma 4):** download a CPU build of [llama.cpp](https://github.com/ggml-org/llama.cpp/releases) and put `llama-server(.exe)` in `bin/`, or set `PDFT_LLAMA_BIN`.
3. **Models:** use **Settings → Models → Download**, or the command line:
   ```bash
   cd backend
   .venv/bin/python -m app.model_store list
   .venv/bin/python -m app.model_store download indictrans2-indic-en-1b
   .venv/bin/python -m app.model_store download gemma4-e2b
   .venv/bin/python -m app.model_store import /path/to/model-pack   # offices without Hugging Face access
   ```
4. Start with `python run.py`. The hardware profile (8 GB or 12 GB) is chosen from the installed RAM. Set `PDFT_PROFILE` to override it.

The exact Hugging Face repos, files and checksums in `models/catalog.yaml` are pinned during Phase 0 on the team's test laptop.

## How it works

```
PDF → classify each page → native text / OCR → split sentences, protect numbers
    → IndicTrans2 quick draft → Gemma 4 final (paragraph by paragraph)
    → check every sentence → pick the best version → Word / text / review screen
```

- **Only one model is in memory at a time.** The worker runs one stage for the whole document, then unloads that model before the next stage.
- **Jobs survive interruptions.** Every sentence is saved, so a job resumes after sleep or a restart.
- **The app listens only on `127.0.0.1`.** Other machines on the network can't reach it.

## Project layout

```
backend/app/
  main.py            HTTP API + serves the web UI
  worker.py          stage-by-stage job runner (python -m app.worker)
  model_manager.py   user choice → model, memory guard, engine creation
  model_store.py     model catalog, Hugging Face download, pack import, checksums
  pipeline/          classify, extract, ocr/, normalize, quality, segment, protect,
                     translate/ (IndicTrans2, llama-server, dev stand-in), validate, select, render/
backend/tests/       pytest suite (uses generated Hindi PDFs and a fake llama-server)
frontend/src/        React + TypeScript + Tailwind UI
profiles/            hardware profiles (laptop-8gb, laptop-12gb, workstation, dev)
models/catalog.yaml  the tested models users can choose from
run.py               starts the web app + worker and opens the browser
```

## Tests

```bash
cd backend && .venv/bin/python -m pytest -q
cd frontend && npm run typecheck
```
