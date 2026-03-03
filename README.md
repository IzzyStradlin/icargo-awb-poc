# iCargo AWB PoC - Documentation

## Overview

This is a **Proof of Concept (PoC)** application for intelligent **Air Waybill (AWB) extraction and validation**. The system reads AWB data from PDF and email documents, processes the information through a hybrid approach (rule-based + LLM), and compares the extracted data with records in the iCargo IBS system.

### Key Features

- 📄 **PDF & Email Processing**: Extract AWB data from PDF files and email attachments
- 🤖 **Hybrid Extraction**: Combines deterministic rule-based extraction with LLM intelligence
- 🔄 **Multi-LLM Support**: Switch between Phi3 (local) and Cohere (cloud) providers
- 🔍 **OCR Integration**: Automatic OCR fallback with configurable parameters
- 📊 **Data Validation**: Compares extracted data against iCargo IBS system records
- 🔐 **Secure Authentication**: Authenticated API calls to iCargo backend

---

## Architecture

### System Components

```
┌─────────────────────────────────────────────────────────┐
│                  User Interface Layer                    │
│  (Streamlit Web App + FastAPI REST API)                │
└────────────────────┬────────────────────────────────────┘
                     │
        ┌────────────┴────────────┐
        │                         │
   ┌────▼────────┐          ┌────▼────────┐
   │ PDF Upload  │          │Email Upload │
   └────┬────────┘          └────┬────────┘
        │                         │
        └────────────┬────────────┘
                     │
        ┌────────────▼────────────────┐
        │  Text Extraction Layer      │
        ├─────────────────────────────┤
        │ • PDF Parser                │
        │ • Email Parser              │
        │ • OCR Engine (Tesseract)    │
        └────────────┬────────────────┘
                     │
        ┌────────────▼──────────────────────┐
        │  AWB Interpretation Layer         │
        ├───────────────────────────────────┤
        │ • Rule-based Extraction           │
        │ • LLM Processing (Phi3/Cohere)   │
        │ • Hybrid Merger                   │
        └────────────┬──────────────────────┘
                     │
        ┌────────────▼──────────────────┐
        │  Validation & Comparison      │
        ├───────────────────────────────┤
        │ • iCargo IBS API Integration  │
        │ • Data Mapping                │
        │ • Diff Calculation            │
        └───────────────────────────────┘
```

### Directory Structure

```
icargo-awb-poc/
├── app/
│   ├── main.py                          # Application entry point
│   ├── common/
│   │   ├── exceptions.py                # Custom exceptions
│   │   ├── logging.py                   # Logging configuration
│   │   └── utils.py                     # Utility functions
│   ├── config/
│   │   └── settings.py                  # Configuration & env vars
│   ├── extraction/
│   │   ├── pdf_text_extractor.py       # PDF parsing & OCR
│   │   └── email_text_extractor.py     # Email extraction
│   ├── ingestion/
│   │   ├── pdf_ingestor.py             # PDF file handling
│   │   └── email_ingestor.py           # Email file handling
│   ├── interpretation/
│   │   ├── awb_extractor.py            # Base extraction interface
│   │   ├── awb_field_detector.py       # Rule-based field detection
│   │   ├── awb_hybrid_extractor.py     # Hybrid rule+LLM extractor
│   │   ├── awb_llm_parser.py           # LLM response parsing
│   │   ├── awb_normalizer.py           # Data normalization
│   │   ├── awb_number.py               # AWB number utilities
│   │   └── awb_schema.py               # Data structures
│   ├── llm/
│   │   ├── phi3_local_provider.py      # Phi3 local LLM provider
│   │   └── cohere_provider.py          # Cohere cloud LLM provider
│   ├── integration/
│   │   ├── awb_repository.py           # Data persistence layer
│   │   └── icargo_ibs_client.py        # iCargo IBS API client
│   ├── comparison/
│   │   └── awb_diff_ibs.py             # Diff calculation logic
│   ├── pipelines/
│   │   ├── run_from_pdf.py             # PDF processing pipeline
│   │   └── run_from_email.py           # Email processing pipeline
│   └── ui/
│       ├── web_streamlit.py             # Streamlit web interface
│       ├── web_fastapi.py               # FastAPI REST interface
│       └── pages/
│           ├── pdf_upload.py            # PDF upload page
│           └── email_upload.py          # Email upload page
├── tests/
│   └── unit/
│       ├── test_awb_diff_engine.py     # Diff calculation tests
│       └── test_awb_field_detector.py  # Rule-based extraction tests
├── requirements.txt                     # Python dependencies
└── README.md                            # This file
```

