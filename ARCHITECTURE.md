# Architecture — iCargo AWB Intelligent Processor (PoC)

> Status: Proof of Concept
> Version: 1.6.0
> Owner: MSC Air Cargo

---

## 1. Purpose

This repository implements a document-intelligence workflow for Air Waybill (AWB) review and validation.

The current codebase focuses on:

1. Ingesting PDF and email-based AWB documents.
2. Splitting multi-AWB PDFs into logical document ranges before extraction.
3. Extracting MAWB and HAWB fields with a vision-first AI pipeline.
4. Comparing extracted data with the iCargo IBS system.
5. Surfacing discrepancies through a Streamlit UI and a lightweight FastAPI endpoint layer.

---

## 2. High-Level Runtime Architecture

```text
┌───────────────────────────────────────────────────────────────────────┐
│                         Presentation Layer                               │
│  Streamlit Web App  •  FastAPI HTTP endpoints (optional)              │
└───────────────────────────────┬───────────────────────────────────────┘
                                │
                    ┌───────────▼───────────┐
                    │    Workflow Entry     │
                    │ app/main.py           │
                    │ UI_MODE=streamlit/api │
                    └───────────┬───────────┘
                                │
        ┌───────────────────────┼───────────────────────┐
        │                       │                       │
┌───────▼────────┐   ┌──────────▼──────────┐   ┌────────▼──────────┐
│ PDF workflow    │   │ Email workflow     │   │ AWB lookup        │
│ pdf_upload.py   │   │ email_upload.py    │   │ awb_lookup.py     │
└───────┬────────┘   └──────────┬──────────┘   └────────┬──────────┘
        │                       │                       │
        └────────────┬──────────┘                       │
                     │                                  │
        ┌────────────▼─────────────────────────────────────┐
        │               Extraction & Interpretation          │
        │  AwbDocumentPreSplitter → AwbVisionExtractor      │
        │  PDFTextExtractor / OCR fallback                  │
        └────────────┬─────────────────────────────────────┘
                     │
        ┌────────────▼─────────────────────────────────────┐
        │             Integration & Comparison               │
        │ ICargoIBSClient → AwbRepository / AwbDiffEngine   │
        └────────────────────────────────────────────────────┘
```

---

## 3. Current Code Architecture

### 3.1 Entry Point

The launcher in [app/main.py](app/main.py) selects the UI runtime from the `UI_MODE` environment variable:

- `streamlit` → launches the Streamlit shell
- `api` → launches FastAPI through Uvicorn

This makes the application a single repository with two front ends sharing the same core modules.

### 3.2 User Interface Layer

The current UI is built around Streamlit:

- [app/ui/web_streamlit.py](app/ui/web_streamlit.py)
  - app shell
  - page routing
  - branding and layout
- [app/ui/pages/pdf_upload.py](app/ui/pages/pdf_upload.py)
  - main PDF ingestion workflow
  - AWB splitting and extraction
  - comparative rendering of extracted vs iCargo fields
- [app/ui/pages/email_upload.py](app/ui/pages/email_upload.py)
  - email intake placeholder for `.eml` processing
- [app/ui/pages/awb_lookup.py](app/ui/pages/awb_lookup.py)
  - direct AWB lookup against the iCargo system

The API surface is exposed by [app/ui/web_fastapi.py](app/ui/web_fastapi.py). It provides a small set of endpoints for PDF extraction and iCargo lookup.

### 3.3 Ingestion Layer

The ingestion layer is responsible for reading raw artefacts and handing them to the extraction pipeline.

Relevant modules:

- [app/ingestion/pdf_ingestor.py](app/ingestion/pdf_ingestor.py)
- [app/ingestion/email_ingestor.py](app/ingestion/email_ingestor.py)

The flow is intentionally file-first: the application receives a PDF or email blob, then converts it into an internal extraction-friendly representation.

### 3.4 Extraction Layer

This is the core intelligence layer.

#### 3.4.1 PDF text and OCR extraction

- [app/extraction/pdf_text_extractor.py](app/extraction/pdf_text_extractor.py)
  - reads PDF content
  - uses native PDF text extraction when possible
  - falls back to OCR-oriented processing for ambiguous pages

