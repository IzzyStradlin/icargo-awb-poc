# Architecture — iCargo AWB Intelligent Processor (PoC)

> **Status:** Proof of Concept  
> **Version:** 1.4.0  
> **Owner:** MSC Air Cargo

---

## 1. Purpose

This application automates the extraction, validation, and comparison of **Air Waybill (AWB)** data received as PDF attachments or email files (`.eml`). It is designed to reduce manual data-entry effort for cargo operations staff by:

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
          │  • Tesseract OCR fallback (100–300 DPI)         │
          │  • Fuzzy AWB boundary detection                 │
          │  • Parallel fast mode / sequential normal mode  │
          └──────────────────┬──────────────────────────────┘
                             │  (page ranges per MAWB)
          ┌──────────────────▼──────────────────────────────┐
          │            AI Extraction Layer                   │
          │  AwbVisionExtractor → ClaudeVisionProvider      │
          │  • PDF pages rendered to PNG images             │
          │  • Sent directly to Claude Haiku 4.5 Vision     │
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
│   │   ├── email_text_extractor.py      # HTML-to-text converter for email bodies
│   │   ├── awb_document_presplitter.py  # Multi-AWB boundary detection engine
│   │   └── awb_document_splitter.py     # Single-pass text splitter (FastAPI pipeline)
│   ├── ingestion/
│   │   ├── pdf_ingestor.py              # File-level PDF intake
│   │   └── email_ingestor.py            # File-level .eml intake
│   ├── interpretation/
│   │   ├── awb_vision_extractor.py      # Main extractor (Claude Vision)
│   │   ├── awb_field_detector.py        # Regex / heuristic field detector (FastAPI pipeline)
│   │   ├── awb_schema.py                # Pydantic schema for AWB fields
│   │   ├── awb_normalizer.py            # Field normalisation (dates, weights, codes)
│   │   ├── awb_number.py                # AWB number parsing & validation helpers
│   │   ├── awb_llm_parser.py            # JSON response cleaner / parser
│   │   ├── awb_table_parser.py          # Table structure extractor (quantity / weight)
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

| Mode     | DPI  | Page area | Execution  | Use case                                              |
|----------|------|-----------|------------|-------------------------------------------------------|
| Smart    | 300  | Top 20 %  | Parallel   | Recommended — high AWB# accuracy on poor scans, fast |
| Normal   | 200  | Full page | Sequential | Difficult/rotated scans, worst-case fallback          |

> **Why 300 DPI / 20%?** On any IATA AWB form the AWB number and the "Shipper's Name and Address" label always appear in the top 12–15% of the page. A 20% crop adds a safe margin. 300 DPI is needed to reliably OCR small printed digits (e.g. `233-10166763`) on low-quality scans. Running in parallel on just the top slice keeps total wall-clock time well below the full-page sequential mode.

**Orientation detection (Smart mode):**

For every scanned page, a second Tesseract task runs `--psm 0` (OSD) on the full rendered image alongside the boundary-detection OCR. OSD detects the rotation (0°, 90°, 180°, or 270°) and stores the correction angle in `page_rotations` within the document dict. This feeds directly into the Claude Vision render step.

**Cluster radii (boundary deduplication):**

The fuzzy sliding-window scanner produces multiple consecutive hits for the same physical marker. Two cluster radii collapse these hits:

| Cluster step | Radius | Rationale |
|---|---|---|
| Internal — inside `_find_shipper_name_markers` | **50 chars** | Sliding-window duplicates span at most `len(marker) − 1` = 24 chars; 50 is a safe collapse margin |
| Merge — primary + secondary combined in `_presplit_by_shipper_marker` | **200 chars** | Large enough to unify "Shipper's Name" and "Shipper's Account" hits for the same AWB header (real separation ≤ ~150 chars in linearised 2-column OCR), small enough not to absorb a genuine second boundary when intermediate manifest pages produce sparse OCR output (~80 chars in the top-20% crop) |

