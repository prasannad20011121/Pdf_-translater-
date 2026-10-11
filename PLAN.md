# Hindi PDF Translator: Project Plan

> **Request (Vikram Chandra):** We get many documents from Beltron, all in Hindi. We need a small web page where anyone on the team can upload a PDF and get it translated. Today this is done by hand with Copilot, which sometimes won't accept the upload.
>
> **Added requirements:**
> - It runs **locally**.
> - It uses **only free or local models** (no paid APIs).
> - It runs on an **ordinary office laptop with 8 GB of RAM (12 GB at most)**.
> - **Gemma 4 is the primary model.** Users can **choose the model**, and models are **downloaded from Hugging Face, not Ollama**.
> - It has **fallbacks**.
> - Its translation quality is the **best achievable within these limits**.

| | |
|---|---|
| Status | Draft v6, for review |
| Date | 2026-10-11 |
| Scope | Hindi (including Hindi mixed with English) to English. The design leaves room for English to Hindi and other Indian languages later. |
| Changes in v6 | **A modern web interface** (§9.1): clean, light and dark themes, works offline. **A dedicated translation page** (§9.2) with a stage tracker, time remaining, a live preview of the English as it appears, and a **"While you wait" tech-news panel** (§9.3). The news headlines are fetched by the app's backend, carry no document data, can be switched off by an admin, and are replaced by offline tips when there's no internet. |
| Changes in v5 | **Users can choose the model** from a short, tested list: Auto (recommended), Fast, Balanced or Best quality (§4.4). **Ollama is removed.** Models are **downloaded from Hugging Face**, pinned to exact versions and checked, and Gemma 4 runs through the bundled **llama.cpp** server (§4.5). An **offline model pack** lets IT install models on many laptops without each one downloading. |
| Changes in v4 | **Gemma 4 is now the primary translation model**: Gemma 4 E2B on 8 GB laptops and Gemma 4 E4B on 12 GB laptops. The same model also re-reads difficult scanned pages. **IndicTrans2 moves to a supporting role.** It produces a quick draft within minutes, and it is the first fallback whenever Gemma's version fails a check or memory is short. **Two consequences:** the app's memory limit on 8 GB laptops rises from about 3 GB to **about 4.5 GB**, and the final translation takes **longer** on a laptop processor (§11). Qwen3.5 is now only an optional third opinion on 12 GB laptops. |
| Changes in v3 | Redesigned for laptops with 8–12 GB RAM and no graphics card. One model in memory at a time, a memory guard, and a native Windows install instead of Docker. |
| Changes in v2 | Removed every paid cloud API. Bhashini (free, Government of India) remains as an optional fallback that is off by default. |

---

## 1. Summary

- **What we build:** a small app that each person installs on their own laptop.
  - It opens in the browser at `http://localhost:8080`.
  - You drag in a PDF and it translates in the background while you keep working.
  - You review the English side by side with the original.
  - You download a Word file, a PDF that keeps the original layout, or plain text.
- **Primary model is Gemma 4,** run locally on the laptop's processor through **llama.cpp**, a small engine bundled with the app. Models are downloaded **from Hugging Face** (§4.5). Ollama is not used.
  - It translates **whole paragraphs** with context.
  - It follows the team glossary and handles mixed Hindi and English text and tables.
  - It writes natural English.
  - The same model also **re-reads scanned pages that classic OCR couldn't read**.
- **IndicTrans2 is the safety net.** It is the specialist translation model with the strongest published Hindi-to-English scores.
  - It produces a **quick draft within a few minutes**, so users can read something straight away while Gemma 4 finishes the final version.
  - It takes over for any sentence where Gemma's output fails a check.
  - It takes over the whole job if there isn't enough free memory for Gemma 4.
- **Users can choose the model:** *Auto (recommended)*, *Fast*, *Balanced* or *Best quality*. Only tested models are offered, and options that don't fit the laptop are greyed out (§4.4).
- **A modern interface:** a clean design in light and dark themes that works offline. While a document translates, the page shows progress, time remaining, a live preview of the English, and the **latest tech news headlines** (§9).
- **Runs on an 8 GB laptop with no graphics card.** Only one model is in memory at a time, and the app peaks at about 4.5 GB on 8 GB laptops and about 7 GB on 12 GB laptops. On 8 GB laptops, close heavy apps such as Teams or many Chrome tabs while the final translation runs.
- **Free and local only:** Gemma 4 and every other component are free and openly licensed. There are no paid APIs and no per-page charges. Documents never leave the laptop. The only optional external service is Bhashini (free, Government of India), and it is off by default.
- **The text-extraction step matters most.** Bihar government PDFs often use legacy fonts such as Kruti Dev, or are scans. The pipeline sorts pages by type and extracts each type differently (§3).
- **Fallbacks at every step:**
  - The translation chain is Gemma 4, then IndicTrans2, then an optional third model, then Bhashini if allowed.
  - If memory runs short, a smaller model takes over.
  - Jobs continue after sleep or a restart.
  - A document never just "fails". In the worst case one sentence is marked for human review.
- **Measured, not assumed:** a blind test on real Beltron documents, run on an actual 8 GB laptop, confirms that Gemma 4 as primary beats or matches IndicTrans2 alone and today's Copilot output.
- **Timeline for one developer:** a working version in about 2–3 weeks. About 8 weeks until it is ready for daily use, including a Windows installer.

---

## 2. Requirements

### Functional

| ID | Requirement |
|---|---|
| F1 | Upload one or more PDFs by drag and drop. Default limits are 50 MB and 100 pages per file, both configurable. |
| F2 | Translate Hindi, including code-mixed Hindi and English, into English. |
| F3 | Outputs: **editable Word (.docx)**, **side-by-side web view**, **PDF with the original layout**, and plain text. |
| F4 | Show progress page by page. A **quick draft** appears first and the **final version** follows. Keep a history, and show a Windows notification when a job is done. |
| F5 | Let users correct individual sentences. There is **no approve step**: a saved correction is remembered and reused automatically next time (translation memory). |
| F6 | A glossary **shared by the team** across laptops, for example ज्ञापांक → "Memo No." and कार्यादेश → "Work Order". |
| F7 | **A modern, easy interface** with light and dark themes. A **translation page** that shows a stage tracker, time remaining, a live preview, and a **tech-news panel** while the user waits. |

### Non-functional

| ID | Requirement |
|---|---|
| N1 | **Free and local:** only free, openly licensed models running on the laptop, with **Gemma 4 as the primary model**. No paid APIs or subscriptions. Works with no internet after installation. |
| N2 | **Laptop hardware:** runs on a Windows 10/11 laptop with **8 GB RAM**, 4 CPU cores, **no graphics card**, and about 10 GB of free disk space (20 GB on 12 GB laptops). **Peak memory use: no more than 4.5 GB on 8 GB laptops, and no more than 7 GB on 12 GB laptops.** |
| N3 | **Fallback:** no single failure stops a translation. That includes a crashed model, low memory, a bad scan, a strange font, or the laptop going to sleep. |
| N4 | **Quality:** at least as good as the current Copilot output in a blind review. **No errors in numbers, dates or reference numbers.** |
| N5 | **Privacy:** documents stay on the laptop. Files are deleted automatically after N days. The app listens only on `localhost`. The only routine outbound traffic is downloading **news headlines** (no document data), which an admin can switch off. |
| N6 | **Easy to run:** one installer and a desktop shortcut. Models are downloaded from Hugging Face on first run, or imported from an offline model pack. No Ollama, no Docker, no background service, no admin rights for the model engine, and no command line for users. |
| N7 | **Model choice:** users choose from a short list of tested models, by speed or quality. Every document records which model translated it. |

### Assumptions (to be confirmed)

- The laptops run Windows 10 or 11, with a 4+ core Intel Core i5 or Ryzen 5 class processor (2019 or newer) and an SSD.
- Each person runs their own copy and translates a few documents a day, usually 1–30 pages each.
- Document types: letters, office orders, tenders, RFPs and corrigenda, work orders, empanelment notices and minutes. Many contain **tables, stamps, signatures and handwritten notes**.
- A mix of digitally created PDFs and scans.

### Open questions for Vikram and the team

1. What are the actual volume and typical page counts?
2. May we use **Bhashini** (the free Government of India language API) as an optional fallback for non-confidential documents? Or must everything stay strictly offline? The plan works either way. Bhashini is off by default.
3. **What exact laptop models will run this** (processor, RAM, Windows version, free disk space)? **We need one representative 8 GB laptop to test on in week 1.**
4. **Can IT install software on these laptops?** Is **huggingface.co reachable** from the office network? If it isn't, IT imports the models from an offline **model pack** on a shared drive or USB instead (§4.5).
5. Is **10–20 minutes** for the final translation of a 10-page document acceptable, given that a quick draft is ready in a few minutes? (§11)
6. Which output do people use most: an editable Word file or a PDF that looks like the original?
7. Will we need **English to Hindi** later, for drafting replies to Beltron? Both Gemma 4 and IndicTrans2 can translate in that direction.
8. Who can spend about 2 days as a bilingual reviewer to build the evaluation set (§13)?
9. **Tech news panel:** the sources are decided: **free, general IT news from public RSS feeds** (§9.3.1). Is IT happy for the app to download headlines from those 8 sites? No document data is sent.

---

## 3. Why Hindi PDFs are harder than they look

The translation model is not the main risk. **Most quality is lost before translation starts**, when the text is pulled out of the PDF.