#### 3.4.2 Pre-splitting before extraction

- [app/extraction/awb_document_presplitter.py](app/extraction/awb_document_presplitter.py)

This module is the most important architectural feature of the current PoC. It splits a multi-document PDF into page ranges belonging to one logical MAWB block before the AI extraction stage starts.

The strategy is based on:

- fuzzy matching of AWB header markers
- fallback to MAWB phrase markers
- page clustering and document boundary detection

This is intentionally designed to avoid OCR or model context bleeding between adjacent AWBs.

#### 3.4.3 Vision extraction

- [app/interpretation/awb_vision_extractor.py](app/interpretation/awb_vision_extractor.py)
- [app/llm/claude_vision_provider.py](app/llm/claude_vision_provider.py)
- [app/llm/msc_tech_ai_provider.py](app/llm/msc_tech_ai_provider.py)

The current production path is driven by Claude Vision. The extractor:

- renders PDF page ranges to images
- sends them directly to the chosen provider
- parses the returned structured JSON into the AWB schema

The repository also supports an MSC Tech AI handoff provider, where the image work is written to a folder-based inbox/outbox instead of directly calling an API.

### 3.5 Interpretation Layer

These modules normalize and shape the extracted content into data structures:

- [app/interpretation/awb_schema.py](app/interpretation/awb_schema.py)
- [app/interpretation/awb_normalizer.py](app/interpretation/awb_normalizer.py)
- [app/interpretation/awb_number.py](app/interpretation/awb_number.py)
- [app/interpretation/awb_llm_parser.py](app/interpretation/awb_llm_parser.py)
- [app/interpretation/awb_field_detector.py](app/interpretation/awb_field_detector.py)
- [app/interpretation/awb_table_parser.py](app/interpretation/awb_table_parser.py)

This layer provides the schema, numeric normalization, string cleanup, and field-detection logic used downstream by the comparison workflow.

### 3.6 Comparison Layer

The comparison flow is split between two modules:

- [app/compare/awb_diff_ibs.py](app/compare/awb_diff_ibs.py)
  - maps extracted data into a comparison-friendly structure
  - computes field-level differences versus iCargo values
- [app/comparison/awb_diff_engine.py](app/comparison/awb_diff_engine.py)
  - typed diff engine used to produce structured comparison results

This is where the PoC turns extraction output into operational discrepancies for review.

### 3.7 Integration Layer

The external system integration is centered on the iCargo HTTP client:

- [app/integration/icargo_ibs_client.py](app/integration/icargo_ibs_client.py)
- [app/integration/awb_repository.py](app/integration/awb_repository.py)

Current responsibilities:

- authenticate against the iCargo auth endpoint
- retrieve AWB, booking, tracking, route, and HAWB-related records
- hand off the returned payload to the comparison layer

### 3.8 Pipeline Layer

Headless runners are available for scripted or test execution:

- [app/pipelines/run_from_pdf.py](app/pipelines/run_from_pdf.py)
- [app/pipelines/run_from_email.py](app/pipelines/run_from_email.py)

These pipelines are the repo’s batch-oriented entry points and generally mirror the same flow shown in the UI, but without the Streamlit interaction.

---

## 4. Main Processing Flow

The current end-to-end PDF path is:

1. User uploads a PDF through the Streamlit page.
2. The app ingests the binary content.
3. `AwbDocumentPreSplitter` groups pages into MAWB blocks.
4. Each block is rendered and sent to the selected vision provider.
5. The provider returns structured JSON with MAWB + HAWB fields.
6. The result is normalized and compared with the iCargo record.
7. The UI displays extracted data and diff outcomes.

A simplified view:

```text
PDF upload
  → PDFIngestor
  → PDFTextExtractor / OCR preprocessing
  → AwbDocumentPreSplitter
  → AwbVisionExtractor
  → ClaudeVisionProvider or MscTechAiProvider
  → AwbNormalizer / AWB schema mapping
  → ICargoIBSClient / AwbRepository
  → AwbDiffEngine
  → Streamlit diff rendering
```

