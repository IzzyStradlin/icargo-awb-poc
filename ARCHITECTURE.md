# Architecture — iCargo AWB Intelligent Processor (PoC)

> **Status:** Proof of Concept  
> **Version:** 1.0.0  
> **Owner:** MSC Air Cargo

---

## 1. Purpose

This application automates the extraction, validation, and comparison of **Air Waybill (AWB)** data received as PDF attachments or email files (`.eml`). It is designed to reduce manual data entry effort for cargo operations staff by:

1. Splitting multi-AWB PDFs into individual document boundaries.
2. Extracting MAWB (Master Air Waybill) and HAWB (House Air Waybill) fields using Claude Vision (AI).
3. Comparing the extracted data against the live **iCargo IBS** system to surface discrepancies.

---

## 2. High-Level Architecture

```
┌───────────────────────────────────────────────────────────────────────┐
│                        User Interface Layer                           │
│             Streamlit Web App  ·  FastAPI REST (optional)             │
└────────────────────────────┬──────────────────────────────────────────┘
                             │
          ┌──────────────────┴──────────────────┐
          │                                     │
   ┌──────▼──────────┐                 ┌────────▼──────────┐
   │  PDF Workflow   │                 │  Email Workflow   │
   │  (pdf_upload)   │                 │  (email_upload)   │
   └──────┬──────────┘                 └────────┬──────────┘
          │                                     │
          └──────────────────┬──────────────────┘
                             │
          ┌──────────────────▼──────────────────────────────┐
          │              Pre-Splitting Layer                 │
          │  AwbDocumentPreSplitter                         │
          │  • pdfplumber native text extraction            │
          │  • Tesseract OCR fallback (100–200 DPI)         │
          │  • Fuzzy AWB boundary detection                 │
          │  • Parallel fast mode / sequential normal mode  │
          └──────────────────┬──────────────────────────────┘
                             │  (page ranges per MAWB)
          ┌──────────────────▼──────────────────────────────┐
          │            AI Extraction Layer                   │
          │  AwbVisionExtractor → ClaudeVisionProvider      │
          │  • PDF pages rendered to PNG images             │
          │  • Sent directly to Claude Haiku 4.5 Vision    │
          │  • Returns structured JSON (MAWB + HAWBs)       │
          └──────────────────┬──────────────────────────────┘
                             │
          ┌──────────────────▼──────────────────────────────┐
          │           Validation & Comparison Layer          │
          │  ICargoIBSClient  +  AwbDiffEngine              │
          │  • Bearer-token auth against iCargo API         │
          │  • Field-level diff (extracted vs iCargo)       │
          │  • Tabular results displayed in the UI          │
          └─────────────────────────────────────────────────┘
```

---

## 3. Directory Structure

