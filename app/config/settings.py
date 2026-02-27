# app/config/settings.py
from pydantic import BaseSettings, AnyHttpUrl, Field
from typing import Optional

class Settings(BaseSettings):
    # iCargo
    ICARGO_BASE_URL: AnyHttpUrl = "https://icargo.example.com/api"
    ICARGO_CLIENT_ID: Optional[str] = None
    ICARGO_CLIENT_SECRET: Optional[str] = None
    ICARGO_API_KEY: Optional[str] = None
    ICARGO_TIMEOUT_SEC: int = 30

    # LLM / Parsing strategy
    LLM_PROVIDER: str = "disabled"  # "azure_openai", "openai", "llama", "disabled"
    OCR_ENABLED: bool = True

    # Security (placeholder PoC)
    ALLOW_WRITEBACK: bool = True

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()