---

## 5. Runtime Configuration

The application relies on environment variables from `.env`.

Key configuration areas:

- UI runtime selection
  - `UI_MODE`
- Anthropic / Claude
  - `ANTHROPIC_API_KEY`
  - `CLAUDE_MODEL`
  - `CLAUDE_TIMEOUT`
- iCargo connectivity
  - `ICARGO_BASE_URL`
  - `ICARGO_USERNAME`
  - `ICARGO_PASSWORD`
  - `ICARGO_TIMEOUT`
- MSC Tech AI handoff
  - `MSC_TECH_PNG_FOLDER`
  - `MSC_TECH_JSON_FOLDER`
  - `MSC_TECH_GROUP_LABEL`

The settings abstraction is defined in [app/config/settings.py](app/config/settings.py), though the runtime still relies heavily on direct `os.getenv(...)` reads in the active modules.

---

## 6. Design Notes

### Strengths of the current architecture

- clear separation between UI, extraction, normalization, comparison, and integration
- document-oriented pre-splitting reduces contamination between AWBs
- vision-first extraction is better aligned with real AWB layouts than pure text regex parsing
- support for both Claude and MSC Tech AI providers keeps the execution path flexible

### Current limitations

- the email workflow is only partially wired
- some modules still have legacy compatibility paths that reflect previous implementations
- configuration is still spread across local environment variables and module-level defaults

---

## 7. Practical Repository Summary

The repository is best understood as a layered PoC with three operational pillars:

1. Ingest and prepare documents
2. Extract AWB structure using vision-first AI
3. Compare extracted values with iCargo records

That is the architecture represented by the current source tree and runtime behavior.

- **Weights / numeric fields:** parse from various formats (`"150 kg"`, `{"value":150,"unit":"kg"}`, `150.0`).
- **AWB numbers:** normalise to `NNN-NNNNNNNN` format.

**HAWB matching strategy (UI — `pdf_upload.py`):**

When the user clicks *Fetch & Compare iCargo*, HAWBs from the PDF are matched to iCargo HAWBs **by number** rather than by position:

1. `_ic_num(h)` extracts the HAWB number from the iCargo record, checking `hawb`, `hawb_number`, `hawbNumber`, `houseAirwaybillNumber`, `hawbNo` in priority order.
2. Both sides are normalised with `_norm_hawb_key`: strip spaces/dashes, remove leading zeros, uppercase.
3. A dict `ic_by_norm` maps normalised key → iCargo record.
4. For each PDF HAWB, lookup is done on the normalised key.
5. **Fallback:** if zero matches are found across all PDF HAWBs (format mismatch), the comparison falls back to positional order with a visible warning.
6. **Orphans:** PDF HAWBs with no iCargo counterpart are shown as *"solo PDF"*; iCargo HAWBs not matched by any PDF HAWB are shown as *"solo iCargo"*.
7. An expander shows the raw iCargo JSON response for debugging.

---

### 4.6 UI — Streamlit (`web_streamlit.py`)

Single-page application with a simple client-side router stored in `st.session_state["page"]`.

**Pages:**

| Route          | File               | Description                              |
|----------------|--------------------|------------------------------------------|
| `landing`      | `web_streamlit.py` | Hero landing with workflow selector      |
| `pdf_upload`   | `pdf_upload.py`    | Full PDF → split → Vision → compare flow |
| `email_upload` | `email_upload.py`  | .eml intake (placeholder for extension)  |

**Supported upload formats:**

| Format | Behaviour |
|--------|-----------|
| Single `.pdf` | Processed as a single source file (existing behaviour) |
| `.zip` archive | All `.pdf` files inside are extracted (sorted by name, `__MACOSX` entries skipped), then processed as a batch — each PDF goes through presplit + Claude Vision independently |

In batch (ZIP) mode the source PDF name is displayed alongside each MAWB result and added as a `source_pdf` column in the CSV export.

**Session state keys used by `pdf_upload`:**