| Page type | What naive copy-paste gives | How we handle it |
|---|---|---|
| **A. Digital, Unicode font** (Mangal, Nirmala UI) | Usually correct, but vowel signs and conjunct letters sometimes come out in the wrong order | Extract the text, check its quality, and run OCR on the page if the check fails |
| **B. Digital, legacy font** (Kruti Dev, DevLys, Chanakya; very common in Bihar government offices) | Latin-letter gibberish. For example, `fcgkj ljdkj` is how **बिहार सरकार** is stored in Kruti Dev | Detect the font name, convert the text to Unicode and check it. Run OCR if the conversion fails |
| **C. Scanned or photographed** | No text at all | OCR |
| **D. Mixed** (typed text plus stamps, signatures and handwritten notes) | Some text is missing | Process each region separately. Flag handwriting for human review |

Other complications:

- Tables, such as bills of quantities and eligibility criteria.
- Devanagari digits (२०२६) and Indian number grouping (5,00,000/-).
- English terms written in Latin script inside Hindi sentences (RFP, GeM, EMD, SLA).
- Reference numbers such as `ज्ञापांक-1234/2026`, which must survive translation exactly.

Types A and B cover most digital Beltron documents. **They need no AI model at all to extract.**

---

## 4. Engines for 8–12 GB laptops

### 4.1 Memory budget

Windows 11 with Outlook, Office and a browser typically uses 3.5–4.5 GB. Gemma 4 E2B as a 4-bit GGUF needs about 4 GB, so:

| Laptop | App peak (during the Gemma 4 stage) | Left for Windows and other apps |
|---|---|---|
| **8 GB** | **~4.5 GB** | ~3.5 GB. Close heavy apps (Teams, many Chrome tabs) during the final translation. |
| **12 GB** | **~7 GB** (Gemma 4 E4B) | ~5 GB. Normal use is fine. |

**Only one model is in memory at a time.** Each stage loads its model, processes the whole document, and unloads it (§6). The **memory guard** checks free memory before loading Gemma 4. If there isn't enough, the job finishes with IndicTrans2 instead of slowing the laptop down.

### 4.2 Engine choices

All engines run on the processor and are free and openly licensed. The RAM column shows roughly how much memory each needs while it runs. We measure the real figures in Phase 0.

| Stage | 8 GB laptop | 12 GB laptop | RAM while running | Role |
|---|---|---|---|---|
| PDF parsing | **PyMuPDF** | same | < 0.3 GB | Text, font names, layout boxes and tables. No model needed. |
| Legacy font conversion | **legacylipi** (Kruti Dev) plus our own mapping tables | same | negligible | For Kruti Dev and similar fonts. |
| OCR, standard (both engines run, better result kept) | **PaddleOCR PP-OCRv5 Devanagari mobile** + **Tesseract 5** `hin+eng` | same | ~0.5–1 GB | Small and fast. Two engines let us cross-check numbers. PaddleOCR must use its **Devanagari model**, because its default multilingual model garbles Hindi. |
| OCR, hard pages (flagged pages only) | **Gemma 4 E2B**, reading the page image | **Gemma 4 E4B**, reading the page image | ~4 / ~6–7 GB | Gemma 4 accepts images directly, so the primary model also re-reads pages that classic OCR couldn't read. PaddleOCR-VL 0.9B is a candidate in the blind test. |
| **⭐ Primary translation** | **Gemma 4 E2B** (4-bit GGUF) | **Gemma 4 E4B** (4-bit GGUF) | **~4 / ~6–7 GB** | Translates whole paragraphs with context. Follows the glossary and translation-memory examples. Handles code-mixed text and tables, and writes natural English. |
| Quick draft and first fallback | **IndicTrans2 1B, Indic→English, int8** (CTranslate2) | same | ~1.5 GB | A specialist translation model with the strongest published Hindi-to-English scores, and fast on CPU. Its draft is ready within minutes. It replaces any Gemma sentence that fails a check, or the whole job if memory is short. |
| Translation when memory is very short | **IndicTrans2 distilled 200M, int8** | same | ~0.4 GB | The last-resort local model. |
| Quality check | **IndicTrans2 English→Indic distilled 200M** (back-translation, §7.3) | same | ~0.4 GB | Cheap. Runs on every sentence. |
| Third opinion (optional) | n/a | **Qwen3.5-4B** (4-bit) | ~3.5 GB | A different model family, used for sentences where both Gemma 4 and IndicTrans2 fail. |
| Optional free external service (**off by default**) | **Bhashini** | same | none locally | Only for documents allowed to leave the laptop. It needs both an admin switch and the user's permission for that document. |

**Excluded:**
- **Gemma 4 E4B on 8 GB laptops.** It uses about 5.5–8 GB depending on the source, which leaves too little for Windows.
- **Gemma 4 26B MoE and 31B.** They need 16 GB or more. They remain only in the optional `workstation` profile (§10).
- **Paid APIs** (Claude, GPT, Gemini API, Google, Azure, DeepL).
- **The free tiers of commercial APIs.** Their terms may let the provider use what we send, and their quotas can change without notice.

### 4.3 What this choice gives and costs

| | Effect |
|---|---|
| ✅ **Context and fluency** | Gemma 4 translates paragraph by paragraph, keeps names and terms consistent, follows glossary instructions, and writes more natural English than a sentence-by-sentence translation model. |
| ✅ **One model, two jobs** | The same Gemma 4 download translates and also re-reads difficult scanned pages. |
| ✅ **Safety net** | Every Gemma sentence is checked (§7.3). A sentence that fails is replaced by IndicTrans2's draft, which is already computed, so it costs no extra time. |
| ⚠️ **Speed** | An LLM writes its output word by word, and on a laptop processor that is slow. Final translation of a 10-page document is about **10–20 minutes**, against 2–4 minutes for IndicTrans2 alone. Because of that, **the quick draft appears first** (§9). |
| ⚠️ **Memory** | On 8 GB laptops the app peaks at about 4.5 GB, so heavy apps should be closed during the final stage. The memory guard falls back to IndicTrans2 if they aren't. |
| ⚠️ **Hindi quality is not yet proven** | We found **no published Hindi-to-English benchmark for the small Gemma 4 models**. IndicTrans2 has the strongest published scores. Small LLMs can occasionally drop or add content. The checks catch that, and the blind test (§13) confirms Gemma 4 as primary on our own documents. If IndicTrans2 turns out better on them, swapping the order is a single line of config. |
| ⚠️ **Hard scans and handwriting** | Small models are weaker than large vision models on bad scans. Expect more amber and red sentences for human review on those pages. |
| ⚠️ **Compared with Copilot** | Copilot uses large cloud models. Our edge is **correct extraction**, **exact numbers**, **consistent terminology**, privacy and no upload limits. The blind test measures overall quality. |

### 4.4 Letting users choose the model

**Recommendation: yes, offer a choice, but from a short tested list, with Auto as the default.** Users don't need to know model names. They choose by what matters to them, speed or quality, and the app works out which model that means on their laptop.

| Choice shown to users | Model used | 10 pages, digital* | Needs |
|---|---|---|---|
| **Auto (recommended, default)** | The best model that fits this laptop and its free memory right now: Gemma 4 E4B on 12 GB laptops, Gemma 4 E2B on 8 GB laptops | Depends on the model | n/a |
| **Fast** | IndicTrans2 only. More literal English, but very quick. | ~2–4 min | 8 GB |
| **Balanced** | Gemma 4 E2B | ~10–15 min | 8 GB |
| **Best quality** | Gemma 4 E4B | ~15–25 min | 12 GB |
| *Alternative* (optional) | Qwen3.5-4B, a different model family | About the same as Balanced | 12 GB |

\*Planning estimates, measured in Phase 0.

**Where users choose:**
- **Settings:** the default for this laptop.
- **Upload:** override the default for one document. For example, *Fast* for a routine circular, *Best quality* for a tender.
- **Review:** re-translate one sentence with a different model.

**Rules that keep it safe and simple:**
- **Only models in the tested catalog are offered** (§4.5). Users can't enter any Hugging Face model, for four reasons:
  - Hindi quality is untested.
  - Some models have non-commercial licences.
  - Many won't fit in 8 GB.
  - Some repositories require running their own code.
- **New models are added by an admin.** A model goes into the catalog only after passing the bake-off (§13).
- **Options that don't fit are greyed out, with the reason.** For example: "Best quality needs a 12 GB laptop".
- **The fallback chain applies whatever the choice.** The chosen model goes first. The IndicTrans2 draft and the other fallbacks stay behind it, so a weaker or failed choice never leaves sentences untranslated.
- **Memory is still protected.** If there isn't enough free memory for the chosen model when the job starts, the app asks the user: "Close other apps, or continue with Balanced?" Auto steps down automatically and says so.
- **Each document records the model that translated it,** in the job history and in the Word file's properties, so results can be traced later.

### 4.5 Where models come from: Hugging Face, no Ollama

**Yes, every model can come straight from Hugging Face, and Ollama isn't needed.** Ollama is essentially a wrapper around **llama.cpp** with its own model library. We use llama.cpp directly, with **GGUF** model files (the compact 4-bit format llama.cpp reads) downloaded from Hugging Face.

