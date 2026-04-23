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
          │  • Sent directly to Claude 3.5 Sonnet Vision    │
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
│   │   ├── pdf_text_extractor.py        # pdfplumber + Tesseract/EasyOCR per-page extractor
│   │   ├── email_text_extractor.py      # .eml parser (body + attachments)
│   │   ├── awb_document_presplitter.py  # Multi-AWB boundary detection engine
│   │   ├── awb_document_splitter.py     # Legacy single-pass splitter
│   │   ├── awb_multisplit.py            # Multi-document orchestrator
│   │   └── awb_section_extractor.py     # Section-level text slicer
│   ├── ingestion/
│   │   ├── pdf_ingestor.py              # File-level PDF intake
│   │   ├── email_ingestor.py            # File-level .eml intake
│   │   └── enhanced_pdf_ocr.py          # High-quality OCR pipeline (EasyOCR)
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
│       ├── integration_easyocr.py       # EasyOCR integration helpers
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

**Two OCR modes:**

| Mode     | DPI  | Page area | Execution  | Use case                           |
|----------|------|-----------|------------|------------------------------------|
| Smart    | 300  | Top 20 %  | Parallel   | Recommended — high AWB# accuracy on poor scans, small crop keeps it fast |
| Normal   | 200  | Full page | Sequential | Difficult/rotated scans, worst-case fallback |

> **Why 300 DPI / 20%?** On any IATA AWB form the AWB number and the "Shipper's Name and Address" label (the primary split marker) always appear in the top 12–15 % of the page. A 20% crop adds a safe margin. 300 DPI is needed to reliably OCR small printed digits (e.g. `233-10166763`) on low-quality scans — lower DPI is the primary cause of missed AWB numbers. Running in parallel on just the top 20% keeps total wall-clock time well below the full-page sequential mode.

---

### 4.3 AI Extraction — `AwbVisionExtractor` + `ClaudeVisionProvider`

Each MAWB page range is converted to PNG images (via PyMuPDF/fitz) and sent to **Claude 3.5 Sonnet Vision** through the Anthropic REST API.

**Key design decisions:**
- No intermediate OCR text is sent to Claude — images are sent directly, preserving the 2-column IATA AWB layout that regex cannot reliably parse.
- A structured JSON prompt instructs Claude to return exactly the AWB schema fields (`awb_number`, `shipper`, `consignee`, `origin`, `destination`, `flight_number`, `pieces`, `weight`, …).
- **Landscape normalisation** — before base64-encoding, every page is checked for landscape orientation (`width > height`). Landscape pages (typical of HAWB forms) are automatically rotated 90° clockwise with PIL so Claude always receives portrait-oriented images. This significantly improves HAWB field extraction accuracy because Claude's training is predominantly on portrait documents. The operation is zero-cost: Claude internally resizes images to a 1568 px long side regardless of orientation.
- The first call returns the **MAWB** (portrait page). HAWB pages are included in a second call that returns `{ "mawb": {...}, "hawbs": [{...}] }`. All images sent have already been normalised to portrait.
- Safety cap: max 10 images per API call to stay within the token budget.
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
| `split_documents`     | `list[dict]` | Pre-split result (page ranges + AWB #)   |
| `split_mode`          | `str`        | `"fast"` or `"normale"`                  |
| `awb_results`         | `list[dict]` | Claude Vision extraction results         |
| `vision_refined_awbs` | `dict`       | Per-AWB re-extraction overrides          |
| `debug_page_texts`    | `dict`       | Raw page text cache for the debug panel  |

---

## 5. Data Flow — PDF Workflow

```
User uploads PDF
       │
       ▼
AwbDocumentPreSplitter.presplit_pdf_fast / presplit_pdf_with_text
  → List[{ awb_number, start_page, end_page, text }]
       │
       ▼  (for each document)
ClaudeVisionProvider.extract_mawb_with_hawbs_json(pdf_bytes, start_page, end_page)
  → raw JSON string
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
| EasyOCR    | easyocr       | Deep-learning OCR (GPU optional)       | Last resort when Tesseract absent   |
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
| easyocr          | ≥ 1.7            | Deep-learning OCR (optional)         |
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

*Document generated: April 2026 — MSC Air Cargo / iCargo PoC Team*
