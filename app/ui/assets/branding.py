"""MSC Air Cargo branding helpers for the Streamlit UI."""

from __future__ import annotations

import base64
from pathlib import Path


MSC_COLORS = {
    "yellow": "#FCD116",
    "yellow_soft": "#FFF7CC",
    "black": "#000000",
    "ink": "#111111",
    "slate": "#5B616E",
    "white": "#FFFFFF",
    "surface": "#FFFFFF",
    "surface_alt": "#F7F7F4",
    "line": "#E7E2CF",
    "shadow": "rgba(17, 17, 17, 0.08)",
}

MSC_BRAND = {
    "company_name": "MSC Air Cargo",
    "product_name": "AWB Intelligent Processor",
    "tagline": "Intelligent document processing for air cargo operations",
    "version": "1.0.0",
    "copyright": "© 2026 Mediterranean Shipping Company. All rights reserved.",
    "website": "www.msc.com",
}


def _assets_dir() -> Path:
    return Path(__file__).resolve().parent


def _asset_data_uri(filename: str) -> str | None:
    path = _assets_dir() / filename
    if not path.exists():
        return None
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def get_logo_data_uri() -> str | None:
    return _asset_data_uri("logo.png")


def get_background_data_uri() -> str | None:
    return _asset_data_uri("background.png")