| Key                   | Type         | Description                                                        |
|-----------------------|--------------|--------------------------------------------------------------------|
| `pdf_name`            | `str`        | Uploaded file name — change detector to reset all downstream state |
| `batch_pdfs`          | `list[dict]` | Normalised list of `{"name", "bytes"}` — one entry per PDF         |
| `raw_pdf_bytes`       | `bytes`      | First PDF bytes (kept for single-file debug panel compatibility)   |
| `split_documents`     | `list[dict]` | Pre-split result across all PDFs; each entry carries `_pdf_bytes` and `_pdf_name` |
| `split_mode`          | `str`        | `"fast"` or `"normale"`                                            |
| `awb_results`         | `list[dict]` | Claude Vision extraction results; each entry carries `_pdf_name`  |
| `vision_refined_awbs` | `dict`       | Per-AWB re-extraction overrides                                    |
| `debug_page_texts`    | `dict`       | Raw page text cache for the debug panel (first PDF only)           |

**UI workflow (pdf_upload page):**

1. **Upload** — user drops a PDF or a ZIP; for ZIP the contained files are listed in a collapsible expander.
2. **Pre-split** — runs automatically; processes each PDF in the batch sequentially.
3. **🔍 Debug split** *(expander)* — raw page text + document boundaries for the first PDF (ZIP batch: labelled accordingly).
4. **🖼 Preview rendered pages** *(expander)* — renders all pages across all PDFs with orientation correction applied and packages them into a ZIP. File names use the path `{pdf_stem}/{awb_number}/page_001_rot90.png`. Use this to verify orientation before spending API credits.
5. **🚀 Extract all with Claude Vision** — calls Claude for every detected AWB block across all PDFs.
6. **Results** — MAWB + HAWB fields displayed; each result shows its source PDF name in ZIP mode; re-extract per AWB; download JSON; compare with iCargo.

---

## 5. Data Flow — PDF Workflow

```
User uploads PDF or ZIP
       │
       ▼  (_extract_pdfs_from_upload)
[ZIP] unzip → sort PDFs by name → List[{ name, bytes }]
[PDF] wrap as single-item list
       │
       ▼  (for each PDF in batch)
AwbDocumentPreSplitter.presplit_pdf_fast / presplit_pdf_with_text
  → List[{ awb_number, start_page, end_page, text, page_rotations,
            _pdf_name, _pdf_bytes }]
  │
  │  Smart mode runs TWO parallel Tesseract tasks per scanned page:
  │    • PSM 6, OEM 1  (top 20%)   → boundary-detection text
  │    • PSM 0, OEM 0  (full page) → per-page rotation correction angle
  │                                   via the 5-step cascade:
  │                                   w>h dim → OSD conf≥3 (non-zero) →
  │                                   4-rotation body probe → OSD zero →
  │                                   OSD retry at 90° CCW
  │  page_rotations: { page_num → CCW_degrees }  (only non-zero entries stored)
       │
       ├──► [optional] 🖼 Preview PNG ZIP (no Claude call)
       │         renders pages from each source PDF with orientation correction
       │         folder structure: {pdf_stem}/{awb_number}/page_001_rot90.png
       │         → user verifies upright images before spending credits
       │
       ▼  (for each document — uses doc["_pdf_bytes"] not the first-PDF shortcut)
ClaudeVisionProvider._render_pages(doc["_pdf_bytes"], start_page, end_page, page_rotations)
  │   per page: apply OSD correction → fallback landscape heuristic → no rotation
  │   → portrait PNG, base64-encoded
       │
       ▼
ClaudeVisionProvider.extract_mawb_with_hawbs_json  → raw JSON string
       │
       ▼
AwbVisionExtractor.extract_mawb_with_hawbs
  → { "mawb": {...}, "hawbs": [{...}, ...] }
       │
       ├──► Rendered in UI (_awb_form / _hawb_form)
       │
       └──► [optional] ICargoIBSClient.get_awb(awb_number)
                → icargo_raw JSON
                → map_icargo_awb_ibs(icargo_raw)  → flat dict
                → diff_awb(extracted, icargo_flat) → DiffRow list
                → Rendered as dataframe in UI

            [optional] ICargoIBSClient.get_hawbs(awb_number)
                → hawbs_resp JSON  (key "hawb" carries the HAWB number)
                → _flatten_hawbs_resp()  → ic_hawb_list
                → match by normalised HAWB number (strip dashes/spaces/leading zeros)
                    ├── matched     → diff_hawb(pdf_hawb, ic_hawb) → DiffRow list
                    ├── solo PDF    → diff_hawb(pdf_hawb, {})       → shown as orphan
                    └── solo iCargo → diff_hawb({}, ic_hawb)        → shown as orphan
                → fallback positional if zero matches found (with warning)

Batch (ZIP) download:
  results list → JSON  (all MAWBs + HAWBs across all source PDFs)
               → CSV   (one row per MAWB; includes source_pdf column)
```