```
icargo-awb-poc/
├── app/
│   ├── main.py                          # Entry point — dispatches Streamlit or FastAPI
│   ├── common/
│   │   ├── exceptions.py                # Custom exception hierarchy
│   │   ├── logging.py                   # Structured logging setup
│   │   └── utils.py                     # Shared utility functions
│   ├── config/
│   │   └── settings.py                  # Pydantic-based env-var configuration
│   ├── extraction/
│   │   ├── pdf_text_extractor.py        # pdfplumber + Tesseract per-page extractor
│   │   ├── email_text_extractor.py      # .eml parser (body + attachments)
│   │   ├── awb_document_presplitter.py  # Multi-AWB boundary detection engine
│   │   ├── awb_document_splitter.py     # Legacy single-pass splitter
│   │   ├── awb_multisplit.py            # Multi-document orchestrator
│   │   └── awb_section_extractor.py     # Section-level text slicer
│   ├── ingestion/
│   │   ├── pdf_ingestor.py              # File-level PDF intake
│   │   └── email_ingestor.py            # File-level .eml intake
│   ├── interpretation/
│   │   ├── awb_vision_extractor.py      # Main extractor (Claude Vision)
│   │   ├── awb_llm_extractor.py         # LLM text-based extractor (legacy)
│   │   ├── awb_hybrid_extractor.py      # Merged rule-based + LLM result
│   │   ├── awb_field_detector.py        # Regex / heuristic field detector
│   │   ├── awb_extractor.py             # Base extractor interface
│   │   ├── awb_schema.py                # Pydantic schema for AWB fields
│   │   ├── awb_normalizer.py            # Field normalisation (dates, weights, codes)
│   │   ├── awb_number.py                # AWB number parsing & validation helpers
│   │   ├── awb_llm_parser.py            # JSON response cleaner / parser
│   │   ├── awb_table_parser.py          # Table structure extractor
│   │   ├── awb_section_analyzer.py      # Semantic section labelling
│   │   ├── awb_section_field_extractor.py # Field extraction per section
│   │   ├── awb_text_field_extractor.py  # Plain-text field extraction
│   │   ├── awb_parsing_agent.py         # Orchestrator for multi-strategy extraction
│   │   ├── awb_extraction_prompt.py     # Extraction prompt templates
│   │   ├── iata_awb_extraction_pipeline_v3.py  # v3 IATA-aligned pipeline
│   │   ├── iata_awb_parsing_agent_v3.py         # v3 parsing agent
│   │   └── iata_awb_label_extractor.py          # IATA label field extractor
│   ├── llm/
│   │   └── claude_vision_provider.py    # Anthropic API client (vision + text fallback)
│   ├── compare/
│   │   └── awb_diff_ibs.py              # Field normalisation + diff logic vs iCargo IBS
│   ├── comparison/
│   │   └── awb_diff_engine.py           # Typed diff engine (list of DiffItem)
│   ├── integration/
│   │   ├── awb_repository.py            # AWB CRUD abstraction over iCargo API
│   │   └── icargo_ibs_client.py         # Low-level iCargo IBS HTTP client
│   ├── pipelines/
│   │   ├── run_from_pdf.py              # Headless PDF pipeline runner
│   │   └── run_from_email.py            # Headless email pipeline runner
│   └── ui/
│       ├── web_streamlit.py             # Streamlit app shell & navigation router
│       ├── web_fastapi.py               # FastAPI REST endpoints
│       ├── ocr_export.py                # OCR result export utilities
│       ├── assets/
│       │   └── branding.py              # MSC brand colours, CSS, logo helpers
│       └── pages/
│           ├── pdf_upload.py            # PDF workflow page (split → extract → compare)
│           └── email_upload.py          # Email workflow page (.eml intake)
├── tests/
│   └── unit/
│       ├── test_awb_diff_engine.py
│       ├── test_awb_field_detector.py
│       └── test_multi_awb_extraction.py
├── requirements.txt
├── README.md
└── ARCHITECTURE.md                      # This document
```

---

## 4. Component Details

### 4.1 Entry Point — `app/main.py`

Reads the `UI_MODE` environment variable and launches either:

| `UI_MODE`   | Runtime           | Port  |
|-------------|-------------------|-------|
| `streamlit` | Streamlit web app | 8501  |
| `api`       | FastAPI + uvicorn | 8080  |

---

### 4.2 Pre-Splitting — `AwbDocumentPreSplitter`

Multi-AWB PDFs (e.g. a batch of scanned MAWBs from an airline) are split into individual document page ranges **before** any AI extraction occurs. This prevents context bleeding between documents.

**Strategy (in order of priority):**

1. **Shipper boundary detection** — fuzzy match for `"Shipper's Name and Address"` (IATA Box 1), tolerance 0.72. Present on every standard AWB header.
2. **Shipper account fallback** — fuzzy match for `"Shipper's Account Number"`, tolerance 0.75.
3. **MAWB phrase markers** — `"Not Negotiable Air Waybill Issued by"` and variants, tolerance 0.85.
4. **AWB number clustering** — extract all AWB numbers per page and cluster by 3-digit prefix.

**Two OCR modes (boundary detection):**

| Mode     | DPI  | Page area | Execution  | Use case                           |
|----------|------|-----------|------------|------------------------------------|
| Smart    | 300  | Top 20 %  | Parallel   | Recommended — high AWB# accuracy on poor scans, small crop keeps it fast |
| Normal   | 200  | Full page | Sequential | Difficult/rotated scans, worst-case fallback |

**Orientation detection (Smart mode — runs in the same parallel pass):**

For every scanned page, a second Tesseract task runs `--psm 0` (OSD) on the **full** rendered image alongside the boundary-detection OCR. OSD detects the rotation of the scan (0°, 90°, 180°, or 270°) and stores the correction angle in `page_rotations` within the document dict. This is the primary input for orientation correction in the Claude Vision render step.