def get_css() -> str:
    background_uri = get_background_data_uri()
    hero_background = ""
    if background_uri:
        hero_background = (
            "background-image: linear-gradient(90deg, rgba(255,255,255,0.96) 0%, "
            "rgba(255,255,255,0.88) 42%, rgba(255,255,255,0.18) 100%), "
            f"url('{background_uri}');"
            "background-position: center right;"
            "background-size: cover;"
        )

    return f"""
<style>
:root {{
    --msc-yellow: {MSC_COLORS['yellow']};
    --msc-yellow-soft: {MSC_COLORS['yellow_soft']};
    --msc-black: {MSC_COLORS['black']};
    --msc-ink: {MSC_COLORS['ink']};
    --msc-slate: {MSC_COLORS['slate']};
    --msc-white: {MSC_COLORS['white']};
    --msc-surface: {MSC_COLORS['surface']};
    --msc-surface-alt: {MSC_COLORS['surface_alt']};
    --msc-line: {MSC_COLORS['line']};
    --msc-shadow: {MSC_COLORS['shadow']};
}}

html, body, [data-testid="stAppViewContainer"], .stApp {{
    background:
        radial-gradient(circle at top left, rgba(252, 209, 22, 0.12), transparent 28%),
        linear-gradient(180deg, #fcfbf7 0%, #f4f1e8 100%) !important;
    color: var(--msc-ink);
}}

[data-testid="stHeader"] {{
    background: rgba(255, 255, 255, 0.72);
    backdrop-filter: blur(8px);
}}

[data-testid="stSidebar"] {{
    background: linear-gradient(180deg, #111111 0%, #1b1b1b 100%) !important;
    border-right: 1px solid rgba(252, 209, 22, 0.22);
}}

[data-testid="stSidebar"] * {{
    color: #f8f6ef !important;
}}

[data-testid="stSidebar"] .stAlert {{
    background: rgba(252, 209, 22, 0.12) !important;
    border: 1px solid rgba(252, 209, 22, 0.24) !important;
}}

[data-testid="stFileUploaderDropzone"],
div[data-testid="stAlert"],
.stTextInput > div > div > input,
.stTextArea textarea,
.stSelectbox > div > div,
.stMultiSelect > div > div,
.stNumberInput input,
.stDateInput input,
.stDownloadButton > button,
.stButton > button,
[data-testid="stFileUploaderDropzone"] button,
.stExpander,
.stCodeBlock,
[data-baseweb="tab-panel"] {{
    border-radius: 18px !important;
}}

div[data-testid="stAlert"] {{
    background: rgba(255, 255, 255, 0.92) !important;
    border: 1px solid var(--msc-line) !important;
    box-shadow: 0 10px 30px var(--msc-shadow);
}}

.stButton > button,
.stButton > button[kind="primary"],
.stButton > button[kind="primaryFormSubmit"],
.stDownloadButton > button {{
    min-height: 38px;
    border: 1px solid var(--msc-black) !important;
    background: var(--msc-black) !important;
    color: var(--msc-white) !important;
    font-weight: 700;
    letter-spacing: 0.01em;
    box-shadow: none;
    transition: background 0.18s ease, color 0.18s ease, border-color 0.18s ease, transform 0.18s ease;
}}

.stButton > button *,
.stButton > button[kind="primary"] *,
.stDownloadButton > button * {{
    color: var(--msc-white) !important;
}}

.stButton > button:hover,
.stButton > button[kind="primary"]:hover,
.stDownloadButton > button:hover {{
    background: var(--msc-white) !important;
    color: var(--msc-black) !important;
    border-color: var(--msc-black) !important;
    transform: translateY(-1px);
}}

.stButton > button:hover *,
.stButton > button[kind="primary"]:hover *,
.stDownloadButton > button:hover * {{
    color: var(--msc-black) !important;
}}

.stButton > button:focus,
.stButton > button:active,
.stButton > button[kind="primary"]:focus,
.stButton > button[kind="primary"]:active,
.stDownloadButton > button:focus,
.stDownloadButton > button:active {{
    background: var(--msc-white) !important;
    color: var(--msc-black) !important;
    border-color: var(--msc-black) !important;
    box-shadow: 0 0 0 0.2rem rgba(17, 17, 17, 0.12) !important;
}}

.stButton > button:focus *,
.stButton > button:active *,
.stDownloadButton > button:focus *,
.stDownloadButton > button:active * {{
    color: var(--msc-black) !important;
}}

/* ── File uploader "Browse files" button ── */
[data-testid="stFileUploaderDropzone"] button {{
    min-height: 46px;
    border: 1px solid var(--msc-black) !important;
    background: var(--msc-black) !important;
    color: var(--msc-white) !important;
    font-weight: 700;
    letter-spacing: 0.01em;
    border-radius: 18px !important;
    box-shadow: 0 10px 24px rgba(0, 0, 0, 0.12);
    transition: background 0.18s ease, color 0.18s ease, border-color 0.18s ease, transform 0.18s ease;
}}

[data-testid="stFileUploaderDropzone"] button * {{
    color: var(--msc-white) !important;
}}

[data-testid="stFileUploaderDropzone"] button:hover {{
    background: var(--msc-white) !important;
    color: var(--msc-black) !important;
    border-color: var(--msc-black) !important;
    transform: translateY(-1px);
}}

[data-testid="stFileUploaderDropzone"] button:hover * {{
    color: var(--msc-black) !important;
}}

[data-testid="stFileUploaderDropzone"] button:focus,
[data-testid="stFileUploaderDropzone"] button:active {{
    background: var(--msc-white) !important;
    color: var(--msc-black) !important;
    border-color: var(--msc-black) !important;
    box-shadow: 0 0 0 0.2rem rgba(17, 17, 17, 0.12) !important;
}}

.stButton > button[kind="secondary"] {{
    background: var(--msc-black) !important;
    color: var(--msc-white) !important;
    border-color: var(--msc-black) !important;
}}

.stButton > button[kind="secondary"] *,
.stDownloadButton > button[kind="secondary"] * {{
    color: var(--msc-white) !important;
}}

.stButton > button[kind="secondary"]:hover,
.stButton > button[kind="secondary"]:focus,
.stButton > button[kind="secondary"]:active,
.stDownloadButton > button[kind="secondary"]:hover,
.stDownloadButton > button[kind="secondary"]:focus,
.stDownloadButton > button[kind="secondary"]:active {{
    background: var(--msc-white) !important;
    color: var(--msc-black) !important;
    border-color: var(--msc-black) !important;
}}

.stButton > button[kind="secondary"]:hover *,
.stButton > button[kind="secondary"]:focus *,
.stButton > button[kind="secondary"]:active *,
.stDownloadButton > button[kind="secondary"]:hover *,
.stDownloadButton > button[kind="secondary"]:focus *,
.stDownloadButton > button[kind="secondary"]:active * {{
    color: var(--msc-black) !important;
}}

.stTextInput > div > div > input,
.stTextArea textarea,
.stNumberInput input,
.stDateInput input {{
    background: rgba(255, 255, 255, 0.92) !important;
    color: var(--msc-ink) !important;
    border: 1px solid var(--msc-line) !important;
}}

/* Compact operational views: dense controls, legible tables, restrained framing. */
.stExpander {{
    border: 1px solid var(--msc-line) !important;
    border-radius: 8px !important;
    background: rgba(255, 255, 255, 0.88) !important;
}}

.stExpander summary {{
    font-weight: 700;
}}

[data-testid="stDataFrame"],
[data-testid="stDataEditor"] {{
    border: 1px solid var(--msc-line);
    border-radius: 8px;
    overflow: hidden;
}}

[data-testid="stMetric"] {{
    padding: 0.35rem 0.15rem;
}}

[data-testid="stMetricLabel"] {{
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}}

[data-testid="stMetricValue"] {{
    font-size: 1.1rem;
}}

h1, h2, h3, h4, h5, h6, p, li, label, span {{
    color: var(--msc-ink);
}}

.stTabs [data-baseweb="tab-list"] {{
    gap: 0.5rem;
    background: transparent !important;
}}

.stTabs [data-baseweb="tab"],
.stTabs [role="tab"] {{
    height: 44px;
    background: rgba(255,255,255,0.68) !important;
    border: 1px solid var(--msc-line) !important;
    border-radius: 999px !important;
    color: var(--msc-slate) !important;
    padding: 0 1rem;
}}

.stTabs [data-baseweb="tab"] p,
.stTabs [data-baseweb="tab"] span,
.stTabs [data-baseweb="tab"] div,
.stTabs [role="tab"] p,
.stTabs [role="tab"] span,
.stTabs [role="tab"] div {{
    color: var(--msc-slate) !important;
}}

.stTabs [data-baseweb="tab"][aria-selected="true"],
.stTabs [role="tab"][aria-selected="true"] {{
    background: var(--msc-black) !important;
    color: var(--msc-white) !important;
    border-color: var(--msc-black) !important;
}}

.stTabs [data-baseweb="tab"][aria-selected="true"] p,
.stTabs [data-baseweb="tab"][aria-selected="true"] span,
.stTabs [data-baseweb="tab"][aria-selected="true"] div,
.stTabs [role="tab"][aria-selected="true"] p,
.stTabs [role="tab"][aria-selected="true"] span,
.stTabs [role="tab"][aria-selected="true"] div {{
    color: var(--msc-white) !important;
}}

.stTabs [data-baseweb="tab-highlight"] {{
    display: none !important;
}}

.stTabs [data-baseweb="tab-panel"],
.stTabs [role="tabpanel"] {{
    background: transparent !important;
}}

.msc-shell {{
    display: grid;
    gap: 1.25rem;
}}

.msc-hero {{
    position: relative;
    overflow: hidden;
    padding: 2rem;
    border-radius: 28px;
    border: 1px solid rgba(17, 17, 17, 0.08);
    background: linear-gradient(135deg, rgba(252,209,22,0.95) 0%, rgba(255,247,204,0.92) 100%);
    box-shadow: 0 28px 60px rgba(17, 17, 17, 0.10);
    {hero_background}
}}

.msc-hero::after {{
    content: "";
    position: absolute;
    inset: 0;
    background: linear-gradient(120deg, rgba(0,0,0,0.05), transparent 38%);
    pointer-events: none;
}}

.msc-hero-inner {{
    position: relative;
    z-index: 1;
    max-width: 760px;
}}

.msc-eyebrow {{
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.9rem;
    padding: 0.45rem 0.8rem;
    border-radius: 999px;
    background: rgba(255,255,255,0.78);
    border: 1px solid rgba(17,17,17,0.10);
    font-size: 0.78rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}}

.msc-hero h1 {{
    margin: 0;
    font-size: clamp(2rem, 3vw, 3.2rem);
    line-height: 1.02;
    letter-spacing: -0.03em;
}}

.msc-hero p {{
    max-width: 48rem;
    margin: 0.9rem 0 0;
    font-size: 1rem;
    line-height: 1.65;
    color: rgba(17,17,17,0.80);
}}

.msc-logo-chip {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 124px;
    min-height: 56px;
    padding: 0.65rem 1rem;
    margin-bottom: 1rem;
    border-radius: 18px;
    background: rgba(255,255,255,0.86);
    border: 1px solid rgba(17,17,17,0.08);
    box-shadow: 0 10px 24px rgba(17,17,17,0.08);
}}

.msc-logo-chip img {{
    max-height: 34px;
    max-width: 132px;
}}

.msc-panel {{
    padding: 1.35rem 1.4rem;
    border-radius: 24px;
    background: rgba(255,255,255,0.88);
    border: 1px solid var(--msc-line);
    box-shadow: 0 18px 40px var(--msc-shadow);
}}

.msc-panel h3 {{
    margin: 0 0 0.35rem;
    font-size: 1.05rem;
}}

.msc-panel p {{
    margin: 0;
    color: var(--msc-slate);
    line-height: 1.6;
}}

.msc-kicker {{
    margin-bottom: 0.5rem;
    color: var(--msc-slate);
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: 700;
}}

.msc-page-header {{
    margin-bottom: 1rem;
    padding: 1.4rem 1.5rem;
    border-radius: 24px;
    background: rgba(255,255,255,0.88);
    border: 1px solid var(--msc-line);
    box-shadow: 0 18px 40px var(--msc-shadow);
}}

.msc-page-header h1 {{
    margin: 0;
    font-size: 1.7rem;
}}

.msc-page-header p {{
    margin: 0.45rem 0 0;
    color: var(--msc-slate);
}}

.msc-footer {{
    margin-top: 1.2rem;
    padding: 1rem 0 0;
    color: var(--msc-slate);
    font-size: 0.88rem;
    border-top: 1px solid rgba(17,17,17,0.08);
}}

.msc-stat-grid {{
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 1rem;
}}

.msc-stat {{
    padding: 1rem 1.1rem;
    border-radius: 20px;
    background: rgba(255,255,255,0.82);
    border: 1px solid rgba(17,17,17,0.08);
}}

.msc-stat strong {{
    display: block;
    margin-bottom: 0.25rem;
    font-size: 1rem;
}}

.msc-stat span {{
    color: var(--msc-slate);
    font-size: 0.92rem;
}}

@media (max-width: 900px) {{
    .msc-hero {{
        padding: 1.35rem;
    }}

    .msc-stat-grid {{
        grid-template-columns: 1fr;
    }}
}}
</style>
"""


def get_colors():
    return MSC_COLORS


def get_brand_info():
    return MSC_BRAND