---

## 6. OCR Stack

| Layer      | Library       | Purpose                                | Trigger                               |
|------------|---------------|----------------------------------------|---------------------------------------|
| Native PDF | pdfplumber    | Extract embedded text (fast, lossless) | Always attempted first                |
| Tesseract  | pytesseract   | Rasterise → OCR (rule-based)           | When native text < 200 chars/page     |
| Claude     | Anthropic API | Vision-based layout understanding      | Always used for structured extraction |

---

## 7. Configuration

All runtime settings are loaded from a `.env` file (or process environment) via `pydantic.BaseSettings`:

| Variable            | Default                               | Description                       |
|---------------------|---------------------------------------|-----------------------------------|
| `UI_MODE`           | `streamlit`                           | App mode: `streamlit` or `api`    |
| `ANTHROPIC_API_KEY` | *(required)*                          | Claude API key                    |
| `CLAUDE_MODEL`      | `claude-haiku-4-5-20251001`           | Claude model identifier           |
| `CLAUDE_TIMEOUT`    | `120`                                 | Anthropic HTTP timeout in seconds |
| `ICARGO_BASE_URL`   | `https://mac-stag-icargo.ibsplc.aero` | iCargo base URL                   |
| `ICARGO_USERNAME`   | *(required for comparison)*           | iCargo service account username   |
| `ICARGO_PASSWORD`   | *(required for comparison)*           | iCargo service account password   |
| `ICARGO_TIMEOUT`    | `15`                                  | iCargo HTTP timeout in seconds    |
| `OCR_ENABLED`       | `true`                                | Enable Tesseract OCR fallback     |

---

## 8. Security Considerations

- **Credentials** are never stored in source code — all secrets are injected at runtime via environment variables.
- **API keys** (Anthropic, iCargo) are read from `.env`, which must be excluded from version control (`.gitignore`).
- The iCargo token is a short-lived Bearer JWT and is re-fetched on expiry.
- PDF content is processed entirely in memory; no files are written to disk by the application.
- The PoC uses `ALLOW_WRITEBACK=true` by default — this flag must be reviewed before any production deployment.

---

## 9. Key Dependencies

| Package          | Version (approx) | Purpose                              |
|------------------|------------------|--------------------------------------|
| streamlit        | ≥ 1.30           | Web UI framework                     |
| fastapi          | ≥ 0.100          | REST API (optional mode)             |
| anthropic        | ≥ 0.20           | Claude Vision API client             |
| pdfplumber       | ≥ 0.10           | Native PDF text extraction           |
| pymupdf (fitz)   | ≥ 1.23           | PDF → PNG rasterisation              |
| pytesseract      | ≥ 0.3            | Tesseract OCR wrapper                |
| pillow           | ≥ 10             | Image manipulation                   |
| pydantic         | ≥ 1.10           | Schema validation & settings         |
| httpx            | ≥ 0.25           | Async-capable HTTP client            |
| requests         | ≥ 2.31           | Synchronous HTTP client              |
| pandas           | ≥ 2.0            | Tabular data and CSV export          |
| python-dotenv    | ≥ 1.0            | `.env` file loading                  |

---

## 10. Deployment

### Local (development)

```bash
pip install -r requirements.txt
cp .env.example .env          # fill in ANTHROPIC_API_KEY, ICARGO_* credentials
python -m app.main            # starts Streamlit on http://localhost:8501
```