> **Why 300 DPI / 20%?** On any IATA AWB form the AWB number and the "Shipper's Name and Address" label (the primary split marker) always appear in the top 12–15 % of the page. A 20% crop adds a safe margin. 300 DPI is needed to reliably OCR small printed digits (e.g. `233-10166763`) on low-quality scans — lower DPI is the primary cause of missed AWB numbers. Running in parallel on just the top 20% keeps total wall-clock time well below the full-page sequential mode.

**Cluster radii (boundary deduplication):**

The fuzzy sliding-window scanner produces multiple consecutive hits for the same physical marker (the window advances one char at a time). Two cluster radii control how these hits are collapsed:

| Cluster step | Radius | Rationale |
|---|---|---|
| Internal — inside `_find_shipper_name_markers` | **50 chars** | Sliding-window duplicates span at most `len(marker) − 1` = 24 chars; 50 is a safe collapse margin |
| Merge — primary + secondary combined in `_presplit_by_shipper_marker` | **200 chars** | Large enough to unify "Shipper's Name" and "Shipper's Account" hits for the same AWB header (real separation ≤ ~150 chars in linearised 2-column OCR), small enough not to absorb a genuine second boundary when intermediate pages (e.g. manifest pages) produce sparse OCR output (as few as ~80 chars in the top-20% crop) |

> **Known failure mode (fixed):** a merge radius of 500 caused the second MAWB in a `MAWB → Manifest → Manifest → MAWB` sequence to be silently dropped when the two manifest pages produced little OCR text, placing both MAWB markers within 500 chars in the concatenated string. Reducing the merge radius to 200 resolves this.

---

### 4.3 AI Extraction — `AwbVisionExtractor` + `ClaudeVisionProvider`

Each MAWB page range is converted to PNG images (via PyMuPDF/fitz) and sent to **Claude Haiku 4.5** (`claude-haiku-4-5-20251001`, overridable via `CLAUDE_MODEL` env var) through the Anthropic REST API.