---

## Installation & Setup

### Prerequisites

- Python 3.9+
- Git
- (Optional) Tesseract OCR engine for advanced PDF text extraction

### 1. Clone Repository

```bash
git clone <repository-url>
cd icargo-awb-poc
```

### 2. Create Virtual Environment

```bash
# Using venv
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Create a `.env` file in the project root:

```bash
# UI Configuration
UI_MODE=streamlit  # Options: streamlit, api

# LLM Configuration
# Phi3 Local (no API key needed)
OLLAMA_BASE_URL=http://localhost:11434

# Cohere Cloud (requires API key)
CO_API_KEY=your-cohere-api-key
COHERE_API_KEY=your-cohere-api-key  # Alternative env var

# iCargo IBS Integration
ICARGO_BASE_URL=https://mac-stag-icargo.ibsplc.aero
ICARGO_USERNAME=your-username
ICARGO_PASSWORD=your-password
ICARGO_TIMEOUT=15

# PDF Extraction
PDF_OCR_LANG=eng
PDF_OCR_DPI=200
PDF_MIN_CHARS=200

# Logging
LOG_LEVEL=INFO
```

### 5. Install Tesseract (Optional but Recommended)

For advanced OCR capabilities:

**Ubuntu/Debian:**
```bash
sudo apt-get install tesseract-ocr tesseract-ocr-eng
```

**macOS:**
```bash
brew install tesseract
```

**Windows:**
- Download installer from: https://github.com/UB-Mannheim/tesseract/wiki

---

## Running the Application

### Option 1: Streamlit Web UI (Recommended)

```bash
python app/main.py
# or directly
streamlit run app/ui/web_streamlit.py
```

The Streamlit app will be available at: `http://localhost:8501`

### Option 2: FastAPI REST API

```bash
UI_MODE=api python app/main.py
# or directly
uvicorn app.ui.web_fastapi:app --reload --port 8080
```

The API will be available at: `http://localhost:8080`
API documentation: `http://localhost:8080/docs`

---

## Managing Credentials & External Integrations

### Why `.env` is NOT in Git

The `.env` file contains secrets (API keys, usernames, passwords) and is listed in `.gitignore` for security:
- GitHub scans for exposed secrets and blocks pushes containing them
- If committed, credentials could be compromised even if deleted later
- Proper practice: secrets in local `.env`, never in version control

### Local Setup for External Integrations

#### Step 1: Create Local `.env` File

```bash
# Copy the template
cp .env.example .env

# Edit with your credentials
nano .env  # or use any text editor
```

#### Step 2: Configure Each Integration

**Cohere LLM (Optional - only if using cloud LLM)**
```env
COHERE_API_KEY=sk-xxxxxxxxxxxx
COHERE_TIMEOUT=30
```
- Get key from: https://dashboard.cohere.ai/
- Only needed if you select "Cohere (Cloud)" in Streamlit UI
- Phi3 (Local) requires **no API key**

**iCargo IBS (Optional - only if comparing with enterprise system)**
```env
ICARGO_BASE_URL=https://mac-stag-icargo.ibsplc.aero
ICARGO_USERNAME=your_username
ICARGO_PASSWORD=your_password
ICARGO_TIMEOUT=15
```
- Contact iCargo admin for credentials
- Only needed to fetch data for comparison
- PDF extraction works without it

#### Step 3: Verify Setup

```bash
# Test that Python can load .env
python -c "from dotenv import load_dotenv; import os; load_dotenv(); print('✅ .env loaded')"

# Check which LLM will be used
python -c "from dotenv import load_dotenv; import os; load_dotenv(); print(os.getenv('COHERE_API_KEY') and 'Cohere available' or 'Using Phi3 (local)')"
```

### Integration Availability