| Model | Hugging Face source (pinned in the catalog) | Format | Runs with |
|---|---|---|---|
| Gemma 4 E2B / E4B | `ggml-org/gemma-4-E2B-it-GGUF` (published by the llama.cpp project). For E4B, a matching GGUF repo such as `unsloth/gemma-4-e4b-it-GGUF`. We switch to Google's official repos if they publish 4-bit (QAT) GGUF files. | A 4-bit GGUF file (e.g. Q4_K_M) plus its **`mmproj` vision file**, which is needed for re-reading page images | `llama-server.exe` (llama.cpp CPU build, bundled with the app) |
| IndicTrans2 1B and 200M | `ai4bharat/indictrans2-indic-en-1B`, `ai4bharat/indictrans2-indic-en-dist-200M`, `ai4bharat/indictrans2-en-indic-dist-200M` | Published as PyTorch weights. **Converted once to CTranslate2 int8** on a build machine. | CTranslate2 |
| Qwen3.5-4B (optional) | The official Qwen GGUF repo (confirmed in Phase 0) | 4-bit GGUF | `llama-server.exe` |
| PaddleOCR Devanagari | PaddleOCR's model hub (pinned version) | Paddle or ONNX | RapidOCR / PaddleOCR |
| Tesseract `hin`, `eng` | GitHub `tesseract-ocr/tessdata_best` (not on Hugging Face) | traineddata | Tesseract |

**Why GGUF and llama.cpp rather than loading the standard PyTorch weights:** the full-precision PyTorch weights of Gemma 4 E2B need roughly 2–3× more memory than the 4-bit GGUF and don't fit next to Windows on an 8 GB laptop. The 4-bit GGUF does.

**How downloading works:**
1. **A model catalog** (`models/catalog.yaml`) records, for each model:
   - the Hugging Face repo and **exact commit**
   - file names, size and **SHA-256 checksum**
   - RAM needed, licence and role (translate, re-read or quality check)
   - its bake-off score
2. **First-run setup:**
   - The app reads the laptop's RAM and proposes the model set for it.
   - It downloads them from Hugging Face with `huggingface_hub`, which resumes interrupted downloads and shows a progress bar.
   - It verifies every checksum.
   - Alternatively, **Import model pack** loads the models from a folder or USB drive.
3. **After setup the app runs fully offline** (`HF_HUB_OFFLINE=1`). It never contacts the internet while translating.
4. **Settings, Models page:** see installed models and their disk use, download optional ones (such as Gemma 4 E4B), remove unused ones, and re-verify checksums.

**Office rollout with an offline model pack:**
- IT runs `packaging/build_model_pack.py` once. It downloads the pinned files from Hugging Face, fetches the Tesseract data, converts IndicTrans2 to CTranslate2, and writes a checksum manifest.
- IT puts the pack on a shared drive.
- Each laptop imports the pack. No laptop downloads 5–10 GB on its own, and this works even if the firewall blocks huggingface.co.

**Safety:**
- **Only data-only file formats reach the laptops:** GGUF, CTranslate2, ONNX and traineddata. None of them contain executable code.
- IndicTrans2's Hugging Face repo needs `trust_remote_code` to load in PyTorch. That happens **once, on the build machine**, during conversion, and **never on the laptops**.
- **Pinned commits and checksums** mean a change in an upstream repo can't silently change our model.
- **Hugging Face account:** Gemma 4 (Apache-2.0) and IndicTrans2 (MIT) are reported to be freely downloadable. If any repo asks users to accept terms, the pack builder uses a free Hugging Face account token once. **Laptops never need an account.**

**How Gemma 4 runs (`llama-server.exe`):**
- The app starts it as a child process **only for the Gemma stage**, roughly like this: `llama-server -m gemma-4-E2B-it-Q4_K_M.gguf --mmproj mmproj-gemma-4-E2B.gguf -c 6144 -t <cores-1> --host 127.0.0.1 --port <random>`.
- It stops the process afterwards, which returns all of that memory.
- JSON output is enforced by llama.cpp's **JSON-schema constrained output**.
- It needs no admin rights and no background service, and it listens only on `127.0.0.1`.
- **Fallback:** if antivirus blocks the `.exe`, `llama-cpp-python` runs the same engine inside the app's Python process.

---

## 5. Architecture

```mermaid
flowchart LR
  U["Browser on the same laptop"] -->|"localhost:8080"| A["FastAPI app: API + React UI"]
  A <--> DB[("SQLite: jobs, segments, glossary, TM")]
  A <--> FS[("data folder: uploads, page images, outputs")]
  A --> W["Worker process: stage-by-stage pipeline + fallbacks"]
  W <--> DB
  W <--> FS
  W --> MM["Model manager: one model in RAM, memory guard"]
  MM --> G4["PRIMARY: Gemma 4 E2B / E4B (GGUF) via llama-server (CPU)"]
  MM --> IT2["IndicTrans2 1B / 200M (CTranslate2, CPU)"]
  MM --> OCR["PaddleOCR + Tesseract (CPU)"]
  MM -.-> Q35["Qwen3.5-4B (12 GB only, optional)"]
  A --> MS["Model store: catalog, Hugging Face download / pack import, checksums"]
  MS --> FS
  W -. "only if admin enables" .-> BH["Bhashini (free govt API)"]
```

- **Native Windows install, no Docker.** Docker Desktop sets aside 2 GB or more of RAM, which an 8 GB laptop can't spare.
- **llama.cpp runs Gemma 4.** The bundled `llama-server.exe` is started only for the Gemma stage and stopped afterwards. There is no Ollama and no background service (§4.5).
- **Model store:** reads the catalog, downloads from Hugging Face or imports the offline pack, verifies checksums, and offers only models that fit this laptop (§4.4).
- **Model manager and memory guard:**
  - Before loading any model, the manager checks free memory with `psutil`.
  - If there isn't enough for the model plus a 0.5 GB safety margin, it uses the next model in the chain: Gemma 4 E4B, then E2B, then IndicTrans2 1B, then IndicTrans2 200M.
  - It never pushes the laptop into heavy swapping.
- **One user, one laptop:** the app listens only on `127.0.0.1`, so no login is needed. An optional shared mode with login exists, but is not recommended on 8 GB laptops.
- **Durable job queue in SQLite:** each sentence is saved as soon as it is done. Jobs continue after sleep, shutdown or a crash.
- **Hardware profiles:** at start-up the app reads the installed RAM and picks the `laptop-8gb`, `laptop-12gb` or `workstation` profile (§10).

---

## 6. Processing pipeline

### 6.1 Stages (one model in memory at a time)

| # | Stage | Model in memory | What happens | User sees |
|---|---|---|---|---|
| 1 | Intake | none | Check the file, then render pages to 300 DPI images on disk, one page at a time | Progress bar |
| 2 | Extract | none, or PaddleOCR + Tesseract | Classify each page. Use native text, convert legacy fonts, or run dual OCR. Check numbers between the two OCR engines. | Pages ticked off |
| 3 | **Quick draft** | IndicTrans2 1B | Translate every sentence. Fast. | **"Quick draft ready"**: readable within minutes |
| 4 | **Final translation** | **The chosen model** (Gemma 4 E2B / E4B under Auto) | (a) Re-read the flagged scanned pages from their images. (b) Translate every paragraph, using context, the glossary and translation-memory examples. | Sentences switch from draft to final as they finish |
| 5 | Check | IndicTrans2 English→Indic 200M (+ IndicTrans2 1B for re-read pages) | Back-translate and validate every sentence. Choose the final version of each sentence: Gemma's if it passes, otherwise IndicTrans2's. Re-draft sentences on pages Gemma re-read. | Confidence colours 🟢🟡🔴 |
| 6 | Fallback | Qwen3.5-4B (12 GB only), or Bhashini if allowed | Only for sentences where both Gemma 4 and IndicTrans2 failed | Fewer red sentences |
| 7 | Render | none | DOCX, side-by-side view, layout PDF and TXT | **"Final ready"** and a notification |

### 6.2 Getting the Hindi text (stage 2)

```mermaid
flowchart TD
  PG["PDF page"] --> CLS{"Classify page"}
  CLS -- "Unicode text" --> NX["Native extract (PyMuPDF)"]
  CLS -- "Legacy font" --> LC["Legacy font to Unicode"]
  CLS -- "No text layer" --> O1
  NX --> Q{"Text quality OK?"}
  LC --> Q
  Q -- yes --> SEG["Segment + protect"]
  Q -- no --> O1["Dual OCR: PaddleOCR + Tesseract (CPU)"]
  O1 --> Q2{"Quality OK and numbers agree?"}
  Q2 -- yes --> SEG
  Q2 -- no --> FL["Flag page for Gemma 4 re-read in stage 4"]
  FL --> SEG
```

**Step details:**

- **Classify:**
  - Font names such as `KrutiDev010` or `DevLys` mean a legacy font.
  - Little or no extractable text means a scan.
  - The **Hindi dictionary hit rate** (the share of words that are real Hindi words) measures text quality.
- **Dual OCR:**
  - Clean up the image first (deskew, denoise and adaptive binarisation, using OpenCV).
  - Run PaddleOCR and Tesseract, and keep the better reading by dictionary hit rate.
  - Numbers, dates and reference numbers must agree between the two engines, or the page is flagged.
- **Gemma 4 re-read (stage 4a):**
  - This happens automatically for up to 3 flagged pages in Standard mode, for all flagged pages in Accurate mode, and on request with the "Re-read this page carefully" button.
  - Gemma 4 returns the page's Hindi text, including Markdown tables, and marks `[STAMP]`, `[SIGNATURE]` and `[HANDWRITTEN: …]`.
  - Its reading replaces the classic OCR text only if it scores higher on the dictionary check **and** its numbers match at least one classic OCR engine.
  - If the re-read is rejected, the page stays flagged.