> **Known failure mode (fixed):** a merge radius of 500 caused the second MAWB in a `MAWB → Manifest → Manifest → MAWB` sequence to be silently dropped. Reducing to 200 resolves this.

---

### 4.3 AI Extraction — `AwbVisionExtractor` + `ClaudeVisionProvider`

Each MAWB page range is converted to PNG images (via PyMuPDF/fitz) and sent to **Claude Haiku 4.5** (`claude-haiku-4-5-20251001`, overridable via `CLAUDE_MODEL` env var) through the Anthropic REST API.

**Key design decisions:**
- No intermediate OCR text is sent to Claude — images are sent directly, preserving the 2-column IATA AWB layout that regex cannot reliably parse.
- A structured JSON prompt instructs Claude to return exactly the AWB schema fields.
- **Orientation correction** — before base64-encoding, `ClaudeVisionProvider._render_pages` applies `fitz.Matrix(1.5, 1.5).prerotate(correction)` per page, where `correction` (CCW degrees) comes from:
1. `page_rotations[page]` (presplitter keyword-probe result) if present — highest priority.
2. PDF content-stream text-direction (rawdict `dir` vectors) for digitally-generated PDFs.
3. Pixel gradient score (row variance / column variance of dark pixels) comparing 0° and 90° — with carry-forward from the previous page when ambiguous.

PyMuPDF automatically applies the page's `/Rotate` entry before rendering, so correction angles are always relative to that already-normalised image.

**Extracted MAWB fields:** `awb_number`, `origin`, `destination`, `shipper` (+ address parts), `consignee` (+ address parts), `agent` (+ address parts), `notify_party`, `pieces`, `weight`, `chargeable_weight`, `volume`, `dimensions`, `rate`, `total_charge`, `currency`, `goods_description`, `hs_code`, `special_handling`, `declared_value_carriage`, `declared_value_customs`, `flight_number`, `flight_date`.

**Extracted HAWB fields:** same as MAWB plus `hawb_number`; AMS Manifest table rows are each extracted as a separate HAWB entry.

**Flight number / date parsing:**
Cargo AWB routing rows often encode flight and day-of-month together with a separator:

| Notation | Example | Separator |
|---|---|---|
| `FLIGHT.DAY` | `CP139.7`, `CP139.07` | dot |
| `FLIGHT/DAY` | `CP137/19`, `LH2054/03` | slash |
| `FLIGHT_DAY` | `CP137_19` | underscore |
| `FLIGHT DAY` | `LH2054 03` | space |

Claude is instructed to:
1. Split on the first occurrence of `.` `/` `_` or space between the alpha code and a 1-2 digit number.
2. Use the left part as `flight_number` (e.g. `"CP137"`).
3. Use the right part as the day-of-month and look for a reference month/year elsewhere in the same document (issue date, footer stamp) to reconstruct `flight_date` in `YYYY-MM-DD`.
4. Return `null` for `flight_date` if no reference month/year is found.

**Rotation detection cascade (`_detect_rotation_page`):**

| Priority | Strategy | Trigger |
|---|---|---|
| 1 | **Keyword probe** (primary) | Runs Tesseract at all 4 rotations (0°, 90°, 180°, 270°) on page body (below top 25%); picks the rotation with the highest AWB keyword count. Requires ≥ 2 keyword matches to override upright. |
| 2 | **OSD non-zero** (`--psm 0 --oem 0`) | Runs only if keyword probe is inconclusive (all scores = 0). `orientation_conf ≥ 3.0` **and** `rotate ≠ 0` → trust immediately. |
| 3 | **OSD zero** | OSD was confident 0° → return 0° |
| 4 | **Give up** | Return 0° (no rotation detected, deferred to gradient in render step) |

**Strategy 3 — Generic rotation probe:**

OSD is unreliable when a page has a portrait company header at the top and landscape HAWB content below — the portrait header dominates and OSD confidently returns 0°. The probe avoids this by working entirely on the **page body** (the area below the top 25%) and scoring all four rotations for HAWB keyword density:

