# Architecture - iCargo AWB Intelligent Processor (PoC)

> Status: Proof of Concept
> Version: 1.7.0
> Owner: MSC Air Cargo

---

## 1. Purpose

This repository implements a local-first workflow for Air Waybill (AWB) extraction, comparison, and controlled writeback to iCargo.

Current scope:

1. Ingest PDF and email artifacts.
2. Split multi-document PDFs into MAWB ranges.
3. Extract MAWB + HAWB fields with vision providers.
4. Compare extracted values against iCargo.
5. Allow selective field-level updates for both Master and House records.

---

## 2. High-Level Runtime Architecture

```text
+--------------------------- Presentation ----------------------------+
| Streamlit UI (primary)                     FastAPI (optional)      |
+-------------------------------+------------------------------------+
                                |
                         app/main.py (UI_MODE)
                                |
             +------------------+------------------+
             |                                     |
   PDF workflow (ui/pages/pdf_upload.py)   AWB lookup (ui/pages/awb_lookup.py)
             |
   +---------+---------------------------------------------------------------+
   |                 Extraction and Interpretation                            |
   | AwbDocumentPreSplitter -> AwbVisionExtractor -> Provider                |
   | Providers: Claude Vision API, MSC Tech AI file handoff                  |
   +---------+---------------------------------------------------------------+
             |
   +---------+---------------------------------------------------------------+
   |                 Comparison and Integration                               |
   | map_icargo_* + diff_* + ICargoIBSClient                                 |
   +--------------------------------------------------------------------------+
```

---

## 3. Main Modules

### 3.1 Entry points

- app/main.py: runtime selector (`streamlit` or `api`).
- app/ui/web_streamlit.py: Streamlit shell and page routing.
- app/ui/web_fastapi.py: lightweight API endpoints.

### 3.2 UI pages

- app/ui/pages/pdf_upload.py
  - PDF/ZIP upload and optional folder polling mode.
  - Pre-split and extraction.
  - MAWB and HAWB compare/edit/update workflow.
- app/ui/pages/awb_lookup.py
  - direct read-only iCargo retrieval pages.
- app/ui/pages/email_upload.py
  - email intake placeholder flow.

### 3.3 Extraction and interpretation

- app/extraction/awb_document_presplitter.py
- app/extraction/pdf_text_extractor.py
- app/interpretation/awb_vision_extractor.py
- app/llm/claude_vision_provider.py
- app/llm/msc_tech_ai_provider.py
- app/interpretation/* (schema, normalization, parsing utilities)

### 3.4 Compare and integration

- app/compare/awb_diff_ibs.py: iCargo mapping and field-level diff rows.
- app/comparison/awb_diff_engine.py: structured diff engine.
- app/integration/icargo_ibs_client.py: reusable iCargo client.
- app/ui/pages/pdf_upload.py: operational iCargo client and writeback orchestration used in the UI flow.

---

## 4. End-to-End PDF Flow

1. User uploads a single PDF or a ZIP containing multiple PDFs.
2. Pre-split detects MAWB ranges (`start_page`, `end_page`, `awb_number`).
3. Each range is rendered to PNG and sent to selected provider.
4. Provider returns MAWB + HAWB JSON.
5. UI renders extraction result.
6. On Fetch and Compare:
   - GET MAWB from iCargo
   - GET HAWBs from iCargo (always, even if PDF has no HAWBs)
   - Diff rows produced for MAWB and each HAWB relation:
     - matched
     - pdf_only
     - icargo_only
7. User can edit `pdf_llm` values and apply updates:
   - Update Master
   - Update House
   - Update All

---

## 5. Provider Model

### 5.1 Claude Vision provider

- Direct API extraction from rendered pages.
- Supports MAWB + HAWB extraction in one flow.

### 5.2 MSC Tech AI provider (file handoff)

- Writes PNGs to inbox folder and waits for JSON output files.
- Uses strict batch completeness checks (expected PNG count must match processed JSON set).
- Ignores subfolders in output scan to avoid stale or unrelated JSON interference.

---

## 6. iCargo Integration Behavior

### 6.1 Authentication strategy

In the Streamlit workflow client:

1. Primary header: `Authorization: Bearer <token>`.
2. On `401`, token is refreshed.
3. Retry variants include `ICO-Authorization` raw token fallback for stage compatibility.

This behavior was introduced to align with observed preprod/stage gateway behavior.

### 6.2 Write safety guard

- Write operations are allowed only when base URL matches preprod stage host.
- Prevents accidental writes to non-approved environments.

### 6.3 Payload strategy

- Master payload starts from latest iCargo AWB snapshot and applies selected field edits.
- House payload is built per selected HAWB candidate.
- For `icargo_only` House rows, source data is seeded from iCargo mapping so updates are possible even without PDF-origin House data.

### 6.4 Consistency rule handling

To avoid `ICO_AWB_009`:

- `stated_pieces` is synchronized with `applicable_charges.rating_details[0].pieces`.
- `stated_weight` is synchronized with `applicable_charges.rating_details[0].weight`.

---

## 7. Compare and Edit UX Model

### 7.1 Grid model

Diff grids include:

- `field`
- `pdf_llm` (editable)
- `icargo` (read-only)
- `match` (read-only)
- `apply` (user-selectable)

### 7.2 Extended POST field coverage

The update UI includes a broad editable catalog of iCargo POST-relevant fields for both MAWB and HAWB, not only baseline diff fields.

This supports API behavior testing even when a field is absent from extracted PDF content.

### 7.3 HAWB scenarios

- matched: PDF House paired to iCargo House by normalized number scoring.
- pdf_only: extracted House without iCargo counterpart.
- icargo_only: House existing only in iCargo, now editable and updatable through the same UI.

---

## 8. Configuration

Environment-driven runtime (`.env` + process env):

- `UI_MODE`
- `ANTHROPIC_API_KEY`, `CLAUDE_MODEL`, `CLAUDE_TIMEOUT`
- `ICARGO_BASE_URL`, `ICARGO_USERNAME`, `ICARGO_PASSWORD`, `ICARGO_TIMEOUT`
- `MSC_TECH_PNG_FOLDER`, `MSC_TECH_JSON_FOLDER`, `MSC_TECH_GROUP_LABEL`

Notes:

- Runtime still uses `os.getenv(...)` directly in several active modules.
- `.env` values are persisted for MSC Tech AI folder settings from UI when provided.

---

## 9. Security and Operational Constraints

1. Secrets are environment-injected; never committed to source.
2. Writeback is guarded to preprod stage host.
3. Local execution model is supported (no mandatory server deployment).
4. Data handling is primarily in-memory during extraction and compare workflows.

---

## 10. Current Strengths

1. Practical end-to-end flow from extraction to controlled iCargo writeback.
2. Strong operational visibility with debug/diagnostic panels.
3. Flexible provider strategy (API direct or file handoff).
4. Robust handling of House scenarios, including iCargo-only cases.

---

## 11. Known Limitations

1. Email workflow remains partial.
2. Some behavior is UI-centric and duplicated versus integration-layer client abstractions.
3. Provider-side JSON quality can still require external team alignment.

---

## 12. Summary

The codebase currently operates as a local-first AWB operations console:

1. Ingest and split AWB documents.
2. Extract MAWB + HAWB with vision providers.
3. Compare against iCargo with editable diff surfaces.
4. Execute selective, guarded writeback for Master and House updates.