- **Normalise:**
  - Unicode NFC, consistent nukta forms and Devanagari digits converted to ASCII digits.
  - Common OCR confusions checked against the dictionary.
- **Segment and protect:**
  - Split into sentences on `।`, `?` and `!` (Indic NLP Library), keeping paragraphs and table cells together.
  - Numbers, dates, amounts, reference numbers, emails, URLs, Latin-script words and glossary terms are replaced by placeholders such as `⟦N1⟧` and `⟦G3⟧`. They are restored after translation, so no model can corrupt them.

### 6.3 How Gemma 4 translates (stage 4b)

- **Model:** whichever the user chose (§4.4). Gemma 4 is the default through Auto.
- **Unit:** one paragraph or table at a time, about 3–10 sentences. The input numbers each sentence, `[1] … [2] …`.
- **Output:** JSON with one English translation per numbered sentence, `{"1": "...", "2": "..."}`. llama.cpp's **JSON-schema constrained output** enforces this structure. Because each sentence comes back separately, each one can be **checked and replaced on its own**.
- **The prompt contains:**
  - the document subject line
  - the previous paragraph's English, for continuity
  - the glossary terms found in this paragraph
  - up to 2 similar corrected pairs from the translation memory
  - the protected Hindi text
- **Settings:** low temperature (about 0.2, tuned in the bake-off) for consistent output, and a 4–8K context window to keep memory low.
- **Variant tested in the bake-off:** giving Gemma 4 the IndicTrans2 draft as a hint ("Gemma with draft"). Gemma stays the primary translator, and the draft helps it avoid missing anything.

---

## 7. Fallback design

### 7.1 Fallbacks at every layer

| Layer | 1st choice | 2nd | 3rd | Last resort | Moves to next when |
|---|---|---|---|---|---|
| Text extraction | Native (PyMuPDF) | Legacy-font conversion | Dual OCR | n/a | Low dictionary hit rate, or a known legacy font |
| OCR | Dual classic OCR (PaddleOCR + Tesseract) | **Gemma 4 vision re-read** | n/a | Keep the best-scoring reading and flag the page | Low dictionary hit rate, or numbers disagree |
| **Translation** | **The user's chosen model.** Under Auto: Gemma 4 E4B on 12 GB, E2B on 8 GB. | IndicTrans2 1B draft (already computed) | Qwen3.5-4B (12 GB, optional) | Bhashini (if enabled **and** allowed), then keep the Hindi and **flag it red** | A validator fails, timeout, or engine error |
| **Memory** | Gemma 4 E4B (12 GB) / E2B (8 GB) | Gemma 4 E2B (12 GB laptops only) | IndicTrans2 1B | IndicTrans2 200M, then pause and ask the user to close other apps | Free RAM is below what the model needs plus 0.5 GB |
| Runtime | `llama-server.exe` (bundled llama.cpp) | `llama-cpp-python` (the same engine inside Python) | IndicTrans2 only (no LLM) | n/a | The server won't start (for example, blocked by antivirus) or stops responding |
| Model files | Installed model, checksum verified | Re-import from the model pack or re-download from Hugging Face | Next model in the chain | n/a | A file is missing or its checksum doesn't match |
| Output | Layout PDF | DOCX | HTML side-by-side | TXT | A render error or text overflow. TXT is always produced. |
| Power and sleep | n/a | n/a | n/a | Resume from the last saved sentence | The laptop sleeps, restarts or crashes |

### 7.2 Per-sentence flow

```mermaid
flowchart TD
  S["Hindi sentence (placeholders protected)"] --> TM{"Exact match in translation memory?"}
  TM -- yes --> OK["Accept"]
  TM -- no --> G4["PRIMARY: Gemma 4 translates (in its paragraph)"]
  G4 --> V1{"Valid?"}
  V1 -- yes --> AMB{"Back-translation score low?"}
  AMB -- no --> OK
  AMB -- yes --> CMP["Compare with IndicTrans2 draft, keep higher-scoring one"] --> OK
  V1 -- no --> IT["IndicTrans2 draft (already computed)"]
  IT --> V2{"Valid?"}
  V2 -- yes --> OK
  V2 -- no --> Q{"12 GB laptop?"}
  Q -- yes --> Q35["Qwen3.5-4B (third opinion)"] --> V3{"Valid?"}
  V3 -- yes --> OK
  V3 -- no --> B
  Q -- no --> B{"Bhashini enabled + allowed for this document?"}
  B -- yes --> BH["Bhashini (free)"] --> V4{"Valid?"}
  V4 -- yes --> OK
  V4 -- no --> FLAG["Keep Hindi, mark RED: needs human"]
  B -- no --> FLAG
```

### 7.3 Validators (these decide when to fall back)

These are cheap, deterministic checks, run on every sentence:

1. **Placeholders:** every `⟦…⟧` from the source appears in the output exactly once.
2. **Numbers:** the set of numbers in the source equals the set in the output, after converting Devanagari digits. Lakh and crore are kept as written, never converted.
3. **Script:** the output is English, with less than 5% Devanagari characters other than allowed names.
4. **Length ratio:** the ratio of English to Hindi characters stays within bounds. We tune the bounds on our own data, starting at roughly 0.6–2.0. This catches content an LLM **dropped or added**.
5. **No loops or chatter:** no repeated n-grams, and no preamble such as "Here is the translation".
6. **Glossary:** every glossary term found in the source uses the approved English term.
7. **Complete JSON:** every numbered sentence came back, with nothing missing, merged or extra.
8. **Back-translation score:** the small IndicTrans2 English→Hindi model translates the English back to Hindi, and we compare it with the source using chrF. A low score turns the sentence amber and triggers the comparison with IndicTrans2 in §7.2. This check is free and licence-safe (§12).

**Confidence colours in the UI:**
- 🟢 Green: all checks pass and the back-translation score is high.
- 🟡 Amber: a fallback engine was used, the back-translation score is low, or the OCR engines disagreed.
- 🔴 Red: untranslated, or a number or placeholder doesn't match.

Reviewers only need to read the amber and red sentences.

### 7.4 Engine health and the memory guard

- Every Gemma 4 call has a timeout scaled to paragraph length, and is retried once.
- **Circuit breaker:** after 3 Gemma failures in a row (llama-server crashed or timed out), the rest of the job uses IndicTrans2, and the job is marked "finished with fallback".
- **Memory guard:** free RAM is checked before every model load (see the Memory row in §7.1).
- CPU threads are capped at the number of cores minus one, so the laptop stays responsive.

### 7.5 Resilience at job level

- Progress is saved after every page and every sentence. Jobs survive sleep, shutdown and crashes.
- The quick draft always exists before Gemma 4 starts. If anything goes wrong later, users still have a complete translation.
- A job is "done" even when some sentences are red. The UI shows "3 segments need review", never a bare "failed".
- The job log records which engine produced each sentence. The Settings page shows the **fallback rate**. A spike means something is wrong, such as llama-server being blocked or too little memory.

---

## 8. Quality strategy (the best we can do on a laptop)