| Feature | Required | Notes |
|---------|----------|-------|
| **PDF Extraction** | None | Always works (no dependencies) |
| **OCR** | Optional | Install Tesseract for better results |
| **Phi3 LLM** | None | Quantized model, CPU-only, auto-downloads |
| **Cohere LLM** | COHERE_API_KEY | Cloud-based, requires subscription |
| **iCargo Comparison** | ICARGO_* credentials | Enterprise integration, optional |

### Minimal Setup (PDF-Only Mode)

If you only need to extract AWB data from PDFs without external systems:

```env
# .env can be empty or minimal
# The app will:
# - Use Phi3 (local) for LLM (no key needed)
# - Skip iCargo integration
# - Skip Cohere fallback
```

Then just run:
```bash
streamlit run app/ui/web_streamlit.py
```

### Full Setup (All Integrations)

For complete functionality:

```env
COHERE_API_KEY=sk-xxxx...           # For cloud LLM option
COHERE_TIMEOUT=30

ICARGO_BASE_URL=https://...         # For system comparison
ICARGO_USERNAME=your_user
ICARGO_PASSWORD=your_pass
ICARGO_TIMEOUT=15
```

### Troubleshooting Missing Credentials

If you see errors like:
- `"ICARGO_USERNAME / ICARGO_PASSWORD missing"` → iCargo integration unavailable, but PDF extraction still works
- `"Cohere API invalid"` → Will fall back to Phi3 (local)
- No specific errors → All integrations working ✅

### For CI/CD and Production

In CI/CD pipelines (GitHub Actions, Docker, etc.):
- Never add `.env` to git
- Instead, use GitHub Secrets or environment-specific config
- Pass credentials as environment variables at runtime
- Each environment (dev, staging, prod) has different credentials

**Example for GitHub Actions:**
```yaml
env:
  COHERE_API_KEY: ${{ secrets.COHERE_API_KEY }}
  ICARGO_USERNAME: ${{ secrets.ICARGO_USERNAME }}
  ICARGO_PASSWORD: ${{ secrets.ICARGO_PASSWORD }}
```

---

## Usage Guide

### Streamlit Web Interface

#### Step 1: Select Input Type

The landing page offers two options:
- **📄 PDF**: Upload and process PDF documents
- **✉️ Email (.eml)**: Upload and process email files

#### Step 2: Upload Document

- Select a PDF file or .eml email attachment
- Configure OCR options if needed

#### Step 3: LLM Provider Selection

In the sidebar **⚙️ Configuration** section, choose your LLM provider:
- **Phi3 (Local)**: Runs on your machine, no API key needed
- **Cohere (Cloud)**: Cloud-based, requires API key

#### Step 4: AWB Extraction

1. **Text Extraction**: The system automatically extracts text from your document
   - Uses native PDF text if available
   - Falls back to OCR (Tesseract) if needed
   - Displays extraction method (OCR used: ✅/❌)

2. **Rule-based Detection**: Automatically finds AWB number patterns using regex
   - Shows all detected AWB candidates
   - Highlights the best match

3. **LLM Reconstruction** (Click button):
   - Click **"Run LLM Reconstruction"** to process the text with your selected LLM
   - The system uses a hybrid approach:
     - **Rule-based** for structured fields (AWB, pieces, weight)
     - **LLM** for text fields (shipper, consignee, goods description)

#### Step 5: Select AWB Number

- System auto-selects: OCR result → LLM result → manual override
- Manually override if needed
- Validates format (NNN-NNNNNNNN)

#### Step 6: Fetch iCargo Data

Click **"Fetch AWB from iCargo"** to:
- Authenticate with iCargo IBS API
- Retrieve current system records
- Prepare for comparison

#### Step 7: Review Differences

The system automatically calculates and displays:
- ✅ Fields that match
- ⚠️ Fields with differences
- Side-by-side comparison table

### Example Workflow

```
PDF Upload
    ↓
Text Extraction (PDF or OCR)
    ↓
Rule-based AWB Detection (Regex)
    ↓
LLM Reconstruction (Phi3/Cohere)
    ↓
Manual AWB Selection
    ↓
iCargo IBS GET
    ↓
Difference Calculation
    ↓
Display Results
```

---

## Core Components

### Text Extraction (`app/extraction/`)

#### PDFTextExtractor
- **Purpose**: Extract text from PDF files with optional OCR
- **Features**:
  - Native PDF text extraction
  - Automatic OCR fallback
  - Configurable language and DPI
  - Per-page processing