**Key design decisions:**
- No intermediate OCR text is sent to Claude — images are sent directly, preserving the 2-column IATA AWB layout that regex cannot reliably parse.
- A structured JSON prompt instructs Claude to return exactly the AWB schema fields (`awb_number`, `shipper`, `consignee`, `origin`, `destination`, `flight_number`, `pieces`, `weight`, …).
- **Orientation correction** — before base64-encoding, `ClaudeVisionProvider._render_pages` applies `fitz.Matrix(1.5, 1.5).prerotate(correction)` per page, where `correction` (CCW degrees) comes from `page_rotations` when available, or from a dimension heuristic (`w > h` → 90° CCW) as a fallback. This ensures Claude always receives upright images regardless of how the PDF was scanned or stored.
- **OSD-based rotation (full pipeline)** — because scans from warehouses can arrive at any rotation (0°, 90°, 180°, 270°), the presplit phase runs Tesseract OSD (`--psm 0 --oem 0`) on the full image of every scanned page **in parallel** with the existing boundary-detection OCR. The detected correction angle is stored in `page_rotations` (a `dict[page_num → CCW_degrees]` added to each presplit document dict). `ClaudeVisionProvider._render_pages` accepts this dict and applies `Matrix.prerotate(correction)` per page, handling all four rotation cases.

  `_detect_rotation_page` applies five strategies in cascade:

  | Priority | Strategy | Trigger |
  |---|---|---|
  | 1 | **Pixel dimensions** | `w > h` (pixmap is landscape) → 90° CCW immediately |
  | 2 | **OSD non-zero** (`--psm 0 --oem 0`) | `orientation_conf ≥ 3.0` **and** `rotate ≠ 0` → trust immediately |
  | 3 | **Generic rotation probe** *(see below)* | **always runs**, even if OSD returned 0° confidently |
  | 4 | **OSD zero** | OSD was confident 0° **and** probe found nothing → return 0° |
  | 5 | **OSD retry on pre-rotated image** | rotate image 90° CCW, re-run OSD; if `conf ≥ 3.0` and `rotate=0` → original needed 90° CCW |
  | 6 | **Give up** | return 0° (no rotation detected) |

  **Strategy 3 — Generic rotation probe:**

  OSD is unreliable when a page has a portrait company header at the top and landscape HAWB content in the body — the portrait header dominates and OSD confidently returns 0°. The strip-based approach (checking left/right columns for keywords) is also fragile because the result depends on which column the content falls in and which direction the text runs.

  The probe is therefore fully generic: it applies all four rotations (0°, 90°, 180°, 270°) to the **page body** (the area below the top 25%, which may contain the portrait letterhead) and selects the rotation that maximises HAWB keyword hits.

  ```
  ┌─────────────────────────┐
  │     COMPANY HEADER      │  ← excluded (top 25%)
  ├─────────────────────────┤
  │                         │
  │   body — OCR scored     │  ← rotated as k=0, 1, 2, 3
  │   at all 4 rotations    │
  │                         │
  └─────────────────────────┘

  best k=1 (90°  CCW of body readable) → HAWB was printed landscape 90° CW  → correction 90° CCW
  best k=2 (180° of body readable)     → HAWB was printed upside-down        → correction 180°
  best k=3 (270° CCW of body readable) → HAWB was printed landscape 90° CCW  → correction 270° CCW
  best k=0 (upright wins)              → page is truly portrait               → no rotation
  ```

  Decision rule: if any non-zero k produces more keyword hits than k=0 (upright), apply the corresponding correction. Ties between k=0 and another k → no rotation (conservative). Ties between two non-zero rotations → the one with more hits wins (k ordering breaks ties deterministically).

  HAWB keywords scored: `shipper`, `consignee`, `sender`, `notify`, `house`, `hawb`, `airway`, `waybill`, `recipient`, `manifest`. The top 25% is excluded because company letterheads often contain words like "airway" or "manifest" in small print that would generate false positives.

  OSD engine notes:
  - `--oem 0` (legacy engine) is mandatory for `--psm 0`; `--oem 1` (LSTM) is silently incompatible with OSD.
  - Results with `orientation_conf < 3.0` are discarded — on sparse pages OSD has too few characters to be reliable.

  > **Known failure mode (fixed — `--oem` bug):** using `--oem 1` with PSM 0 caused OSD to silently fail on low-text pages. The fallback always returned 0° rotation, so Claude received the page sideways. Switching to `--oem 0` resolves this.

  > **Known failure mode (fixed — mixed-orientation page, structural bug):** OSD returning 0° with high confidence caused an immediate return before the rotation probe ran (probe was in the `except` block, never reached on OSD success). Fixed by restructuring the cascade: the OSD result is remembered but only acted upon for non-zero results; the rotation probe always runs as Strategy 3.

  > **Known failure mode (fixed — strip-based probe fragility):** earlier iterations used a left/right strip approach that required knowing which strip the content was in and which direction the text ran — subtle to reason about and easy to get wrong (several 90°/180°/270° inversions during development). Replaced with the generic 4-rotation body probe, which is correct by construction regardless of orientation.

  > **Known limitation — 90° vs 270° ambiguity:** when a landscape page could be portrait either way (e.g. a single-row manifest table), the probe scores k=1 and k=3 equally — both rotations produce the same readable keywords. `max()` then picks deterministically by dictionary order, which may be wrong. Resolving the ambiguity would require a layout-aware signal (e.g. "AWB number column is always on the left") that the keyword probe does not implement. In practice this is acceptable: see the note below.

  > **Observed behaviour — Claude appears robust to 180° inversion (empirical):** in a single production test, a page corrected to portrait-upside-down (270° CCW applied instead of the ideal 90° CCW) was still read and extracted correctly by Claude Vision. This is consistent with vision models being trained on data in various orientations, but it is **not a documented guarantee**. The practical consequence of the ambiguity above is therefore limited: the probe correctly identifies that a landscape-to-portrait correction is needed (the critical step), even when it cannot determine the exact direction.
- The first call returns the **MAWB** (portrait page). HAWB pages are included in a second call that returns `{ "mawb": {...}, "hawbs": [{...}] }`. All images sent have already been normalised to portrait.
- Safety cap: max 20 images per API call (default; overridable via `max_images` parameter) to stay within the token budget.
- Rendering DPI: `fitz.Matrix(1.5, 1.5)` ≈ 108 DPI → ~1263 px long side for A4, just under Claude's 1568 px resize threshold (optimal quality-to-token ratio).
- A text-only fallback (`extract_from_text`) is available when PDF bytes are absent.

---

### 4.4 Legacy Hybrid Extraction (optional)

For environments without Claude API access, the `AwbHybridExtractor` merges:
- **Rule-based fields** from `AwbFieldDetector` (regex, fuzzy matching, heuristics).
- **LLM fields** from a configurable provider (`azure_openai`, `openai`, `llama`, `disabled`).

The hybrid mode is currently not exposed in the main UI but is available via the headless pipelines.

---