### Docker (suggested for production)

```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y tesseract-ocr libgl1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV UI_MODE=streamlit
CMD ["python", "-m", "app.main"]
```

> Tesseract must be available in the container image for OCR to function.  
> Set `ANTHROPIC_API_KEY` and iCargo credentials as container environment variables or secrets.

---

## 11. Extension Points

| Capability                  | Where to extend                                      |
|-----------------------------|------------------------------------------------------|
| Add a new LLM provider      | `app/llm/` — implement provider interface            |
| Add new AWB fields          | `app/interpretation/awb_schema.py` + Claude prompt   |
| Support new input formats   | `app/ingestion/` + new `ui/pages/` page              |
| Write back to iCargo        | `app/integration/awb_repository.py`                  |
| Add field-level confidence  | `app/interpretation/awb_field_detector.py`           |

---

## 12. Known Limitations & Planned Improvements

### 12.1 ~~Pre-split boundary detection on rotated PDFs~~ — **RESOLVED (v1.3.0)**

**Root cause (resolved):** the keyword probe in `_detect_rotation_page` used an incorrect coordinate-system mapping between numpy and fitz. `np.rot90(k=3)` = 90° CW on screen = `fitz.prerotate(90)`, not 270° as the original mapping assumed. For sparse pages (e.g. a near-empty AMS Manifest final page), the probe selected `k=3` (highest keyword score in that orientation) and converted it to `270°`, producing a 180° inversion — the page appeared upside-down in Claude's input.

**Fix applied:**
- `_CORRECTION = {0: 0, 1: 270, 2: 180, 3: 90}` in `_detect_rotation_page` (corrects numpy ↔ fitz axis inversion).
- `presplit_pdf_fast` now propagates detected rotation to subsequent pages within the same document (`page_rotations` carry-forward, scoped to document boundary).
- `_render_pages` gradient fallback uses carry-forward from the previous page when both 0° and 90° gradient scores are ambiguous (instead of arbitrarily choosing 90°).

---

### 12.2 Claude output truncation on high-HAWB documents

**Current behaviour**  
`extract_mawb_with_hawbs_json` sends all pages of a document (MAWB + all HAWBs) in a **single API call** with `max_tokens=8192`. When a consolidation contains many House AWBs the generated JSON can exceed this token budget. Claude truncates the response mid-JSON, producing a parse error such as:

```
JSON parse error: Expecting ',' delimiter: line 641 column 6 (char 21178)
```

**Root cause**  
Each HAWB object in the response contains ~25 fields. At ~15–20 tokens per field the token cost per HAWB is roughly **400–500 tokens**. With `max_tokens=8192` the practical ceiling is approximately **15–18 HAWBs** before truncation risk increases significantly.

**Proposed solution (pending business input)**  
Split the extraction into multiple focused API calls:

| Call | Pages sent       | Prompt               | `max_tokens` | Purpose                   |
|------|------------------|----------------------|-------------|---------------------------|
| 1    | MAWB pages (1–2) | `_EXTRACTION_PROMPT` | 2 048        | Extract MAWB fields only  |
| 2    | HAWBs 1–N        | `_HAWB_ONLY_PROMPT`  | 4 096        | Extract first HAWB batch  |
| 3…K  | HAWBs N+1–M      | `_HAWB_ONLY_PROMPT`  | 4 096        | Extract remaining batches |

Results from all calls are merged in Python before returning `{ "mawb": {...}, "hawbs": [...] }`.

**Open question for business**  
> What is the maximum number of House AWBs that can appear under a single MAWB in real operations?

The answer determines the batch size and whether a fixed batch of 4–5 per call is sufficient. Once confirmed, implementation in `ClaudeVisionProvider.extract_mawb_with_hawbs_json` is straightforward — the architecture is already designed to support it.

---

*Document updated: May 2026 (v1.4.0 — HAWB match-by-number + orphan display, expanded MAWB fields, flight notation parsing CP137/19 and variants) — MSC Air Cargo / iCargo PoC Team*