- **Usage**:
  ```python
  from app.extraction.pdf_text_extractor import PDFTextExtractor, ExtractOptions
  
  options = ExtractOptions(
      force_ocr=False,
      min_text_chars=200,
      ocr_lang="eng",
      ocr_dpi=200
  )
  extractor = PDFTextExtractor(options=options)
  text, used_ocr = extractor.extract_text(pdf_bytes)
  ```

### AWB Interpretation (`app/interpretation/`)

#### AwbFieldDetector (Rule-based)
- **Purpose**: Extract AWB fields using deterministic patterns
- **Handles**: AWB number, origin, destination, pieces, weight, dates
- **Reliability**: Very high for structured fields

#### AwbHybridExtractor
- **Purpose**: Combine rule-based and LLM extraction
- **Strategy**:
  - Rule-based wins for structured fields (high confidence)
  - LLM wins for text fields (semantic intelligence)
- **Usage**:
  ```python
  from app.interpretation.awb_hybrid_extractor import AwbHybridExtractor
  
  llm_provider = get_cohere_llm()  # or get_phi3_llm()
  extractor = AwbHybridExtractor(llm_provider=llm_provider)
  result = extractor.extract(text)
  ```

### LLM Providers (`app/llm/`)

#### Phi3LocalProvider
- **Model**: Microsoft Phi-3 (quantized local version)
- **Advantages**:
  - No API key required
  - Runs entirely offline
  - Fast locally
  - Privacy-preserving
- **Requirements**: ONNX Runtime + model files

#### CohereProvider
- **Model**: Cohere API (cloud-based)
- **Advantages**:
  - More powerful reasoning
  - No local compute required
  - Consistent updates
- **Requirements**: Cohere API key

### iCargo Integration (`app/integration/`)

#### ICargoIBSClient
- **Purpose**: Authenticate and fetch AWB records from iCargo IBS
- **Features**:
  - OAuth-like token authentication
  - Automatic token refresh
  - Error handling and retries
- **Usage**:
  ```python
  from app.integration.icargo_ibs_client import ICargoIBSClient
  
  client = ICargoIBSClient()
  awb_data = client.get_awb("001-12345678")
  ```

### Data Comparison (`app/comparison/`)

#### awb_diff_ibs
- **Purpose**: Calculate differences between extracted and system data
- **Output**: 
  - Field-level comparison
  - Match status (true/false)
  - Side-by-side values
  - Human-readable difference summary

---

## Hybrid Extraction Strategy

The system uses an intelligent hybrid approach that leverages both rule-based and LLM extraction:

```
Input Text (AWB document)
    │
    ├─→ [Rule-based Extractor]  ──→  Structured fields
    │   • AWB Number                  (high confidence)
    │   • Origin/Destination          
    │   • Pieces/Weight               
    │
    └─→ [LLM Extraction]  ──→  Text fields
        • Shipper                 (semantic intelligence)
        • Consignee               
        • Goods Description       
        • Flight Info             
        
        ├─→ [Intelligent Merge]  ──→  Final Result
            • Structured: prefer rule-based
            • Text: prefer LLM
            • Fallback: cross-validate
```

### Why This Works

**Rule-based extraction excels at:**
- Fixed format patterns (AWB numbers, codes)
- Structural parsing (pieces, weight units)
- Reliable field detection

**LLM extraction excels at:**
- Free text parsing (shipper names, addresses)
- Semantic understanding (goods descriptions)
- Handling variations and misspellings

**Combined approach:**
- Maximizes accuracy across all fields
- Reduces false positives
- Provides fallback mechanisms
- Balances speed and quality

---

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `UI_MODE` | No | `streamlit` | UI type: `streamlit` or `api` |
| `CO_API_KEY` | Conditional | - | Cohere API key (for Cohere LLM) |
| `ICARGO_BASE_URL` | Yes | - | iCargo IBS API base URL |
| `ICARGO_USERNAME` | Yes | - | iCargo authentication username |
| `ICARGO_PASSWORD` | Yes | - | iCargo authentication password |
| `OLLAMA_BASE_URL` | No | `http://localhost:11434` | Ollama/Phi3 local API |
| `TESSERACT_PATH` | No | - | Path to Tesseract executable (Windows) |