### 4.5 iCargo IBS Integration — `ICargoIBSClient`

Communicates with the **iCargo IBS** REST API via Bearer token authentication:

```
POST /auth/m4/private/v1/authenticate   → obtains id_token
GET  /icargo-api/m4/enterprise/v2/awbs/{awb_number}  → retrieves AWB record
```

Credentials and base URL are injected via environment variables (`.env` file):

| Variable           | Description                    |
|--------------------|-------------------------------|
| `ICARGO_BASE_URL`  | iCargo environment base URL   |
| `ICARGO_USERNAME`  | Service account username      |
| `ICARGO_PASSWORD`  | Service account password      |
| `ICARGO_TIMEOUT`   | HTTP timeout in seconds       |

---

### 4.6 Diff & Comparison — `awb_diff_ibs.py`

`diff_awb(extracted, icargo_flat)` produces a list of `DiffRow` dicts, one per field:

```python
{
    "field": "shipper",
    "pdf_llm": "ACME LOGISTICS SRL",
    "icargo": "ACME LOGISTICS S.R.L.",
    "match": False
}
```

Normalisation before comparison:
- Strings: strip, collapse whitespace, case-insensitive.
- Airport codes: uppercase 3-letter IATA.
- Weights / numeric fields: parse from various formats (`"150 kg"`, `{"value":150,"unit":"kg"}`, `150.0`).
- AWB numbers: normalise to `NNN-NNNNNNNN` format.

---

### 4.7 UI — Streamlit (`web_streamlit.py`)

Single-page application with a simple client-side router stored in `st.session_state["page"]`.

**Pages:**

| Route          | File               | Description                              |
|----------------|--------------------|------------------------------------------|
| `landing`      | `web_streamlit.py` | Hero landing with workflow selector      |
| `pdf_upload`   | `pdf_upload.py`    | Full PDF → split → Vision → compare flow |
| `email_upload` | `email_upload.py`  | .eml intake (placeholder for extension)  |

**Session state keys used by `pdf_upload`:**