1. **Fix extraction first** (§3, §6.2). Clean Unicode input is the biggest single gain.
2. **Gemma 4 as the primary translator, with context:** paragraph-sized input, the subject line, the previous paragraph's English, glossary terms and translation-memory examples (§6.3).
3. **Sentence-level control despite paragraph-level translation:** numbered input and JSON output, so every sentence is still checked and replaced on its own.
4. **IndicTrans2 as a second opinion on every sentence:** its draft is always available. When Gemma's sentence fails or scores low, the better-scoring version wins.
5. **Glossary**, enforced through placeholders (which a model can't change) and in the prompt. It is seeded with Beltron and Bihar government terms (Appendix A) and checked by validator 6.
6. **Consistency pass across the document:** the same Hindi name, designation or term always gets the same English throughout.
7. **Translation memory:**
   - Exact matches are reused directly.
   - Close matches are given to Gemma 4 as examples.
   - Beltron letters follow standard formats, so the memory improves quickly.
8. **Team sync for glossary and memory** (§9). Corrections made by one person help everyone.
9. **Human in the loop:** reviewers fix amber and red sentences, and their fixes go into the translation memory.
10. **Measure, don't guess:** blind tests and regression checks run on a real 8 GB laptop (§13).

**Gemma 4 prompt (sketch):**
```
System: You translate Indian government correspondence (Bihar, BELTRON) from Hindi to
English. Translate every numbered sentence completely and faithfully; do not add, drop,
merge or explain. Use GLOSSARY terms exactly. Keep every ⟦…⟧ placeholder unchanged.
Formal Indian-English official style (e.g. "Memo No.", "Copy forwarded to", "By order").
Return JSON: {"1": "...", "2": "...", ...} with one entry per numbered sentence.
User: SUBJECT: <doc subject> | PREVIOUS ENGLISH: <previous paragraph>
      GLOSSARY: <matched terms> | EXAMPLES: <2 similar corrected pairs from TM>
      HINDI:
      [1] <sentence 1>
      [2] <sentence 2> ...
```

---

## 9. Web UI

### 9.1 Look and feel

- **A clean, modern single-page app:**
  - card layout, generous spacing and rounded corners
  - smooth but subtle transitions
  - **light and dark themes**, following the Windows setting
- **Built with free, widely used tools:** Tailwind CSS, shadcn/ui components (accessible, built on Radix) and lucide icons, all MIT or ISC licensed.
- **Fonts bundled with the app:** **Inter** for English and **Noto Sans Devanagari** for Hindi (SIL Open Font License). No Google Fonts or other CDN, so it looks the same offline.
- **Designed for laptop screens** from 1366×768 upward. The Review page has keyboard shortcuts: ↑/↓ to move between sentences, E or Enter to correct one.
- **Accessible:** contrast meets WCAG AA, and colour is never the only signal. Confidence is shown by colour, icon and label together: ✓ Good, ! Check, ✕ Needs human.
- **Light on an 8 GB laptop:**
  - no video backgrounds or heavy animation libraries
  - JavaScript under about 1 MB
  - CSS-only animations that respect Windows' "reduce motion" setting
- **A short style guide in Phase 1** (colours, type and components) keeps every page consistent. The team or Beltron logo is optional.

### 9.2 The translation page (shown while a document is processing)

The final translation can take 10–20 minutes, so this page is designed to make the wait useful:

```
┌────────────────────────────────────────────────────────────────────┐
│  Tender_Notice_2026.pdf                     Balanced · Gemma 4 E2B │
│  ●──────────●──────────◐──────────○──────────○                     │
│  Reading    Quick      Final      Checking   Ready                 │
│  pages      draft ✓    (Gemma 4)                                   │
│  Page 4 of 10 · about 8 min left                                   │
├─────────────────────────────────────────────┬──────────────────────┤
│  Live preview                               │  While you wait      │
│  ┌──────────────┐   English sentences       │  Tech news           │
│  │ Hindi page 4 │   appear here as they     │  • Headline – Source │
│  │  (image)     │   finish, colour-coded    │  • Headline – Source │
│  └──────────────┘                           │  • Headline – Source │
│  [ Open quick draft now ]                   │  (opens in browser)  │
└─────────────────────────────────────────────┴──────────────────────┘
   You can close this page. A notification appears when it's ready.
```

- **Stage tracker and time remaining:** the remaining time is estimated from this laptop's own measured speed.
- **Live preview:** shows the page being processed, with its English sentences appearing as they finish. An **"Open quick draft now"** button appears as soon as the quick draft is ready, so most users start reading within a few minutes.
- **"While you wait" panel:** tech news headlines (§9.3).
- **Close the page at any time.** The job continues, and a Windows notification appears when the final version is ready.

### 9.3 The tech news panel

**Our view: it's a nice touch as a side panel, but it shouldn't be the main content of the page.** Two reasons:
1. The most useful thing to show while waiting is the user's **own document**, since the quick draft arrives within minutes. So the live preview gets the main area.
2. News needs the internet. Until now the plan promised that nothing leaves the laptop. The design below keeps documents completely local and keeps the app working offline.

**How it works:**
- **The backend fetches, and the browser only displays.** The app's backend downloads a few **RSS feeds** every 30–60 minutes and caches the headlines. The browser never loads external pages, scripts, ads or trackers.
- **Headlines only:** title, source, time and a link that opens in the normal browser. **No images** by default. That saves memory and bandwidth on 8 GB laptops and avoids unsuitable pictures.
- **Sources:** **free, general IT and tech news**, from the publishers' own public RSS feeds (§9.3.1). An admin can edit the list, and an optional keyword blocklist filters headlines.
- **No document data is ever sent.** The only outbound requests are plain feed downloads. Even so, this is outbound traffic, so:
  - an **admin switch** in Settings turns the panel on or off, and it is on by default when internet is available
  - the panel **switches itself off when the laptop is offline** or the feeds can't be reached
- **When news is off or offline, the panel shows offline content instead:**
  - a **"Glossary term of the day"** from the team glossary
  - **tips** such as "Press E to edit a sentence"
  - the team's translation stats
- **Security:**
  - Feed text is cleaned to plain text, with no HTML.
  - Links open with `rel="noopener noreferrer"`.
  - The app sets a strict **Content-Security-Policy**, so no external script can run inside it.
- **Effort and cost:** about 1–2 days of work, with negligible memory use.

#### 9.3.1 News sources (free, general IT news)

**Decision:** free, general IT and tech news. The sources are the publishers' own **public RSS feeds**. They are free, need no account or API key, and are meant for exactly this kind of headline-and-link display.

**Starting list.** A mix of Indian and global sources, chosen to be IT-focused and suitable for the office:

| # | Source | Focus | Feed address | On by default |
|---|---|---|---|---|
| 1 | The Hindu: Technology | Indian tech news | `https://www.thehindu.com/sci-tech/technology/feeder/default.rss` | ✅ |
| 2 | ETCIO (Economic Times) | Indian enterprise IT, CIO and government IT | `https://cio.economictimes.indiatimes.com/rss/topstories` | ✅ |
| 3 | MediaNama | Indian tech policy and digital government | `https://www.medianama.com/feed/` | ✅ |
| 4 | Gadgets 360 (NDTV) | Indian consumer tech | `https://feeds.feedburner.com/gadgets360-latest` | ✅ |
| 5 | The Register | Global enterprise IT, software and cloud | `https://www.theregister.com/headlines.atom` | ✅ |
| 6 | BBC News: Technology | Global tech headlines | `https://feeds.bbci.co.uk/news/technology/rss.xml` | ✅ |
| 7 | Ars Technica | Global IT and technology | `https://feeds.arstechnica.com/arstechnica/index` | ✅ |
| 8 | BleepingComputer | Cybersecurity and IT security | `https://www.bleepingcomputer.com/feed/` | ✅ |
| 9 | TechCrunch | Startups and the tech industry | `https://techcrunch.com/feed/` | Optional |
| 10 | Inc42 | Indian startups | `https://inc42.com/feed/` | Optional |

> **Check before go-live:** we couldn't open these feeds from our build environment, because its network blocks news sites. The Hindu, The Register and BleepingComputer addresses appear in public feed directories. The rest are the publishers' usual feed addresses. **Phase 3 tests each one from the office network**, replaces any address that has moved, and confirms that IT allows the sites.

**Excluded:**
- **News APIs** (NewsAPI, GNews and similar). Their free tiers are limited to development or non-commercial use, need API keys, and cap requests.
- **Aggregators of user-posted links**, such as Hacker News or Reddit. Their content isn't edited, so it's harder to keep suitable for the office.
- **Scraping websites that have no feed.** It breaks easily and may go against the site's terms.

**How headlines are shown:**
- **Headline, source name and time only.** Clicking opens the full story on the publisher's site in the normal browser. We don't show full articles, summaries or images. Showing only the headline with a link back is what publishers' RSS terms expect.
- **Attribution as each publisher asks:** for example, BBC headlines are labelled **"BBC News"** and BBC logos are never shown.
- **A fair mix:** sources take turns, so one busy source (The Register publishes a lot) doesn't fill the panel. The panel shows the latest 8–10 headlines, removes duplicates of the same story, and hides anything older than 48 hours.
- **Polite fetching:** every 45 minutes per feed, with a clear app User-Agent. The app re-downloads a feed only when it has changed (ETag and If-Modified-Since), with a 10-second timeout per feed. A failing feed is skipped silently.
- **Terms:** before go-live we read each publisher's RSS terms of use. Any source that doesn't allow headline display inside an internal app is dropped.

**Configuration** (an admin edits this in Settings, or in `config.yaml`):
```yaml
news:
  enabled: true                  # admin switch; auto-off when offline
  refresh_minutes: 45
  max_items: 10
  max_age_hours: 48
  show_images: false
  blocklist: []                  # optional keywords to hide
  sources:
    - { name: "The Hindu – Technology", url: "https://www.thehindu.com/sci-tech/technology/feeder/default.rss" }
    - { name: "ETCIO",                  url: "https://cio.economictimes.indiatimes.com/rss/topstories" }
    - { name: "MediaNama",              url: "https://www.medianama.com/feed/" }
    - { name: "Gadgets 360",            url: "https://feeds.feedburner.com/gadgets360-latest" }
    - { name: "The Register",           url: "https://www.theregister.com/headlines.atom" }
    - { name: "BBC News",               url: "https://feeds.bbci.co.uk/news/technology/rss.xml" }
    - { name: "Ars Technica",           url: "https://feeds.arstechnica.com/arstechnica/index" }
    - { name: "BleepingComputer",       url: "https://www.bleepingcomputer.com/feed/" }
```

### 9.4 Pages

| Page | Features |
|---|---|
| **Upload** | Drag and drop one or more PDFs, and choose outputs and a glossary. **Model:** *Auto (recommended)*, *Fast*, *Balanced* or *Best quality* (§4.4). It defaults to the laptop setting. Options that don't fit are greyed out, with the reason. Every choice except Fast shows the IndicTrans2 quick draft first. A **"Careful re-read of scanned pages"** checkbox makes Gemma 4 re-read all flagged pages, which is slow. If an admin has enabled Bhashini, a checkbox **"Allow Bhashini fallback for this document"** appears, off by default. |
| **Translation page** | Stage tracker, time remaining, live preview, "Open quick draft now" and the news panel (§9.2, §9.3). |
| **Jobs** | Status with **two milestones: "Quick draft ready" and "Final ready"**. A progress bar for each page, counts of segments needing review, download and delete buttons, and a Windows notification when each milestone is reached. On 8 GB laptops, a hint during the Gemma stage: "Close heavy apps for faster results". |
| **Review** | The original page on the left and the English on the right, colour-coded by confidence. You can **start reviewing the quick draft straight away**, and sentences update as Gemma 4 finishes them. Only sentences that are wrong need touching: click **Edit**, fix it and save. The correction is remembered for future documents, with no separate approve step. A sentence can also be **re-translated with another engine**. A **"Re-read this page carefully"** button sends one page to Gemma 4. Includes "Copy all English". |
| **Glossary and memory** | Add, edit, and import or export the glossary as CSV. **Team sync:** point the app to a shared network folder, or export and import a sync file, so every laptop has the team's latest glossary and translation memory. |
| **Settings** | Theme (light, dark or follow Windows), **news panel on/off and its sources** (admin), the **default model** for this laptop, the active profile (8 GB, 12 GB or workstation), current memory use, engine status (llama-server OK or not), fallback rate, retention period and Bhashini on/off. |
| **Settings, Models** | Installed models, with size, licence and checksum status. **Download from Hugging Face** or **import a model pack**. Remove unused models, and re-verify files. Only catalog models are listed. |

The interface is in English with Hindi labels where helpful. It is designed to work for non-technical staff with zero training.

---

## 10. Tech stack and code layout

| Concern | Choice |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic, SQLAlchemy and SQLite (WAL mode) |
| Worker | A separate Python process from the same codebase. It runs one stage at a time from a durable queue in the database, with a capped number of CPU threads. |
| Model manager | Loads and unloads models and checks free memory with `psutil` |
| **Primary model** | **Gemma 4 E2B or E4B, as 4-bit GGUF files from Hugging Face**, run by the bundled **`llama-server.exe`** (llama.cpp, CPU build) as a child process for the Gemma stage only. Options: JSON-schema constrained output, context 4–8K, low temperature, and `--mmproj` for page images. The fallback runtime is `llama-cpp-python`. |
| Model downloads | `huggingface_hub` (resumable, pinned `revision`) driven by `models/catalog.yaml`, with SHA-256 verification, then `HF_HUB_OFFLINE=1` at runtime. An offline model pack is built by `packaging/build_model_pack.py`. |
| PDF | PyMuPDF (pypdfium2 as fallback), OpenCV for image clean-up |
| OCR | PaddleOCR `devanagari_PP-OCRv5_mobile_rec`, run through PaddleOCR or RapidOCR (ONNX Runtime). Tesseract 5 via `pytesseract`, with `tessdata_best` `hin` and `eng`. Gemma 4 vision for re-reads. |
| Fallback translation and quality check | IndicTrans2 via CTranslate2 int8 plus IndicTransToolkit. If CTranslate2 conversion doesn't work, the fallback is ONNX Runtime int8. Sentences are split with the Indic NLP Library. |
| Outputs | python-docx and PyMuPDF |
| Frontend | React, Vite and TypeScript, with **Tailwind CSS**, **shadcn/ui** (Radix) components, **lucide** icons and pdf.js. The **Inter** and **Noto Sans Devanagari** fonts are bundled. It is built to static files (JavaScript under about 1 MB) and served by FastAPI. Live updates use Server-Sent Events. |
| News panel | The backend fetches RSS feeds with `feedparser`, caches them in SQLite every 30–60 minutes, and cleans them to plain text. An admin switch turns it on or off, and it falls back to offline tips. A strict Content-Security-Policy is applied. |
| Packaging | **A Windows installer** (PyInstaller and Inno Setup), or a portable zip. Both include `llama-server.exe`. Models are downloaded from Hugging Face on first run, or imported from the offline model pack (USB or network share). |
| Tests | pytest with PDF test files for every page type (A–D), a **memory test** that fails if peak RAM goes over the profile budget, a **JSON-completeness test** for Gemma output, and the evaluation scripts in `eval/` |

```
pdf-translator/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI routes (upload, jobs, review, glossary, settings)
│   │   ├── config.py               # profiles + settings
│   │   ├── db.py, models.py        # SQLite schema: jobs, pages, segments, glossary, tm, log
│   │   ├── worker.py               # stage-by-stage, resumable job runner
│   │   ├── model_manager.py        # one-model-at-a-time loading + memory guard; starts/stops llama-server
│   │   ├── model_store.py          # catalog, Hugging Face download, pack import, checksums
│   │   ├── sync.py                 # glossary/TM team sync (shared folder or file)
│   │   ├── news.py                 # RSS fetch + cache + sanitise for the "While you wait" panel
│   │   └── pipeline/
│   │       ├── classify.py         # page type A/B/C/D
│   │       ├── extract.py          # native text + legacy-font conversion
│   │       ├── ocr/                # paddle.py, tesseract.py, dual.py, gemma_reread.py
│   │       ├── segment.py          # sentence split, paragraph grouping, placeholder protection
│   │       ├── translate/          # gemma.py (primary), indictrans2.py, qwen.py, bhashini.py
│   │       ├── validate.py         # validators + back-translation + confidence
│   │       ├── select.py           # per-sentence choice: Gemma vs IndicTrans2 vs fallbacks
│   │       ├── consistency.py      # same term → same English across the document
│   │       └── render/             # docx.py, layout_pdf.py, html.py, txt.py
│   └── tests/
├── frontend/                       # React + Vite + Tailwind + shadcn/ui; fonts bundled
├── profiles/                       # laptop-8gb.yaml, laptop-12gb.yaml, workstation.yaml
├── eval/                           # golden set, metrics, bake-off scripts (run on the test laptop)
├── packaging/                      # Windows installer, portable build, build_model_pack.py
├── models/
│   ├── catalog.yaml                # tested models: HF repo, commit, files, sha256, RAM, licence, roles
│   └── store/                      # downloaded model files (git-ignored)
└── docs/                           # user guide, IT install guide
```

**Engine interface.** Every engine implements this interface, which makes fallbacks and swaps simple:
```python
class Translator(Protocol):
    name: str
    ram_gb: float            # what the memory guard checks before loading
    is_external: bool        # True only for Bhashini
    def load(self) -> None: ...
    def unload(self) -> None: ...
    def translate(self, paras: list[Paragraph], ctx: DocContext) -> list[Candidate]: ...
```

**Profiles.** The app picks one automatically from the installed RAM:
```yaml
# profiles/laptop-8gb.yaml
ram_budget_gb: 4.5
cpu_threads: auto                    # cores - 1
default_choice: auto                 # auto | fast | balanced | best   (user can override)
auto_model: gemma4-e2b               # PRIMARY under Auto: translation + page re-read
offered: [fast, balanced]            # "best" (E4B) greyed out on 8 GB laptops
translation_chain: [chosen, indictrans2_1b, bhashini, keep_hindi]
memory_chain: [gemma4-e2b, indictrans2-1b, indictrans2-200m]
quick_draft_model: indictrans2-1b
qe_model: indictrans2-en-indic-200m
ocr: [dual_classic, gemma4_reread]
reread_auto_pages: 3
llama_server: { ctx: 6144, temperature: 0.2, threads: auto, paragraph_max_sentences: 10 }
bhashini: { enabled: false }
limits: { max_mb: 50, max_pages: 100, retention_days: 30 }

# profiles/laptop-12gb.yaml  (differences only)
ram_budget_gb: 7
auto_model: gemma4-e4b
offered: [fast, balanced, best, qwen3.5-4b]
translation_chain: [chosen, indictrans2_1b, qwen3.5-4b, bhashini, keep_hindi]
memory_chain: [gemma4-e4b, gemma4-e2b, indictrans2-1b, indictrans2-200m]

# profiles/workstation.yaml  (optional: 16 GB+ RAM or an NVIDIA GPU)
ram_budget_gb: 24
auto_model: gemma4-31b              # or gemma4-26b (MoE)
```
```yaml
# models/catalog.yaml (one entry shown; repo commits, file names and checksums are filled in during Phase 0)
- id: gemma4-e2b
  label: "Balanced: Gemma 4 E2B"
  source: { hf_repo: ggml-org/gemma-4-E2B-it-GGUF, revision: <commit-sha> }
  files:
    - { name: gemma-4-E2B-it-Q4_K_M.gguf, sha256: <...> }
    - { name: mmproj-gemma-4-E2B-it-f16.gguf, sha256: <...> }   # vision, for page re-read
  runtime: llama-server
  ram_gb: 4.0
  min_profile: laptop-8gb
  licence: Apache-2.0
  roles: [translate, reread]
  bakeoff: { chrf: null, blind_win_rate: null }                  # filled in by Phase 2
```
The profiles refer to models by their catalog `id`. The exact repos, files and quantisation are confirmed in Phase 0.

---

## 11. Hardware, speed and installation

| Profile | Hardware | App memory peak | Primary model | Quick draft (10 pages)* | Final translation (10 pages)* |
|---|---|---|---|---|---|
| **laptop-8gb** (minimum) | 8 GB RAM, 4 cores, SSD, no graphics card | ~4.5 GB | Gemma 4 E2B | Digital: ~2–4 min. Scanned: ~5–8 min. | Digital: **~10–15 min**. Scanned: **~15–20 min**. |
| **laptop-12gb** | 12 GB RAM, 4+ cores, SSD | ~7 GB | Gemma 4 E4B | Same as above | About 1.5× slower than E2B, but better quality. If too slow, the profile can use E2B instead. |
| **workstation** (optional, later) | 16 GB+ RAM or an NVIDIA GPU | Large | Gemma 4 26B MoE or 31B | Seconds | A few minutes. Not required. |

Each page Gemma 4 re-reads adds about 1–3 minutes.

\*These are planning estimates. **Phase 0 measures real time and peak memory on the team's actual laptop**, and we update this table. If the final translation turns out too slow, the options are: use E2B on 12 GB laptops, translate only selected pages with Gemma 4, or use "Quick draft only" for routine documents.

**Disk space:**

| What | Size |
|---|---|
| App, runtimes, IndicTrans2 1B and 200M (both directions), PaddleOCR and Tesseract | ~3 GB |
| Gemma 4 E2B (4-bit GGUF + vision file) | ~4 GB |
| Gemma 4 E4B (4-bit GGUF + vision file), 12 GB profile | ~6 GB |
| Qwen3.5-4B, optional | ~3 GB |
| **Total** | **About 7.5 GB (8 GB profile), and about 13–16 GB (12 GB profile)** |

**Installation:**

1. Run the installer, or unzip the portable build.
2. On first run, the setup page recommends models for this laptop. Click **Download from Hugging Face**, or **Import model pack** from the shared drive or USB. Checksums are verified.
3. Done. The browser opens at `http://localhost:8080`. From then on the app runs offline.

The IT install guide covers silent install for pushing the app to many laptops, antivirus exclusions for the models folder, building and publishing the **offline model pack**, allowing `llama-server.exe` through antivirus, and how to roll out new model versions (a new pack plus an updated catalog).

**Tips for users (also shown in the app):**
- On 8 GB laptops, close Teams and extra Chrome tabs while "Final" is running.
- Keep the laptop plugged in for long jobs.
- If the laptop sleeps, the job continues when it wakes.

**Cost:**

| Item | Cost |
|---|---|
| Models and software | **0**. Gemma 4 and every other component are open-source or have an open-weight licence. |
| Per-page or API charges | **0**. No paid APIs are used. |
| Hardware | **0**. Uses existing laptops. |

---

## 12. Security, privacy and licensing

- **Documents never leave the laptop.** The app and `llama-server` listen only on `127.0.0.1`. The only external paths are:
  - the optional Bhashini adapter, which needs both an admin switch and the user's permission for that document, with every call logged
  - the **news panel**, which downloads public headlines only, sends **no document data**, and can be switched off by an admin
- **Laptops get lost.** Turn on **BitLocker** (Windows disk encryption). Uploads, page images and outputs are deleted automatically after N days (default 30), and users can delete a job immediately.
- **Untrusted files:** PDFs are parsed in the worker process with limits on memory, time and page count. We never run PDF JavaScript. Text from a document is passed to Gemma 4 only as **data to translate**. The prompt tells it to translate, never to follow instructions found in the document. The validators reject any output that isn't a translation.
- **Model files:** pinned Hugging Face commits, SHA-256 checksums and data-only formats on laptops. No remote code ever runs on a laptop (§4.5).
- **Team sync** shares only the glossary and translation memory, never documents. Translation memory can contain sentences from documents, so the shared folder needs the same access control as the documents themselves.

**Licences.** Every component is free to use. Verify each licence on its model card before production.

| Component | Licence | Note |
|---|---|---|
| **Gemma 4 (E2B, E4B; 26B and 31B for workstations)** | **Apache-2.0** | ✅ Free. Primary model. |
| IndicTrans2 (1B, 200M) | MIT | ✅ Free |
| Qwen3.5-4B (optional) | Apache-2.0 (verify on the model card) | ✅ Free |
| PaddleOCR, PaddleOCR-VL, RapidOCR | Apache-2.0 | ✅ Free |
| Tesseract | Apache-2.0 | ✅ Free |
| llama.cpp (`llama-server`, `llama-cpp-python`), CTranslate2, ONNX Runtime | MIT | ✅ Free |
| `huggingface_hub` | Apache-2.0 | ✅ Free |
| React, Vite, Tailwind CSS, shadcn/ui, Radix, lucide icons | MIT / ISC | ✅ Free |
| Inter and Noto Sans Devanagari fonts | SIL Open Font License | ✅ Free. Bundled. |
| `feedparser` (news panel) | BSD-2-Clause | ✅ Free |
| GGUF conversions on Hugging Face (ggml-org, Unsloth) | Same as the original model (Apache-2.0 for Gemma 4) | ✅ Free. Check each repo's licence tag. |
| PyMuPDF | AGPL-3.0 (or commercial) | Fine for an internal tool, but confirm with whoever handles legal. pypdfium2 (permissive) is the drop-in alternative. |
| Bhashini (optional) | Free Government of India service | Check its terms of use and access process before enabling |
| NLLB-200, CometKiwi | Non-commercial | ❌ **Not used.** This is why our quality check uses back-translation instead. |
| legacylipi | Check | Confirm before adopting, or replace with our own mapping tables |

---

## 13. Evaluation and acceptance criteria

**Golden set (built in Phase 0, by one bilingual reviewer in about 2 days):**
- 30–50 real documents covering page types A–D, tables and stamps.
- 20 scanned pages with hand-checked Hindi text, to measure OCR quality as character error rate.
- 150–200 sentences with reference English translations.
- Copilot outputs for 15 documents, as today's **baseline**.

**Every test runs on a representative 8 GB laptop** (and a 12 GB one if available), measuring quality, **time** and **peak RAM**.

The bake-off also produces the **speed and quality labels** shown in the model choice (§4.4), and decides which models go into the catalog.

**Candidates (all free and local, all from Hugging Face):**
- **Primary configurations:**
  - **Gemma 4 E2B** direct
  - **Gemma 4 E4B** direct (12 GB)
  - **Gemma 4 with the IndicTrans2 draft as a hint** (E2B and E4B)
  - **Gemma 4 + IndicTrans2 safety net** (§7.2), the planned default
- **Comparisons:**
  - IndicTrans2 1B alone
  - Qwen3.5-4B direct
  - TranslateGemma 4B direct
- **OCR:**
  - Tesseract
  - PaddleOCR Devanagari
  - Dual OCR
  - Gemma 4 E2B and E4B vision re-read
  - PaddleOCR-VL 0.9B
- **Baseline only:** Copilot. It is not part of the system.

**Metrics:**
- **Automatic:** chrF++ and COMET (`wmt22-comet-da`) against the references, plus OCR character error rate.
- **Human, blind:** the reviewer sees two anonymous translations side by side and picks the better one. The reviewer also counts **critical errors** (wrong number, date, name, negation or obligation) and **omissions** (content dropped).

**Acceptance criteria for go-live:**

| Criterion | Target |
|---|---|
| Gemma 4 primary vs IndicTrans2 alone | **At least as good** in the blind test (wins plus ties ≥ 50%). If it isn't, we report it and you decide whether to swap the order (one config line). |
| Blind comparison with Copilot | **At least as good overall** (wins plus ties ≥ 50%), and **better on numbers and terminology** |
| Critical errors and omissions | **0** in the golden set, after validators and fallbacks |
| Glossary terms used correctly | **≥ 95%** |
| Documents that finish (any confidence) | **100%** |
| Peak RAM used by the app | **≤ 4.5 GB** (8 GB profile), **≤ 7 GB** (12 GB profile) |
| 10-page document on the 8 GB test laptop | Quick draft **≤ 5 min**. Final **≤ 15 min** digital, **≤ 20 min** scanned, excluding re-read pages. |
| Laptop stays usable during a job | Office, Outlook and the browser stay usable. On 8 GB laptops, Teams and many tabs may need closing during the final stage. |

The bake-off is **rerun every quarter**. Small models are improving fast, and the plug-in design makes switching a config change.

---

## 14. Roadmap (one developer)

| Phase | Weeks | Deliverables | Done when |
|---|---|---|---|
| **0. Discovery and setup** | 1 | Get **one representative 8 GB laptop**. Collect 50 sample PDFs and sort them by type A–D. Record the Copilot baseline. Seed the glossary with 100–200 terms. **Spikes on the laptop:** **Gemma 4 E2B and E4B RAM, speed and Hindi quality on 30 sentences**; IndicTrans2 int8 conversion and speed; PaddleOCR Devanagari and Tesseract on 5 scans; Gemma 4 vision on 3 bad scans. **Run Gemma 4 GGUF + mmproj with `llama-server.exe` on the laptop.** Choose the exact Hugging Face repos and quantisation, and record commits and checksums. Check that huggingface.co is reachable from the office. | Real speed and memory numbers recorded. Samples and baseline ready. |
| **1. MVP** | 2–3 | FastAPI app, upload, job queue and stage-by-stage worker, model manager. Type A extraction and Tesseract OCR. Segmentation and placeholders. **IndicTrans2 quick draft plus Gemma 4 final translation through `llama-server`, with JSON output.** A first model catalog and a Hugging Face download script. Basic validators. DOCX and side-by-side output. **The modern UI foundation** (style guide, Tailwind and shadcn/ui, light and dark themes) and **the translation page** with stage tracker, time remaining and live preview. A start script for the test laptop. | **The team translates real Beltron documents with Gemma 4 on an 8 GB laptop** |
| **2. Quality and fallbacks** | 3–5 | Page classifier and legacy-font conversion. Dual OCR with number cross-check, image clean-up and tables. Gemma 4 page re-read. Memory guard and profiles. **Model choice (Auto, Fast, Balanced, Best quality).** All validators, back-translation, per-sentence selection, the Qwen3.5 third opinion and the circuit breaker. Consistency pass. Prompt tuning. **Bake-off on the laptop.** | Bake-off report written, defaults confirmed and acceptance criteria met |
| **3. Review and reuse** | 5–6 | Sentence editor with live updates from draft to final, "Re-translate with…", "Re-read this page carefully", translation memory, glossary admin and **team sync**. **The tech news panel** with admin switch, offline tips and the source list from §9.3.1. Each feed is tested from the office network and its terms checked (1–2 days). | Corrections reach every laptop |
| **4. Packaging and hardening** | 6–8 | **Windows installer and portable build** (with `llama-server.exe`), **first-run model download**, **Settings, Models page**, and the **offline model pack builder**. Retention and auto-delete. Layout-preserving PDF. Notifications. Settings page. Optional Bhashini adapter, if approved. User guide and IT install guide. **Pilot on 3–5 team laptops.** | **Go-live** |
| **5. Later (optional)** | n/a | English → Hindi for replies, other Indian languages, a shared workstation profile with Gemma 4 26B or 31B if a bigger machine becomes available | Prioritised by usage |

---

## 15. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| **Gemma 4 is slow on a laptop processor** | Final translation takes 10–20 minutes or more | The quick draft is ready first and users can start reviewing it. Gemma translates whole paragraphs to cut overhead. The 12 GB profile can drop to E2B. "Quick draft only" mode covers routine documents. Phase 0 measures the real speed. |
| **Not enough free RAM for Gemma 4** (Teams, Chrome tabs) | The laptop lags, or Gemma can't load | The memory guard. Gemma 4 loads only for its stage. Falls back to IndicTrans2 automatically, and the app suggests closing other apps. |
| **Small Gemma 4 models are weaker at Hindi than expected** | Lower quality than IndicTrans2 alone | Every sentence is checked against the IndicTrans2 draft and the better one wins. The bake-off measures this, and the chain order is one config line. |
| **An LLM drops, adds or merges content** | Silent errors | Numbered JSON output, a completeness check, length ratio, number and placeholder checks, and the back-translation score. Any failed sentence is replaced by the IndicTrans2 draft. |
| IT blocks software installation, or antivirus flags `llama-server.exe` | No rollout | A portable build that needs no admin rights. An antivirus exclusion for the app folder. `llama-cpp-python` as the in-process fallback. Involve IT in week 1 (question 4). |
| **huggingface.co blocked, or slow downloads in the office** | Models can't be installed | The **offline model pack** from a shared drive or USB. Each laptop never needs to download on its own. |
| **An upstream Hugging Face repo changes or disappears** | Different or missing model | Pinned commits and checksums. A copy of every pinned file is kept in our own model pack on the shared drive. |
| **News panel: feeds blocked, offline, or an unsuitable headline** | Empty panel, or awkward content at work | Offline tips when feeds can't be reached. Curated sources, an optional keyword blocklist, no images, and an admin switch. |
| **Users pick a slow or unsuitable model** | Long waits or weaker results | Auto as the default, clear speed and quality labels, greyed-out options that don't fit, and fallbacks that work whatever the choice |
| Hard scans and handwriting | Missing or wrong text | Dual OCR with number cross-check, the Gemma 4 re-read with checks, and human review |
| IndicTrans2 doesn't convert to CTranslate2 | Slower quick draft | ONNX Runtime int8, or PyTorch dynamic int8. Tested in Phase 0. |
| Glossaries and memories drift apart across laptops | Inconsistent terminology | Team sync through a shared folder or a sync file |
| A lost or stolen laptop holding documents | Data exposure | BitLocker, automatic deletion and no cloud copies |
| Copilot reads more fluently on some sentences | Users prefer Copilot for some documents | Gemma 4 narrows the fluency gap. Our advantages: extraction, numbers, terminology, privacy, no upload limits. |
| Legacy-font variants we don't recognise | Gibberish text | The dictionary hit rate catches it and the page is sent to OCR. We add mapping tables as new fonts appear. |
| Licence problems | Legal exposure | The licence table in §12. No non-commercial models. |

---

## 16. Next steps (this week)

1. Share this plan with Vikram and get answers to the **open questions** in §2, especially the **laptop models**, **whether huggingface.co is reachable** (or whether we use the offline model pack), and whether **10–20 minutes for the final version** is acceptable.
2. **Get one representative 8 GB laptop.** Download Gemma 4 E2B (GGUF) from Hugging Face and run it with `llama-server.exe`, to test speed and memory first, since this is the biggest unknown.
3. Collect about 50 sample Beltron PDFs and keep the Copilot output for 15 of them.
4. Find a bilingual reviewer for about 2 days in Phase 0 and Phase 2.

---

## Appendix A: Seed glossary (Beltron and Bihar government)

| Hindi | English |
|---|---|
| बिहार स्टेट इलेक्ट्रॉनिक्स डेवलपमेंट कॉरपोरेशन लिमिटेड / बेल्ट्रॉन | Bihar State Electronics Development Corporation Ltd. (BELTRON) |
| सूचना प्रावैधिकी विभाग | Department of Information Technology |
| प्रबंध निदेशक | Managing Director |
| अपर मुख्य सचिव / प्रधान सचिव / सचिव | Additional Chief Secretary / Principal Secretary / Secretary |
| ज्ञापांक | Memo No. |
| पत्रांक | Letter No. |
| दिनांक | Date / dated |
| सेवा में | To |
| विषय | Subject |
| प्रसंग / संदर्भ | Reference |
| महाशय / महोदय | Sir / Sir/Madam |
| उपर्युक्त विषय के संबंध में | With reference to the above-mentioned subject |
| अधोहस्ताक्षरी | the undersigned |
| आदेश से | By order |
| विश्वासभाजन | Yours faithfully |
| संलग्नक / अनुलग्नक | Enclosure / Annexure |
| प्रतिलिपि | Copy forwarded to |
| सूचनार्थ एवं आवश्यक कार्रवाई हेतु प्रेषित | Forwarded for information and necessary action |
| कार्यालय आदेश | Office Order |
| अधिसूचना | Notification |
| संकल्प | Resolution |
| निविदा | Tender |
| निविदा आमंत्रण सूचना | Notice Inviting Tender (NIT) |
| शुद्धि पत्र | Corrigendum |
| कार्यादेश | Work Order |
| सूचीबद्धता / पैनलबद्धता | Empanelment |
| अग्रधन राशि | Earnest Money Deposit (EMD) |
| वित्तीय वर्ष | Financial Year (FY) |
| लाख / करोड़ | lakh / crore (keep Indian units) |
| एतद् द्वारा | hereby |

## Appendix B: References used for engine choices

- Gemma 4 release (Apache-2.0; E2B, E4B, 26B MoE and 31B; image input on all sizes): <https://alternativeto.net/news/2026/4/google-releases-gemma-4-open-weight-ai-models-with-apache-2-0-license>
- Gemma 4 memory needs when run locally (Unsloth): <https://unsloth.ai/docs/models/gemma-4>
- Gemma 4 E2B GGUF for llama.cpp (ggml-org): <https://huggingface.co/ggml-org/gemma-4-E2B-it-GGUF>
- Gemma 4 E4B GGUF (Unsloth): <https://huggingface.co/unsloth/gemma-4-e4b-it-GGUF>
- Gemma 4 licence and Hugging Face access (Apache-2.0, reported ungated): <https://vorplabs.com/models/gemma-license>
- IndicTrans2 Indic→English 1B on Hugging Face (MIT): <https://huggingface.co/ai4bharat/indictrans2-indic-en-1B>
- Gemma 4 model sizes (QAT builds): <https://codersera.com/blog/how-to-run-gemma-4-with-ollama-setup-guide/amp/>
- Gemma 4 E4B memory in practice (16 GB Mac mini): <https://brain.ansonbiggs.com/Gemma-4-on-M4-Mac-Mini>
- IndicTrans2 paper: <https://arxiv.org/pdf/2305.16307>
- Hindi chrF++ comparison of IndicTrans2, Sarvam-Translate and TranslateGemma (on a competitor's model card, so treat with care): <https://huggingface.co/bodhan-ai/indic-translate>
- "Can OCR-VLMs Read Devanagari?" (June 2026 benchmark): <https://arxiv.org/abs/2606.29213v1>
- Why extracting Hindi text from PDFs is hard: <https://digitalorientalist.com/2025/12/02/why-extracting-hindi-text-from-pdfs-is-so-much-harder-than-english-and-how-you-can-do-it/>
- legacylipi (legacy font to Unicode): <https://pypi.org/project/legacylipi/>
- PP-OCRv5 multilingual and Devanagari recognition: <https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.html>
- PaddleOCR Hindi needs the Devanagari model (iText knowledge base): <https://kb.itextpdf.com/itext/pdfocr-paddleocr-model-support>
- PaddleOCR-VL: <https://www.paddleocr.ai/latest/en/version3.x/algorithm/PaddleOCR-VL/PaddleOCR-VL.html>
- Qwen3.5 small models: <https://gigazine.net/gsc_news/en/20260303-qwen-3-5-small>
- CTranslate2 (int8 CPU inference): <https://github.com/OpenNMT/CTranslate2/>
- Bhashini (Government of India language platform): <https://bhashini.gov.in>
- The Hindu RSS feeds (directory listing): <https://feeder.co/discover/site/thehindu.com>
- The Register feed: <https://feeder.co/discover/3ff67330bc/theregister-com>
- BleepingComputer feed in a threat-intelligence source list: <https://knowledge.threatconnect.com/docs/cal-automated-threat-library-atl-supported-blogs>
- BBC News RSS attribution guidance (archived): <https://webarchive.archive.unhcr.org/20170807165546mp_/http://www.bbc.com/news/10628494>