### OCR Configuration

Fine-tune OCR behavior in the UI expander:

| Option | Range | Description |
|--------|-------|-------------|
| Force OCR | - | Skip native PDF text, use OCR directly |
| Min Chars | 0-2000 | Threshold to trigger OCR fallback |
| OCR Language | ISO codes | Languages (e.g., `eng`, `ita`, `fra`) |
| OCR DPI | 150-300 | Output quality vs processing time |
| Max Pages | 0+ | Limit pages processed (0 = all) |

---

## Testing

### Run Unit Tests

```bash
pytest tests/ -v
```

### Run with Coverage

```bash
pytest tests/ --cov=app --cov-report=html
```

### Test AWB Field Detection

```bash
pytest tests/unit/test_awb_field_detector.py -v
```

### Test Diff Calculation

```bash
pytest tests/unit/test_awb_diff_engine.py -v
```

---

## LLM Provider Comparison

| Aspect | Phi3 (Local) | Cohere (Cloud) |
|--------|------------|----------------|
| **Cost** | Free | Pay per API call |
| **Privacy** | 100% local | Cloud-based |
| **Speed** | Depends on hardware | Fast API response |
| **Accuracy** | Good for AWB data | Excellent |
| **Setup** | Requires Ollama | Requires API key |
| **Offline** | Yes | No |
| **Best For** | PoC, privacy-focused | Production, reliability |

---

## Troubleshooting

### Common Issues

#### 1. **"Tesseract not found" Error**
- Install Tesseract OCR (see Installation section)
- Set `TESSERACT_PATH` environment variable (Windows)

#### 2. **iCargo Authentication Fails**
- Verify credentials in `.env`
- Check network connectivity
- Confirm iCargo IBS API is available

#### 3. **LLM Provider Not Responding**
- **Phi3**: Ensure Ollama is running (`ollama serve`)
- **Cohere**: Verify API key and rate limits

#### 4. **PDF Text Extraction Poor Quality**
- Increase OCR DPI (slower but more accurate)
- Try different OCR languages
- Check PDF is not scanned image-only

### Debug Mode

Enable detailed logging:

```bash
LOG_LEVEL=DEBUG python app/main.py
```

Check logs in `logs/` directory for detailed tracing.

---

## API Documentation

### FastAPI Endpoints

The FastAPI server provides REST endpoints for programmatic access:

```
GET  /docs              # Swagger UI
GET  /health            # Health check
POST /extract/pdf       # Extract from PDF
POST /extract/email     # Extract from email
POST /compare           # Compare with iCargo
```

Example request:

```bash
curl -X POST "http://localhost:8080/extract/pdf" \
  -F "file=@document.pdf" \
  -F "llm_provider=cohere"
```

---

## Performance Considerations

### Optimization Tips

1. **Use Phi3 (Local)** for fast PoC development
2. **Cache LLM instances** in Streamlit with `@st.cache_resource`
3. **Limit OCR DPI** to 200 for balance between quality and speed
4. **Process single pages** for large PDFs
5. **Batch API calls** to iCargo when processing multiple AWBs

### Benchmarks

- PDF text extraction: ~1-5 seconds (depends on size/OCR)
- LLM processing: ~5-15 seconds (Phi3) / ~1-3 seconds (Cohere)
- iCargo API call: ~2-5 seconds
- Diff calculation: <100ms

---

## Future Enhancements

- [ ] Batch AWB processing
- [ ] Email attachment automatic extraction
- [ ] Advanced data quality scoring
- [ ] ML-based confidence metrics
- [ ] Database persistence layer
- [ ] Advanced diff visualization
- [ ] Multi-language support
- [ ] Performance metrics dashboard
- [ ] AWB historical tracking
- [ ] Integration with warehouse systems

---

## License

[Add your license information here]

---

## Support

For issues, questions, or contributions:
- Open an issue on the repository
- Contact the development team
- Check the troubleshooting section above

---

## Version History

- **v0.1.0** (Feb 2026): Initial PoC release
  - PDF & email extraction
  - Hybrid rule-based + LLM processing
  - iCargo IBS integration
  - Streamlit & FastAPI interfaces
  - Phi3 & Cohere LLM support

---

**Last Updated**: February 25, 2026