| Key                   | Type         | Description                              |
|-----------------------|--------------|------------------------------------------|
| `raw_pdf_bytes`       | `bytes`      | Current PDF file contents                |
| `pdf_name`            | `str`        | Uploaded file name (change detector)     |
| `split_documents`     | `list[dict]` | Pre-split result (page ranges, AWB #, `page_rotations`) |
| `split_mode`          | `str`        | `"fast"` or `"normale"`                  |
| `awb_results`         | `list[dict]` | Claude Vision extraction results         |
| `vision_refined_awbs` | `dict`       | Per-AWB re-extraction overrides          |
| `debug_page_texts`    | `dict`       | Raw page text cache for the debug panel  |

**UI workflow (pdf_upload page):**

1. **Upload** — user drops a PDF; presplit runs automatically.
2. **🔍 Debug split** *(expander)* — raw page text + document boundaries, useful to verify the split logic without calling Claude.
3. **🖼 Preview rendered pages** *(expander)* — click **"📦 Build PNG preview ZIP"** to render all pages with orientation correction applied (same pipeline as Claude receives) and download the ZIP. File names include a `_rotN` suffix when a page was rotated (e.g. `page_002_rot90.png`). Use this to verify rotation before spending API credits.
4. **🚀 Extract all with Claude Vision** — calls Claude for every detected AWB block.
5. **Results** — MAWB + HAWB fields displayed; re-extract per AWB; download JSON; compare with iCargo.

---

## 5. Data Flow — PDF Workflow

```
User uploads PDF
       │
       ▼
AwbDocumentPreSplitter.presplit_pdf_fast / presplit_pdf_with_text
  → List[{ awb_number, start_page, end_page, text, page_rotations }]
  │
  │  Smart mode runs TWO parallel Tesseract tasks per scanned page:
  │    • PSM 6, OEM 1  (top 20%)   → boundary-detection text
  │    • PSM 0, OEM 0 / OSD        → per-page rotation correction angle
  │                                   4-step cascade: OSD conf≥3 → w>h dim →
  │                                   OSD@90°CCW → HAWB keyword probe (left vs top strip)
  │  page_rotations: { page_num → CCW_degrees }  (only non-zero entries)
       │
       ├──► [optional] 🖼 Preview PNG ZIP (no Claude call)
       │         renders pages with orientation correction applied
       │         → user verifies upright images before spending credits
       │
       ▼  (for each document)
ClaudeVisionProvider._render_pages(pdf_bytes, start_page, end_page, page_rotations)
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
```

---

## 6. OCR Stack

| Layer      | Library       | Purpose                                | Trigger                             |
|------------|---------------|----------------------------------------|-------------------------------------|
| Native PDF | pdfplumber    | Extract embedded text (fast, lossless) | Always attempted first              |
| Tesseract  | pytesseract   | Rasterise → OCR (rule-based)           | When native text < 200 chars/page   |
| Claude     | Anthropic API | Vision-based layout understanding      | Always used for structured extraction |

---

## 7. Configuration

All runtime settings are loaded from a `.env` file (or process environment) via `pydantic.BaseSettings`:

| Variable            | Default                          | Description                         |
|---------------------|----------------------------------|-------------------------------------|
| `UI_MODE`           | `streamlit`                      | App mode: `streamlit` or `api`      |
| `ANTHROPIC_API_KEY` | *(required)*                     | Claude API key                      |
| `ICARGO_BASE_URL`   | `https://mac-stag-icargo.ibsplc.aero` | iCargo base URL               |
| `ICARGO_USERNAME`   | *(required for comparison)*      | iCargo service account username     |
| `ICARGO_PASSWORD`   | *(required for comparison)*      | iCargo service account password     |
| `ICARGO_TIMEOUT`    | `15`                             | HTTP timeout in seconds             |
| `LLM_PROVIDER`      | `disabled`                       | Legacy LLM: `azure_openai`, `openai`, `llama`, `disabled` |
| `OCR_ENABLED`       | `true`                           | Enable Tesseract OCR fallback       |

---

## 8. Security Considerations

- **Credentials** are never stored in source code — all secrets are injected at runtime via environment variables.
- **API keys** (Anthropic, iCargo) are read from `.env` which must be excluded from version control (`.gitignore`).
- The iCargo token is short-lived (Bearer JWT) and is re-fetched on expiry.
- PDF content is processed in memory only; no files are written to disk by the application.
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
| Add new AWB fields          | `app/interpretation/awb_schema.py` + Claude prompt  |
| Support new input formats   | `app/ingestion/` + new `ui/pages/` page              |
| Write back to iCargo        | `app/integration/awb_repository.py`                  |
| Add field-level confidence  | `app/interpretation/awb_field_detector.py`           |
| Export formats (XML, XFDF)  | `app/ui/ocr_export.py`                               |

---

## 12. Known Limitations & Planned Improvements

### 12.1 Claude output truncation on high-HAWB documents

**Current behaviour**  
`extract_mawb_with_hawbs_json` sends all pages of a document (MAWB + all HAWBs) in a **single API call** with `max_tokens=8192`. When a consolidation contains many House AWBs the generated JSON can exceed this token budget. Claude truncates the response mid-JSON, producing a parse error such as:

```
JSON parse error: Expecting ',' delimiter: line 641 column 6 (char 21178)
```

**Root cause**  
Each HAWB object in the response contains ~25 fields. At ~15–20 tokens per field the token cost per HAWB is roughly **400–500 tokens**. With `max_tokens=8192` the practical ceiling is approximately **15–18 HAWBs** before truncation risk increases significantly.

**Proposed solution (pending business input)**  
Split the extraction into multiple focused API calls:

| Call | Pages sent | Prompt | `max_tokens` | Purpose |
|------|-----------|--------|-------------|---------|
| 1 | MAWB pages (first 1–2) | `_EXTRACTION_PROMPT` | 2 048 | Extract MAWB fields only |
| 2 | HAWBs 1–N (first batch) | `_HAWB_ONLY_PROMPT` (returns JSON array) | 4 096 | Extract first batch of HAWBs |
| 3…K | HAWBs N+1–M (next batches) | `_HAWB_ONLY_PROMPT` | 4 096 | Extract remaining batches |

Results from all calls are merged in Python before returning `{ "mawb": {...}, "hawbs": [...] }`.

**Open question for business**  
> What is the maximum number of House AWBs that can appear under a single MAWB in real operations?

The answer determines the batch size (HAWBs per call) and whether a fixed batch of 4 or 5 per call is sufficient, or whether a larger/dynamic batch is needed. Once confirmed, implementation in `ClaudeVisionProvider.extract_mawb_with_hawbs_json` is straightforward — the architecture is already designed to support it.

---

*Document generated: April 2026 — MSC Air Cargo / iCargo PoC Team*