```
┌─────────────────────────┐
│     COMPANY HEADER      │  ← excluded (top 25%)
├─────────────────────────┤
│                         │
│   body — OCR scored     │  ← scored at k = 0, 1, 2, 3 rotations
│   at all 4 rotations    │
│                         │
└─────────────────────────┘

best k=1 (90°  CCW readable) → HAWB printed landscape 90° CW  → correction 90° CCW
best k=2 (180° readable)     → HAWB printed upside-down       → correction 180°
best k=3 (270° CCW readable) → HAWB printed landscape 90° CCW → correction 270° CCW
best k=0 (upright wins)      → page is truly portrait         → no rotation
```

AWB keywords scored: `shipper`, `consignee`, `air waybill`, `waybill`, `hawb`, `manifest`, `master`, `flight`, `departure`, `destination`, `pieces`, `weight`, `sender`, `notify`, `house`, `apt dest`, `hawb n`, `nature of goods`, `chargeable`, `issuing carrier`, `gross weight`. Decision rule: the rotation with the highest keyword count wins, provided it scores ≥ 2 keywords; ties resolve via k order (lower k preferred).

**Coordinate system note:** numpy and fitz (PDF math) have opposite y-axis directions. The `_CORRECTION` mapping accounts for this:

| numpy `rot90(k)` | Screen result | Correct fitz correction |
|---|---|---|
| k=1 | 90° CCW | `fitz.prerotate(270)` |
| k=2 | 180° | `fitz.prerotate(180)` |
| k=3 | 90° CW | `fitz.prerotate(90)` |

OSD notes:
- `--oem 0` (legacy engine) is mandatory for `--psm 0`; `--oem 1` (LSTM) is silently incompatible with OSD.
- Results with `orientation_conf < 3.0` are discarded.

**Render-step fallback (gradient orientation):** for pages where the presplitter found no rotation (sparse pages, e.g. a near-empty final AMS Manifest page), `_render_pages` compares pixel gradient scores at 0° and 90° and carries forward the last known correction within the same document if ambiguous.

**Presplitter carry-forward:** `presplit_pdf_fast` propagates detected rotation to subsequent pages within the same document that had no own detection result. This is scoped to the document boundary to prevent contaminating the next MAWB block.

**Other rendering parameters:**
- Safety cap: max 20 images per API call (overridable via `max_images`).
- Rendering DPI: `fitz.Matrix(1.5, 1.5)` ≈ 108 DPI → ~1263 px long side for A4, just under Claude's 1568 px resize threshold (optimal quality-to-token ratio).
- Text-only fallback (`extract_from_text`) is available when PDF bytes are absent.

---

### 4.4 iCargo IBS Integration — `ICargoIBSClient`

Communicates with the **iCargo IBS** REST API via Bearer token authentication:

```
POST /auth/m4/private/v1/authenticate                       → obtains id_token
GET  /icargo-api/m4/enterprise/v2/awbs/{awb_number}         → retrieves AWB record
```

Credentials and base URL are injected via environment variables (`.env` file):

| Variable           | Description                    |
|--------------------|-------------------------------|
| `ICARGO_BASE_URL`  | iCargo environment base URL   |
| `ICARGO_USERNAME`  | Service account username      |
| `ICARGO_PASSWORD`  | Service account password      |
| `ICARGO_TIMEOUT`   | HTTP timeout in seconds       |

---

### 4.5 Diff & Comparison — `awb_diff_ibs.py`

`diff_awb(extracted, icargo_flat)` produces a list of `DiffRow` dicts, one per field:

```python
{
    "field": "shipper",
    "pdf_llm": "ACME LOGISTICS SRL",
    "icargo": "ACME LOGISTICS S.R.L.",
    "match": False
}
```

Normalisation applied before comparison:
- **Strings:** strip, collapse whitespace, case-insensitive.
- **Airport codes:** uppercase 3-letter IATA.
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
